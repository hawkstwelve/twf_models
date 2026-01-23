# Setup Guide

## Development Environment Setup

### Prerequisites
- Python 3.10 or higher
- pip and virtualenv
- Git

### Local Setup

1. **Clone and navigate to project**
```bash
cd twf_models
```

2. **Create virtual environment**
```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. **Install dependencies**
```bash
pip install -r backend/requirements.txt
```

4. **Set up environment variables**
```bash
cp .env.example .env
# Edit .env with your configuration
```

5. **Run development server**
```bash
cd backend
uvicorn app.main:app --reload
```

## Digital Ocean Droplet Setup

### Initial Server Configuration

1. **Create Droplet**
   - Ubuntu 22.04 LTS
   - Minimum: 1GB RAM, 1 vCPU
   - Recommended: 2GB RAM, 2 vCPU
   - Add SSH key during creation

2. **Initial Server Setup** (run `scripts/setup_droplet.sh`)
   - Update system packages
   - Install Python 3.10+
   - Install system dependencies (for cartopy, etc.)
   - Set up firewall
   - Create application user

3. **Deploy Application**
   - Clone repository
   - Set up virtual environment
   - Install dependencies
   - Configure environment variables
   - Set up systemd service
   - Configure nginx reverse proxy (optional)

### System Dependencies

Cartopy and other geospatial libraries require:
```bash
sudo apt-get update
sudo apt-get install -y \
    python3-dev \
    libproj-dev \
    proj-data \
    proj-bin \
    libgeos-dev \
    libgdal-dev \
    gdal-bin
```

## Configuration

### Environment Variables

See `.env.example` for required variables:
- `DATA_SOURCE`: GFS, Graphcast, or both
- `STORAGE_PATH`: Where to save images
- `API_HOST`: API server host
- `UPDATE_INTERVAL`: How often to fetch new data (hours)

## Data Sources

### GFS (Global Forecast System)

**Option 1: AWS S3 (Recommended)**
- Free, no rate limits
- Bucket: `noaa-gfs-bdp-pds`
- Requires `s3fs` or `boto3`

**Option 2: NOMADS**
- Direct HTTP access
- Rate limits apply
- URL pattern: `https://nomads.ncep.noaa.gov/pub/data/nccf/com/gfs/prod/`

### Graphcast

- Check Google's Graphcast API documentation
- May require API key
- Or download model weights for local inference

## Deployment

See `scripts/deploy.sh` for automated deployment script.

## Monitoring

- Set up logging to track processing times
- Monitor disk space
- Set up alerts for failed jobs
- Track API usage
