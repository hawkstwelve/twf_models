# NOMADS Migration Guide

**Date:** January 26, 2026  
**Status:** ✅ IMPLEMENTED - Ready for Testing

---

## Overview

This guide documents the migration from AWS S3 to NOMADS as the primary GFS data source.

### Why NOMADS?

1. **Faster Data Availability** - NOMADS receives GFS data 1-2 hours before AWS S3 sync completes
2. **Selective Downloads** - NOMADS filter allows downloading only needed variables and regions
3. **Bandwidth Savings** - Filtered downloads are 5-10x smaller than full GRIB files
4. **Better Performance** - For our use case, NOMADS is typically faster overall

---

## Implementation Details

### Code Changes

#### 1. Configuration (`backend/app/config.py`)
Added NOMADS-specific settings:
```python
nomads_use_filter: bool = True  # Use NOMADS filter for selective downloads
nomads_timeout: int = 120       # HTTP timeout in seconds
nomads_max_retries: int = 3     # Number of retries for failed downloads
```

#### 2. Data Fetcher (`backend/app/services/data_fetcher.py`)
- Implemented complete NOMADS fetching logic
- Added NOMADS filter URL builder (`_build_nomads_filter_url()`)
- Added HTTP download with retry logic (`_download_from_nomads()`)
- Maintained same GRIB processing logic as AWS (same data quality)
- Preserved caching mechanism for performance

#### 3. Scheduler (`backend/app/scheduler.py`)
- Updated `check_data_available()` to support NOMADS
- Uses HTTP HEAD requests to check NOMADS file existence
- Conditionally initializes S3 only when using AWS source

### NOMADS Filter Details

The NOMADS filter allows us to download only:
- **Variables we need** (e.g., TMP, UGRD, VGRD, PRMSL)
- **Levels we need** (e.g., 2m, 10m, 850mb, 1000mb, 500mb)
- **Region we need** (PNW: 42-49°N, 125-110°W)

Example filtered download:
- **Full file:** ~150 MB
- **Filtered (PNW region, 5 variables):** ~15-20 MB
- **Speedup:** ~10x smaller, faster download

---

## Testing Before Production

### Step 1: Run Test Suite

```bash
cd /Users/brianaustin/twf_models
python3 test_nomads_fetch.py
```

This tests:
1. ✅ NOMADS availability checking
2. ✅ Full GRIB file download
3. ✅ Filtered download (region + variables)
4. ✅ Performance comparison with AWS S3
5. ✅ Data quality validation

### Step 2: Test Single Map Generation

```bash
# Test generating one map using NOMADS
cd backend
export GFS_SOURCE=nomads
export NOMADS_USE_FILTER=True

python3 -c "
from app.services.data_fetcher import GFSDataFetcher
from app.services.map_generator import MapGenerator

fetcher = GFSDataFetcher()
run_time = fetcher.get_latest_run_time()

# Fetch data
ds = fetcher.fetch_gfs_data(
    run_time=run_time,
    forecast_hour=12,
    variables=['tmp2m', 'prate'],
    subset_region=True
)

print('Data fetched successfully!')
print(f'Variables: {list(ds.data_vars)}')

# Generate a test map
generator = MapGenerator()
generator.generate_map(
    ds=ds,
    variable='temp',
    model='GFS',
    run_time=run_time,
    forecast_hour=12
)

print('Map generated successfully!')
"
```

---

## Switching to NOMADS in Production

### Option A: Environment Variable (Temporary Test)

```bash
# SSH into droplet
ssh brian@174.138.84.70

# Edit environment
cd /opt/twf_models
sudo nano backend/.env

# Add or update:
GFS_SOURCE=nomads
NOMADS_USE_FILTER=True
NOMADS_TIMEOUT=120
NOMADS_MAX_RETRIES=3

# Restart scheduler to apply changes
sudo systemctl restart twf-models-scheduler

# Monitor logs
sudo tail -f /var/log/twf-models-scheduler.log
```

### Option B: Update config.py (Permanent)

```bash
# Edit config.py
sudo nano /opt/twf_models/backend/app/config.py

# Change line 11:
gfs_source: str = "nomads"  # Changed from "aws"

# Restart scheduler
sudo systemctl restart twf-models-scheduler
```

---

## Monitoring After Switch

### Watch First Run

```bash
# Monitor scheduler logs in real-time
sudo tail -f /var/log/twf-models-scheduler.log | grep -E "(NOMADS|Downloading|✅|❌)"
```

### Key Metrics to Watch

1. **Download Speed**
   - Look for: "✅ Downloaded X.X MB from NOMADS"
   - Should be faster than AWS downloads

2. **Data Availability**
   - Look for: "✅ Found N new forecast hours"
   - Should find data earlier than AWS (1-2 hours improvement)

3. **Error Rate**
   - Watch for: "❌" or "Error" messages
   - NOMADS should be reliable, but occasional 503 errors are normal (retry handles them)

4. **Map Generation Success**
   - Look for: "✅ fXXX: All N maps generated successfully"
   - Should match AWS success rate

---

## Rollback Plan

If NOMADS has issues, quickly revert to AWS:

```bash
# SSH into droplet
ssh brian@174.138.84.70

# Edit config
cd /opt/twf_models/backend
sudo nano .env

# Change back to AWS
GFS_SOURCE=aws

# Restart
sudo systemctl restart twf-models-scheduler

# Verify
sudo systemctl status twf-models-scheduler
```

---

## Performance Expectations

### Before (AWS S3):
- First maps available: **4-5 hours** after run time
- f000-f072 complete: **5-6 hours** after run time
- Download time per GRIB: **20-40 seconds** (full file)

### After (NOMADS with filter):
- First maps available: **2-3 hours** after run time (1-2 hour improvement)
- f000-f072 complete: **3.5-4 hours** after run time
- Download time per GRIB: **5-15 seconds** (filtered file)

### Overall Improvement:
- **~2 hours faster** to first maps
- **~1.5 hours faster** to completion
- **~70% smaller** downloads (bandwidth savings)

---

## Troubleshooting

### Issue: NOMADS returns 503 errors

**Cause:** NOMADS server temporarily overloaded  
**Solution:** Retry logic will handle this automatically (3 retries with 5s delay)

### Issue: Filtered download missing variables

**Cause:** NOMADS variable mapping incorrect  
**Solution:** Check `_build_nomads_filter_url()` variable map, add missing mappings

### Issue: Data quality differs from AWS

**Cause:** Unlikely - same source data  
**Solution:** Run comparison test, check GRIB processing logic

### Issue: Downloads slower than AWS

**Cause:** Network path to NOMADS or filter overhead  
**Solution:** Disable filtering (`NOMADS_USE_FILTER=False`) to download full files

---

## Configuration Reference

### Environment Variables

```bash
# Data source
GFS_SOURCE=nomads              # Options: aws, nomads
GFS_RESOLUTION=0p25            # Options: 0p25, 0p50

# NOMADS-specific
NOMADS_USE_FILTER=True         # Use filtered downloads
NOMADS_TIMEOUT=120             # HTTP timeout (seconds)
NOMADS_MAX_RETRIES=3           # Number of retries
```

### URLs

- **NOMADS Base:** https://nomads.ncep.noaa.gov/
- **GFS 0.25° Filter:** https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl
- **GFS 0.50° Filter:** https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p50.pl
- **Direct Files:** https://nomads.ncep.noaa.gov/pub/data/nccf/com/gfs/prod/

---

## Next Steps

After successful NOMADS migration:

1. ✅ Monitor for 24-48 hours to ensure stability
2. ✅ Adjust check frequency (from 60s to 30s) for even faster updates
3. ✅ Start scheduler earlier (from 03:30 to 02:00 UTC)
4. ✅ Extend forecast hours (from f72 to f120+)

These additional optimizations can further improve map availability.

---

## Support

**Documentation:** `docs/NOMADS_MIGRATION.md`  
**Test Script:** `test_nomads_fetch.py`  
**Configuration:** `backend/app/config.py`  
**Data Fetcher:** `backend/app/services/data_fetcher.py`  
**Scheduler:** `backend/app/scheduler.py`
