# Total Snowfall Map Implementation Summary

## Overview
Implemented a new "Total Snowfall (10:1 Ratio)" map that shows accumulated snowfall from forecast hour 0 to the selected hour, similar to the Total Precipitation map.

## Supported Models
**Currently: GFS only**

AIGFS snowfall has been **disabled** pending availability of more helpful variables in NOAA GRIB files (CSNOW or improved temperature fields).

## Problem Solved
GFS provides categorical snow mask (CSNOW) which enables direct snowfall calculation. The implementation uses this native field for accurate snow accumulation.

### GFS Approach (has_precip_type_masks=True)
- Uses native **CSNOW** field (categorical snow mask)
- Direct classification from model output
- Straightforward and accurate

### AIGFS Approach (DISABLED - has_precip_type_masks=False)
**Note: AIGFS snowfall generation is currently disabled and will be re-enabled once NOAA provides better variables.**

The temperature-based approach attempted for AIGFS was not sufficiently accurate:
- AIGFS GRIB2 files **do not include CSNOW**
- Attempted to derive snow fraction from **T850** (850mb temperature) and **T2m** (2m temperature)
- Temperature-based classification proved inadequate:
  - T850 ≤ -2°C → 100% snow
  - T850 ≥ +1°C → 0% snow
  - Linear interpolation between
  - Optional surface penalty when T2m > 3°C
  
Code remains in place but AIGFS has `"snowfall"` in its `excluded_variables` list, preventing generation.

## Implementation Details

### 1. Variable Requirements (`backend/app/models/variable_requirements.py`)

**Added:**
- `needs_snow_total: bool = False` flag to VariableRequirements dataclass
- New "snowfall" variable entry:
  - Raw fields: `tp`, `prate` (always needed)
  - Optional fields: `csnow` (GFS), `tmp_850`, `tmp2m`, `t2m` (AIGFS)
  - Derived field: `tp_snow_total`
  - `needs_upper_air=True` (AIGFS needs T850 for classification)
- Class method `needs_snow_total()` to check if snowfall computation is needed

### 2. Data Fetcher (`backend/app/services/base_data_fetcher.py`)

**Added:**
- Check for `needs_snow_total` in `build_dataset_for_maps()`
- New method `_compute_total_snowfall()` with **model-aware branching**:

#### GFS Path (has_precip_type_masks=True):
1. Fetches `tp` and `csnow` for each forecast bucket
2. Normalizes csnow to fraction (0-1):
   - Handles 0/1 masks
   - Handles 0-100 percentage masks (divides by 100)
   - Checks units attribute
3. Computes snow liquid equivalent: `snow_liquid = tp * csnow_fraction`
4. Sums across all buckets from 0 to forecast_hour

#### AIGFS Path (DISABLED - has_precip_type_masks=False):
**Note: This code has been removed from base_data_fetcher.py.**

The temperature-based approach has been completely removed from the codebase:
- The `_snow_fraction_from_thermal()` helper function has been deleted
- The entire AIGFS temperature-based computation branch has been removed
- Code cleanup completed to reduce maintenance burden
- Can be restored from git history if needed in the future

#### Shared Logic:
- Explicit unit standardization: `tp_mm = tp * 1000.0`
- Applies 10:1 snow-to-liquid ratio: `snow_depth = snow_liquid * 10`
- Converts to inches: `snow_inches = snow_mm / 25.4`
- Helper functions for clean code:
  - `_drop_timeish()`: removes time coordinates
  - `_get_bucket_precip_mm()`: extracts and standardizes precip units
  - `_to_celsius()`: handles Kelvin/Celsius conversion
  - `_snow_fraction_from_thermal()`: T850/T2m → snow fraction

### 3. Map Generator (`backend/app/services/map_generator.py`)

**Added:**
- Snowfall processing in `generate_map()`:
  - Reads `tp_snow_total` from dataset (already in inches)
  - Custom blue/white colormap for snow visualization
  - Discrete color levels: [0.1, 0.5, 1, 2, 3, 4, 6, 8, 10, 12, 15, 18, 24, 30, 36, 42, 48, 60, 72] inches
  - Colors transition from grays → light blues → deep blues → purples for heavy snow
  - BoundaryNorm for discrete level mapping
  
- Plotting configuration:
  - Uses `snow_norm` for consistent color mapping
  - Colorbar labeled "Total Snowfall (10:1 Ratio) (inches)"
  - Title: "{MODEL} Total Snowfall (10:1 Ratio) (in)"
  
- Station overlay support:
  - Extracts `tp_snow_total` for station points
  - Values already in inches, no conversion needed

## Key Design Decisions

### 1. Model-Aware Branching
- Branches on `model_config.has_precip_type_masks`
- GFS uses native CSNOW (accurate and reliable)
- AIGFS snowfall **disabled** - insufficient variables available
- Clean separation prevents cross-contamination

### 2. Temperature-Based Classification (AIGFS - DISABLED)
**Note: This approach is available in code but not used due to insufficient accuracy.**

The temperature-based approach was deemed inadequate without proper variables:
- T850 alone is insufficient for accurate snow/rain discrimination
- AIGFS lacks CSNOW and other helpful categorical variables
- Will be re-enabled when NOAA provides better GRIB variables

### 3. CSNOW Normalization (GFS)
```python
cs_units = csnow.attrs.get('units')
if cs_units in ('%', 'percent'):
    cs_frac = csnow / 100.0
else:
    # Heuristic: if max > 1.5 => likely 0-100 scale
    cs_frac = (csnow / 100.0) if float(csnow.max()) > 1.5 else csnow
cs_frac = cs_frac.clip(0.0, 1.0)
```
- Checks units attribute first
- Falls back to heuristic (max > 1.5 suggests 0-100 scale)
- Clips to ensure valid [0,1] range

### 3. Explicit Unit Standardization
```python
# Get precip in mm
p_mm = _get_bucket_precip_mm(ds)  # Handles meters/mm conversion

# For GFS: apply snow mask
snow_liquid_mm = p_mm * csnow_fraction

# For AIGFS: apply thermal snow fraction
snow_liquid_mm = p_mm * snow_fraction

# Apply 10:1 ratio
snow_depth_mm = snow_liquid_mm * 10.0

# Convert to inches
snow_inches = (snow_depth_mm / 25.4)
```
- Clear unit conversions at each step
- Prevents unit confusion
- Final output always in inches

### 4. Bucket-Loop Structure
- Processes each forecast bucket independently
- Avoids "late-hour temperature reclassifies early precip" bug
- Each bucket gets classified at its valid time
- Graceful error handling (continues if a bucket is missing)

### 5. Grid Alignment (AIGFS)
```python
if snow_frac.shape != p_mm.shape:
    snow_frac = snow_frac.interp_like(p_mm, method="linear")
```
- Handles cases where pressure-level and surface grids differ
- Uses linear interpolation to match grids
- Prevents dimension mismatch errors

## Why This Approach is Correct

### For GFS:
- ✅ Uses model's native precip-type classification
- ✅ Most accurate method available
- ✅ Handles mixed-phase precipitation correctly
- ✅ No assumptions needed

### For AIGFS (DISABLED):
- ❌ AIGFS GRIB2 files **do not contain CSNOW** (verified via IDX file)
- ❌ T850-based classification insufficient without additional variables
- ⏸️ **Generation disabled** - awaiting better NOAA GRIB variables
- 🗑️ **Code removed** - AIGFS snowfall computation logic deleted from base_data_fetcher.py
- ✅ Clean exclusion via `excluded_variables` list in model registry
- 📜 **Recoverable** - Can be restored from git history if better variables become available

### Universal:
- ✅ Config-driven: respects `has_precip_type_masks` flag and `excluded_variables`
- ✅ Unit-safe: explicit conversions prevent errors
- ✅ Model-agnostic output: MapGenerator treats both the same
- ✅ Bucket-by-bucket: prevents temporal cross-contamination
- ✅ Clean helpers: maintainable and testable code

## Testing

Created test script: `scripts/tests/test_snowfall_map.py`

**Usage:**
```bash
# GFS only (AIGFS snowfall is disabled)
python scripts/tests/test_snowfall_map.py --model gfs --forecast-hour 12
```

**Tests:**
1. Fetches data for GFS model and specified forecast hour
2. Computes tp_snow_total
3. Generates snowfall map
4. Validates output file creation

**Note:** Testing with `--model aigfs` will fail as snowfall is in the excluded_variables list.

## API Integration

To use the snowfall map with GFS, specify variable `'snowfall'` when calling the data fetcher:

```python
# GFS only - AIGFS has snowfall disabled
ds = fetcher.build_dataset_for_maps(
    run_time=run_time,
    forecast_hour=forecast_hour,
    variables=['snowfall'],
    subset_region=True
)

map_path = map_gen.generate_map(
    ds=ds,
    variable='snowfall',
    model='GFS',  # GFS only
    run_time=run_time,
    forecast_hour=forecast_hour,
    region='pnw'
)
```

**Note:** Attempting to generate AIGFS snowfall maps will be filtered out by `VariableRegistry.filter_by_model_capabilities()` which checks the model's `excluded_variables` list.

## Files Modified

1. `backend/app/models/model_registry.py` - Added "snowfall" to AIGFS excluded_variables
2. `backend/app/models/variable_requirements.py` - Added snowfall variable definition
3. `backend/app/services/base_data_fetcher.py` - GFS/HRRR snowfall computation (AIGFS code removed)
4. `backend/app/services/map_generator.py` - Added snowfall visualization
5. `scripts/tests/test_snowfall_map.py` - Test script (GFS only)
6. `scripts/tests/test_all_maps_comprehensive.py` - Removed snowfall from AIGFS test config
7. `docs/SNOWFALL_IMPLEMENTATION.md` - Updated documentation (this file)

## Status & Next Steps

### Current Status:
- ✅ GFS snowfall maps: **ENABLED and working**
- ✅ HRRR snowfall maps: **ENABLED and working**
- ❌ AIGFS snowfall maps: **DISABLED** pending better NOAA variables
- 🗑️ AIGFS snowfall computation code: **REMOVED** (can be restored from git history)

### Future Re-enablement for AIGFS:
When NOAA provides helpful variables in AIGFS GRIB files:
1. Restore AIGFS snowfall code from git history (or re-implement)
2. Remove "snowfall" from AIGFS `excluded_variables` in model_registry.py
3. Test with new variables
4. Update documentation
5. Add back to test configurations

### Completed Steps:
1. ✅ Implemented GFS snowfall (native CSNOW)
2. ✅ Implemented HRRR snowfall (native CSNOW)
3. ✅ Disabled AIGFS snowfall generation
4. ✅ Removed AIGFS temperature-based computation logic
5. ✅ Updated model registry with exclusions
6. ✅ Updated test configurations
7. ✅ Updated documentation
8. ✅ Code cleanup completed

## Notes

- The 10:1 ratio is a standard approximation (1 inch liquid = 10 inches snow)
- Actual snow ratios vary from 5:1 (wet) to 30:1 (powder) based on temperature
- For more accurate results, could implement temperature-dependent ratios
- CSNOW is categorical - areas with mixed precip may show transitional values
- AIGFS temperature-based approach available in code but not executed due to exclusion
