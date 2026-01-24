"""Map generation service"""
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
from cartopy.mpl.gridliner import LONGITUDE_FORMATTER, LATITUDE_FORMATTER
import xarray as xr
import numpy as np
from pathlib import Path
from datetime import datetime
import logging
from typing import Optional

from app.config import settings
from app.services.data_fetcher import GFSDataFetcher
from app.services.stations import get_stations_for_region, format_station_value

logger = logging.getLogger(__name__)


class MapGenerator:
    """Generates weather forecast maps"""
    
    def __init__(self):
        self.data_fetcher = GFSDataFetcher()
        self.storage_path = Path(settings.storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
    
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
        variable: str,
        model: str = "GFS",
        run_time: Optional[datetime] = None,
        forecast_hour: int = 0,
        region: Optional[str] = None
    ) -> Path:
        """Generate a map for a specific variable"""
        logger.info(f"Generating map: {variable} from {model}, forecast hour {forecast_hour}")
        
        # Fetch data - optimized to only get what we need
        if model.upper() == "GFS":
            # Determine which variables we need for this specific map
            needed_vars = []
            if variable in ["temperature_2m", "temp", "precipitation_type", "precip_type"]:
                needed_vars = ['tmp2m', 'prate']  # Need temp and precip for precip type
            elif variable in ["precipitation", "precip"]:
                needed_vars = ['prate']
            elif variable in ["wind_speed_10m", "wind_speed"]:
                needed_vars = ['ugrd10m', 'vgrd10m']
            
            # Fetch only what we need, subset to PNW region
            ds = self.data_fetcher.fetch_gfs_data(
                run_time, 
                forecast_hour,
                variables=needed_vars,
                subset_region=True  # Only fetch PNW region
            )
        else:
            raise ValueError(f"Unsupported model: {model}")
        
        # Select variable and process
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
        elif variable == "precipitation_type" or variable == "precip_type":
            data = self._process_precipitation_type(ds)
            units = ""
            cmap = "Set3"  # Discrete colors for different precip types
        elif variable == "precipitation" or variable == "precip":
            data = self._process_precipitation(ds)
            units = "in"  # Inches for PNW users
            cmap = "Blues"
        elif variable == "wind_speed_10m" or variable == "wind_speed":
            data = self._process_wind_speed(ds)
            units = "mph"  # MPH for PNW users
            cmap = "YlOrRd"
        # Note: wind_gusts removed for initial release, can be added later
        else:
            raise ValueError(f"Unsupported variable: {variable}")
        
        # Generate map
        fig = plt.figure(figsize=(settings.map_width/100, settings.map_height/100), dpi=settings.map_dpi)
        
        # Set projection based on region
        region_to_use = region or settings.map_region
        
        if region_to_use == "pnw":
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
        elif region_to_use == "us":
            ax = plt.axes(projection=ccrs.LambertConformal(central_longitude=-95, central_latitude=35))
            ax.set_extent([-130, -65, 20, 50], crs=ccrs.PlateCarree())
        else:
            ax = plt.axes(projection=ccrs.PlateCarree())
            ax.set_global()
        
        # Add map features
        ax.add_feature(cfeature.COASTLINE, linewidth=0.5)
        ax.add_feature(cfeature.BORDERS, linewidth=0.5)
        ax.add_feature(cfeature.STATES, linewidth=0.3, linestyle=':')
        ax.add_feature(cfeature.LAND, facecolor='lightgray', alpha=0.5)
        ax.add_feature(cfeature.OCEAN, facecolor='lightblue', alpha=0.5)
        
        # Plot data
        # Handle precipitation type differently (discrete values)
        if variable in ["precipitation_type", "precip_type"]:
            # Use discrete colormap for precip type
            from matplotlib.colors import ListedColormap, BoundaryNorm
            colors = ['white', 'blue', 'lightblue', 'cyan']  # None, Rain, Snow, Freezing
            cmap_discrete = ListedColormap(colors)
            bounds = [-0.5, 0.5, 1.5, 2.5, 3.5]
            norm = BoundaryNorm(bounds, cmap_discrete.N)
            
            if hasattr(data, 'lat') and hasattr(data, 'lon'):
                im = ax.contourf(
                    data.lon, data.lat, data,
                    transform=ccrs.PlateCarree(),
                    cmap=cmap_discrete,
                    norm=norm,
                    levels=bounds,
                    extend='neither'
                )
            else:
                im = ax.contourf(
                    data.coords.get('lon', data.coords.get('longitude')),
                    data.coords.get('lat', data.coords.get('latitude')),
                    data,
                    transform=ccrs.PlateCarree(),
                    cmap=cmap_discrete,
                    norm=norm,
                    levels=bounds,
                    extend='neither'
                )
        else:
            # Continuous data
            # For temperature, use fixed levels for consistent colors across all maps
            if variable in ["temperature_2m", "temp"]:
                # Use 2.5 degree increments to make the gradient smoother 
                # while keeping labels consistent with your 5-degree target
                temp_levels = np.arange(-40, 122.5, 2.5)
            else:
                temp_levels = 20  # Auto levels for other variables
            
            if hasattr(data, 'lat') and hasattr(data, 'lon'):
                im = ax.contourf(
                    data.lon, data.lat, data,
                    transform=ccrs.PlateCarree(),
                    cmap=cmap,
                    levels=temp_levels,
                    extend='both'
                )
            else:
                # Fallback if coordinates are different
                im = ax.contourf(
                    data.coords.get('lon', data.coords.get('longitude')),
                    data.coords.get('lat', data.coords.get('latitude')),
                    data,
                    transform=ccrs.PlateCarree(),
                    cmap=cmap,
                    levels=temp_levels,
                    extend='both'
                )
        
        # Add colorbar
        if variable in ["precipitation_type", "precip_type"]:
            cbar = plt.colorbar(im, ax=ax, orientation='horizontal', pad=0.05, aspect=40, 
                               ticks=[0, 1, 2, 3])
            cbar.set_ticklabels(['No Precip', 'Rain', 'Snow', 'Freezing'])
            cbar.set_label("Precipitation Type")
        else:
            cbar = plt.colorbar(im, ax=ax, orientation='horizontal', pad=0.05, aspect=40)
            cbar.set_label(f"{variable.replace('_', ' ').title()} ({units})")
        
        # Add gridlines
        gl = ax.gridlines(crs=ccrs.PlateCarree(), draw_labels=True,
                         linewidth=0.5, color='gray', alpha=0.5, linestyle='--')
        gl.top_labels = False
        gl.right_labels = False
        gl.xformatter = LONGITUDE_FORMATTER
        gl.yformatter = LATITUDE_FORMATTER
        
        # Add title
        run_str = run_time.strftime("%Y-%m-%d %H:00 UTC") if run_time else "Latest"
        plt.title(f"{model} {variable.replace('_', ' ').title()} - {run_str} +{forecast_hour}h", 
                 fontsize=14, fontweight='bold')
        
        # Add station overlays if enabled
        if settings.station_overlays and variable not in ["precipitation_type", "precip_type"]:
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
                    station_values = {k: (v - 273.15) * 9/5 + 32 
                                    for k, v in station_values.items()}
                    
                elif variable in ["precipitation", "precip"]:
                    extract_var = 'prate'
                    station_values = self.extract_station_values(
                        ds, extract_var, 
                        region=region_to_use,
                        priority_level=settings.station_priority
                    )
                    # Convert kg/m²/s to inches (hourly accumulation)
                    station_values = {k: v * 3600 * 0.0393701 
                                    for k, v in station_values.items()}
                    
                elif variable in ["wind_speed_10m", "wind_speed"]:
                    # Wind speed requires calculating magnitude from u and v components
                    from app.services.stations import get_stations_for_region
                    stations = get_stations_for_region(region_to_use, settings.station_priority)
                    station_values = {}
                    
                    for station_name, station_data in stations.items():
                        try:
                            # Extract u and v components
                            u = ds['ugrd10m'].sel(
                                latitude=station_data['lat'],
                                longitude=station_data['lon'],
                                method='nearest'
                            ).values
                            v = ds['vgrd10m'].sel(
                                latitude=station_data['lat'],
                                longitude=station_data['lon'],
                                method='nearest'
                            ).values
                            
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
        plt.close()
        
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
    
    def _process_precipitation(self, ds: xr.Dataset) -> xr.DataArray:
        """Process precipitation data"""
        if 'prate' in ds:
            precip = ds['prate'] * 3600  # Convert kg/m²/s to mm/h
        elif 'APCP_surface' in ds:
            precip = ds['APCP_surface']
        else:
            precip_vars = [v for v in ds.data_vars if 'prate' in v.lower() or 'precip' in v.lower()]
            if precip_vars:
                precip = ds[precip_vars[0]]
            else:
                raise ValueError("Could not find precipitation variable in dataset")
        
        # Convert mm to inches for PNW users
        precip = precip / 25.4
        
        return precip.isel(time=0) if 'time' in precip.dims else precip
    
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
