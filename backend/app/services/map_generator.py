"""Map generation service"""
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt
from matplotlib import colors
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from cartopy.feature import NaturalEarthFeature
from cartopy.mpl.gridliner import LONGITUDE_FORMATTER, LATITUDE_FORMATTER
import xarray as xr
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
import logging
from typing import Optional
import os

# Additional matplotlib configuration to prevent hanging
matplotlib.rcParams['savefig.facecolor'] = 'white'
matplotlib.rcParams['figure.max_open_warning'] = 0  # Disable warning about too many figures
matplotlib.rcParams['agg.path.chunksize'] = 10000  # Larger chunks for better performance

# Set environment variables to help with cartopy/shapely issues
os.environ['CARTOPY_OFFLINE'] = '0'  # Allow downloading map data if needed

from app.config import settings
from app.services.stations import get_stations_for_region, format_station_value

logger = logging.getLogger(__name__)


class MapGenerator:
    """Generates weather forecast maps"""
    
    # Precipitation type configuration with levels and colors
    # Rain levels: 0.01, 0.1, 0.25, 0.5, 1.0, 1.5, 2.5, 4, 6, 10, 16, 24 mm/hr
    RAIN_LEVELS = [0.01, 0.1, 0.25, 0.5, 1.0, 1.5, 2.5, 4, 6, 10, 16, 24]
    # Snow levels: refined increments for better detail
    SNOW_LEVELS = [0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0, 14.0]
    # Other winter precip levels
    WINTER_LEVELS = [0.1, 0.5, 1, 2, 3, 4, 6, 10, 14]
    
    PRECIP_CONFIG = {
        'rain': {
            'levels': RAIN_LEVELS,
            # Colors matching TropicalTidbits: All greens until 4mm/hr, then yellow->orange->red->purple->magenta
            # 0.01-2.5: Various shades of green (light to dark)
            # 4+: Yellow -> Orange -> Red -> Dark Red -> Purple -> Magenta
            'colors': ['#90EE90', '#66DD66', '#33CC33', '#00BB00', '#009900', '#007700', '#005500', '#FFFF00', '#FFB300', '#FF6600', '#FF0000', '#FF00FF']
        },
        'frzr': {
            'levels': WINTER_LEVELS,
            'colors': ['#FFC0CB', '#FF69B4', '#FF1493', '#C71585', '#931040', '#B03060', '#D20000', '#FF2400', '#FF4500']
        },
        'sleet': {
            'levels': WINTER_LEVELS,
            'colors': ['#E0FFFF', '#ADD8E6', '#9370DB', '#8A2BE2', '#9400D3', '#800080', '#4B0082', '#8B008B', '#B22222']
        },
        'snow': {
            'levels': SNOW_LEVELS,
            # Custom refined snow colorbar with specific increments
            # Very light cyan -> cyan shades -> blues -> dark blues -> purples -> magentas
            # Note: First color is light cyan, not white, to avoid gaps between precip types
            'colors': [
                '#c0ffff',  # 0.1-0.25: Very light cyan (not white to avoid gaps)
                '#55ffff',  # 0.25-0.5
                '#4feaff',  # 0.5-0.75
                '#48d3ff',  # 0.75-1.0
                '#42bfff',  # 1.0-1.5
                '#3caaff',  # 1.5-2.0
                '#3693ff',  # 2.0-2.5
                '#2a69f1',  # 2.5-3.0
                '#1d42ca',  # 3.0-3.5
                '#1b18dc',  # 3.5-4.0
                '#161fb8',  # 4.0-5.0
                '#130495',  # 5.0-6.0
                '#130495',  # 6.0-8.0
                '#550a87',  # 8.0-10.0
                '#550a87',  # 10.0-12.0
                '#af068e',  # 12.0-14.0
                '#ea0081'   # >14.0
            ]
        }
    }
    
    # Radar reflectivity configuration with dBZ levels and colors for each precipitation type
    RADAR_CONFIG = {
        'rain': {
            # dBZ levels: 0-10, 10-15, 15-20, 20-23, 23-25, 25-28, 28-30, 30-33, 33-35, 35-38, 38-40, 40-43, 43-45, 45-48, 48-50, 50-53, 53-55, 55-58, 58-60, >60
            'levels': [0, 10, 15, 20, 23, 25, 28, 30, 33, 35, 38, 40, 43, 45, 48, 50, 53, 55, 58, 60, 70],
            'colors': ['#ffffff', '#4efb4c', '#46e444', '#3ecd3d', '#36b536', '#2d9e2e', '#258528', 
                      '#1d6e1f', '#155719', '#feff50', '#fad248', '#f8a442', '#f6763c', '#f5253a',
                      '#de0a35', '#c21230', '#9c0045', '#bc0f9c', '#e300c1', '#f600dc']
        },
        'frzr': {
            # dBZ levels: 0-4, 4-8, 8-12, 12-16, 16-20, 20-24, 24-28, 28-32, 32-36, 36-40, 40-44, 44-48, 48-52, 52-56, 56-60, >60
            'levels': [0, 4, 8, 12, 16, 20, 24, 28, 32, 36, 40, 44, 48, 52, 56, 60, 70],
            'colors': ['#ffffff', '#fbcad0', '#f893ba', '#e96c9f', '#dd88a5', '#dc4f8b', '#d03a80',
                      '#c62773', '#bd1366', '#b00145', '#c21230', '#da2d0d', '#e33403', '#f53c00',
                      '#f53c00', '#f54603']
        },
        'sleet': {
            # dBZ levels: 0-4, 4-8, 8-12, 12-16, 16-20, 20-24, 24-28, 28-32, 32-36, 36-40, 40-44, 44-48, 48-52, 52-56, 56-60, >60
            'levels': [0, 4, 8, 12, 16, 20, 24, 28, 32, 36, 40, 44, 48, 52, 56, 60, 70],
            'colors': ['#ffffff', '#b49dff', '#b788ff', '#c56cff', '#c54ef9', '#c54ef9', '#b730e7',
                      '#a913d3', '#a913d3', '#9b02b4', '#bc0f9c', '#a50085', '#c52c7b', '#cf346f',
                      '#d83c64', '#e24556']
        },
        'snow': {
            # dBZ levels: 0-4, 4-8, 8-12, 12-16, 16-20, 20-24, 24-28, 28-32, 32-36, 36-40, 40-44, 44-48, 48-52, 52-56, 56-60, >60
            'levels': [0, 4, 8, 12, 16, 20, 24, 28, 32, 36, 40, 44, 48, 52, 56, 60, 70],
            'colors': ['#ffffff', '#55ffff', '#4feaff', '#48d3ff', '#42bfff', '#3caaff', '#3693ff',
                      '#2a6aee', '#1e40d0', '#110ba7', '#2a009a', '#0c276f', '#540093', '#bc0f9c',
                      '#d30085', '#f5007f']
        }
    }
    
    def __init__(self):
        self.storage_path = Path(settings.storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
    
    def get_precip_cmap(self, p_type):
        """
        Get colormap and normalization for precipitation type.
        
        Args:
            p_type: Precipitation type ('rain', 'frzr', 'sleet', 'snow')
        
        Returns:
            tuple: (cmap, norm, edges) for the precipitation type
        """
        cfg = self.PRECIP_CONFIG[p_type]
        edges = list(cfg['levels'])
        if len(edges) == len(cfg['colors']):
            edges.append(edges[-1] * 1.25)
        cmap = colors.ListedColormap(cfg['colors'], name=f"{p_type}_cmap")
        cmap.set_under((1, 1, 1, 0))  # transparent under
        norm = colors.BoundaryNorm(edges, cmap.N, clip=False)
        return cmap, norm, edges
    
    def get_radar_cmap(self, p_type):
        """
        Get colormap and normalization for radar reflectivity by precipitation type.
        
        Args:
            p_type: Precipitation type ('rain', 'frzr', 'sleet', 'snow')
        
        Returns:
            tuple: (cmap, norm, levels) for the radar reflectivity
        """
        cfg = self.RADAR_CONFIG[p_type]
        levels = cfg['levels']
        cmap = colors.ListedColormap(cfg['colors'], name=f"radar_{p_type}_cmap")
        cmap.set_under((1, 1, 1, 0))  # transparent under minimum
        norm = colors.BoundaryNorm(levels, cmap.N, clip=False)
        return cmap, norm, levels
    
    def _setup_base_map(self, region: str = 'pnw', 
                       land_color: str = '#fbf5e7',
                       ocean_color: str = '#e3f2fd',
                       border_color: str = '#000000',  # Force Black for visibility
                       border_linewidth: float = 0.8,  # Increased from 0.6
                       state_linewidth: float = 1.2,  # Increased from 0.6 for better visibility
                       county_linewidth: float = 0.8):  # Increased from 0.3 for better visibility
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
            county_linewidth: Width of county boundary lines
            
        Returns:
            matplotlib axes object with base map configured
        """
        fig = plt.figure(figsize=(settings.map_width/100, settings.map_height/100), dpi=settings.map_dpi)
        
        # Minimize margins by adjusting subplot parameters
        fig.subplots_adjust(left=0.02, right=0.98, top=0.95, bottom=0.05)
        
        # Set projection based on region
        if region == "pnw":
            # Pacific Northwest: WA, OR, ID
            # Use Lambert Conformal optimized for PNW
            # Create axes with specific position to minimize margins
            ax = fig.add_subplot(1, 1, 1, projection=ccrs.LambertConformal(
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
            ax = fig.add_subplot(1, 1, 1, projection=ccrs.LambertConformal(central_longitude=-95, central_latitude=35))
            ax.set_extent([-130, -65, 20, 50], crs=ccrs.PlateCarree())
        else:
            ax = fig.add_subplot(1, 1, 1, projection=ccrs.PlateCarree())
            ax.set_global()
        
        # Add map features - land/ocean at bottom, borders/states on top of precip
        ax.add_feature(cfeature.OCEAN, facecolor=ocean_color, zorder=0)
        ax.add_feature(cfeature.LAND, facecolor=land_color, zorder=0)
        
        # Move borders and states to zorder=10 to ensure visibility above precipitation
        ax.add_feature(cfeature.COASTLINE, linewidth=border_linewidth, edgecolor=border_color, zorder=10)
        ax.add_feature(cfeature.BORDERS, linewidth=border_linewidth, edgecolor=border_color, zorder=10)
        
        # Add county boundaries for better geographic reference
        # Using NaturalEarthFeature to load counties at 1:10m scale (highest resolution available)
        try:
            counties = NaturalEarthFeature(
                category='cultural',
                name='admin_2_counties',
                scale='10m',
                facecolor='none',
                edgecolor='#333333'  # Darker gray for better visibility
            )
            ax.add_feature(counties, linewidth=county_linewidth, linestyle='-', alpha=0.7, zorder=9)
        except Exception as e:
            # If counties can't be loaded (missing data files), log warning but continue
            logger.warning(f"Could not load county boundaries: {e}")
        
        # Make state lines bolder and more opaque for better visibility
        ax.add_feature(cfeature.STATES, linewidth=state_linewidth, edgecolor=border_color, 
                       linestyle='-', alpha=0.8, zorder=10)
        
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
        
        # Detect coordinate names and 0-360 longitude format only once
        lat_name = 'latitude' if 'latitude' in ds.coords else 'lat'
        lon_name = 'longitude' if 'longitude' in ds.coords else 'lon'
        lon_vals = ds.coords[lon_name].values
        uses_360_format = lon_vals.min() >= 0 and lon_vals.max() > 180
        for station_name, station_data in stations.items():
            try:
                station_lat = station_data['lat']
                station_lon = station_data['lon']
                if uses_360_format and station_lon < 0:
                    station_lon = station_lon % 360
                value = ds[variable].sel(
                    {lat_name: station_lat, lon_name: station_lon},
                    method='nearest'
                ).values
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
            temp_data = self._process_temperature(ds)
            logger.info(f"Temperature data before normalize - shape: {temp_data.shape}, coords: {list(temp_data.coords.keys())}, dims: {list(temp_data.dims)}")
            logger.info(f"Temperature range: min={float(temp_data.min()):.2f}, max={float(temp_data.max()):.2f}")
            data = self._normalize_lonlat(temp_data)
            logger.info(f"Temperature data after normalize - shape: {data.shape}, coords: {list(data.coords.keys())}, dims: {list(data.dims)}")
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
            # Use tp_total from dataset (pre-computed by build_dataset_for_maps)
            # This is the total accumulated precipitation from hour 0 to forecast_hour
            if 'tp_total' not in ds:
                raise ValueError(
                    f"tp_total not found in dataset. Dataset must be built using "
                    f"build_dataset_for_maps() which computes derived fields."
                )
            data = ds['tp_total'].squeeze() / 25.4  # Convert mm to inches
            data = self._normalize_lonlat(data)
            units = "in"  # Inches for PNW users
            # Custom colormap matching the known-good precipitation scale
            from matplotlib import colors
            
            # Define the specific hex colors for each interval (no white for 0 bin)
            precip_colors = [
                '#C0C0C0', '#909090', '#606060', # 0.01, 0.05, 0.1
                '#B0F090', '#80E060', '#50C040',            # 0.2, 0.3, 0.5
                '#3070F0', '#5090F0', '#80B0F0', '#B0D0F0', # 0.7, 0.9, 1.2, 1.6
                '#FFFF80', '#FFD060', '#FFA040',            # 2.0, 3.0, 4.0
                '#FF6030', '#E03020', '#A01010', '#700000', # 6.0, 8.0, 10.0, 12.0
                '#D0B0E0', '#B080D0', '#9050C0', '#7020A0', # 14.0, 16.0, 18.0, 20.0
                '#C040C0'                                   # 25.0+
            ]
            
            # Define exact non-linear boundaries (increments), no 0.0 edge
            precip_levels = [0.01, 0.05, 0.1, 0.2, 0.3, 0.5, 0.7, 0.9, 1.2, 1.6, 
                             2.0, 3.0, 4.0, 6.0, 8.0, 10.0, 12.0, 14.0, 16.0, 18.0, 20.0, 25.0]
            
            # Create the discrete colormap
            custom_precip_cmap = colors.ListedColormap(precip_colors[:len(precip_levels)-1])
            custom_precip_cmap.set_over(precip_colors[-1])  # Use last color for values > 25.0
            custom_precip_cmap.set_under((1, 1, 1, 0))      # Transparent for < 0.01
            
            # Use BoundaryNorm to map the data to these uneven levels
            precip_norm = colors.BoundaryNorm(precip_levels, custom_precip_cmap.N)
            
            cmap = custom_precip_cmap
        elif variable == "snowfall":
            # Use tp_snow_total from dataset (pre-computed by build_dataset_for_maps)
            # This is the total accumulated snowfall from hour 0 to forecast_hour
            if 'tp_snow_total' not in ds:
                raise ValueError(
                    f"tp_snow_total not found in dataset. Dataset must be built using "
                    f"build_dataset_for_maps() which computes derived fields."
                )
            # tp_snow_total is already in inches (computed by _compute_total_snowfall)
            data = ds['tp_snow_total'].squeeze()
            data = self._normalize_lonlat(data)
            units = "in"  # Inches (10:1 ratio)
            
            # Snowfall colormap - custom hex colors for different accumulation levels
            from matplotlib import colors
            
            # Define hex colors for snowfall accumulation (from user specification)
            snow_colors = [
                '#ffffff', '#dbdbdb', '#959595', '#6e6e6e', '#505050',  # 0.1-2.0"
                '#96d1fa', '#78b9fb', '#50a5f5', '#3c97f5', '#3083f1',  # 2.0-4.5"
                '#2b6eeb', '#2664d3', '#215ac3',                         # 4.5-6.0"
                '#3e0091', '#4c008f', '#5a008d', '#67008a', '#860087',  # 6.0-8.5"
                '#a10285', '#c90181', '#f3027c',                         # 8.5-10.0"
                '#f41484', '#f53b9b', '#f65faf', '#f76eb7', '#f885c3',  # 10-15"
                '#f58dc7', '#ea95ca', '#e79dcd', '#d9acd5', '#cfb2d6',  # 15-20"
                '#c1c7dd', '#b6d8ec', '#a9e3ef', '#a1eff3', '#94f8f6',  # 20-25"
                '#8dedeb', '#7edbd9', '#73c0c7', '#7cb9ca', '#81b7cd',  # 25-30"
                '#88b0ce', '#8db0d0', '#90b0d2', '#93abd7', '#93abd7',  # 30-35"
                '#99a7db', '#9da5dd', '#a5a0df', '#a5a0df', '#af9be7',  # 35-40"
                '#af9be7', '#ad95e2', '#b795eb', '#b291e5', '#bf91f1',  # 40-45"
                '#c68df5', '#c488f0', '#d187f9', '#cb84f3'               # 45-48"+
            ]
            
            # Define boundaries for snowfall levels (inches)
            snow_levels = [
                0.1, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5,      # 0.1-5.0"
                5.0, 5.5, 6.0, 6.5, 7.0, 7.5, 8.0, 8.5, 9.0, 9.5,      # 5.0-10.0"
                10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0, 17.0, 18.0, 19.0,  # 10-20"
                20.0, 21.0, 22.0, 23.0, 24.0, 25.0, 26.0, 27.0, 28.0, 29.0,  # 20-30"
                30.0, 31.0, 32.0, 33.0, 34.0, 35.0, 36.0, 37.0, 38.0, 39.0,  # 30-40"
                40.0, 41.0, 42.0, 43.0, 44.0, 45.0, 46.0, 47.0, 48.0         # 40-48"
            ]
            
            # Create discrete colormap
            custom_snow_cmap = colors.ListedColormap(snow_colors[:len(snow_levels)-1])
            custom_snow_cmap.set_over('#cb84f3')     # Purple for values > 48"
            custom_snow_cmap.set_under((1, 1, 1, 0))  # Transparent for < 0.1"
            
            # Use BoundaryNorm for discrete levels
            snow_norm = colors.BoundaryNorm(snow_levels, custom_snow_cmap.N)
            
            cmap = custom_snow_cmap
        elif variable == "wind_speed_10m" or variable == "wind_speed":
            # For forecast hour 0 (analysis), wind components may not be available
            # Check if wind data exists before processing
            has_wind = ('u10' in ds or 'ugrd10m' in ds) and ('v10' in ds or 'vgrd10m' in ds)
            if not has_wind and forecast_hour == 0:
                raise ValueError(f"Wind components not available in analysis file (f000) for {variable}. Skipping wind_speed map for forecast hour 0.")
            data = self._normalize_lonlat(self._process_wind_speed(ds))
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
            data = self._normalize_lonlat(ds['tmp_850'])
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
            # Use p6_rate_mmhr from dataset (pre-computed by build_dataset_for_maps)
            if 'p6_rate_mmhr' not in ds:
                raise ValueError(
                    f"p6_rate_mmhr not found in dataset. Dataset must be built using "
                    f"build_dataset_for_maps() which computes derived fields."
                )
            data = ds['p6_rate_mmhr'].squeeze()
            data = self._normalize_lonlat(data)
            units = "mm/hr"
            cmap = "Greens" # Default, though we plot layers below
            is_mslp_precip = True
        elif variable == "radar" or variable == "radar_reflectivity":
            data = self._normalize_lonlat(self._process_radar_reflectivity(ds))
            units = "dBZ"
            # Radar colors are now defined per precipitation type
            # Will be used in the plotting section
        # Note: wind_gusts removed for initial release, can be added later
        else:
            raise ValueError(f"Unsupported variable: {variable}")
        
        # Determine base map colors based on variable type
        # MSLP & Precip, Total Precip, Snowfall, and Radar maps: all white with black borders
        if is_mslp_precip or variable in ["precipitation", "precip", "snowfall", "radar", "radar_reflectivity"]:
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
            # data is already 6-hr rate (mm/hr) from fetch_6hr_precip_rate_mmhr
            # A. Normalize all inputs
            rate = self._normalize_coords(data).squeeze()
            mslp_data = self._normalize_coords(self._process_mslp(ds))
            has_gh = ('gh_1000' in ds and 'gh_500' in ds) or 'gh' in ds or any('gh' in str(v).lower() for v in ds.data_vars)
            thickness_data = self._normalize_coords(self._process_thickness(ds)) if has_gh else None

            # Detect coordinate names
            lon_name = 'longitude' if 'longitude' in rate.coords else 'lon'
            lat_name = 'latitude' if 'latitude' in rate.coords else 'lat'

            # PERFORMANCE: Early threshold - skip expensive processing if rate is negligible
            min_rate_threshold = 0.1  # mm/hr
            max_rate = float(rate.max())
            
            if max_rate < min_rate_threshold:
                # No significant precipitation - skip expensive upsampling/smoothing
                rate_smooth = rate
                new_lon = rate[lon_name].values
                new_lat = rate[lat_name].values
                has_precip = np.zeros_like(rate.values, dtype=bool)
                masks = {
                    'rain': xr.zeros_like(rate),
                    'snow': xr.zeros_like(rate),
                    'sleet': xr.zeros_like(rate),
                    'frzr': xr.zeros_like(rate)
                }
            else:
                # B. Create a master categorical "Owner" grid via per-type masks
                crain = ds.get('crain', xr.zeros_like(rate))
                csnow = ds.get('csnow', xr.zeros_like(rate))
                cicep = ds.get('cicep', xr.zeros_like(rate))
                cfrzr = ds.get('cfrzr', xr.zeros_like(rate))

                if 'time' in crain.dims: crain = crain.isel(time=0)
                if 'time' in csnow.dims: csnow = csnow.isel(time=0)
                if 'time' in cicep.dims: cicep = cicep.isel(time=0)
                if 'time' in cfrzr.dims: cfrzr = cfrzr.isel(time=0)

                # PERFORMANCE: Precompute hi-res grid once (reusable across variables)
                # Store in instance cache for reuse if needed by other variables same hour
                cache_key = f"{forecast_hour}_{lon_name}_{lat_name}"
                if not hasattr(self, '_hires_grid_cache'):
                    self._hires_grid_cache = {}
                
                if cache_key not in self._hires_grid_cache:
                    # Use 0.02 degrees (~2km) for smooth contours
                    new_lon = np.arange(float(rate[lon_name].min()), float(rate[lon_name].max()), 0.02)
                    new_lat = np.arange(float(rate[lat_name].min()), float(rate[lat_name].max()), 0.02)
                    self._hires_grid_cache[cache_key] = (new_lon, new_lat)
                else:
                    new_lon, new_lat = self._hires_grid_cache[cache_key]
                
                # Upsample rate and masks ONCE with linear interpolation
                rate_smooth = rate.interp({lon_name: new_lon, lat_name: new_lat}, method="linear")
                
                # Build hi-res masks first, then pick the winner on the hi-res grid
                # This avoids blocky edges from nearest-neighbor upsampling
                precip_types = [('crain', 'rain'), ('csnow', 'snow'), ('cicep', 'sleet'), ('cfrzr', 'frzr')]
                
                mask_hi_list = []
                for var_key, p_type in precip_types:
                    if var_key in ds:
                        mask_src = ds[var_key]
                        if 'time' in mask_src.dims:
                            mask_src = mask_src.isel(time=0)
                        mask_src = self._normalize_coords(mask_src)
                    else:
                        mask_src = xr.zeros_like(rate)
                    
                    mask_hi = mask_src.interp({lon_name: new_lon, lat_name: new_lat}, method='linear')
                    mask_hi_list.append(mask_hi.values)
                
                # Find winner on hi-res grid for smoother boundaries
                mask_stack_hi = np.stack(mask_hi_list, axis=0)
                winner_idx = np.argmax(mask_stack_hi, axis=0)
                winner_field_hi = xr.DataArray(
                    winner_idx,
                    coords=rate_smooth.coords,
                    dims=rate_smooth.dims
                )
                
                # PERFORMANCE: Single smoothing pass on final rate field (not per-type)
                from scipy.ndimage import gaussian_filter
                rate_smooth.values = gaussian_filter(rate_smooth.values, sigma=0.7)
                
                # Apply threshold after smoothing
                has_precip = rate_smooth.values > min_rate_threshold
                
                # Create masks dict from upsampled winner field
                masks = {
                    'rain': xr.DataArray((winner_field_hi.values == 0) & has_precip, coords=rate_smooth.coords, dims=rate_smooth.dims),
                    'snow': xr.DataArray((winner_field_hi.values == 1) & has_precip, coords=rate_smooth.coords, dims=rate_smooth.dims),
                    'sleet': xr.DataArray((winner_field_hi.values == 2) & has_precip, coords=rate_smooth.coords, dims=rate_smooth.dims),
                    'frzr': xr.DataArray((winner_field_hi.values == 3) & has_precip, coords=rate_smooth.coords, dims=rate_smooth.dims)
                }
            
            # C. Plot precip types (simplified - no complex overlap logic)
            # Plot in REVERSE priority order (frzr->sleet->snow->rain)
            precip_contours = {}
            plot_order = [('frzr', 1), ('sleet', 2), ('snow', 3), ('rain', 4)]
            
            for p_type, z_val in plot_order:
                cmap, norm, edges = self.get_precip_cmap(p_type)
                
                # Create many intermediate levels for smooth appearance
                smooth_levels = []
                for i in range(len(edges) - 1):
                    smooth_levels.append(edges[i])
                    smooth_levels.append(edges[i] + (edges[i+1] - edges[i]) / 3)
                    smooth_levels.append(edges[i] + 2 * (edges[i+1] - edges[i]) / 3)
                smooth_levels.append(edges[-1])
                
                # Create data for this type using simplified mask
                type_mask = masks[p_type].values if hasattr(masks[p_type], 'values') else masks[p_type]
                type_min_threshold = edges[0] if p_type != 'rain' else 0.01
                
                # Apply mask and threshold
                type_data = np.where(type_mask & (rate_smooth.values >= type_min_threshold), 
                                    rate_smooth.values, np.nan)
                
                # Only plot if there's actual data
                if np.any(~np.isnan(type_data)) and np.nanmax(type_data) > 0.001:
                    pm = ax.contourf(
                        new_lon, new_lat, type_data,
                        levels=smooth_levels,
                        transform=ccrs.PlateCarree(),
                        cmap=cmap, norm=norm,
                        extend='neither',
                        antialiased=True,
                        zorder=z_val,
                    )
                    precip_contours[p_type] = (pm, cmap, norm, edges)
                else:
                    precip_contours[p_type] = (None, cmap, norm, edges)

            im = list(precip_contours.values())[0][0] if precip_contours else None
            cs_mslp = ax.contour(
                mslp_data[lon_name].values, mslp_data[lat_name].values, mslp_data.values,
                levels=np.arange(960, 1060, 4),
                colors='black', linewidths=1.2,
                transform=ccrs.PlateCarree(), zorder=12
            )
            ax.clabel(cs_mslp, inline=True, fontsize=9, fmt='%d', zorder=13)
            if thickness_data is not None:
                # Blue dashed for <= 540 dam, red dashed for > 540 dam
                cold_levels = np.arange(480, 542, 6)
                warm_levels = np.arange(546, 601, 6)

                # Clip levels to data range
                tmin = float(thickness_data.min())
                tmax = float(thickness_data.max())

                if tmin <= 540:
                    cold_levels_in = cold_levels[(cold_levels >= tmin) & (cold_levels <= min(540, tmax))]
                    if cold_levels_in.size:
                        cs_cold = ax.contour(
                            thickness_data[lon_name].values, thickness_data[lat_name].values, thickness_data.values,
                            levels=cold_levels_in,
                            colors='blue',
                            linewidths=1.2,
                            linestyles='dashed',
                            transform=ccrs.PlateCarree(),
                            zorder=11,
                        )
                        ax.clabel(cs_cold, inline=True, fontsize=8, fmt='%d', zorder=13)

                if tmax >= 546:
                    warm_levels_in = warm_levels[(warm_levels >= max(546, tmin)) & (warm_levels <= tmax)]
                    if warm_levels_in.size:
                        cs_warm = ax.contour(
                            thickness_data[lon_name].values, thickness_data[lat_name].values, thickness_data.values,
                            levels=warm_levels_in,
                            colors='red',
                            linewidths=1.2,
                            linestyles='dashed',
                            transform=ccrs.PlateCarree(),
                            zorder=11,
                        )
                        ax.clabel(cs_warm, inline=True, fontsize=8, fmt='%d', zorder=13)
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
        elif variable == "radar" or variable == "radar_reflectivity":
            # Radar reflectivity with precipitation-type-specific colors
            lon_vals = data.coords.get('lon', data.coords.get('longitude'))
            lat_vals = data.coords.get('lat', data.coords.get('latitude'))
            
            # Get precipitation type categorical data
            crain = ds.get('crain', xr.zeros_like(data))
            csnow = ds.get('csnow', xr.zeros_like(data))
            cicep = ds.get('cicep', xr.zeros_like(data))
            cfrzr = ds.get('cfrzr', xr.zeros_like(data))
            
            # Remove time dimension if present
            if 'time' in crain.dims: crain = crain.isel(time=0)
            if 'time' in csnow.dims: csnow = csnow.isel(time=0)
            if 'time' in cicep.dims: cicep = cicep.isel(time=0)
            if 'time' in cfrzr.dims: cfrzr = cfrzr.isel(time=0)
            
            # Normalize coordinates for categorical data
            crain = self._normalize_coords(crain)
            csnow = self._normalize_coords(csnow)
            cicep = self._normalize_coords(cicep)
            cfrzr = self._normalize_coords(cfrzr)
            
            # Apply minimum reflectivity threshold first
            min_dbz_threshold = 10  # Increased from 5 to 10 to match TropicalTidbits
            data_vals = np.asarray(data.values, dtype=float)
            data_vals = np.where(np.isfinite(data_vals), data_vals, np.nan)
            has_precip = np.isfinite(data_vals) & (data_vals >= min_dbz_threshold)
            
            # Check if we have any precipitation type data
            crain_vals = np.nan_to_num(np.asarray(crain.values, dtype=float), nan=0.0)
            csnow_vals = np.nan_to_num(np.asarray(csnow.values, dtype=float), nan=0.0)
            cicep_vals = np.nan_to_num(np.asarray(cicep.values, dtype=float), nan=0.0)
            cfrzr_vals = np.nan_to_num(np.asarray(cfrzr.values, dtype=float), nan=0.0)

            has_type_data = (
                np.max(crain_vals) > 0 or np.max(csnow_vals) > 0 or
                np.max(cicep_vals) > 0 or np.max(cfrzr_vals) > 0
            )
            
            if has_type_data:
                # Stack masks to determine dominant precipitation type
                mask_stack = np.stack([
                    crain_vals,
                    csnow_vals,
                    cicep_vals,
                    cfrzr_vals
                ], axis=0)
                
                # Find the index of maximum probability at each point
                # 0=rain, 1=snow, 2=sleet, 3=frzr
                winner_idx = np.argmax(mask_stack, axis=0)
                
                # Only consider areas with actual precipitation type data (>0)
                has_type_info = np.max(mask_stack, axis=0) > 0
                
                # Plot in REVERSE priority order with OVERLAP to eliminate white gaps
                # (frzr->sleet->snow->rain) so dominant types paint over less dominant ones
                im = None
                plot_order = [
                    ('frzr', cfrzr, 3),
                    ('sleet', cicep, 2),
                    ('snow', csnow, 1),
                    ('rain', crain, 0)
                ]
                
                from scipy.ndimage import binary_dilation
                
                for p_type, mask, idx in plot_order:
                    cmap_type, norm_type, levels_type = self.get_radar_cmap(p_type)
                    
                    # Create mask where this type is dominant and has reflectivity
                    type_mask = (winner_idx == idx) & has_precip & has_type_info
                    type_mask = np.asarray(type_mask, dtype=bool)
                    
                    # EXPAND the mask slightly to create overlap and eliminate white gaps
                    # Use binary dilation with a small structure to expand by ~2 grid points
                    structure = np.ones((3, 3))
                    expanded_mask = binary_dilation(type_mask, structure=structure, iterations=1)
                    
                    # Mask the data for this precipitation type using expanded mask
                    masked_data = np.where(expanded_mask, data_vals, np.nan)
                    
                    if np.any(~np.isnan(masked_data)):
                        im_temp = ax.contourf(
                            lon_vals, lat_vals, masked_data,
                            transform=ccrs.PlateCarree(),
                            cmap=cmap_type,
                            levels=levels_type,
                            extend='max',
                            zorder=1
                        )
                        # Keep the last plotted image for colorbar
                        if im is None:
                            im = im_temp
            else:
                # Fall back to single rain colormap if no type data available
                logger.warning("No precipitation type data available, using rain colormap for all reflectivity")
                cmap_type, norm_type, levels_type = self.get_radar_cmap('rain')
                masked_data = np.where(has_precip, data_vals, np.nan)
                
                im = ax.contourf(
                    lon_vals, lat_vals, masked_data,
                    transform=ccrs.PlateCarree(),
                    cmap=cmap_type,
                    levels=levels_type,
                    extend='max',
                    zorder=1
                )
        elif is_wind_speed_map:
            # Wind Speed with Streamlines
            # Use helper to get correct coordinates and transform
            X, Y, transform = self._get_plot_coords_and_transform(data, ax)
            
            # Wind speed levels matching the screenshot (0-100 mph)
            wind_levels = [0, 4, 6, 8, 9, 10, 12, 14, 16, 20, 22, 24, 26, 30, 34, 36, 40, 44, 48, 52, 58, 64, 70, 75, 85, 95, 100]
            
            # Plot filled contours for wind speed
            im = ax.contourf(
                X, Y, data,
                transform=transform,
                cmap=cmap,
                levels=wind_levels,
                extend='max',
                zorder=1
            )
            
            # Add contour lines with labels for key wind speeds
            contour_levels = [3, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 60, 70, 80, 90]
            cs = ax.contour(
                X, Y, data,
                levels=contour_levels,
                colors='black',
                linewidths=0.5,
                alpha=0.6,
                transform=transform,
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
                    X, Y, 
                    u.values, v.values,
                    transform=transform,
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
            # Also check dims if not in coords
            lon_coord_name = None
            lat_coord_name = None
            
            for lon_name in ['lon', 'longitude', 'x']:
                if lon_name in data.coords or lon_name in data.dims:
                    lon_coord_name = lon_name
                    break
            
            for lat_name in ['lat', 'latitude', 'y']:
                if lat_name in data.coords or lat_name in data.dims:
                    lat_coord_name = lat_name
                    break
            
            if lon_coord_name is None or lat_coord_name is None:
                raise ValueError(f"Could not find coordinates. Available coords: {list(data.coords.keys())}, dims: {list(data.dims)}")
            
            # Get coordinate values (from coords or as dimension coordinate)
            lon_vals = data.coords[lon_coord_name] if lon_coord_name in data.coords else data[lon_coord_name]
            lat_vals = data.coords[lat_coord_name] if lat_coord_name in data.coords else data[lat_coord_name]
            
            # Log coordinate info for debugging
            logger.debug(f"Using coordinates: {lon_coord_name}, {lat_coord_name}")
            logger.info(f"Lon vals type: {type(lon_vals)}, has values: {hasattr(lon_vals, 'values')}")
            logger.info(f"Lat vals type: {type(lat_vals)}, has values: {hasattr(lat_vals, 'values')}")
            if hasattr(lon_vals, 'shape'):
                logger.info(f"Lon shape: {lon_vals.shape}, range: {float(lon_vals.min()):.2f} to {float(lon_vals.max()):.2f}")
                logger.info(f"Lat shape: {lat_vals.shape}, range: {float(lat_vals.min()):.2f} to {float(lat_vals.max()):.2f}")
            logger.info(f"Map extent: lon [-125.0 to -110.0], lat [42.0 to 49.0]")
            logger.info(f"Data coverage: lon [{float(lon_vals.min()):.2f} to {float(lon_vals.max()):.2f}], lat [{float(lat_vals.min()):.2f} to {float(lat_vals.max()):.2f}]")
            logger.debug(f"Data shape: {data.shape}, Lon shape: {lon_vals.shape}, Lat shape: {lat_vals.shape}")
            logger.debug(f"Data min: {float(data.min()):.2f}, max: {float(data.max()):.2f}, mean: {float(data.mean()):.2f}")
            
            # For precipitation, use BoundaryNorm for discrete color mapping
            if variable in ["precipitation", "precip"]:
                logger.info(f"Plotting precipitation with {len(temp_levels)} levels")
                im = ax.contourf(
                    lon_vals, lat_vals, data,
                    transform=ccrs.PlateCarree(),
                    cmap=cmap,
                    norm=precip_norm,
                    levels=temp_levels,
                    extend='both',
                    zorder=1
                )
            elif variable == "snowfall":
                logger.info(f"Plotting snowfall with {len(snow_levels)} levels")
                im = ax.contourf(
                    lon_vals, lat_vals, data,
                    transform=ccrs.PlateCarree(),
                    cmap=cmap,
                    norm=snow_norm,
                    levels=snow_levels,
                    extend='both',
                    zorder=1
                )
            else:
                logger.info(f"Plotting {variable} with {len(temp_levels) if isinstance(temp_levels, (list, np.ndarray)) else temp_levels} levels")
                logger.info(f"Data array shape: {data.shape}, lon_vals shape: {lon_vals.shape}, lat_vals shape: {lat_vals.shape}")
                im = ax.contourf(
                    lon_vals, lat_vals, data,
                    transform=ccrs.PlateCarree(),
                    cmap=cmap,
                    levels=temp_levels,
                    extend='both',
                    zorder=1
                )
                logger.info(f"Contourf completed successfully")
        
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
        
        # Add colorbar (shrink=0.6 makes it 60% width, centered on the map)
        if variable in ["precipitation_type", "precip_type"]:
            cbar = plt.colorbar(im, ax=ax, orientation='horizontal', pad=0.05, aspect=40, 
                               shrink=0.6, ticks=[0, 1, 2, 3])
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

                    # Create colorbar - use ScalarMappable if no contour exists
                    if contour is not None:
                        cbar = plt.colorbar(contour, cax=cbar_ax, orientation='horizontal', 
                                           cmap=cmap, norm=norm)
                    else:
                        # No data for this type - create colorbar with ScalarMappable
                        sm = matplotlib.cm.ScalarMappable(cmap=cmap, norm=norm)
                        sm.set_array([])
                        cbar = plt.colorbar(sm, cax=cbar_ax, orientation='horizontal')
                    
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
                cbar = plt.colorbar(im, ax=ax, orientation='horizontal', pad=0.05, aspect=40, shrink=0.6)
                tick_positions = [0.1, 0.5, 1, 2.5, 4, 6, 10, 14, 16, 18]
                cbar.set_ticks(tick_positions)
                cbar.set_label("6-hour Averaged Precip Rate (mm/hr), MSLP (hPa), & 1000-500mb Thick (dam)")
        elif is_850mb_map:
            cbar = plt.colorbar(im, ax=ax, orientation='horizontal', pad=0.05, aspect=40, shrink=0.6)
            cbar.set_label("850mb Temperature (°C)")
        elif is_wind_speed_map:
            cbar = plt.colorbar(im, ax=ax, orientation='horizontal', pad=0.05, aspect=40, shrink=0.6)
            # Set tick positions for wind speed colorbar to match the screenshot
            tick_positions = [0, 4, 6, 8, 10, 12, 14, 16, 20, 22, 24, 26, 30, 34, 36, 40, 44, 48, 52, 58, 64, 70, 75, 85, 95, 100]
            cbar.set_ticks(tick_positions)
            cbar.set_label("10m Wind Speed + Streamlines (mph)")
        elif variable == "radar" or variable == "radar_reflectivity":
            # Create vertical color bars for each precipitation type on the right side
            from matplotlib.colors import ListedColormap, BoundaryNorm
            
            fig = plt.gcf()
            
            # Adjust the main plot to make room for colorbars on the right
            fig.subplots_adjust(right=0.85)
            
            # Create color bars for each precipitation type
            # Order from top to bottom: Rain, FrzR, Sleet, Snow
            precip_types = [
                ('rain', 'Rain'),
                ('frzr', 'FrzR'),
                ('sleet', 'Sleet'),
                ('snow', 'Snow')
            ]
            
            # Create vertical colorbars stacked on the right side
            num_types = len(precip_types)
            cbar_width = 0.015  # Width of each colorbar
            cbar_spacing = 0.02  # Vertical spacing between colorbars
            
            # Calculate total height available and divide by number of colorbars
            total_height = 0.80  # Use 80% of figure height
            cbar_height = (total_height - (num_types - 1) * cbar_spacing) / num_types
            
            # Start position (top of the first colorbar)
            top_start = 0.90
            
            for idx, (p_type, label) in enumerate(precip_types):
                cmap_type, norm_type, levels_type = self.get_radar_cmap(p_type)
                
                # Position from top: top_start - idx * (height + spacing)
                bottom_pos = top_start - (idx + 1) * cbar_height - idx * cbar_spacing
                cbar_ax = fig.add_axes([0.87, bottom_pos, cbar_width, cbar_height])
                
                # Create a scalar mappable for the colorbar
                sm = plt.cm.ScalarMappable(cmap=cmap_type, norm=norm_type)
                sm.set_array([])
                
                cbar = plt.colorbar(sm, cax=cbar_ax, orientation='vertical')
                cbar.set_label(label, fontsize=9, rotation=0, ha='left', va='center', labelpad=15)
                cbar.ax.tick_params(labelsize=7)
                
                # Set appropriate tick positions based on the levels
                # Show fewer ticks for vertical orientation to avoid crowding
                if len(levels_type) > 10:
                    tick_positions = levels_type[::3]  # Every third level
                elif len(levels_type) > 6:
                    tick_positions = levels_type[::2]  # Every other level
                else:
                    tick_positions = levels_type
                cbar.set_ticks(tick_positions)
        elif variable in ["precipitation", "precip"]:
            # Custom colorbar with specific tick labels matching the increments
            # Use the same norm for the colorbar
            cbar = plt.colorbar(im, ax=ax, orientation='horizontal', pad=0.05, aspect=40, shrink=0.6, norm=precip_norm)
            # Set tick positions at the boundaries between color segments
            tick_positions = [0.01, 0.05, 0.1, 0.2, 0.3, 0.5, 0.7, 0.9, 1.2, 1.6, 2, 3, 4, 6, 8, 10, 12, 14, 16, 18, 20]
            cbar.set_ticks(tick_positions)
            cbar.set_label("Total Precipitation (inches)")
        elif variable == "snowfall":
            # Custom colorbar for snowfall
            cbar = plt.colorbar(im, ax=ax, orientation='horizontal', pad=0.05, aspect=40, shrink=0.6, norm=snow_norm)
            # Set tick positions at key snowfall amounts
            tick_positions = [0.1, 0.5, 1, 2, 3, 4, 6, 8, 10, 12, 15, 18, 24, 30, 36, 42, 48, 60, 72]
            cbar.set_ticks(tick_positions)
            cbar.set_label("Total Snowfall (10:1 Ratio) (inches)")
        else:
            cbar = plt.colorbar(im, ax=ax, orientation='horizontal', pad=0.05, aspect=40, shrink=0.6)
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
        # Use the model parameter to dynamically set the model name in titles
        if variable in ["precipitation", "precip"]:
            map_title = f"{model} Total Precip (in)"
        elif variable == "snowfall":
            map_title = f"{model} Total Snowfall (10:1 Ratio) (in)"
        elif is_mslp_precip:
            map_title = f"{model} 6-hour Averaged Precip Rate (mm/hr), MSLP (hPa), & 1000-500mb Thick (dam)"
        elif is_850mb_map:
            map_title = f"{model} 850mb Temperature (°C)"
        elif is_wind_speed_map:
            map_title = f"{model} 10m Wind Speed (mph) & Streamlines"
        elif variable == "radar" or variable == "radar_reflectivity":
            map_title = f"{model} Simulated Composite Radar Reflectivity (dBZ)"
        elif variable in ["temperature_2m", "temp"]:
            map_title = f"{model} 2m Temperature (°F)"
        else:
            map_title = f"{model} {variable.replace('_', ' ').title()}"
        
        # Add second line with Init/Forecast/Valid info
        info_line = f"Init: {init_time}   Forecast Hour: [{forecast_hour}]  valid at {valid_str}"
        title_text = f"{map_title}\n{info_line}"
        
        # Adjust figure layout to minimize margins and ensure data fills entire map region
        # Set all margins to allow data to stretch to edges while leaving room for title/colorbar
        plt.subplots_adjust(left=0.02, right=0.98, top=0.95, bottom=0.15)
        
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
                    station_values = {k: (v - 273.15) * 9/5 +  32 if v > 100 else v
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
                    # Use 'tp_total' (total precipitation accumulated from hour 0) for station overlays
                    # This matches the total precip shown in contours/colors
                    extract_var = 'tp_total' if 'tp_total' in ds else ('tp' if 'tp' in ds else 'prate')
                    station_values = self.extract_station_values(
                        ds, extract_var, 
                        region=region_to_use,
                        priority_level=settings.station_priority
                    )
                    # Convert based on variable type
                    if extract_var in ['tp_total', 'tp']:
                        # tp_total/tp is already in mm, just convert to inches
                        station_values = {k: v / 25.4 for k, v in station_values.items()}
                    else:
                        # prate is in kg/m²/s, convert to inches (hourly accumulation)
                        station_values = {k: v * 3600 * 0.0393701 
                                        for k, v in station_values.items()}
                
                elif variable == "snowfall":
                    # Use 'tp_snow_total' (total snowfall accumulated from hour 0) for station overlays
                    extract_var = 'tp_snow_total'
                    if extract_var in ds:
                        station_values = self.extract_station_values(
                            ds, extract_var, 
                            region=region_to_use,
                            priority_level=settings.station_priority
                        )
                        # tp_snow_total is already in inches, no conversion needed
                    else:
                        logger.warning("tp_snow_total not found in dataset for station overlays")
                    
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
        
        logger.info(f"Saving map to: {filepath}")
        
        # Save with tight bbox to minimize whitespace around the map
        # pad_inches=0.05 adds just a tiny bit of padding to prevent edge clipping
        # Added explicit format parameter to help matplotlib determine file type
        try:
            plt.savefig(
                filepath, 
                format='png',
                dpi=settings.map_dpi, 
                bbox_inches='tight', 
                pad_inches=0.05, 
                facecolor='white',
                edgecolor='none'
            )
            logger.info(f"plt.savefig() completed")
        except Exception as e:
            logger.error(f"Error during plt.savefig(): {e}")
            raise
        
        # Verify file was created and has content
        if not filepath.exists():
            raise IOError(f"Failed to save map file: {filepath}")
        file_size = filepath.stat().st_size
        if file_size == 0:
            raise IOError(f"Map file is empty: {filepath}")
        logger.info(f"Map file verified: {filepath} ({file_size} bytes)")
        
        # Aggressive memory cleanup to prevent matplotlib leaks
        # CRITICAL: Must explicitly close figure and delete references
        try:
            # Get reference to current figure and axes
            fig = plt.gcf()
            ax = plt.gca()
            
            # Close the specific figure
            plt.close(fig)
            
            # Delete references
            del fig, ax
            
            # Clear any remaining state
            plt.clf()
            plt.cla()
            plt.close('all')
            
            # Force garbage collection for this specific map's objects
            import gc
            gc.collect()
        except Exception as cleanup_error:
            logger.warning(f"Non-critical cleanup warning: {cleanup_error}")
        
        logger.info(f"✓ Map complete: {filename}")
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
        
        result = temp.isel(time=0) if 'time' in temp.dims else temp
        logger.info(f"_process_temperature result - shape: {result.shape}, coords: {list(result.coords.keys())}, dims: {list(result.dims)}")
        return result
    
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
                    precip = precip / max(1, ds['tp'].attrs.get('step', 1))  # Divide by forecast hour
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
                    actual_lat = float(precip.sel({lon_coord: test_lon_sel, lat_coord: test_lat}, method='nearest').coords[latCoord].values)
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
                    # Cannot reliably derive a rate from accumulated tp alone
                    raise ValueError("Cannot derive reflectivity: prate missing and tp-to-rate is not reliable")
                else:
                    raise ValueError("Cannot calculate radar reflectivity: need prate or refc")
                
                # Convert precipitation rate (mm/h) to dBZ using Marshall-Palmer relationship
                # Z = 200 * R^1.6, where Z is reflectivity factor and R is rain rate (mm/h)
                # dBZ = 10 * log10(Z)
                # For R > 0.1 mm/h: dBZ ≈ 10 * log10(200 * R^1.6)
                # For R <= 0.1 mm/h: use lower bound
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
        
        # Clean fill values / invalids before plotting logic
        try:
            fill_values = []
            for key in ['_FillValue', 'missing_value']:
                if key in reflectivity.attrs:
                    fill_values.append(reflectivity.attrs[key])
            for fv in fill_values:
                reflectivity = reflectivity.where(reflectivity != fv)
            reflectivity = reflectivity.where(np.isfinite(reflectivity))
        except Exception:
            pass

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
                if gusts.max() < 200:  # If less than 200, probably m/s
                    gusts = gusts * 2.237  # Convert m/s to mph
            else:
                # Calculate from wind components if available
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
            precip = ds['prate']
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
    
    def _process_thickness(self, ds: xr.Dataset) -> xr.DataArray:
        """
        Process 1000-500mb thickness data.
        
        Thickness is the difference between 500mb and 1000mb geopotential heights,
        measured in decameters (dam). It's used to identify warm/cold air masses.
        
        Args:
            ds: Dataset containing geopotential height data
            
        Returns:
            DataArray with thickness in decameters
        """
        # Try to find gh_500 and gh_1000
        if 'gh_500' in ds and 'gh_1000' in ds:
            gh_500 = ds['gh_500']
            gh_1000 = ds['gh_1000']
        elif 'gh' in ds:
            # Try to extract from multi-level gh variable
            gh = ds['gh']
            if 'isobaricInhPa' in gh.dims:
                try:
                    gh_500 = gh.sel(isobaricInhPa=500)
                    gh_1000 = gh.sel(isobaricInhPa=1000)
                except:
                    logger.warning("Could not extract 500mb and 1000mb levels from gh variable")
                    return None
            else:
                logger.warning("gh variable does not have isobaricInhPa dimension")
                return None
        else:
            # Try to find any geopotential height variables
            gh_vars = [v for v in ds.data_vars if 'gh' in v.lower() and 'geopotential' not in v.lower()]
            if len(gh_vars) >= 2:
                # Assume first two are what we need
                gh_500 = ds[gh_vars[0]]
                gh_1000 = ds[gh_vars[1]]
            else:
                logger.warning("Could not find geopotential height variables for thickness calculation")
                return None
        
        # Clean up time dimensions
        if 'time' in gh_500.dims:
            gh_500 = gh_500.isel(time=0)
        if 'time' in gh_1000.dims:
            gh_1000 = gh_1000.isel(time=0)
        
        gh_500 = gh_500.squeeze()
        gh_1000 = gh_1000.squeeze()
        
        # Calculate thickness (in meters), then convert to decameters
        # Thickness = gh_500 - gh_1000
        thickness = (gh_500 - gh_1000) / 10.0  # Convert meters to decameters
        
        logger.info(f"Thickness range (dam): min={float(thickness.min()):.1f}, max={float(thickness.max()):.1f}")
        
        return thickness
    
    def _process_precipitation_mmhr(self, ds: xr.Dataset, hours: int = 6) -> xr.DataArray:
        """
        Process precipitation data with unit-safety and convert to mm/hr rate.
        
        This method ensures proper unit conversion from accumulated precipitation
        to an average rate in mm/hr for the specified time period.
        
        Args:
            ds: Dataset containing precipitation data
            hours: Number of hours over which precipitation accumulated (default: 6)
            
        Returns:
            DataArray with precipitation rate in mm/hr
        """
        if 'tp' in ds:
            # tp is total precipitation (accumulated), already in mm
            precip = ds['tp']
            
            # Clean up time-related dimensions
            if 'time' in precip.dims:
                precip = precip.isel(time=0)
            if 'valid_time' in precip.coords and hasattr(precip.coords['valid_time'].values, '__len__'):
                if len(precip.coords['valid_time'].values) > 1:
                    precip = precip.isel(valid_time=0)
            
            # Squeeze out any single-element dimensions
            precip = precip.squeeze()
            
            # Convert accumulated mm to mm/hr rate
            precip = precip / hours
            
        elif 'prate' in ds:
            # Precipitation rate: kg/m²/s needs conversion to mm/hr
            # 1 kg/m²/s = 3600 mm/hr
            precip = ds['prate'] * 3600
            if 'time' in precip.dims:
                precip = precip.isel(time=0)
            precip = precip.squeeze()
            
        elif 'APCP_surface' in ds:
            precip = ds['APCP_surface']
            if 'time' in precip.dims:
                precip = precip.isel(time=0)
            precip = precip.squeeze()
            # Convert accumulated mm to mm/hr rate
            precip = precip / hours
            
        else:
            # Try to find precipitation variable
            precip_vars = [v for v in ds.data_vars if 'prate' in v.lower() or 'precip' in v.lower() or v.lower() == 'tp']
            if precip_vars:
                precip = ds[precip_vars[0]]
                if 'prate' in precip_vars[0].lower():
                    precip = precip * 3600  # Convert prate to mm/hr
                else:
                    precip = precip / hours  # Convert accumulated to rate
                if 'time' in precip.dims:
                    precip = precip.isel(time=0)
                precip = precip.squeeze()
            else:
                raise ValueError("Could not find precipitation variable in dataset")
        
        logger.info(f"Precipitation rate range (mm/hr): min={float(precip.min()):.4f}, max={float(precip.max()):.4f}, mean={float(precip.mean()):.4f}")
        
        return precip

    def _get_plot_coords_and_transform(self, da: xr.DataArray, ax):
        """
        Returns (X, Y, transform) suitable for contourf/pcolormesh.
        
        Handles both lat/lon (degrees) and projected (meters) coordinates correctly:
        - If 2D lon/lat exist: use them with PlateCarree() (HRRR curvilinear)
        - If 1D lon/lat exist: use them with PlateCarree() (GFS regular)
        - Else fall back to x/y with ax.projection (already projected coordinates)
        
        This prevents the bug where x/y in meters gets plotted with PlateCarree()
        transform (which expects degrees), causing blank or shifted plots.
        """
        import cartopy.crs as ccrs
        
        # Prefer explicit 2D lon/lat coords (HRRR)
        for lon_name, lat_name in [('longitude', 'latitude'), ('lon', 'lat')]:
            if lon_name in da.coords and lat_name in da.coords:
                lonc = da.coords[lon_name]
                latc = da.coords[lat_name]
                if lonc.ndim == 2 and latc.ndim == 2:
                    logger.debug(f"Using 2D {lon_name}/{lat_name} with PlateCarree()")
                    return lonc, latc, ccrs.PlateCarree()
                if lonc.ndim == 1 and latc.ndim == 1:
                    logger.debug(f"Using 1D {lon_name}/{lat_name} with PlateCarree()")
                    return lonc, latc, ccrs.PlateCarree()
        
        # Fallback: projected grid coordinates (meters) - use ax.projection
        if 'x' in da.coords and 'y' in da.coords:
            logger.debug("Using x/y coords with ax.projection (projected coordinates)")
            return da.coords['x'], da.coords['y'], ax.projection
        
        if 'x' in da.dims and 'y' in da.dims:
            logger.debug("Using x/y dims with ax.projection (projected coordinates)")
            return da['x'], da['y'], ax.projection
        
        raise ValueError(
            f"Could not determine plot coords for DataArray. "
            f"coords={list(da.coords)} dims={list(da.dims)}"
        )

    def _normalize_lonlat(self, da: xr.DataArray) -> xr.DataArray:
        """
        Normalize lon/lat coordinates to standard ranges and orientations.
        
        Handles both:
        - 1D regular grids (GFS): lon(lon), lat(lat)
        - 2D curvilinear grids (HRRR): lon(y,x), lat(y,x)
        """
        import numpy as np
        
        logger.info(f"_normalize_lonlat input - coords: {list(da.coords.keys())}, dims: {list(da.dims)}")
        
        # Identify lon/lat coord names (coords preferred; dims fallback)
        lon = next((n for n in ['longitude', 'lon'] if n in da.coords), None)
        lat = next((n for n in ['latitude', 'lat'] if n in da.coords), None)
        
        # If lon/lat not present as coords, leave unchanged
        if lon is None or lat is None:
            logger.info("No explicit lon/lat coords found; leaving data unchanged for normalization.")
            return da
        
        lon_vals = da.coords[lon].values
        lat_vals = da.coords[lat].values
        
        logger.info(f"Found coords - lon: {lon} (shape: {lon_vals.shape}), lat: {lat} (shape: {lat_vals.shape})")
        
        # --- 2D curvilinear grid path (HRRR etc.) ---
        if np.ndim(lon_vals) == 2 or np.ndim(lat_vals) == 2:
            logger.info("Detected 2D curvilinear grid (HRRR-style)")
            
            # Wrap 0..360 -> -180..180 elementwise (no sorting possible on 2D)
            if np.nanmax(lon_vals) > 180:
                lon_wrapped = (((lon_vals + 180) % 360) - 180)
                da = da.assign_coords({lon: (da.coords[lon].dims, lon_wrapped)})
                logger.info("Applied 0-360 to -180-180 longitude wrapping (2D)")
            
            # Flip "north-up" if needed by comparing mean lat on first vs last row
            lat2 = da.coords[lat].values
            if np.ndim(lat2) == 2:
                # Pick a y-like dim: first dim of lat coord
                ydim = da.coords[lat].dims[0]
                first_row_mean = float(np.nanmean(lat2[0, :]))
                last_row_mean = float(np.nanmean(lat2[-1, :]))
                logger.info(f"Checking orientation: first row mean={first_row_mean:.2f}, last row mean={last_row_mean:.2f}")
                
                if first_row_mean > last_row_mean:
                    da = da.isel({ydim: slice(None, None, -1)})
                    logger.info(f"Flipped {ydim} dimension for north-up orientation")
            
            logger.info(f"_normalize_lonlat 2D output - coords: {list(da.coords.keys())}, dims: {list(da.dims)}")
            return da
        
        # --- 1D regular lat/lon path (GFS etc.) ---
        logger.info("Detected 1D regular grid (GFS-style)")
        
        if np.nanmax(lon_vals) > 180:
            da = da.assign_coords({lon: (((lon_vals + 180) % 360) - 180)})
            da = da.sortby(lon)
            logger.info("Applied 0-360 to -180-180 longitude wrapping and sorting (1D)")
        
        if lat_vals[0] > lat_vals[-1]:
            da = da.reindex({lat: lat_vals[::-1]})
            logger.info("Reindexed latitude to ascending order (1D)")
        
        logger.info(f"_normalize_lonlat 1D output - coords: {list(da.coords.keys())}, dims: {list(da.dims)}")
        return da

    def _normalize_coords(self, obj):
        """Normalize longitude/latitude on either Dataset or DataArray."""
        import xarray as xr
        if isinstance(obj, xr.Dataset):
            for v in list(obj.data_vars):
                obj[v] = self._normalize_lonlat(obj[v])
            return obj
        return self._normalize_lonlat(obj)
