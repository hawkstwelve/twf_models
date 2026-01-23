# Quick Start Guide

## Local Development Setup (5 minutes)

1. **Create and activate virtual environment**
```bash
cd twf_models
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. **Install dependencies**
```bash
pip install -r backend/requirements.txt
```

3. **Set up environment variables**
```bash
cp .env.example .env
# Edit .env if needed (defaults should work for local dev)
```

4. **Create images directory**
```bash
mkdir -p images
```

5. **Run the API server**
```bash
cd backend
uvicorn app.main:app --reload
```

6. **Test the API**
```bash
# In another terminal
curl http://localhost:8000/
curl http://localhost:8000/api/maps
```

## Generate Your First Map (Testing)

The map generation requires actual GFS data, which can be large. For initial testing:

1. **Test data fetching** (this will download a large file):
```python
from app.services.data_fetcher import GFSDataFetcher
fetcher = GFSDataFetcher()
ds = fetcher.fetch_gfs_data(forecast_hour=0)
print(ds)
```

2. **Generate a test map**:
```python
from app.services.map_generator import MapGenerator
generator = MapGenerator()
generator.generate_map(
    variable="temperature_2m",
    model="GFS",
    forecast_hour=0
)
```

## Next Steps

1. **Review the documentation**:
   - [README.md](README.md) - Project overview
   - [docs/SETUP.md](docs/SETUP.md) - Detailed setup
   - [docs/API.md](docs/API.md) - API documentation
   - [docs/GOTCHAS.md](docs/GOTCHAS.md) - Common issues

2. **Configure for production**:
   - Set up Digital Ocean droplet
   - Run `scripts/setup_droplet.sh`
   - Deploy application
   - Configure scheduled jobs

3. **Integrate with your forum**:
   - See [docs/INTEGRATION.md](docs/INTEGRATION.md)
   - Set up CORS properly
   - Create frontend page

## Troubleshooting

### Import Errors
- Make sure virtual environment is activated
- Install system dependencies (see SETUP.md)

### Data Fetching Fails
- Check internet connection
- Verify AWS S3 access (if using AWS source)
- Check GFS data availability

### Map Generation Fails
- Ensure data was fetched successfully
- Check variable names match GFS dataset
- Verify cartopy/cartographic libraries installed

### Port Already in Use
- Change `API_PORT` in `.env`
- Or kill process using port 8000

## Getting Help

- Check [docs/GOTCHAS.md](docs/GOTCHAS.md) for common issues
- Review error logs
- Test individual components separately
