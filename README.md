# TWF Weather Models - Custom Forecast Maps

A system for generating and hosting custom weather forecast maps from models like GFS and Graphcast.

## Project Overview

This project consists of:
1. **Backend Service** (Digital Ocean droplet): Downloads weather model data, processes it, and generates custom maps
2. **API Server**: Serves generated maps and metadata
3. **Frontend Integration**: Displays maps at `theweatherforums.com/models` (Invision Community)

**Note**: The forums are hosted on a Digital Ocean droplet. This project can be deployed on the same droplet or a separate one (recommended for isolation).

## Architecture

```
┌─────────────────┐
│  Weather Models │  (GFS, Graphcast APIs/data sources)
│  (External)     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Backend Worker │  (Digital Ocean Droplet)
│  - Data Fetch   │
│  - Processing   │
│  - Map Gen      │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Image Storage  │  (Local filesystem or S3/DO Spaces)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  API Server     │  (FastAPI/Flask)
│  - Serve images │
│  - Metadata     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Frontend       │  (theweatherforums.com/models)
│  - Map Gallery  │
│  - Viewer       │
└─────────────────┘
```

## Technology Stack

### Backend
- **Python 3.10+**: Core language
- **FastAPI**: API framework
- **xarray**: NetCDF/GRIB data handling
- **MetPy**: Meteorological calculations
- **Cartopy**: Map projections and visualization
- **Matplotlib/Plotly**: Map generation
- **APScheduler**: Scheduled data fetching
- **Celery** (optional): For heavy async processing

### Data Sources
- **GFS**: NOAA's Global Forecast System (via NOMADS or AWS)
- **Graphcast**: Google's AI weather model (via API or local processing)

### Infrastructure
- **Digital Ocean Droplet**: $6-24/month depending on specs
- **Storage**: Local or DO Spaces ($5/month for 250GB)
- **CDN** (optional): Cloudflare for image delivery

## Cost Estimates

### Monthly Costs
- **Digital Ocean Droplet**: 
  - Basic: $6/month (512MB RAM, 1 vCPU) - *may be insufficient*
  - Recommended: $12/month (1GB RAM, 1 vCPU) - *minimum for processing*
  - Optimal: $24/month (2GB RAM, 2 vCPU) - *better performance*
- **Storage (DO Spaces)**: $5/month for 250GB
- **Bandwidth**: Usually included (1-2TB)
- **Domain/CDN**: Free if using existing domain

**Total Estimated Monthly Cost: $17-29/month**

### One-Time Costs
- Domain setup (if needed): $0-15/year
- Development time: Variable

## Difficulty Assessment

### Complexity: **Medium to High**

**Challenges:**
1. **Weather Data Formats**: GRIB/NetCDF files require specialized libraries
2. **Map Projections**: Geographic coordinate systems and projections
3. **Data Volume**: GFS files can be 100MB-1GB+ per forecast
4. **Processing Time**: Map generation can take 30 seconds to several minutes
5. **Scheduling**: Coordinating data availability with processing
6. **Error Handling**: Network issues, missing data, processing failures

**Easier Aspects:**
- Well-documented Python libraries (MetPy, Cartopy)
- Standard web API patterns
- Existing infrastructure (your forum)

## Potential Gotchas

### 1. **Data Access & Rate Limits**
- GFS data via NOMADS has rate limits
- AWS S3 bucket (noaa-gfs-bdp-pds) is free but requires proper access patterns
- Graphcast may require API keys or local model execution

### 2. **File Sizes & Storage**
- GFS full resolution files are massive (500MB-2GB per run)
- Need strategy for partial downloads or subsetting
- Image storage will grow over time (need cleanup/rotation)

### 3. **Processing Time**
- Full GFS processing can take 10-30 minutes
- Need async processing or background jobs
- Users shouldn't wait for real-time generation

### 4. **Coordinate Systems**
- Weather data uses various projections
- Need to handle lat/lon conversions correctly
- Map boundaries and zoom levels

### 5. **Update Frequency**
- GFS updates every 6 hours (00, 06, 12, 18 UTC)
- Need to sync processing with model runs
- Handle delays in data availability

### 6. **Resource Constraints**
- Memory usage for large datasets
- CPU for map rendering
- Disk space for cached data

### 7. **Integration with Existing Site**
- CORS if different domains
- Authentication if needed
- Styling consistency

### 8. **Error Recovery**
- What if model run is delayed?
- What if processing fails?
- Need fallback/retry mechanisms

## Project Structure

```
twf_models/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py              # FastAPI app
│   │   ├── config.py            # Configuration
│   │   ├── models/              # Data models
│   │   ├── services/
│   │   │   ├── data_fetcher.py  # Download weather data
│   │   │   ├── processor.py     # Process data
│   │   │   └── map_generator.py # Generate maps
│   │   ├── api/
│   │   │   └── routes.py        # API endpoints
│   │   └── scheduler.py         # Scheduled tasks
│   ├── tests/
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/                    # (Optional, if separate)
│   └── ...
├── scripts/
│   ├── setup_droplet.sh         # Initial server setup
│   └── deploy.sh                # Deployment script
├── docs/
│   └── API.md                   # API documentation
├── .env.example
├── docker-compose.yml
└── README.md
```

## Current Status

✅ **Phase 1 Complete**: Backend deployed and operational on Digital Ocean  
🚧 **Phase 2 In Progress**: Local development of enhanced features  
⏳ **Phase 3 Planned**: Frontend development and testing on sodakweather.com  
⏳ **Phase 4 Planned**: Production launch on theweatherforums.com/models

**Deployment**: http://174.138.84.70:8000 (Backend API)

## Quick Start

### Test Locally
```bash
# Generate a quick test map
python3 test_quick_map.py

# Generate all maps for all forecast hours
python3 test_all_maps_all_hours.py

# Test station overlay feature
python3 test_station_overlays.py
```

### Configuration
Copy `.env.example` to `.env` and adjust settings:
```bash
cp .env.example backend/.env
```

## Documentation

- **[DEPLOYMENT_SUCCESS.md](DEPLOYMENT_SUCCESS.md)** - Deployment summary and monitoring
- **[RECOMMENDED_NEXT_STEPS.md](RECOMMENDED_NEXT_STEPS.md)** - Development roadmap and TODO
- **[docs/DEPLOYMENT_GUIDE_WALKTHROUGH.md](docs/DEPLOYMENT_GUIDE_WALKTHROUGH.md)** - Step-by-step deployment
- **[docs/ROADMAP.md](docs/ROADMAP.md)** - Project phases and timeline
- **[docs/INTEGRATION.md](docs/INTEGRATION.md)** - Forum integration strategy
- **[docs/GOTCHAS.md](docs/GOTCHAS.md)** - Common issues and solutions

## Features

✅ **Implemented:**
- GFS data fetching from AWS S3
- 0.25° high-resolution maps (4x better than standard)
- 4 map types: Temperature, Precipitation, Wind Speed, Precipitation Type
- 4 forecast hours: 0h, 24h, 48h, 72h
- Station overlays showing values at major PNW cities
- GRIB file caching (75% bandwidth reduction)
- Automated generation every 6 hours
- FastAPI server with health checks

🚧 **In Development:**
- Extended forecast hours (every 3h to 48h, every 6h to 120h)
- Additional map types (850mb temp, MSLP, 500mb height, etc.)
- Interactive frontend with slider/animation
- Mobile-responsive design

## Project Status

**Backend**: ✅ Deployed and stable  
**API**: ✅ Operational at http://174.138.84.70:8000  
**Maps**: ✅ Generating every 6 hours (00, 06, 12, 18 UTC)  
**Frontend**: ⏳ Planned for sodakweather.com testing
