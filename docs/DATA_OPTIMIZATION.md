# Data Fetching Optimization

## Overview

The data fetcher has been optimized to minimize download size and processing time by:

1. **Using lower resolution data** (0.5° instead of 0.25°)
2. **Selecting only needed variables** before loading
3. **Subsetting to PNW region** before loading full dataset
4. **Using efficient GRIB reading** with cfgrib

## File Size Comparison

### Full GFS Files
- **0.25° resolution**: 500MB - 2GB per forecast hour
- **0.5° resolution**: 125MB - 500MB per forecast hour (4x smaller)
- **1.0° resolution**: 30MB - 125MB per forecast hour (16x smaller)

### Optimized Fetching (Current Implementation)

For PNW region with only needed variables:
- **Before optimization**: ~500MB - 2GB per file
- **After optimization**: ~10-50MB per file (20-40x smaller!)

## Optimization Strategies

### 1. Resolution Selection

We use **0.5° resolution** instead of 0.25°:
- Still provides good detail for PNW maps
- Files are 4x smaller
- Faster to download and process
- Sufficient for regional maps

**To change resolution**, modify `data_fetcher.py`:
```python
# 0.5° (current - recommended)
file_path = f"{base_path}/gfs.t{run_str[-2:]}z.pgrb2.0p50.f{hour_str}"

# 0.25° (higher resolution, larger files)
file_path = f"{base_path}/gfs.t{run_str[-2:]}z.pgrb2.0p25.f{hour_str}"

# 1.0° (lower resolution, smallest files)
file_path = f"{base_path}/gfs.t{run_str[-2:]}z.pgrb2.1p00.f{hour_str}"
```

### 2. Variable Selection

Only fetch variables we actually use:

**Temperature maps**: `tmp2m`
**Precipitation maps**: `prate`
**Precipitation type**: `tmp2m`, `prate` (need both)
**Wind speed maps**: `ugrd10m`, `vgrd10m`

This reduces data by ~90% compared to fetching all variables.

### 3. Geographic Subsetting

Subset to PNW region before loading:
- **Full globe**: All latitudes/longitudes
- **PNW subset**: Only -125° to -110° longitude, 42° to 49° latitude
- **Reduction**: ~95% less data

### 4. Efficient GRIB Reading

Using `cfgrib` with filtering:
- Only reads needed GRIB messages
- Filters by level (2m above ground)
- Doesn't load entire file into memory first

## Current Data Usage

### Per Forecast Hour
- **Variables fetched**: 2-4 variables (depending on map type)
- **Region**: PNW only (~7° x 7° area)
- **Resolution**: 0.5°
- **Estimated size**: 10-50MB per forecast hour

### Per Update Cycle (4 forecast hours)
- **Forecast hours**: 0, 24, 48, 72
- **Total data**: ~40-200MB per update
- **Variables per hour**: 2-4
- **Total variables**: 8-16 variables across all hours

## Comparison: Before vs After

### Before Optimization
```
Full 0.25° GFS file: ~1GB
× 4 forecast hours: ~4GB
× All variables: ~4GB
= 4GB per update cycle
```

### After Optimization
```
0.5° GFS file: ~250MB
× PNW subset (5%): ~12.5MB
× Only needed variables (10%): ~1.25MB
× 4 forecast hours: ~5MB
= ~5-20MB per update cycle (200-800x smaller!)
```

## Monitoring Data Usage

The data fetcher logs data sizes:
```
INFO: Dataset size before load: 15.23 MB
INFO: Dataset loaded: 15.23 MB
```

Monitor these logs to track actual data usage.

## Further Optimization Options

### 1. Use 1.0° Resolution
- Even smaller files (~30MB full file)
- Less detail but still usable for regional maps
- Change: `pgrb2.1p00` instead of `pgrb2.0p50`

### 2. Cache Data
- Cache fetched data for multiple map generations
- Reuse same dataset for temp, precip, wind maps
- Reduces redundant downloads

### 3. Incremental Updates
- Only fetch new forecast hours
- Keep previous hours cached
- Reduces data when only one hour is new

### 4. Compression
- GRIB files are already compressed
- Further compression not recommended (minimal benefit)

## Troubleshooting

### Issue: Still downloading large files
- Check that `subset_region=True` is being used
- Verify PNW bounds are correct
- Ensure variable selection is working

### Issue: Missing variables
- GRIB variable names may differ
- Check logs for available variables
- May need to adjust variable name mapping

### Issue: Region subsetting not working
- Verify coordinate names (lon/lat vs longitude/latitude)
- Check that bounds are correct
- Ensure coordinates exist in dataset

## Recommendations

1. **Start with current settings** (0.5°, PNW subset, variable selection)
2. **Monitor actual data usage** via logs
3. **Adjust if needed** based on:
   - Download speed
   - Processing time
   - Map quality requirements
4. **Consider caching** if generating multiple maps from same data

## Cost Impact

### Bandwidth
- **Before**: ~4GB per update = ~16GB/month = minimal cost
- **After**: ~80MB per update = ~320MB/month = negligible cost

### Storage
- **Before**: Would need to store full files
- **After**: Only store processed images (~5MB each)

The optimization primarily helps with:
- **Download speed** (faster updates)
- **Processing time** (faster map generation)
- **Memory usage** (less RAM needed)
- **Development/testing** (faster iterations)
