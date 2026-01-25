# TWF Weather Models - Project Overview

**Last Updated**: January 25, 2026

## Executive Summary

The TWF Weather Models project is a **production-ready weather forecast visualization system** that automatically generates and serves high-resolution forecast maps from NOAA's GFS (Global Forecast System) model. The system is deployed on a Digital Ocean droplet and provides both a REST API and a web-based frontend for viewing forecast maps.

**Current Status**: ✅ **Phase 5A Complete** - Backend deployed and operational, generating maps automatically 4 times daily.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    EXTERNAL DATA SOURCE                      │
│  NOAA GFS Model (AWS S3: noaa-gfs-bdp-pds bucket)           │
│  - 0.25° resolution GRIB2 files                             │
│  - Updates every 6 hours (00, 06, 12, 18 UTC)               │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                    BACKEND (Digital Ocean Droplet)          │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Scheduler Service (APScheduler)                     │   │
│  │  - Monitors AWS S3 for new GFS data                  │   │
│  │  - Triggers map generation every 6 hours              │   │
│  │  - Progressive generation (f000 → f024 → f048 → f072)│   │
│  └──────────────────┬───────────────────────────────────┘   │
│                     │                                        │
│  ┌──────────────────▼───────────────────────────────────┐   │
│  │  Data Fetcher Service                                 │   │
│  │  - Downloads GRIB2 files from AWS S3                  │   │
│  │  - GRIB file caching (75% bandwidth reduction)        │   │
│  │  - Handles coordinate system conversion (0-360° ↔ -180/180°)│
│  │  - Subsets data to PNW region for efficiency          │   │
│  └──────────────────┬───────────────────────────────────┘   │
│                     │                                        │
│  ┌──────────────────▼───────────────────────────────────┐   │
│  │  Map Generator Service                               │   │
│  │  - Processes xarray datasets                         │   │
│  │  - Generates maps using Matplotlib + Cartopy         │   │
│  │  - Adds station overlays (9 major PNW cities)        │   │
│  │  - Professional color gradients (38-color temp scale)│   │
│  │  - Outputs PNG images (1920×1080, 150 DPI)          │   │
│  └──────────────────┬───────────────────────────────────┘   │
│                     │                                        │
│  ┌──────────────────▼───────────────────────────────────┐   │
│  │  Storage (Local Filesystem)                         │   │
│  │  - /opt/twf_models/images/                           │   │
│  │  - Filename format: gfs_YYYYMMDD_HH_variable_fHHH.png│
│  │  - Auto-cleanup: Keeps last 4 runs (24 hours)       │   │
│  └──────────────────┬───────────────────────────────────┘   │
│                     │                                        │
│  ┌──────────────────▼───────────────────────────────────┐   │
│  │  FastAPI Server                                      │   │
│  │  - REST API endpoints                                │   │
│  │  - Serves map images and metadata                    │   │
│  │  - CORS-enabled for frontend access                  │   │
│  │  - Health check endpoint                             │   │
│  └──────────────────┬───────────────────────────────────┘   │
└──────────────────────┼────────────────────────────────────────┘
                      │
                      │ HTTPS
                      ▼
┌─────────────────────────────────────────────────────────────┐
│                    FRONTEND (Web Viewer)                     │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Static HTML/CSS/JavaScript                           │   │
│  │  - Pure client-side (no build step)                  │   │
│  │  - Responsive design (mobile/tablet/desktop)         │   │
│  │  - Variable selector (temp, precip, wind, etc.)      │   │
│  │  - Forecast hour selector (0, 24, 48, 72 hours)      │   │
│  │  - Auto-refresh every minute                          │   │
│  │  - Loading indicators and error handling             │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## Backend Components

### 1. **Scheduler Service** (`backend/app/scheduler.py`)

**Purpose**: Automated map generation triggered by GFS data availability

**Key Features**:
- **Progressive Monitoring**: Checks AWS S3 every minute for 90 minutes after each GFS run time
- **Smart Timing**: Runs at 03:30, 09:30, 15:30, 21:30 UTC (3.5 hours after GFS runs)
- **Parallel Generation**: Uses multiprocessing to generate maps for multiple forecast hours simultaneously
- **Error Recovery**: Handles missing data gracefully, retries failed maps
- **Run Management**: Tracks multiple GFS runs, keeps last 4 runs (24 hours)

**Technology**: APScheduler (BlockingScheduler), multiprocessing

**Deployment**: Systemd service (`twf-models-scheduler.service`)

---

### 2. **Data Fetcher Service** (`backend/app/services/data_fetcher.py`)

**Purpose**: Download and process GFS weather data from AWS S3

**Key Features**:
- **GRIB File Caching**: 75% bandwidth reduction by caching downloaded files
- **Coordinate System Handling**: Automatically detects and converts between 0-360° and -180/180° longitude formats
- **Regional Subsetting**: Extracts only Pacific Northwest region data (reduces memory usage)
- **Variable Extraction**: Selectively extracts only needed variables from GRIB files
- **Multi-Level Support**: Handles surface, 2m, 10m, isobaric levels (850mb, 500mb, 1000mb)

**Technology**: 
- `s3fs` for AWS S3 access
- `xarray` + `cfgrib` for GRIB file parsing
- Automatic coordinate system detection and conversion

**Data Source**: AWS S3 bucket `noaa-gfs-bdp-pds` (public, no authentication required)

---

### 3. **Map Generator Service** (`backend/app/services/map_generator.py`)

**Purpose**: Generate high-quality weather forecast maps from processed data

**Key Features**:
- **Multiple Map Types**: Temperature, Precipitation, Wind Speed, MSLP+Precip, 850mb Temp, Radar
- **Professional Styling**: 
  - 38-color temperature gradient (matches TropicalTidbits quality)
  - Fixed color levels for consistent comparison across maps
  - Lambert Conformal projection optimized for PNW
- **Station Overlays**: Displays forecast values at 9 major PNW cities
  - Seattle, Portland, Spokane, Boise, Eugene, Bend, Yakima, Tri-Cities, Bellingham
- **Map Features**: Coastlines, borders, state boundaries, grid lines
- **Memory Management**: Explicitly closes figures and clears memory after generation

**Technology**:
- `matplotlib` for plotting
- `cartopy` for map projections and geographic features
- `xarray` for data manipulation

**Output**: PNG images (1920×1080 pixels, 150 DPI)

---

### 4. **API Server** (`backend/app/main.py`, `backend/app/api/routes.py`)

**Purpose**: REST API for serving maps and metadata to frontend

**Key Endpoints**:
- `GET /api/maps` - List available maps (with filtering by variable, forecast_hour, run_time)
- `GET /api/runs` - List available GFS runs with metadata
- `GET /api/maps/{map_id}` - Get specific map metadata
- `GET /images/{filename}` - Serve map image files
- `GET /health` - Health check endpoint
- `POST /update` - Manually trigger map generation (admin only)

**Features**:
- CORS middleware for cross-origin requests
- Static file serving for images
- Automatic filtering by latest run (if no run_time specified)
- ISO 8601 date format support

**Technology**: FastAPI, Uvicorn

**Deployment**: Systemd service (`twf-models-api.service`), Nginx reverse proxy with SSL

---

### 5. **Configuration** (`backend/app/config.py`)

**Purpose**: Centralized application settings

**Key Settings**:
- Data source configuration (GFS source: AWS vs NOMADS)
- Storage paths and types
- API host/port/CORS origins
- Map generation settings (resolution, region, forecast hours)
- Station overlay configuration

**Configuration Method**: Environment variables via `.env` file (Pydantic Settings)

---

## Frontend Components

### 1. **Main Viewer** (`frontend/models/index.html`)

**Purpose**: Primary user interface for viewing weather maps

**Structure**:
- Header with title and description
- Control panel with variable and forecast hour selectors
- Map display area with loading indicators
- Footer with attribution and update schedule

**Features**:
- Responsive layout (mobile/tablet/desktop)
- Button-based variable selection
- Button-based forecast hour selection
- Real-time map loading with visual feedback

---

### 2. **API Client** (`frontend/models/js/api-client.js`)

**Purpose**: JavaScript client for communicating with backend API

**Methods**:
- `getMaps(filters)` - Fetch maps with optional filtering
- `getRuns()` - Fetch available GFS runs
- `getImageUrl(imageUrl)` - Construct full image URL
- `checkHealth()` - Check API availability

**Technology**: Fetch API (native JavaScript)

---

### 3. **Map Viewer** (`frontend/models/js/map-viewer.js`)

**Purpose**: Main application logic for map display and user interaction

**Key Functionality**:
- Variable selection handling
- Forecast hour selection handling
- Map loading and display
- Auto-refresh every minute
- Error handling and user feedback
- Metadata display (run time, valid time, region)

**Features**:
- Automatic latest map selection
- Loading indicators
- Error messages
- Metadata formatting (human-readable dates/times)

---

### 4. **Configuration** (`frontend/models/config.js`)

**Purpose**: Frontend configuration (API URL, variables, forecast hours)

**Key Settings**:
- `API_BASE_URL` - Backend API endpoint
- `VARIABLES` - Available map types with labels/units
- `FORECAST_HOURS` - Available forecast hours
- `REFRESH_INTERVAL` - Auto-refresh rate (milliseconds)
- `REGION` - Display region name

**Note**: Easy migration between domains by changing `API_BASE_URL`

---

### 5. **Styling** (`frontend/models/css/style.css`)

**Purpose**: Visual styling for the map viewer

**Features**:
- Modern, clean design
- Responsive CSS Grid/Flexbox layout
- Button states (active/inactive)
- Loading spinner animation
- Error message styling
- Mobile-friendly breakpoints

---

## Data Flow

### Map Generation Flow

1. **Scheduler triggers** at scheduled time (03:30, 09:30, 15:30, 21:30 UTC)
2. **Monitor AWS S3** every minute for 90 minutes, checking for new GFS data
3. **Data Fetcher downloads** GRIB file from S3 (or uses cache if available)
4. **Data Fetcher parses** GRIB file, extracts needed variables, subsets to PNW region
5. **Map Generator creates** map image using Matplotlib/Cartopy
6. **Map Generator saves** PNG file to `/opt/twf_models/images/`
7. **Process repeats** for each forecast hour (0, 24, 48, 72) and each variable

### Frontend Request Flow

1. **User selects** variable and forecast hour in UI
2. **Map Viewer calls** `apiClient.getMaps()` with filters
3. **API Client sends** HTTP GET request to `/api/maps?variable=X&forecast_hour=Y`
4. **FastAPI server** scans image directory, filters by criteria, returns JSON
5. **Map Viewer receives** map metadata, constructs image URL
6. **Browser loads** image from `/images/{filename}` endpoint
7. **Map displays** in viewer with metadata

---

## Current Capabilities

### ✅ Implemented Features

**Map Types** (6):
1. Temperature (2m) - °F with 38-color gradient
2. Precipitation - inches
3. Wind Speed - mph
4. MSLP & Precipitation - combined pressure and precip
5. 850mb Temperature, Wind, MSLP - mid-level dynamics
6. Simulated Radar Reflectivity - dBZ

**Forecast Hours**: 0, 24, 48, 72 hours

**Resolution**: 0.25° GFS (46×78 grid points, ~15 mile spacing)

**Region**: Pacific Northwest (WA, OR, ID)

**Station Overlays**: 9 major PNW cities with forecast values

**Automation**: 
- Runs 4 times daily (aligned with GFS updates)
- Progressive generation (maps appear as data becomes available)
- Automatic cleanup (keeps last 4 runs, ~24 hours)

**Performance**:
- GRIB caching: 75% bandwidth reduction
- First map available: ~1 minute after GFS data appears
- Full run generation: ~2-3 minutes for 16 maps (4 hours × 4 variables)

---

## Technology Stack

### Backend
- **Python 3.10+** - Core language
- **FastAPI** - REST API framework
- **APScheduler** - Task scheduling
- **xarray** - Multi-dimensional array handling
- **cfgrib** - GRIB file parsing
- **Matplotlib** - Map generation
- **Cartopy** - Map projections and geographic features
- **s3fs** - AWS S3 file system interface
- **Uvicorn** - ASGI server

### Frontend
- **HTML5** - Structure
- **CSS3** - Styling (Grid, Flexbox)
- **Vanilla JavaScript** - No frameworks (easy portability)
- **Fetch API** - HTTP requests

### Infrastructure
- **Digital Ocean Droplet** - Ubuntu 22.04, 2 vCPU, 2GB RAM
- **Systemd** - Service management
- **Nginx** - Reverse proxy and SSL termination
- **Let's Encrypt/Certbot** - SSL certificates
- **UFW** - Firewall

### Data Sources
- **NOAA GFS** via AWS S3 (`noaa-gfs-bdp-pds` bucket)
- **0.25° GRIB2 files** (pgrb2.0p25)

---

## File Structure

```
twf_models/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py              # FastAPI application
│   │   ├── config.py            # Configuration settings
│   │   ├── scheduler.py         # Automated map generation scheduler
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   └── routes.py        # API endpoints
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   └── schemas.py       # Pydantic data models
│   │   └── services/
│   │       ├── __init__.py
│   │       ├── data_fetcher.py  # GFS data download and processing
│   │       ├── map_generator.py # Map image generation
│   │       └── stations.py      # Station overlay data
│   └── requirements.txt
│
├── frontend/
│   └── models/
│       ├── index.html           # Main viewer page
│       ├── config.js            # Frontend configuration
│       ├── css/
│       │   └── style.css       # Styling
│       └── js/
│           ├── api-client.js    # API communication
│           └── map-viewer.js   # Main app logic
│
├── deployment/
│   ├── twf-models-api.service      # Systemd service for API
│   └── twf-models-scheduler.service # Systemd service for scheduler
│
├── scripts/
│   ├── setup_droplet.sh         # Initial server setup
│   └── deploy.sh                # Deployment script
│
└── docs/
    ├── API.md                   # API documentation
    ├── DEPLOYMENT_GUIDE_WALKTHROUGH.md
    ├── INTEGRATION.md           # Frontend integration guide
    ├── GOTCHAS.md               # Common issues
    └── ROADMAP.md               # Project roadmap
```

---

## Deployment

### Production Environment

**API Server**: `https://api.sodakweather.com` (or `http://174.138.84.70:8000`)  
**Frontend**: `https://sodakweather.com/models`  
**Droplet**: 174.138.84.70 (2GB RAM, 2 vCPU, Ubuntu 22.04)

**Services**:
- `twf-models-api` - FastAPI server (runs on port 8000)
- `twf-models-scheduler` - Map generation scheduler

**Storage**: `/opt/twf_models/images/` (local filesystem)

**SSL**: Let's Encrypt certificates via Certbot

---

## Future Enhancements (Planned)

### High Priority
- **Additional Map Types** (10-15 more): MSLP+precip, 500mb height/vorticity, accumulated snowfall, 24h precip, etc.
- **Extended Forecast Hours**: Every 3h to 48h (17 maps), every 6h to 120h (12 maps) = ~30 total hours
- **Interactive Slider**: Play/pause animation, speed control, step forward/backward
- **Run Time Selection**: Dropdown to view last 4 runs with age display
- **GIF Generation**: Create animated GIFs from forecast sequences

### Medium Priority
- **Mobile Optimization**: Touch-friendly controls, responsive improvements
- **Parallel Processing**: Reduce full generation time to <2 minutes
- **Memory Optimization**: Handle 2GB RAM constraints better
- **Terrain Overlays**: Add elevation/topography to maps

---

## Key Design Decisions

1. **GRIB-Only Data Source**: NetCDF had SSL certificate issues; GRIB is reliable and well-cached
2. **Progressive Monitoring**: Real-time S3 checks provide better UX than scheduled bulk generation
3. **Fixed Color Levels**: Essential for professional weather maps and user comparison
4. **Multi-Run Retention**: Keeps last 4 runs (24 hours) for model comparison
5. **Pure JavaScript Frontend**: No build step, easy to deploy to any web host
6. **Regional Subsetting**: Only fetch PNW data to reduce memory and bandwidth usage
7. **GRIB Caching**: 75% bandwidth reduction makes system viable on small droplet

---

## Performance Metrics

- **Map Generation Time**: ~5-10 seconds per map (with cache)
- **First Map Available**: ~1 minute after GFS data appears on S3
- **Full Run Generation**: ~2-3 minutes for 16 maps (4 hours × 4 variables)
- **Bandwidth Saved**: 75% reduction via GRIB caching
- **Uptime**: Stable since deployment, auto-recovers from errors

---

## Documentation

- **PROJECT_STATUS.md** - Current status and progress tracking
- **DEPLOYMENT_SUCCESS.md** - Deployment summary and monitoring
- **docs/API.md** - API endpoint documentation
- **docs/INTEGRATION.md** - Frontend integration guide
- **docs/DEPLOYMENT_GUIDE_WALKTHROUGH.md** - Step-by-step deployment instructions
- **docs/GOTCHAS.md** - Common issues and solutions
- **docs/ROADMAP.md** - Project phases and timeline

---

## Summary

This is a **production-ready weather forecast visualization system** that:
- Automatically generates high-quality forecast maps from GFS model data
- Serves maps via a REST API and web frontend
- Handles data fetching, processing, and visualization automatically
- Provides professional-quality maps with station overlays
- Is deployed and operational, generating maps 4 times daily

The system is well-architected, documented, and ready for expansion to additional map types and forecast hours.
