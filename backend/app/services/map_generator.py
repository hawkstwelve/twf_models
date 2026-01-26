"""Map generation service"""
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt
from matplotlib import colors
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from cartopy.mpl.gridliner import LONGITUDE_FORMATTER, LATITUDE_FORMATTER
import xarray as xr
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
import logging
from typing import Optional

from app.config import settings
from app.services.data_fetcher import GFSDataFetcher
from app.services.stations import get_stations_for_region, format_station_value

logger = logging.getLogger(__name__)


class MapGenerator:
    """Generates weather forecast maps"""
    
    # Precipitation type configuration with levels and colors
    RAIN_LEVELS = [0, 0.1, 0.5, 1.5, 2.5, 4, 6, 10, 16, 24]
    WINTER_LEVELS = [0, 0.1, 0.5, 1, 2, 3, 4, 6, 10, 14]
    
    PRECIP_CONFIG = {
        'rain': {
            'levels': RAIN_LEVELS,
            'colors': ['#FFFFFF', '#00FF00', '#00C800', '#008000', '#FFFF00', '#FFD700', '#FFA500', '#FF0000', '#B22222', '#FF00FF']
        },
        'frzr': {
            'levels': WINTER_LEVELS,
            'colors': ['#FFFFFF', '#FFC0CB', '#FF69B4', '#FF1493', '#C71585', '#931040', '#B03060', '#D20000', '#FF2400', '#FF4500']
        },
        'sleet': {
            'levels': WINTER_LEVELS,
            'colors': ['#FFFFFF', '#E0FFFF', '#ADD8E6', '#9370DB', '#8A2BE2', '#9400D3', '#800080', '#4B0082', '#8B008B', '#B22222']
        },
        'snow': {
            'levels': WINTER_LEVELS,
            'colors': ['#FFFFFF', '#F0FFFF', '#00FFFF', '#00BFFF', '#1E90FF', '#0000FF', '#0000CD', '#00008B', '#483D8B', '#FF007F']
        }
    }
    
    def __init__(self):
        self.data_fetcher = GFSDataFetcher()
        self.storage_path = Path(settings.storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
    
    def get_precip_cmap(self, p_type):
        """
        Get colormap and normalization for precipitation type.
        
        Args:
            p_type: Precipitation type ('rain', 'frzr', 'sleet', 'snow')
        
        Returns:
            tuple: (cmap, norm, levels) for the precipitation type
        """
        config = self.PRECIP_CONFIG[p_type]
        
        # Create the discrete colormap
        cmap = colors.ListedColormap(config['colors'])
        
        # Create the normalization based on the boundaries
        norm = colors.BoundaryNorm(config['levels'], cmap.N)
        
        return cmap, norm, config['levels']
    
    def _setup_base_map(self, region: str = 'pnw', 
                       land_color: str = '#fbf5e7',
                       ocean_color: str = '#e3f2fd',
                       border_color: str = '#333333',
                       border_linewidth: float = 0.6,
                       state_linewidth: float = 0.4):
        """
        Set up the base map with projection, extent, and geographic features.
        
        This is the foundation for all maps - provides consistent base styling
        that can be customized per map type.
        
        Args:
            region: Map region ('pnw', 'us', or 'global')
            land_color: Color for land areas (default: light beige)
            ocean_color: Color for ocean areas (default: light blue)
            border_color: Color for borders/coastlines (default: dark gray)
            border_linewidth: Width of coastline/border lines
            state_linewidth: Width of state boundary lines
            
        Returns:
            matplotlib axes object with base map configured
        """
        fig = plt.figure(figsize=(settings.map_width/100, settings.map_height/100), dpi=settings.map_dpi)
        
        # Set projection based on region
        if region == "pnw":
            # Pacific Northwest: WA, OR, ID
            # Use Lambert Conformal optimized for PNW
            ax = plt.axes(projection=ccrs.LambertConformal(
                central_longitude=-117.5,  # Center of PNW
                central_latitude=45.5,     # Center of PNW
                standard_parallels=(43, 48)
            ))
            bounds = settings.map_region_bounds or {
                "west": -125.0, "east": -110.0,
                "south": 42.0, "north": 49.0
            }
            ax.set_extent(
                [bounds["west"], bounds["east"], bounds["south"], bounds["north"]],
                crs=ccrs.PlateCarree()
            )
        elif region == "us":
            ax = plt.axes(projection=ccrs.LambertConformal(central_longitude=-95, central_latitude=35))
            ax.set_extent([-130, -65, 20, 50], crs=ccrs.PlateCarree())
        else:
            ax = plt.axes(projection=ccrs.PlateCarree())
            ax.set_global()
        
        # Add map features (zorder=0 to keep them below data)
        ax.add_feature(cfeature.OCEAN, facecolor=ocean_color, zorder=0)
        ax.add_feature(cfeature.LAND, facecolor=land_color, zorder=0)
        ax.add_feature(cfeature.COASTLINE, linewidth=border_linewidth, edgecolor=border_color, zorder=2)
        ax.add_feature(cfeature.BORDERS, linewidth=border_linewidth, edgecolor=border_color, zorder=2)
        ax.add_feature(cfeature.STATES, linewidth=state_linewidth, edgecolor=border_color, linestyle=':', zorder=2)
        
        return fig, ax
    
    def extract_station_values(self, ds: xr.Dataset, variable: str, region: str = 'pnw', 
                               priority_level: int = 2):
        """
        Extract model values at station locations.
        
        Args:
            ds: xarray Dataset with forecast data
            variable: Variable name in dataset (e.g., 't2m', 'tp')
            region: Region identifier for station selection
            priority_level: Station priority level (1=major only, 2=major+secondary, 3=all)
        
        Returns:
            Dictionary mapping station names to their values
        """
        stations = get_stations_for_region(region, priority_level)
        values = {}
        
        # Detect if dataset uses 0-360 longitude format
        lon_coord_name = 'longitude' if 'longitude' in ds.coords else 'lon'
        lon_vals = ds.coords[lon_coord_name].values
        uses_360_format = lon_vals.min() >= 0 and lon_vals.max() > 180
        
        for station_name, station_data in stations.items():
            try:
                station_lat = station_data['lat']
                station_lon = station_data['lon']
                
                # Convert longitude to match dataset format if needed
                if uses_360_format and station_lon < 0:
                    station_lon = station_lon % 360
                
                # Extract value at station location using nearest neighbor
                value = ds[variable].sel(
                    latitude=station_lat,
                    longitude=station_lon,
                    method='nearest'
                ).values
                
                # Handle numpy arrays and scalars
                if hasattr(value, 'item'):
                    value = value.item()
                
                values[station_name] = float(value)
                
            except Exception as e:
                logger.warning(f"Could not extract value for station {station_name}: {e}")
                continue
        
        return values
    
    def plot_station_overlays(self, ax, station_values: dict, variable: str, 
                              region: str = 'pnw', transform=None):
        """
        Plot station values as overlays on the map.
        
        Args:
            ax: Matplotlib axes object
            station_values: Dictionary of station names to values
            variable: Variable type for formatting (temp, precip, wind_speed, etc.)
            region: Region identifier
            transform: Cartopy transform (defaults to PlateCarree)
        """
        if transform is None:
            transform = ccrs.PlateCarree()
        
        stations = get_stations_for_region(region, priority_level=3)  # Get all for positioning
        
        for station_name, value in station_values.items():
            if station_name not in stations:
                continue
            
            station = stations[station_name]
            lat = station['lat']
            lon = station['lon']
            
            # Format the value for display
            formatted_value = format_station_value(value, variable)
            
            if not formatted_value:  # Skip if empty
                continue
            
            # Plot station dot
            ax.plot(lon, lat, 'o', 
                   color='black', 
                   markersize=4,
                   markeredgecolor='white',
                   markeredgewidth=0.5,
                   transform=transform,
                   zorder=100)
            
            # Plot value text with white background box for readability
            ax.text(lon, lat, 
                   formatted_value,
                   transform=transform,
                   fontsize=8,
                   fontweight='bold',
                   ha='left',
                   va='bottom',
                   color='black',
                   bbox=dict(
                       boxstyle='round,pad=0.3',
                       facecolor='white',
                       edgecolor='black',
                       linewidth=0.5,
                       alpha=0.85
                   ),
                   zorder=101)
            
            # Optionally add station name below (for major stations only)
            if station.get('priority', 3) == 1:  # Only major cities
                ax.text(lon, lat - 0.15,  # Slight offset below
                       station.get('abbr', station_name[:3].upper()),
                       transform=transform,
                       fontsize=6,
                       ha='center',
                       va='top',
                       color='black',
                       style='italic',
                       alpha=0.7,
                       zorder=99)
    
    def generate_map(
        self,
        ds: xr.Dataset,
        variable: str,
        model: str = "GFS",
        run_time: Optional[datetime] = None,
        forecast_hour: int = 0,
        region: Optional[str] = None
    ) -> Path:
        """Generate a map for a specific variable"""
        logger.info(f"Generating map: {variable} from {model}, forecast hour {forecast_hour}")
        
        # Select variable and process
        is_mslp_precip = False
        is_850mb_map = False
        is_wind_speed_map = False
        if variable == "temperature_2m" or variable == "temp":
            data = self._process_temperature(ds)
            units = "°F"
            from matplotlib.colors import LinearSegmentedColormap
            
            # Expanded color list to match the visual complexity of your screenshot
            temp_colors = [
                '#E8D0D8', '#D8B0C8', '#C080B0', '#9050A0', '#703090', # -40 to -15 (Purples)
                '#A070B0', '#C8A0D0', '#E8E0F0', '#D0E0F0', '#A0C0E0', # -10 to 10 (Light Purple/Blue)
                '#7090C0', '#4070B0', '#2050A0', '#103070',            # 15 to 30 (Deep Blues)
                '#204048', '#406058', '#709078', '#A0C098', '#D0E0B0', # 35 to 50 (Teal/Sage Greens)
                '#F0F0C0', '#E0D0A0', '#C0B080', '#A08060', '#805040', # 55 to 70 (Yellow/Tan/Brown)
                '#602018', '#801010', '#A01010', '#702020',            # 75 to 90 (Deep Reds)
                '#886666', '#A08888', '#C0A0A0', '#D8C8C8', '#E8E0E0', # 95 to 110 (Muted Grays/Pinks)
                '#B0A0A0', '#807070', '#504040'                        # 115+ (Dark Grays)
            ]
            
            cmap = LinearSegmentedColormap.from_list('temperature', temp_colors, N=256)
        elif variable == "precipitation" or variable == "precip":
            data = self._process_precipitation(ds, forecast_hour=forecast_hour)
            units = "in"  # Inches for PNW users
            # Custom colormap matching the known-good precipitation scale
            from matplotlib import colors
            
            # Define the specific hex colors for each interval
            # Following the known-good map: Grey -> Green -> Blue -> Yellow -> Orange -> Red -> Purple
            precip_colors = [
                '#FFFFFF', '#C0C0C0', '#909090', '#606060', # 0.00, 0.01, 0.05, 0.1
                '#B0F090', '#80E060', '#50C040',            # 0.2, 0.3, 0.5
                '#3070F0', '#5090F0', '#80B0F0', '#B0D0F0', # 0.7, 0.9, 1.2, 1.6
                '#FFFF80', '#FFD060', '#FFA040',            # 2.0, 3.0, 4.0
                '#FF6030', '#E03020', '#A01010', '#700000', # 6.0, 8.0, 10.0, 12.0
                '#D0B0E0', '#B080D0', '#9050C0', '#7020A0', # 14.0, 16.0, 18.0, 20.0
                '#C040C0'                                   # 25.0+
            ]
            
            # Define exact non-linear boundaries (increments)
            # These must match the length of color list minus any 'extend' colors
            precip_levels = [0.0, 0.01, 0.05, 0.1, 0.2, 0.3, 0.5, 0.7, 0.9, 1.2, 1.6, 
                             2.0, 3.0, 4.0, 6.0, 8.0, 10.0, 12.0, 14.0, 16.0, 18.0, 20.0, 25.0]
            
            # Create the discrete colormap
            # ListedColormap is best for these fixed categories
            # Number of colors = number of levels - 1 (one color per interval)
            custom_precip_cmap = colors.ListedColormap(precip_colors[:len(precip_levels)-1])
            custom_precip_cmap.set_over(precip_colors[-1])  # Use last color for values > 25.0
            custom_precip_cmap.set_under('#FFFFFF')         # Explicitly white for < 0.01
            
            # Use BoundaryNorm to map the data to these uneven levels
            precip_norm = colors.BoundaryNorm(precip_levels, custom_precip_cmap.N)
            
            cmap = custom_precip_cmap
        elif variable == "wind_speed_10m" or variable == "wind_speed":
            # For forecast hour 0 (analysis), wind components may not be available
            # Check if wind data exists before processing
            has_wind = ('u10' in ds or 'ugrd10m' in ds) and ('v10' in ds or 'vgrd10m' in ds)
            if not has_wind and forecast_hour == 0:
                raise ValueError(f"Wind components not available in analysis file (f000) for {variable}. Skipping wind_speed map for forecast hour 0.")
            data = self._process_wind_speed(ds)
            units = "mph"  # MPH for PNW users
            
            # Custom wind speed colormap matching WeatherBell style
            from matplotlib.colors import LinearSegmentedColormap
            wind_colors = [
                (0, '#FFFFFF'),      # 0 mph - White
                (4, '#E6F2FF'),      # Light blue
                (6, '#CCE5FF'),      
                (8, '#99CCFF'),      # Blue
                (9, '#66B2FF'),      
                (10, '#3399FF'),     
                (12, '#66FF66'),     # Light green
                (14, '#33FF33'),     
                (16, '#00FF00'),     # Green
                (20, '#CCFF33'),     # Yellow-green
                (22, '#FFFF00'),     # Yellow
                (24, '#FFCC00'),     
                (26, '#FF9900'),     # Orange
                (30, '#FF6600'),     
                (34, '#FF3300'),     # Red-orange
                (36, '#FF0000'),     # Red
                (40, '#CC0000'),     # Dark red
                (44, '#990000'),     
                (48, '#800000'),     
                (52, '#660033'),     # Dark maroon
                (58, '#660066'),     # Purple
                (64, '#800080'),     
                (70, '#990099'),     
                (75, '#B300B3'),     
                (85, '#CC00CC'),     
                (95, '#E600E6'),     
                (100, '#680868')     # Dark purple
            ]
            
            # Normalize positions
            min_val = 0
            max_val = 100
            norm_colors = []
            for val, hex_code in wind_colors:
                pos = (val - min_val) / (max_val - min_val)
                norm_colors.append((pos, hex_code))
            
            cmap = LinearSegmentedColormap.from_list('wind_speed', norm_colors, N=256)
            is_wind_speed_map = True
        elif variable == "temp_850_wind_mslp" or variable == "850mb":
            # 850mb Temperature shading, Wind Arrows, and MSLP Contours
            data = ds['tmp_850']
            if float(data.max()) > 100: # Kelvin
                data = data - 273.15 # Convert to Celsius
            units = "°C"
            from matplotlib.colors import LinearSegmentedColormap
            
            # 1. Define anchor points in Celsius (Converted from the professional F scale)
            # Mapping: (Value in C, Hex Code)
            colors = [
                (-40.0, '#E8D0D8'), # -40F
                (-34.4, '#D0A0C0'), # -30F
                (-28.9, '#A070B0'), # -20F
                (-23.3, '#704090'), # -10F
                (-17.8, '#8050A0'), #  0F
                (-12.2, '#C0D0F0'), # 10F
                (-6.7,  '#80A0D0'), # 20F
                (-1.1,  '#4060B0'), # 30F
                (0.0,   '#204080'), # 32F (FREEZING LINE)
                (1.7,   '#406050'), # 35F
                (7.2,   '#709070'), # 45F
                (12.8,  '#D0D090'), # 55F
                (18.3,  '#B09060'), # 65F
                (23.9,  '#804030'), # 75F
                (29.4,  '#901010'), # 85F
                (35.0,  '#A08080'), # 95F
                (40.6,  '#D0C0C0'), # 105F
                (46.1,  '#504040')  # 115F
            ]

            # 2. Set the data range in Celsius
            min_val = -40.0 
            max_val = 46.1

            # 3. Normalize and Create Cmap
            norm_colors = []
            for val, hex_code in colors:
                pos = (val - min_val) / (max_val - min_val)
                norm_colors.append((max(0, min(1, pos)), hex_code))
            
            # Ensure first position is exactly 0.0 and last is exactly 1.0
            if norm_colors[0][0] != 0.0:
                norm_colors[0] = (0.0, norm_colors[0][1])
            if norm_colors[-1][0] != 1.0:
                norm_colors[-1] = (1.0, norm_colors[-1][1])

            cmap = LinearSegmentedColormap.from_list('weatherbell_c', norm_colors, N=256)
            is_850mb_map = True
        elif variable == "mslp_precip" or variable == "mslp_pcpn":
            # MSLP & Categorical Precipitation (Rain/Snow/Sleet/Freezing Rain)
            # This follows the WeatherBell/TropicalTidbits style
            data = self._process_precipitation_mmhr(ds)  # Keep in mm/hr
            units = "mm/hr"
            cmap = "Greens" # Default, though we plot layers below
            # Mark as categorical for special plotting below
            is_mslp_precip = True
        elif variable == "radar" or variable == "radar_reflectivity":
            # Simulated Radar Reflectivity (Composite Reflectivity)
            data = self._process_radar_reflectivity(ds)
            units = "dBZ"
            # Standard radar colormap (similar to NWS/NEXRAD)
            from matplotlib.colors import LinearSegmentedColormap
            # Radar colors: light blue -> green -> yellow -> orange -> red -> purple
            radar_colors = [
                (-10, '#000000'),  # Below detectable (transparent/black)
                (5, '#00CCFF'),    # Light blue (5 dBZ)
                (10, '#0099FF'),   # Blue (10 dBZ)
                (15, '#00FF00'),   # Green (15 dBZ)
                (20, '#00CC00'),   # Dark green (20 dBZ)
                (25, '#FFFF00'),   # Yellow (25 dBZ)
                (30, '#FFCC00'),   # Orange (30 dBZ)
                (35, '#FF9900'),   # Dark orange (35 dBZ)
                (40, '#FF0000'),   # Red (40 dBZ)
                (45, '#CC0000'),   # Dark red (45 dBZ)
                (50, '#FF00FF'),   # Magenta (50 dBZ)
                (55, '#CC00CC'),   # Purple (55 dBZ)
                (60, '#9900CC'),   # Dark purple (60 dBZ)
                (65, '#FFFFFF')    # White (65+ dBZ)
            ]
            norm_colors = []
            min_val = -10
            max_val = 70
            for val, hex_code in radar_colors:
                pos = (val - min_val) / (max_val - min_val)
                # Ensure positions are in [0, 1] range and first/last are exactly 0 and 1
                pos = max(0.0, min(1.0, pos))
                norm_colors.append((pos, hex_code))
            
            # Ensure first position is exactly 0.0 and last is exactly 1.0
            if norm_colors[0][0] != 0.0:
                norm_colors[0] = (0.0, norm_colors[0][1])
            if norm_colors[-1][0] != 1.0:
                norm_colors[-1] = (1.0, norm_colors[-1][1])
            
            cmap = LinearSegmentedColormap.from_list('radar', norm_colors, N=256)
        # Note: wind_gusts removed for initial release, can be added later
        else:
            raise ValueError(f"Unsupported variable: {variable}")
        
        # Determine base map colors based on variable type
        # MSLP & Precip, Total Precip, and Radar maps: all white with black borders
        if is_mslp_precip or variable in ["precipitation", "precip", "radar", "radar_reflectivity"]:
            land_color = '#ffffff'
            ocean_color = '#ffffff'
            border_color = '#000000'
        else:
            # Default: light beige land, light blue ocean, gray borders
            land_color = '#fbf5e7'
            ocean_color = '#e3f2fd'
            border_color = '#333333'
        
        # Generate base map using reusable function
        region_to_use = region or settings.map_region
        fig, ax = self._setup_base_map(
            region=region_to_use,
            land_color=land_color,
            ocean_color=ocean_color,
            border_color=border_color
        )
        
        # Plot data
        # Handle precipitation type differently (discrete values)
        if variable in ["precipitation_type", "precip_type"]:
            # ... (existing precip type logic)
            # Use discrete colormap for precip type
            from matplotlib.colors import ListedColormap, BoundaryNorm
            colors = ['white', 'blue', 'lightblue', 'cyan']  # None, Rain, Snow, Freezing
            cmap_discrete = ListedColormap(colors)
            bounds = [-0.5, 0.5, 1.5, 2.5, 3.5]
            norm = BoundaryNorm(bounds, cmap_discrete.N)
            
            lon_vals = data.lon if hasattr(data, 'lat') else data.coords.get('lon', data.coords.get('longitude'))
            lat_vals = data.lat if hasattr(data, 'lat') else data.coords.get('lat', data.coords.get('latitude'))
            
            im = ax.contourf(
                lon_vals, lat_vals, data,
                transform=ccrs.PlateCarree(),
                cmap=cmap_discrete,
                norm=norm,
                levels=bounds,
                extend='neither',
                zorder=1
            )
        elif is_mslp_precip:
            # MSLP & Categorical Precipitation Plotting
            mslp_data = self._process_mslp(ds)
            has_gh = ('gh_1000' in ds and 'gh_500' in ds) or 'gh' in ds or any('gh' in str(v).lower() for v in ds.data_vars)
            thickness_data = self._process_thickness(ds) if has_gh else None
            
            lon_vals = data.coords.get('lon', data.coords.get('longitude'))
            lat_vals = data.coords.get('lat', data.coords.get('latitude'))
            
            # Plot ALL precipitation types - always create all 4 colorbars
            # Map GRIB variables to precipitation types
            precip_type_map = {
                'crain': 'rain',
                'cfrzr': 'frzr',
                'cicep': 'sleet',
                'csnow': 'snow'
            }
            
            # Store all precipitation type contourf plots for colorbars
            precip_contours = {}
            
            for var_key, p_type in precip_type_map.items():
                # Get colormap and levels for this precipitation type
                cmap, norm, levels = self.get_precip_cmap(p_type)
                
                if var_key in ds:
                    mask = ds[var_key].isel(time=0) if 'time' in ds[var_key].dims else ds[var_key]
                    
                    # Use the mask values directly (0-1) to weight precipitation
                    # This creates smoother transitions than hard cutoff at 0.5
                    type_data = data * mask
                    
                    if float(type_data.max()) > 0.005:
                        # Plot actual data with smooth gradients
                        contour = ax.contourf(
                            lon_vals, lat_vals, type_data,
                            transform=ccrs.PlateCarree(),
                            cmap=cmap,
                            norm=norm,
                            levels=levels,
                            extend='max',
                            zorder=1,
                            alpha=0.85
                        )
                    else:
                        # No data but create invisible contour for colorbar
                        contour = ax.contourf(
                            lon_vals, lat_vals, data.where(data < 0),
                            transform=ccrs.PlateCarree(),
                            cmap=cmap,
                            norm=norm,
                            levels=levels,
                            extend='max',
                            zorder=1,
                            alpha=0
                        )
                else:
                    # Variable not in dataset, create invisible contour for colorbar
                    contour = ax.contourf(
                        lon_vals, lat_vals, data.where(data < 0),
                        transform=ccrs.PlateCarree(),
                        cmap=cmap,
                        norm=norm,
                        levels=levels,
                        extend='max',
                        zorder=1,
                        alpha=0
                    )
                
                # Always store the contour for colorbar display
                precip_contours[p_type] = (contour, cmap, norm, levels)
            
            # Set im to the first available contour for compatibility with later code
            im = list(precip_contours.values())[0][0] if precip_contours else None
            
            # Plot MSLP Contours
            cs_mslp = ax.contour(
                lon_vals, lat_vals, mslp_data,
                levels=np.arange(960, 1060, 4),
                colors='black',
                linewidths=1.2,
                transform=ccrs.PlateCarree(),
                zorder=12
            )
            ax.clabel(cs_mslp, inline=True, fontsize=9, fmt='%d', zorder=13)
            
            # Plot Dual-Color Thickness
            if thickness_data is not None:
                # ... (rest of the logic)
                # Cold thickness (<= 540) - Blue
                cold_levels = np.arange(480, 541, 6)
                cs_cold = ax.contour(
                    lon_vals, lat_vals, thickness_data,
                    levels=cold_levels,
                    colors='blue',
                    linewidths=1.2,
                    linestyles='dashed',
                    transform=ccrs.PlateCarree(),
                    zorder=11
                )
                ax.clabel(cs_cold, inline=True, fontsize=8, fmt='%d', colors='blue')
                
                # Warm thickness (> 546) - Red
                warm_levels = np.arange(552, 601, 6)
                cs_warm = ax.contour(
                    lon_vals, lat_vals, thickness_data,
                    levels=warm_levels,
                    colors='red',
                    linewidths=1.2,
                    linestyles='dashed',
                    transform=ccrs.PlateCarree(),
                    zorder=11
                )
                ax.clabel(cs_warm, inline=True, fontsize=8, fmt='%d', colors='red')
                
                # 546 line itself in Red
                ax.contour(lon_vals, lat_vals, thickness_data, levels=[546], 
                           colors='red', linewidths=1.2, linestyles='dashed', 
                           transform=ccrs.PlateCarree(), zorder=11)
            
            # Label HIGH/LOW (MSLP Precip case)
            mslp_data_to_label = mslp_data
        elif is_850mb_map:
            # 850mb Temp shading
            lon_vals = data.coords.get('lon', data.coords.get('longitude'))
            lat_vals = data.coords.get('lat', data.coords.get('latitude'))
            # Use Celsius levels from -40 to 46 with 1 degree increments for smoothness
            temp_levels = np.arange(-40, 47, 1)
            
            im = ax.contourf(
                lon_vals, lat_vals, data,
                transform=ccrs.PlateCarree(),
                cmap=cmap,
                levels=temp_levels,
                extend='both',
                zorder=1
            )
            
            # MSLP Contours
            mslp_data = self._process_mslp(ds)
            cs_mslp = ax.contour(
                lon_vals, lat_vals, mslp_data,
                levels=np.arange(960, 1060, 4),
                colors='black',
                linewidths=1.0,
                transform=ccrs.PlateCarree(),
                zorder=12
            )
            ax.clabel(cs_mslp, inline=True, fontsize=9, fmt='%d', zorder=13)
            
            # Wind Arrows (Black)
            u = ds['ugrd_850'].squeeze()
            v = ds['vgrd_850'].squeeze()
            
            # Subsample for readability
            skip = 4
            ax.quiver(
                lon_vals[::skip].values, lat_vals[::skip].values, 
                u[::skip, ::skip].values, v[::skip, ::skip].values,
                transform=ccrs.PlateCarree(),
                color='black',
                scale=400,
                width=0.005,
                zorder=14
            )
            
            # Set this so the H/L labeling logic runs
            mslp_data_to_label = mslp_data
        elif variable == "radar" or variable == "radar_reflectivity":
            # Radar reflectivity with standard dBZ levels
            lon_vals = data.coords.get('lon', data.coords.get('longitude'))
            lat_vals = data.coords.get('lat', data.coords.get('latitude'))
            # Standard radar reflectivity levels (dBZ)
            radar_levels = np.arange(-10, 70, 5)  # -10 to 65 dBZ in 5 dBZ increments
            
            im = ax.contourf(
                lon_vals, lat_vals, data,
                transform=ccrs.PlateCarree(),
                cmap=cmap,
                levels=radar_levels,
                extend='max',
                zorder=1
            )
        elif is_wind_speed_map:
            # Wind Speed with Streamlines
            lon_vals = data.coords.get('lon', data.coords.get('longitude'))
            lat_vals = data.coords.get('lat', data.coords.get('latitude'))
            
            # Wind speed levels matching the screenshot (0-100 mph)
            wind_levels = [0, 4, 6, 8, 9, 10, 12, 14, 16, 20, 22, 24, 26, 30, 34, 36, 40, 44, 48, 52, 58, 64, 70, 75, 85, 95, 100]
            
            # Plot filled contours for wind speed
            im = ax.contourf(
                lon_vals, lat_vals, data,
                transform=ccrs.PlateCarree(),
                cmap=cmap,
                levels=wind_levels,
                extend='max',
                zorder=1
            )
            
            # Add contour lines with labels for key wind speeds
            contour_levels = [3, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 60, 70, 80, 90]
            cs = ax.contour(
                lon_vals, lat_vals, data,
                levels=contour_levels,
                colors='black',
                linewidths=0.5,
                alpha=0.6,
                transform=ccrs.PlateCarree(),
                zorder=3
            )
            # Add labels to contour lines
            ax.clabel(cs, inline=True, fontsize=8, fmt='%d', zorder=4)
            
            # Get wind components for streamlines
            u_var = None
            v_var = None
            
            if 'u10' in ds:
                u_var = ds['u10']
                v_var = ds['v10']
            elif 'ugrd10m' in ds and 'vgrd10m' in ds:
                u_var = ds['ugrd10m']
                v_var = ds['vgrd10m']
            else:
                # Try to find wind variables
                u_vars = [v for v in ds.data_vars if 'u' in v.lower() and '10' in v.lower()]
                v_vars = [v for v in ds.data_vars if 'v' in v.lower() and '10' in v.lower()]
                if u_vars and v_vars:
                    u_var = ds[u_vars[0]]
                    v_var = ds[v_vars[0]]
            
            if u_var is not None and v_var is not None:
                # Extract u and v components
                u = u_var.isel(time=0) if 'time' in u_var.dims else u_var
                v = v_var.isel(time=0) if 'time' in v_var.dims else v_var
                
                # Add streamlines to show wind direction
                # Use a moderate density for clarity
                ax.streamplot(
                    lon_vals.values, lat_vals.values, 
                    u.values, v.values,
                    transform=ccrs.PlateCarree(),
                    color='black',
                    linewidth=0.6,
                    density=1.5,
                    arrowsize=0.8,
                    arrowstyle='->',
                    zorder=2
                )
        else:
            # Continuous data
            # For temperature, use fixed levels for consistent colors across all maps
            if variable in ["temperature_2m", "temp"]:
                # Use 2.5 degree increments to make the gradient smoother 
                # while keeping labels consistent with your 5-degree target
                temp_levels = np.arange(-40, 122.5, 2.5)
            elif variable in ["precipitation", "precip"]:
                # Fixed precipitation levels matching the known-good color scale (in inches)
                # These levels are defined above in the colormap section
                temp_levels = precip_levels
            else:
                temp_levels = 20  # Auto levels for other variables
            
            # Extract coordinates - handle both 'lon'/'lat' and 'longitude'/'latitude' naming
            lon_coord_name = 'lon' if 'lon' in data.coords else 'longitude'
            lat_coord_name = 'lat' if 'lat' in data.coords else 'latitude'
            lon_vals = data.coords[lon_coord_name]
            lat_vals = data.coords[lat_coord_name]
            
            # Log coordinate info for debugging
            logger.debug(f"Using coordinates: {lon_coord_name}, {lat_coord_name}")
            logger.debug(f"Lon range: {float(lon_vals.min()):.2f} to {float(lon_vals.max()):.2f}")
            logger.debug(f"Lat range: {float(lat_vals.min()):.2f} to {float(lat_vals.max()):.2f}")
            logger.debug(f"Data shape: {data.shape}, Lon shape: {lon_vals.shape}, Lat shape: {lat_vals.shape}")
            
            # For precipitation, use BoundaryNorm for discrete color mapping
            if variable in ["precipitation", "precip"]:
                im = ax.contourf(
                    lon_vals, lat_vals, data,
                    transform=ccrs.PlateCarree(),
                    cmap=cmap,
                    norm=precip_norm,
                    levels=temp_levels,
                    extend='both',
                    zorder=1
                )
            else:
                im = ax.contourf(
                    lon_vals, lat_vals, data,
                    transform=ccrs.PlateCarree(),
                    cmap=cmap,
                    levels=temp_levels,
                    extend='both',
                    zorder=1
                )
        
        # Add shared HIGH/LOW labels if MSLP data is available
        if 'mslp_data_to_label' in locals() and mslp_data_to_label is not None:
            try:
                from scipy.ndimage import maximum_filter, minimum_filter
                mslp_array = mslp_data_to_label.values
                local_max = maximum_filter(mslp_array, size=20) == mslp_array
                local_min = minimum_filter(mslp_array, size=20) == mslp_array
                
                # Use lon/lat from the data itself
                lons = mslp_data_to_label.coords.get('lon', mslp_data_to_label.coords.get('longitude'))
                lats = mslp_data_to_label.coords.get('lat', mslp_data_to_label.coords.get('latitude'))
                is_360 = lons.max() > 180
                
                west = -125.0 % 360 if is_360 else -125.0
                east = -110.0 % 360 if is_360 else -110.0
                lon_min, lon_max = (west, east) if west < east else (west, 360)
                lat_min, lat_max = 42.5, 48.5
                
                for i in range(5, len(lats) - 5):
                    for j in range(5, len(lons) - 5):
                        lat_v, lon_v = lats[i], lons[j]
                        if not (lon_min <= lon_v <= lon_max and lat_min <= lat_v <= lat_max):
                            continue
                        val = mslp_array[i, j]
                        if local_max[i, j] and val > 1013:
                            ax.text(lon_v, lat_v, 'H', transform=ccrs.PlateCarree(), fontsize=16, fontweight='bold', ha='center', color='blue', zorder=15)
                            ax.text(lon_v, lat_v - 0.2, f'{int(val)}', transform=ccrs.PlateCarree(), fontsize=10, fontweight='bold', ha='center', color='blue', zorder=15)
                        elif local_min[i, j] and val < 1013:
                            ax.text(lon_v, lat_v, 'L', transform=ccrs.PlateCarree(), fontsize=16, fontweight='bold', ha='center', color='red', zorder=15)
                            ax.text(lon_v, lat_v - 0.2, f'{int(val)}', transform=ccrs.PlateCarree(), fontsize=10, fontweight='bold', ha='center', color='red', zorder=15)
            except Exception as e:
                logger.warning(f"Error labeling H/L: {e}")
        
        
        # Add colorbar
        if variable in ["precipitation_type", "precip_type"]:
            cbar = plt.colorbar(im, ax=ax, orientation='horizontal', pad=0.05, aspect=40, 
                               ticks=[0, 1, 2, 3])
            cbar.set_ticklabels(['No Precip', 'Rain', 'Snow', 'Freezing'])
            cbar.set_label("Precipitation Type")
        elif is_mslp_precip:
            # Create colorbars for ALL precipitation types (always show all 4)
            if 'precip_contours' in locals() and precip_contours:
                # Define precipitation type labels in desired order
                precip_order = ['rain', 'frzr', 'sleet', 'snow']
                precip_labels = {
                    'rain': 'Rain',
                    'frzr': 'Freezing Rain',
                    'sleet': 'Sleet',
                    'snow': 'Snow'
                }
                
                # Always create 4 colorbars
                num_cbars = 4
                
                # Create multiple colorbars side by side
                cbar_width = 0.20  # Fixed width for each
                cbar_height = 0.03
                cbar_bottom = 0.06
                cbar_spacing = 0.01
                
                # Calculate starting position to center all colorbars
                total_width = (num_cbars * cbar_width) + ((num_cbars - 1) * cbar_spacing)
                left_start = (1.0 - total_width) / 2
                
                for idx, p_type in enumerate(precip_order):
                    # Calculate position for this colorbar
                    left_position = left_start + idx * (cbar_width + cbar_spacing)
                    
                    # Create axes for colorbar
                    cbar_ax = fig.add_axes([left_position, cbar_bottom, cbar_width, cbar_height])
                    
                    # Get contour data for this type
                    contour, cmap, norm, levels = precip_contours[p_type]
                    
                    # Create colorbar
                    cbar = plt.colorbar(contour, cax=cbar_ax, orientation='horizontal', 
                                       cmap=cmap, norm=norm)
                    
                    # Set appropriate tick positions based on type
                    if p_type == 'rain':
                        tick_positions = [0.1, 0.5, 1.5, 2.5, 4, 6, 10, 16, 24]
                    else:
                        tick_positions = [0.1, 0.5, 1, 2, 3, 4, 6, 10, 14]
                    
                    cbar.set_ticks(tick_positions)
                    cbar.set_label(f"{precip_labels[p_type]} (mm/hr)", fontsize=9)
                    cbar.ax.tick_params(labelsize=7)
                    cbar.ax.tick_params(labelsize=8)
                    
                    idx += 1
            else:
                # Fallback to single colorbar if no precipitation types detected
                cbar = plt.colorbar(im, ax=ax, orientation='horizontal', pad=0.05, aspect=40)
                tick_positions = [0.1, 0.5, 1, 2.5, 4, 6, 10, 14, 16, 18]
                cbar.set_ticks(tick_positions)
                cbar.set_label("6-hour Averaged Precip Rate (mm/hr), MSLP (hPa), & 1000-500mb Thick (dam)")
        elif is_850mb_map:
            cbar = plt.colorbar(im, ax=ax, orientation='horizontal', pad=0.05, aspect=40)
            cbar.set_label("850mb Temperature (°F), Wind (arrows, mph), MSLP (hPa)")
        elif is_wind_speed_map:
            cbar = plt.colorbar(im, ax=ax, orientation='horizontal', pad=0.05, aspect=40)
            # Set tick positions for wind speed colorbar to match the screenshot
            tick_positions = [0, 4, 6, 8, 10, 12, 14, 16, 20, 22, 24, 26, 30, 34, 36, 40, 44, 48, 52, 58, 64, 70, 75, 85, 95, 100]
            cbar.set_ticks(tick_positions)
            cbar.set_label("10m Wind Speed + Streamlines (mph)")
        elif variable == "radar" or variable == "radar_reflectivity":
            cbar = plt.colorbar(im, ax=ax, orientation='horizontal', pad=0.05, aspect=40)
            cbar.set_label("Simulated Composite Radar Reflectivity (dBZ)")
        elif variable in ["precipitation", "precip"]:
            # Custom colorbar with specific tick labels matching the increments
            # Use the same norm for the colorbar
            cbar = plt.colorbar(im, ax=ax, orientation='horizontal', pad=0.05, aspect=40, norm=precip_norm)
            # Set tick positions at the boundaries between color segments
            tick_positions = [0.01, 0.05, 0.1, 0.2, 0.3, 0.5, 0.7, 0.9, 1.2, 1.6, 2, 3, 4, 6, 8, 10, 12, 14, 16, 18, 20]
            cbar.set_ticks(tick_positions)
            cbar.set_label("Total Precipitation (inches)")
        else:
            cbar = plt.colorbar(im, ax=ax, orientation='horizontal', pad=0.05, aspect=40)
            cbar.set_label(f"{variable.replace('_', ' ').title()} ({units})")
        
        # Add gridlines
        gl = ax.gridlines(crs=ccrs.PlateCarree(), draw_labels=False,
                         linewidth=0.5, color='gray', alpha=0.5, linestyle='--')
        
        # Add title at the TOP of the figure with Init/Forecast/Valid info
        # Format times
        init_time = run_time.strftime("%Hz %b %d %Y") if run_time else "Latest"
        valid_time = (run_time + timedelta(hours=forecast_hour)) if run_time else None
        valid_str = valid_time.strftime("%Hz %a, %b %d %Y") if valid_time else ""
        
        # Build title based on map type
        if variable in ["precipitation", "precip"]:
            map_title = "GFS Total Precip (in)"
        elif is_mslp_precip:
            map_title = "GFS 6-hour Averaged Precip Rate (mm/hr), MSLP (hPa), & 1000-500mb Thick (dam)"
        elif is_850mb_map:
            map_title = "GFS 850mb Temperature (°F), Wind, & MSLP (hPa)"
        elif is_wind_speed_map:
            map_title = "GFS 10m Wind Speed (mph) & Streamlines"
        elif variable == "radar" or variable == "radar_reflectivity":
            map_title = "GFS Simulated Composite Radar Reflectivity (dBZ)"
        elif variable in ["temperature_2m", "temp"]:
            map_title = "GFS 2m Temperature (°F)"
        else:
            map_title = f"{model} {variable.replace('_', ' ').title()}"
        
        # Add second line with Init/Forecast/Valid info
        info_line = f"Init: {init_time}   Forecast Hour: [{forecast_hour}]  valid at {valid_str}"
        title_text = f"{map_title}\n{info_line}"
        
        # Adjust figure layout to make title nearly flush with map
        plt.subplots_adjust(top=0.96)  # Significantly reduce top margin
        
        # Add title with explicit position very close to map
        fig.suptitle(title_text, fontsize=12, fontweight='bold', y=0.995)
        
        # Add station overlays if enabled
        if settings.station_overlays and variable not in ["precipitation_type", "precip_type", "radar", "radar_reflectivity"]:
            try:
                station_values = None
                
                # Determine which dataset variable to use for extraction
                if variable in ["temperature_2m", "temp"]:
                    extract_var = 't2m' if 't2m' in ds else 'tmp2m'
                    station_values = self.extract_station_values(
                        ds, extract_var, 
                        region=region_to_use,
                        priority_level=settings.station_priority
                    )
                    # Convert K to F for display
                    station_values = {k: (v - 273.15) * 9/5 + 32 if v > 100 else v
                                    for k, v in station_values.items()}
                
                elif variable in ["temp_850_wind_mslp", "850mb"]:
                    station_values = self.extract_station_values(
                        ds, 'tmp_850', 
                        region=region_to_use,
                        priority_level=settings.station_priority
                    )
                    # Convert K to C for 850mb map
                    station_values = {k: (v - 273.15) if v > 100 else v
                                    for k, v in station_values.items()}
                    
                elif variable in ["precipitation", "precip"]:
                    # Use 'tp' (total precipitation accumulated) instead of 'prate' (rate)
                    extract_var = 'tp' if 'tp' in ds else 'prate'
                    station_values = self.extract_station_values(
                        ds, extract_var, 
                        region=region_to_use,
                        priority_level=settings.station_priority
                    )
                    # Convert based on variable type
                    if extract_var == 'tp':
                        # tp is already in mm, just convert to inches
                        station_values = {k: v / 25.4 for k, v in station_values.items()}
                    else:
                        # prate is in kg/m²/s, convert to inches (hourly accumulation)
                        station_values = {k: v * 3600 * 0.0393701 
                                        for k, v in station_values.items()}
                    
                elif variable in ["wind_speed_10m", "wind_speed"]:
                    # Wind speed requires calculating magnitude from u and v components
                    from app.services.stations import get_stations_for_region
                    stations = get_stations_for_region(region_to_use, settings.station_priority)
                    station_values = {}
                    
                    # Detect coordinate names in dataset
                    lat_coord_name = 'latitude' if 'latitude' in ds.coords else 'lat'
                    lon_coord_name = 'longitude' if 'longitude' in ds.coords else 'lon'
                    
                    # Detect if dataset uses 0-360 longitude format
                    lon_vals = ds.coords[lon_coord_name].values
                    uses_360_format = lon_vals.min() >= 0 and lon_vals.max() > 180
                    
                    for station_name, station_data in stations.items():
                        try:
                            # Extract u and v components (try both naming conventions)
                            u_var = 'u10' if 'u10' in ds else 'ugrd10m' if 'ugrd10m' in ds else None
                            v_var = 'v10' if 'v10' in ds else 'vgrd10m' if 'vgrd10m' in ds else None
                            
                            if u_var is None or v_var is None:
                                logger.warning(f"Could not find wind components for station {station_name}")
                                continue
                            
                            station_lat = station_data['lat']
                            station_lon = station_data['lon']
                            
                            # Convert longitude to match dataset format if needed
                            if uses_360_format and station_lon < 0:
                                station_lon = station_lon % 360
                            
                            # Build selector dictionary dynamically
                            selector = {
                                lat_coord_name: station_lat,
                                lon_coord_name: station_lon
                            }
                            
                            u = ds[u_var].sel(**selector, method='nearest').values
                            v = ds[v_var].sel(**selector, method='nearest').values
                            
                            # Handle numpy arrays
                            if hasattr(u, 'item'):
                                u = u.item()
                            if hasattr(v, 'item'):
                                v = v.item()
                            
                            # Calculate wind speed magnitude
                            wind_speed = np.sqrt(u**2 + v**2)
                            # Convert m/s to mph
                            wind_speed_mph = wind_speed * 2.23694
                            station_values[station_name] = float(wind_speed_mph)
                            
                        except Exception as e:
                            logger.warning(f"Could not extract wind speed for station {station_name}: {e}")
                            continue
                
                if station_values:
                    self.plot_station_overlays(
                        ax, station_values, variable,
                        region=region_to_use,
                        transform=ccrs.PlateCarree()
                    )
                    logger.info(f"Added station overlays: {len(station_values)} stations")
                    
            except Exception as e:
                # Don't fail the whole map generation if overlays fail
                logger.warning(f"Could not add station overlays: {e}")
        
        # Save image
        if run_time:
            run_str = run_time.strftime("%Y%m%d_%H")
        else:
            run_str = datetime.utcnow().strftime("%Y%m%d_%H")
        
        filename = f"{model.lower()}_{run_str}_{variable}_{forecast_hour}.png"
        filepath = self.storage_path / filename
        
        plt.savefig(filepath, dpi=settings.map_dpi, bbox_inches='tight', facecolor='white')
        
        # Verify file was created and has content
        if not filepath.exists():
            raise IOError(f"Failed to save map file: {filepath}")
        file_size = filepath.stat().st_size
        if file_size == 0:
            raise IOError(f"Map file is empty: {filepath}")
        logger.debug(f"Map file saved: {filepath} ({file_size} bytes)")
        
        # Aggressive memory cleanup
        plt.clf()
        plt.cla()
        plt.close('all')
        
        # Force garbage collection for this specific map's objects
        import gc
        gc.collect()
        
        logger.info(f"Map saved to: {filepath}")
        return filepath
    
    def _process_temperature(self, ds: xr.Dataset) -> xr.DataArray:
        """Process temperature data"""
        # GFS variable names may vary - adjust as needed
        if 't2m' in ds:
            temp = ds['t2m'] - 273.15  # Convert K to C
        elif 'tmp2m' in ds:
            temp = ds['tmp2m'] - 273.15
        elif 'TMP_2maboveground' in ds:
            temp = ds['TMP_2maboveground'] - 273.15
        else:
            # Try to find temperature variable
            temp_vars = [v for v in ds.data_vars if 'tmp' in v.lower() or 't2m' in v.lower() or 'temp' in v.lower()]
            if temp_vars:
                temp = ds[temp_vars[0]] - 273.15
            else:
                raise ValueError("Could not find temperature variable in dataset")
        
        # Convert Celsius to Fahrenheit for PNW users
        temp = (temp * 9/5) + 32
        
        return temp.isel(time=0) if 'time' in temp.dims else temp
    
    def _process_precipitation(self, ds: xr.Dataset, forecast_hour: int = 0) -> xr.DataArray:
        """
        Process precipitation data.
        
        NOTE: This method is called from generate_map() which now receives a dataset
        that already contains the correctly summed total precipitation (via
        fetch_total_precipitation). We just need to extract and clean it.
        
        Args:
            ds: Dataset containing total precipitation (already summed across forecast hours)
            forecast_hour: Target forecast hour (used for logging)
            
        Returns:
            Precipitation in inches
        """
        if 'tp' in ds:
            # tp is total precipitation (accumulated), already in mm
            # Dataset from fetch_total_precipitation already has correct total
            precip = ds['tp']
            
            # Log metadata for debugging
            logger.info(f"tp variable found. Dims: {precip.dims}, Shape: {precip.shape}")
            logger.info(f"tp coords: {list(precip.coords.keys())}")
            
            # Clean up any remaining time-related coordinates
            # (fetch_total_precipitation should have already cleaned these)
            if 'step' in precip.coords:
                step_val = precip.coords['step'].values
                import numpy as np
                step_array = np.atleast_1d(step_val)
                logger.info(f"tp step coordinate values: {step_array}")
            
            # Check for valid_time dimension
            if 'valid_time' in precip.coords:
                valid_times = precip.coords['valid_time'].values
                logger.info(f"tp valid_time coordinate values: {valid_times}")
                if hasattr(valid_times, '__len__') and len(valid_times) > 1:
                    precip = precip.isel(valid_time=0)
                    logger.info(f"Selected first valid_time")
            
            # Check for time dimension
            if 'time' in precip.coords:
                time_vals = precip.coords['time'].values
                logger.info(f"tp time coordinate values: {time_vals}")
                if hasattr(time_vals, '__len__') and len(time_vals) > 1:
                    precip = precip.isel(time=0)
            
            if hasattr(precip, 'attrs'):
                # Log key GRIB attributes for debugging
                grib_attrs = {
                    'GRIB_stepType': precip.attrs.get('GRIB_stepType', 'N/A'),
                    'GRIB_stepUnits': precip.attrs.get('GRIB_stepUnits', 'N/A'),
                    'units': precip.attrs.get('units', 'N/A'),
                    'long_name': precip.attrs.get('long_name', 'N/A')
                }
                logger.info(f"tp GRIB attrs: {grib_attrs}")
            
            # Squeeze out any single-element dimensions
            precip = precip.squeeze()
            
        elif 'prate' in ds:
            # For forecast hour 0 (analysis), tp might not exist, use prate
            # Convert kg/m²/s to mm/h, then treat as hourly accumulation
            precip = ds['prate'] * 3600  # mm/h
        elif 'APCP_surface' in ds:
            precip = ds['APCP_surface']
        else:
            precip_vars = [v for v in ds.data_vars if 'prate' in v.lower() or 'precip' in v.lower() or v.lower() == 'tp']
            if precip_vars:
                precip = ds[precip_vars[0]]
                # If it's prate, convert from kg/m²/s to mm/h
                if 'prate' in precip_vars[0].lower():
                    precip = precip * 3600
            else:
                raise ValueError("Could not find precipitation variable in dataset")
        
        # Log value range before conversion
        if hasattr(precip, 'values'):
            precip_values = precip.values
            if hasattr(precip_values, 'min') and hasattr(precip_values, 'max'):
                logger.info(f"Precipitation range (mm): min={float(precip_values.min()):.4f}, max={float(precip_values.max()):.4f}, mean={float(precip_values.mean()):.4f}")
                logger.debug(f"Precipitation dims: {precip.dims}, coords: {list(precip.coords.keys())}")
                
                # Log a few sample values at specific coordinates for comparison
                # Known-good map shows peak around 125°W, 48°N with value 3.03"
                try:
                    lon_coord = 'lon' if 'lon' in precip.coords else 'longitude'
                    lat_coord = 'lat' if 'lat' in precip.coords else 'latitude'
                    
                    lon_vals = precip.coords[lon_coord].values
                    lat_vals = precip.coords[lat_coord].values
                    
                    # Handle 0-360 longitude format
                    lon_is_0_360 = lon_vals.min() >= 0 and lon_vals.max() > 180
                    
                    # Find where the maximum value actually is
                    max_idx = np.unravel_index(np.argmax(precip.values), precip.shape)
                    max_lon = float(lon_vals[max_idx[1] if len(max_idx) > 1 else max_idx[0]])
                    max_lat = float(lat_vals[max_idx[0] if len(max_idx) > 1 else max_idx[1]])
                    max_val_mm = float(precip.values[max_idx])
                    max_val_inches = max_val_mm / 25.4
                    
                    # Convert to -180 to 180 if needed
                    if lon_is_0_360 and max_lon > 180:
                        max_lon = max_lon - 360
                    
                    logger.info(f"Maximum precipitation location: {max_lon:.2f}°W, {max_lat:.2f}°N = {max_val_mm:.4f} mm = {max_val_inches:.4f} inches")
                    
                    # Try to get value near known peak location (125°W, 48°N)
                    test_lon = -125.0
                    test_lat = 48.0
                    
                    if lon_is_0_360:
                        test_lon_sel = test_lon % 360
                    else:
                        test_lon_sel = test_lon
                    
                    sample_value = precip.sel(
                        {lon_coord: test_lon_sel, lat_coord: test_lat},
                        method='nearest'
                    ).values
                    
                    if hasattr(sample_value, 'item'):
                        sample_value = sample_value.item()
                    sample_inches = float(sample_value) / 25.4
                    
                    # Get the actual coordinates of the selected point
                    actual_lon = float(precip.sel({lon_coord: test_lon_sel, lat_coord: test_lat}, method='nearest').coords[lon_coord].values)
                    actual_lat = float(precip.sel({lon_coord: test_lon_sel, lat_coord: test_lat}, method='nearest').coords[lat_coord].values)
                    if lon_is_0_360 and actual_lon > 180:
                        actual_lon = actual_lon - 360
                    
                    logger.info(f"Sample value at requested ~125°W, 48°N (actual: {actual_lon:.2f}°W, {actual_lat:.2f}°N): {float(sample_value):.4f} mm = {sample_inches:.4f} inches (known-good shows ~3.03\" at 125°W, 48°N)")
                    
                    # Check a few more locations for comparison
                    test_points = [
                        (-123.0, 47.0, "Seattle area"),
                        (-122.0, 45.5, "Portland area"),
                        (-120.0, 46.0, "Central WA"),
                    ]
                    for test_lon_pt, test_lat_pt, label in test_points:
                        if lon_is_0_360:
                            test_lon_sel_pt = test_lon_pt % 360
                        else:
                            test_lon_sel_pt = test_lon_pt
                        try:
                            pt_value = precip.sel(
                                {lon_coord: test_lon_sel_pt, lat_coord: test_lat_pt},
                                method='nearest'
                            ).values
                            if hasattr(pt_value, 'item'):
                                pt_value = pt_value.item()
                            pt_inches = float(pt_value) / 25.4
                            logger.debug(f"  {label} ({test_lon_pt:.1f}°W, {test_lat_pt:.1f}°N): {pt_inches:.4f}\"")
                        except:
                            pass
                except Exception as e:
                    logger.debug(f"Could not get sample values: {e}")
        
        # Convert mm to inches for PNW users
        precip = precip / 25.4
        
        # Log value range after conversion
        if hasattr(precip, 'values'):
            precip_values = precip.values
            if hasattr(precip_values, 'min') and hasattr(precip_values, 'max'):
                logger.info(f"Precipitation range (inches): min={float(precip_values.min()):.4f}, max={float(precip_values.max()):.4f}, mean={float(precip_values.mean()):.4f}")
        
        return precip.isel(time=0) if 'time' in precip.dims else precip
    
    def _process_radar_reflectivity(self, ds: xr.Dataset) -> xr.DataArray:
        """Process simulated radar reflectivity (composite reflectivity)
        
        If refc is not available, calculate simulated reflectivity from precipitation rate.
        This is a workaround since GFS GRIB files don't always include refc.
        """
        # Try to find actual composite reflectivity first
        if 'refc' in ds:
            reflectivity = ds['refc']
        elif 'REFC' in ds:
            reflectivity = ds['REFC']
        else:
            # Try to find reflectivity variable (case-insensitive)
            refc_vars = [v for v in ds.data_vars if 'refc' in v.lower() or 'reflectivity' in v.lower()]
            if refc_vars:
                logger.info(f"Found reflectivity variable: {refc_vars[0]}")
                reflectivity = ds[refc_vars[0]]
            else:
                # refc not available - calculate simulated reflectivity from precipitation
                logger.warning("refc not available in GRIB file, calculating simulated reflectivity from precipitation")
                
                # Get precipitation rate (mm/h)
                if 'prate' in ds:
                    prate = ds['prate'] * 3600  # Convert kg/m²/s to mm/h
                elif 'tp' in ds:
                    # For accumulated, estimate hourly rate (rough approximation)
                    prate = ds['tp'] / max(1, ds['tp'].attrs.get('step', 1))  # Divide by forecast hour
                else:
                    raise ValueError("Cannot calculate radar reflectivity: need prate or tp")
                
                # Convert precipitation rate (mm/h) to dBZ using Marshall-Palmer relationship
                # Z = 200 * R^1.6, where Z is reflectivity factor and R is rain rate (mm/h)
                # dBZ = 10 * log10(Z)
                # For R > 0.1 mm/h: dBZ ≈ 10 * log10(200 * R^1.6)
                # For R <= 0.1 mm/h: use lower bound
                import numpy as np
                prate_values = prate.values if hasattr(prate, 'values') else prate
                # Handle NaN and inf values
                prate_values = np.nan_to_num(prate_values, nan=0.0, posinf=0.0, neginf=0.0)
                # Avoid log of zero/negative
                prate_values = np.maximum(prate_values, 0.01)  # Minimum 0.01 mm/h
                z_factor = 200 * (prate_values ** 1.6)
                dbz = 10 * np.log10(z_factor)
                # Clamp to reasonable range (-10 to 70 dBZ) and handle any remaining invalid values
                dbz = np.clip(dbz, -10, 70)
                dbz = np.nan_to_num(dbz, nan=-10.0, posinf=70.0, neginf=-10.0)
                
                # Create DataArray with same coordinates as prate
                reflectivity = xr.DataArray(
                    dbz,
                    coords=prate.coords,
                    dims=prate.dims,
                    attrs={'units': 'dBZ', 'long_name': 'Simulated radar reflectivity from precipitation'}
                )
        
        # Handle time dimension if present
        return reflectivity.isel(time=0) if 'time' in reflectivity.dims else reflectivity
    
    def _process_wind_speed(self, ds: xr.Dataset) -> xr.DataArray:
        """Process wind speed data"""
        # Try common GFS wind variable names
        u_var = None
        v_var = None
        
        if 'u10' in ds:
            u_var = ds['u10']
            v_var = ds['v10']
        elif 'ugrd10m' in ds and 'vgrd10m' in ds:
            u_var = ds['ugrd10m']
            v_var = ds['vgrd10m']
        else:
            # Try to find wind variables
            u_vars = [v for v in ds.data_vars if 'u' in v.lower() and '10' in v.lower()]
            v_vars = [v for v in ds.data_vars if 'v' in v.lower() and '10' in v.lower()]
            if u_vars and v_vars:
                u_var = ds[u_vars[0]]
                v_var = ds[v_vars[0]]
        
        if u_var is None or v_var is None:
            raise ValueError("Could not find wind components in dataset")
        
        wind_speed = np.sqrt(u_var**2 + v_var**2)
        # Convert m/s to mph
        wind_speed = wind_speed * 2.237
        
        return wind_speed.isel(time=0) if 'time' in wind_speed.dims else wind_speed
    
    def _process_wind_gusts(self, ds: xr.Dataset) -> xr.DataArray:
        """Process wind gusts data"""
        # GFS may have gust data, or we calculate from wind components
        if 'gust' in str(ds.data_vars).lower():
            # Try to find gust variable
            gust_vars = [v for v in ds.data_vars if 'gust' in v.lower()]
            if gust_vars:
                gusts = ds[gust_vars[0]]
                # Convert m/s to mph if needed
                if gusts.max() < 50:  # Likely in m/s
                    gusts = gusts * 2.237
            else:
                # Fallback: use wind speed as proxy (gusts are typically 1.3-1.5x wind speed)
                u = ds.get('ugrd10m', None)
                v = ds.get('vgrd10m', None)
                if u is not None and v is not None:
                    wind_speed = np.sqrt(u**2 + v**2) * 2.237  # Convert to mph
                    gusts = wind_speed * 1.4  # Approximate gust factor
                else:
                    raise ValueError("Could not find wind gust data or wind components")
        else:
            # Calculate from wind speed with gust factor
            u = ds.get('ugrd10m', None)
            v = ds.get('vgrd10m', None)
            if u is not None and v is not None:
                wind_speed = np.sqrt(u**2 + v**2) * 2.237  # Convert to mph
                gusts = wind_speed * 1.4  # Approximate gust factor
            else:
                raise ValueError("Could not find wind components for gust calculation")
        
        return gusts.isel(time=0) if 'time' in gusts.dims else gusts
    
    def _process_precipitation_type(self, ds: xr.Dataset) -> xr.DataArray:
        """Process precipitation type data (rain, snow, sleet, freezing rain)"""
        # GFS doesn't directly provide precip type, but we can infer from:
        # - Temperature at 2m and 850mb
        # - Precipitation rate
        # This is a simplified version - may need refinement
        
        # Get temperature data
        if 't2m' in ds:
            temp_2m = ds['t2m'] - 273.15  # Convert K to C
        elif 'tmp2m' in ds:
            temp_2m = ds['tmp2m'] - 273.15
        else:
            temp_vars = [v for v in ds.data_vars if ('tmp' in v.lower() or 't2m' in v.lower()) and '2' in v.lower()]
            if temp_vars:
                temp_2m = ds[temp_vars[0]] - 273.15
            else:
                raise ValueError("Could not find 2m temperature for precip type")
        
        # Get precipitation
        if 'prate' in ds:
            precip = ds['prate'] * 3600  # Convert to mm/h
        else:
            precip_vars = [v for v in ds.data_vars if 'prate' in v.lower() or 'precip' in v.lower()]
            if precip_vars:
                precip = ds[precip_vars[0]]
                # Check if it needs conversion
                if precip.max() < 1:  # Likely in kg/m²/s
                    precip = precip * 3600
            else:
                raise ValueError("Could not find precipitation for precip type")
        
        # Simple classification:
        # 0 = No precip
        # 1 = Rain (temp > 2°C)
        # 2 = Snow (temp < 0°C)
        # 3 = Freezing rain/sleet (0-2°C with precip)
        precip_type = xr.zeros_like(temp_2m)
        
        # No precipitation
        precip_type = xr.where(precip < 0.1, 0, precip_type)
        
        # Rain
        precip_type = xr.where((precip >= 0.1) & (temp_2m > 2), 1, precip_type)
        
        # Snow
        precip_type = xr.where((precip >= 0.1) & (temp_2m < 0), 2, precip_type)
        
        # Freezing rain/sleet
        precip_type = xr.where((precip >= 0.1) & (temp_2m >= 0) & (temp_2m <= 2), 3, precip_type)
        
        return precip_type.isel(time=0) if 'time' in precip_type.dims else precip_type
    
    def _process_mslp(self, ds: xr.Dataset) -> xr.DataArray:
        """Process Mean Sea Level Pressure data"""
        # Try common MSLP variable names
        if 'prmsl' in ds:
            mslp = ds['prmsl']
        elif 'msl' in ds:
            mslp = ds['msl']
        elif 'PRMSL_meansealevel' in ds:
            mslp = ds['PRMSL_meansealevel']
        else:
            # Try to find MSLP variable
            mslp_vars = [v for v in ds.data_vars if 'msl' in v.lower() or 'prmsl' in v.lower()]
            if mslp_vars:
                mslp = ds[mslp_vars[0]]
            else:
                raise ValueError("Could not find MSLP variable in dataset")
        
        # Convert Pa to mb (hPa) if needed
        if mslp.max() > 10000:  # Likely in Pa
            mslp = mslp / 100.0
        
        return mslp.isel(time=0) if 'time' in mslp.dims else mslp
    
    def _process_precipitation_mmhr(self, ds: xr.Dataset) -> xr.DataArray:
        """Process precipitation data in mm/hr (6-hour average rate)"""
               # Try common precipitation variable names
        precip = None
        
        # Check for 'tp' (Total Precipitation) - often used for accumulated precip
        if 'tp' in ds:
            precip = ds['tp']
            # If it's accumulated, we might need to handle it, but for GFS 6-hour files
            # it often represents the accumulation in that period.
        elif 'prate' in ds:
            # prate is in kg/m²/s, convert to mm/hr
            precip = ds['prate'] * 3600  # Convert to mm/h
        elif 'APCP_surface' in ds:
            precip = ds['APCP_surface']
        elif 'Total_precipitation' in ds:
            precip = ds['Total_precipitation']
        else:
            # Search for anything matching precip or prate
            precip_vars = [v for v in ds.data_vars if 'prate' in v.lower() or 'precip' in v.lower() or 'tp' == v.lower()]
            if precip_vars:
                precip = ds[precip_vars[0]]
                # Check if it needs conversion from kg/m2/s to mm/h
                if float(precip.max()) < 0.1:  # Likely in kg/m²/s
                    precip = precip * 3600
            else:
                # Log available variables to help debugging
                logger.warning(f"Available variables in dataset: {list(ds.data_vars)}")
                raise ValueError("Could not find precipitation variable in dataset")
        
        return precip.isel(time=0) if 'time' in precip.dims else precip
    
    def _process_thickness(self, ds: xr.Dataset) -> xr.DataArray:
        """Process 1000-500mb thickness (decameters)"""
        try:
            # Check if we have the separate gh_1000 and gh_500 variables
            if 'gh_1000' in ds and 'gh_500' in ds:
                gh_1000 = ds['gh_1000']
                gh_500 = ds['gh_500']
                logger.info("Using separate gh_1000 and gh_500 variables for thickness")
            elif 'gh' in ds:
                # Try to extract from multi-level gh variable
                gh_var = ds['gh']
                if 'isobaricInhPa' in gh_var.dims:
                    gh_1000 = gh_var.sel(isobaricInhPa=1000, method='nearest')
                    gh_500 = gh_var.sel(isobaricInhPa=500, method='nearest')
                elif 'level' in gh_var.dims:
                    gh_1000 = gh_var.sel(level=1000, method='nearest')
                    gh_500 = gh_var.sel(level=500, method='nearest')
                else:
                    logger.warning(f"Geopotential height does not have pressure level dimension: {gh_var.dims}")
                    return None
            else:
                logger.warning("Could not find geopotential height variables for thickness")
                return None
            
            # Remove time dimension if present
            if 'time' in gh_1000.dims:
                gh_1000 = gh_1000.isel(time=0)
            if 'time' in gh_500.dims:
                gh_500 = gh_500.isel(time=0)
            
            # Calculate thickness (in meters, convert to decameters)
            thickness = (gh_500 - gh_1000) / 10.0  # Convert m to dam (decameters)
            
            logger.info(f"Calculated thickness: range {float(thickness.min()):.1f} to {float(thickness.max()):.1f} dam")
            return thickness
            
        except Exception as e:
            logger.warning(f"Could not calculate thickness: {e}")
            return None
