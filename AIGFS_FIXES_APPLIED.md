# AIGFS Map Generation Fixes Applied

## Date: January 28, 2026

## Problem Summary
AIGFS maps were not being generated due to:
1. **404 errors** - The NOMADS filter script `filter_aigfs_0p25.pl` does not exist
2. **Wrong product selection** - Code was trying to use 'pres' product for all fields
3. **Incorrect analysis file pattern** - Was using 'pres' instead of 'sfc' for f000
4. **Relative storage path** - Maps were being saved to wrong directory

## Root Cause
NOAA does not provide a filter CGI script for AIGFS like they do for GFS. The system was attempting to use a non-existent filter, resulting in 404 errors for all AIGFS data requests.

## Fixes Applied

### 1. Updated AIGFS Model Configuration (`model_registry.py`)
**Changes:**
- Set `use_filter=False` - Don't attempt to use non-existent filter script
- Removed `filter_script` references (set to `None`)
- Reordered products: `"sfc"` first, then `"pres"` (sfc is more commonly needed)
- Fixed `analysis_pattern` to use `"aigfs.t{run_hour}z.sfc.f000.grib2"` (was using pres)
- Explicitly set `run_hours=[0, 6, 12, 18]`

**Result:** AIGFS will now download full GRIB2 files instead of trying to filter them.

### 2. Added Intelligent Product Selection (`nomads_data_fetcher.py`)
**New Method:** `_select_product_for_fields()`
- Determines which product file (sfc vs pres) to use based on variables needed
- Surface fields (2m temp, 10m wind, precip, MSLP) → use 'sfc' product
- Upper air fields (850mb, 500mb) → use 'pres' product
- Prefers 'sfc' when both are needed

### 3. Added Multi-Product Fetching Support (`nomads_data_fetcher.py`)
**New Method:** `_fetch_from_multiple_products()`
- Handles cases where variables need data from BOTH sfc and pres products
- Example: `temp_850_wind_mslp` needs:
  - 850mb temp/wind from 'pres' product
  - MSLP from 'sfc' product
- Downloads both files and merges the datasets

**New Method:** `_build_nomads_url_for_product()`
- Builds URL for a specific product file
- Handles analysis file pattern matching

### 4. Fixed Storage Path (`config.py`)
**Changed:**
```python
# Before:
storage_path: str = "./images"

# After:
storage_path: str = "/opt/twf_models/backend/app/static/images"
```
**Result:** Maps now save to the correct absolute path on the VPS server.

## Files Modified
1. `/backend/app/models/model_registry.py` - AIGFS configuration
2. `/backend/app/services/nomads_data_fetcher.py` - Data fetching logic
3. `/backend/app/config.py` - Storage path

## Expected Behavior After Fixes
1. AIGFS will download full GRIB2 files (~50-100MB each) instead of filtered subsets
2. System will intelligently fetch from 'sfc' or 'pres' products based on variables needed
3. For variables needing both products, system will fetch and merge both files
4. Maps will be saved to `/opt/twf_models/backend/app/static/images/`
5. AIGFS maps should appear alongside GFS maps for both 00z and 06z runs

## Deployment Instructions

### On VPS Server:
```bash
# 1. Pull the latest code
cd /opt/twf_models
git pull origin main

# 2. Restart the scheduler service
sudo systemctl restart twf-models-scheduler.service

# 3. Monitor logs to verify AIGFS is working
sudo journalctl -u twf-models-scheduler.service -f

# 4. Wait for next scheduled run (3:30, 9:30, 15:30, or 21:30 UTC)
# Or trigger manually:
cd /opt/twf_models/backend
python3 -m app.scheduler

# 5. Check for AIGFS maps
ls -lh /opt/twf_models/backend/app/static/images/aigfs_*
```

## Verification
After the next scheduled run, you should see:
- AIGFS map files with pattern: `aigfs_YYYYMMDD_HH_variable_fhour.png`
- Example: `aigfs_20260128_12_temp_6.png`, `aigfs_20260128_12_precip_12.png`, etc.
- Maps for all variables except 'radar' (AIGFS doesn't have radar reflectivity)

## Performance Notes
- **File sizes:** Full AIGFS GRIB2 files are larger than filtered GFS files
- **SFC files:** ~50-80 MB each (vs ~5-10 MB filtered)
- **PRES files:** ~100-150 MB each (vs ~10-20 MB filtered)
- **Bandwidth:** Expect ~2-3 GB download per complete AIGFS run (all forecast hours)
- **Caching:** Files are cached locally in `/tmp/aigfs_cache/` to avoid re-downloading

## Troubleshooting
If AIGFS maps still don't generate:

1. **Check data availability:**
   ```bash
   # Verify AIGFS files exist on NOMADS
   curl -I "https://nomads.ncep.noaa.gov/pub/data/nccf/com/aigfs/prod/aigfs.YYYYMMDD/HH/model/atmos/grib2/aigfs.tHHz.sfc.f006.grib2"
   ```

2. **Check logs for errors:**
   ```bash
   sudo journalctl -u twf-models-scheduler.service --since "1 hour ago" | grep -i aigfs
   ```

3. **Verify storage directory exists and is writable:**
   ```bash
   ls -ld /opt/twf_models/backend/app/static/images/
   ```

4. **Check disk space:**
   ```bash
   df -h /opt/twf_models
   ```

## Rollback (if needed)
If AIGFS causes issues:

1. **Disable AIGFS temporarily:**
   Edit `/backend/app/models/model_registry.py`, change:
   ```python
   enabled=False  # in AIGFS ModelConfig
   ```

2. **Restart scheduler:**
   ```bash
   sudo systemctl restart twf-models-scheduler.service
   ```

## Next Steps
- Monitor first few AIGFS runs to ensure stability
- Compare AIGFS vs GFS forecasts for accuracy
- Consider adding AIGFS to frontend model selector
- Document any AIGFS-specific quirks discovered
