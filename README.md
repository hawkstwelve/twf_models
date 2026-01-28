# TWF Weather Models - Custom Forecast Maps

An automated weather forecast map generation and delivery system providing high-resolution, professional-quality maps for the Pacific Northwest region. The system supports multiple weather models (GFS, AIGFS), generates custom maps with station overlays, and serves them via a REST API with an interactive frontend viewer.

## Project Overview

This project provides custom weather forecast maps for display on The Weather Forums (theweatherforums.com/models). The system runs on a VPS (16GB RAM / 8 vCPU), automatically generating maps four times daily aligned with model run schedules.

### System Components

1. **Multi-Model Backend Service**: Automated data fetching, processing, and map generation for GFS and AIGFS models
2. **REST API**: FastAPI server serving generated maps and metadata with model-aware endpoints
3. **Frontend Viewer**: Interactive map gallery with model selector, variable dropdown, time slider, and animation controls
4. **Scheduler**: Systemd-based automation with progressive generation and intelligent worker management

### Current Deployment

- **API**: https://api.sodakweather.com
- **Test Frontend**: https://sodakweather.com/models
- **Production Target**: theweatherforums.com/models

## Architecture

The system follows a multi-model pipeline architecture with intelligent data fetching:

```
┌──────────────────┐
│ Weather Models   │  NOAA NOMADS Server
│ GFS + AIGFS      │  Updated every 6 hours (00, 06, 12, 18 UTC)
│ (NOMADS)         │
└────────┬─────────┘
         │
         │ Progressive monitoring (checks every minute for up to 90 min)
         ▼
┌──────────────────┐
│  Model Factory   │  Creates model-specific data fetchers
│  Data Fetcher    │  - GFS: Filtered NOMADS requests (small downloads)
│  (Backend)       │  - AIGFS: Full GRIB2 files (~2-3GB per run)
│                  │  - Regional subsetting (PNW: 40-50°N, 235-245°E)
│                  │  - Intelligent GRIB caching (75% bandwidth savings)
└────────┬─────────┘
         │
         │ Dataset building with derived fields
         ▼
┌──────────────────┐
│  Map Generator   │  Pure rendering engine (matplotlib + cartopy)
│  (Backend)       │  - Station overlays (9 PNW cities)
│                  │  - Professional colormaps (38-color temp gradient)
│                  │  - Model-aware variable filtering
└────────┬─────────┘
         │
         │ Parallel generation (2-3 workers based on memory)
         ▼
┌──────────────────┐
│  Image Storage   │  Local filesystem with automated cleanup
│  (/opt/...)      │  - Retains last 4 runs (24 hours) per model
│                  │  - Naming: {model}_{run}_{variable}_{hour}.png
└────────┬─────────┘
         │
         │ HTTP requests
         ▼
┌──────────────────┐
│  FastAPI Server  │  REST API with CORS support
│  (Port 8000)     │  - /api/models (list available models)
│                  │  - /api/maps (filter by model/variable/hour)
│                  │  - /api/runs (list model runs with metadata)
│                  │  - SSL via Let's Encrypt
└────────┬─────────┘
         │
         │ HTTPS
         ▼
┌──────────────────┐
│  Frontend        │  Interactive viewer with:
│  (sodakweather)  │  - Model dropdown selector
│                  │  - Variable dropdown
│                  │  - Time slider with animation
│                  │  - Play/pause controls with speed adjustment
│                  │  - Mobile-responsive design
└──────────────────┘
```

### Scheduling & Data Flow
- **Systemd Services**: API server and scheduler run as separate systemd services
- **Model Alignment**: Generation starts 3.5 hours after each model run time
- **Progressive Generation**: Checks data availability every minute, generates maps as data arrives
- **Parallel Processing**: 2-3 worker processes (dynamically calculated based on available RAM)
- **Error Handling**: Automatic retry logic with exponential backoff
- **Memory Management**: Intelligent cleanup between models to prevent OOM conditions

## Technology Stack

### Backend
- **Python 3.11**: Core language
- **FastAPI**: REST API framework with async support
- **xarray & cfgrib**: GRIB2 data parsing and manipulation
- **MetPy**: Meteorological calculations and variable transformations
- **Cartopy**: Map projections and geographic features
- **Matplotlib**: Professional-quality map rendering (non-interactive AGG backend)
- **Systemd**: Service management and scheduling
- **Multiprocessing**: Parallel map generation with dynamic worker allocation

### Data Sources
- **GFS 0.25°**: NOAA's Global Forecast System via NOMADS
  - High-resolution model (46×78 grid points over PNW)
  - Updated every 6 hours (00, 06, 12, 18 UTC)
  - Filtered requests for efficient downloads
  - 75% bandwidth savings via intelligent GRIB caching
  
- **AIGFS**: NOAA's AI-Enhanced Global Forecast System via NOMADS
  - Same resolution and schedule as GFS
  - Full GRIB2 downloads (~2-3GB per run)
  - No simulated radar support (excluded automatically)
  - Includes upper air pressure levels

### Infrastructure
- **VPS**: 16GB RAM, 8 vCPU, 240GB SSD, Ubuntu 22.04
- **SSL**: Let's Encrypt certificates via Certbot
- **Storage**: Local filesystem with automated cleanup and multi-run retention
- **Performance**: Dynamic worker allocation based on available memory

## Current Capabilities

### Supported Models
1. **GFS** (Global Forecast System) - NOAA's operational global model
2. **AIGFS** (AI-Enhanced GFS) - NOAA's machine learning-enhanced model
3. **HRRR** (High-Resolution Rapid Refresh) - Registered but disabled (future support)

### Map Products (6 Variables)
Generated for both GFS and AIGFS models (where supported):

1. **Surface Temperature (2m)** - Professional 38-color gradient, °F with fixed levels (-40°F to 115°F)
2. **Precipitation** - Total accumulation from forecast start, inches
3. **Wind Speed** - 10m winds, mph
4. **MSLP & Precipitation** - Mean sea level pressure contours with 6-hour precipitation rate overlay (mm/hr)
5. **850mb Analysis** - Temperature (°F), wind barbs (kt), and MSLP contours (mb)
6. **Simulated Radar** - Composite reflectivity (dBZ) - **GFS only** (AIGFS excluded automatically)

### Features
- **Multi-Model Support**: Extensible model registry system with model-specific configurations
- **0.25° Resolution**: 4x higher detail than standard GFS maps (~15 mile grid spacing)
- **Station Overlays**: Forecast values displayed at 9 major PNW cities (handles 0-360° vs -180/180° longitude formats)
- **Progressive Generation**: Maps available as soon as model data arrives (f000 first, then f006, f012, etc.)
- **Multi-Run Retention**: Keeps last 4 model runs (24 hours) per model for comparison
- **Automated Cleanup**: Manages disk space automatically per model
- **Smart Caching**: 75% bandwidth reduction via GRIB file reuse
- **Model-Aware API**: Frontend can filter by model and automatically detects available variables per model
- **Variable Requirements System**: Central registry defines data requirements for each map type

### Forecast Range
- **Current Implementation**: 13 forecast hours (0, 6, 12, 18, 24, 30, 36, 42, 48, 54, 60, 66, 72)
- **6-hour increments** for smooth temporal resolution
- **Configurable**: Can easily extend to 120+ hours in 6-hour increments

## Project Structure

```
twf_models/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                     # FastAPI app
│   │   ├── config.py                   # Configuration (forecast hours, regions, etc.)
│   │   ├── scheduler.py                # Multi-model scheduler with worker management
│   │   ├── models/
│   │   │   ├── model_registry.py       # Model configurations (GFS, AIGFS, HRRR)
│   │   │   ├── variable_requirements.py # Data requirements for each map type
│   │   │   └── schemas.py              # API response models
│   │   ├── services/
│   │   │   ├── model_factory.py        # Creates model-specific data fetchers
│   │   │   ├── base_data_fetcher.py    # Base fetcher with GRIB caching
│   │   │   ├── nomads_data_fetcher.py  # NOMADS-specific fetching logic
│   │   │   ├── map_generator.py        # Pure rendering engine
│   │   │   └── stations.py             # Station overlay data
│   │   └── api/
│   │       └── routes.py               # API endpoints (models, maps, runs)
│   ├── requirements.txt
│   └── test_setup.py
├── frontend/models/                    # Interactive viewer
│   ├── index.html                      # Main HTML with model/variable selectors
│   ├── config.js                       # Frontend configuration
│   ├── css/style.css                   # Modern weather app styling
│   └── js/
│       ├── api-client.js               # API communication layer
│       └── map-viewer.js               # Viewer logic (slider, animation)
├── deployment/
│   ├── twf-models-api.service          # Systemd service for API
│   └── twf-models-scheduler.service    # Systemd service for scheduler
├── scripts/
│   ├── deploy.sh
│   └── tests/                          # Manual test scripts
│       ├── run_latest_gfs_now.py       # Generate GFS maps on demand
│       ├── run_latest_aigfs_now.py     # Generate AIGFS maps on demand
│       ├── run_latest_now.py           # Generate all models
│       ├── test_temp_map.py            # Test individual map types
│       ├── test_850mb_map.py
│       ├── test_radar_map.py
│       └── test_mslp_precip_map.py
├── docs/
│   ├── API.md                          # API documentation
│   ├── INTEGRATION.md                  # Forum integration strategy
│   └── PERFORMANCE_PLAN.md             # Memory optimization & diagnostics
├── archive/research/                    # Historical research/tests
└── README.md
```

## Project Status

### ✅ Completed
- **Multi-Model Backend**: GFS and AIGFS support with extensible model registry
- **API Operational**: FastAPI server with SSL certificates at api.sodakweather.com
- **Model-Aware Endpoints**: `/api/models`, `/api/maps`, `/api/runs` with filtering
- **Automated Generation**: 4x daily (03:30, 09:30, 15:30, 21:30 UTC) for all enabled models
- **Progressive Monitoring**: Checks NOMADS every minute, generates maps as data arrives
- **6 Map Variables**: Temperature, precipitation, wind speed, MSLP & precip, 850mb analysis, radar (GFS only)
- **13 Forecast Hours**: 0-72h in 6-hour increments (configurable to 120h+)
- **Station Overlays**: Accurate coordinate handling for 9 PNW cities
- **GRIB Caching**: 75% bandwidth reduction for GFS filtered requests
- **Multi-Run Retention**: Last 4 runs per model with automated cleanup
- **Interactive Frontend**: Deployed at sodakweather.com/models with:
  - Model dropdown selector (GFS/AIGFS)
  - Variable dropdown (auto-populated from API)
  - Time slider with forecast hour labels
  - Play/pause animation controls with adjustable speed (0.5-4 fps)
  - Mobile-responsive design
- **Dynamic Worker Management**: Adjusts parallelism based on available RAM (2-3 workers)
- **Memory Optimization**: Intelligent cleanup between models to prevent OOM

### 🚧 In Progress
- **Performance Tuning**: Addressing memory pressure on 16GB VPS
  - Dynamic worker calculation (psutil-based)
  - Swap space configuration
  - Memory cleanup between models
- **Additional Variables**: Expanding beyond current 6 types
  - 500mb Height & Vorticity
  - Accumulated Snowfall (10:1 SLR)
  - 24-hour Accumulated Precipitation
  - Precipitation Type (rain/snow/freezing masks)
  - 700mb Temperature Advection & Frontogenesis
  - PWAT, CAPE, Surface Wind Gusts

### ⏳ Planned
- **Extended Forecast Hours**: 
  - Every 3h to 48h (17 hours)
  - Every 6h to 120h (13 additional hours)
  - Total: ~30 forecast hours per variable per model
- **HRRR Model Support**: High-resolution short-range forecasts (currently registered but disabled)
- **Frontend Enhancements**:
  - Model run time selector dropdown
  - Side-by-side model comparison
  - GIF animation export
  - Full-screen mode
- **Production Deployment**: Launch on theweatherforums.com/models after thorough testing on sodakweather.com
- **Additional Regions**: Expand beyond PNW (configurable via settings)

## Documentation

Detailed documentation is available in the `docs/` directory:

- **[API.md](docs/API.md)** - Complete API documentation with examples for multi-model endpoints
- **[INTEGRATION.md](docs/INTEGRATION.md)** - 3-phase deployment strategy and forum integration guide
- **[PERFORMANCE_PLAN.md](docs/PERFORMANCE_PLAN.md)** - VPS performance optimization, memory management, and diagnostic commands

## API Endpoints

The REST API provides model-aware access to generated maps and metadata:

### Model Management
- `GET /api/models` - List all enabled models with capabilities (resolution, max forecast hour, excluded variables)
- `GET /api/models/{model_id}` - Get detailed info about a specific model (GFS, AIGFS, etc.)

### Map Access
- `GET /api/maps` - List available maps with filtering:
  - `?model=GFS` - Filter by model
  - `?variable=temp` - Filter by variable
  - `?forecast_hour=12` - Filter by forecast hour
  - `?run_time=2026-01-27T12:00:00Z` - Filter by run time
- `GET /api/runs` - List available model runs with metadata
  - `?model=GFS` - Filter by model (default: GFS)
- `GET /images/{filename}` - Serve map images with ETag support
- `GET /health` - API health check

**Example:**
```
https://api.sodakweather.com/api/models
https://api.sodakweather.com/api/maps?model=GFS&variable=temp&forecast_hour=24
https://api.sodakweather.com/api/maps?model=AIGFS
```

## Development & Testing

### Test Scripts
Manual test scripts are available in `scripts/tests/` for local development and on-demand generation:

```bash
# Generate maps for specific models
python scripts/tests/run_latest_gfs_now.py      # GFS only (filtered downloads, ~10-20 min)
python scripts/tests/run_latest_aigfs_now.py    # AIGFS only (full GRIB2, ~20-40 min)
python scripts/tests/run_latest_now.py          # All enabled models (~30-60 min)

# Test individual map types
python scripts/tests/test_temp_map.py           # Temperature map
python scripts/tests/test_precip_map.py         # Precipitation
python scripts/tests/test_850mb_map.py          # 850mb analysis
python scripts/tests/test_radar_map.py          # Simulated radar
python scripts/tests/test_mslp_precip_map.py    # MSLP with precipitation
python scripts/tests/test_wind_speed_map.py     # Wind speed
```

See `scripts/tests/TEST_SCRIPTS_README.md` for detailed usage instructions.

### Configuration
Configuration is managed through:
- **Environment variables**: Set in production systemd services
- **backend/app/config.py**: Forecast hours, regions, storage paths, API settings
- **Model Registry**: `backend/app/models/model_registry.py` - Add/configure models
- **Variable Requirements**: `backend/app/models/variable_requirements.py` - Define data needs per map type

### Adding a New Model
1. Register model in `model_registry.py` with NOMADS paths and patterns
2. Implement data fetcher in `services/` if special handling needed (or use base fetcher)
3. Add model to frontend `config.js` for dropdown
4. Enable in registry (`enabled=True`)

### Adding a New Variable
1. Define requirements in `variable_requirements.py` (raw fields, derived fields)
2. Add rendering logic in `map_generator.py`
3. Add to scheduler's `variables` list
4. Frontend auto-detects via API

## Next Steps

The project is currently focused on stability, performance optimization, and expanding capabilities:

### Immediate Priorities
1. **Variable Expansion**: Add 5-10 additional map types
   - Winter weather focus (snowfall, ice, freezing levels)
   - Upper air products (500mb height, vorticity)
   - Convective parameters (CAPE, helicity)
2. **Extended Forecast Hours**: Implement 3-hour resolution to 48h, 6-hour to 120h

### Medium-Term Goals
3. **HRRR Support**: Enable high-resolution short-range model
4. **Frontend Polish**: 
   - Model run time selector
   - Side-by-side comparison
   - GIF export

### Long-Term Vision
5. **Production Launch**: Deploy to theweatherforums.com/models after comprehensive testing
6. **Additional Regions**: Support CONUS, other regions beyond PNW
7. **Model Ensemble**: Compare multiple model outputs side-by-side

For integration strategy, see [INTEGRATION.md](docs/INTEGRATION.md).  
For performance diagnostics, see [PERFORMANCE_PLAN.md](docs/PERFORMANCE_PLAN.md).

---

**Last Updated**: January 28, 2026
