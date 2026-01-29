# Total Snowfall Map Implementation Summary

## Overview
Implemented a new "Total Snowfall (10:1 Ratio)" map that shows accumulated snowfall from forecast hour 0 to the selected hour, similar to the Total Precipitation map.

## Problem Solved
Neither GFS nor AIGFS provide direct accumulated snowfall variables. The implementation uses **two different approaches** based on model capabilities:

### GFS Approach (has_precip_type_masks=True)
- Uses native **CSNOW** field (categorical snow mask)
- Direct classification from model output
- Straightforward and accurate

### AIGFS Approach (has_precip_type_masks=False)
- AIGFS GRIB2 files **do not include CSNOW**
- Derives snow fraction from **T850** (850mb temperature) and **T2m** (2m temperature)
- Temperature-based classification:
  - T850 ≤ -2°C → 100% snow
  - T850 ≥ +1°C → 0% snow
  - Linear interpolation between
  - Optional surface penalty when T2m > 3°C

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

#### AIGFS Path (has_precip_type_masks=False):
1. Fetches `tp` (surface), `tmp_850` (pressure level), and optionally `tmp2m` (surface)
2. Converts temperatures to Celsius (handles Kelvin/Celsius automatically)
3. Computes snow fraction from thermal profile:
   ```python
   if T850 <= -2°C: snow_frac = 1.0
   if T850 >= +1°C: snow_frac = 0.0
   else: linear interpolation
   
   # Optional surface penalty
   if T2m >= +3°C: multiply by 0
   if 0°C < T2m < +3°C: taper down
   ```
4. Aligns grids if pressure/surface levels differ (interpolation)
5. Computes snow liquid equivalent: `snow_liquid = tp * snow_fraction`
6. Sums across all buckets

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
- GFS uses native CSNOW (more accurate)
- AIGFS derives from temperature (necessary workaround)
- Clean separation prevents cross-contamination

### 2. Temperature-Based Classification (AIGFS)
**Why T850?**
- Most stable single-level discriminator for snow vs rain
- Better than surface temp which is too variable
- Standard meteorological practice

**Temperature Thresholds:**
```python
T850 ≤ -2°C: 100% snow (well below freezing)
T850 ≥ +1°C: 0% snow (above freezing)
Between: linear ramp (handles transitions)
```

**Surface Penalty (Optional):**
- Suppresses snow when T2m is clearly warm (>3°C)
- Prevents unrealistic snow in warm surface conditions
- Applied as multiplicative factor

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

### For AIGFS:
- ✅ AIGFS GRIB2 files **do not contain CSNOW** (verified via IDX file)
- ✅ T850 is meteorologically sound for snow/rain discrimination
- ✅ Piecewise-linear ramp avoids hard thresholds and artifacts
- ✅ Surface penalty prevents unrealistic warm-snow events
- ✅ Handles grid mismatches via interpolation
- ✅ Extensible: can add wet-bulb or thickness logic later

### Universal:
- ✅ Config-driven: respects `has_precip_type_masks` flag
- ✅ Unit-safe: explicit conversions prevent errors
- ✅ Model-agnostic output: MapGenerator treats both the same
- ✅ Bucket-by-bucket: prevents temporal cross-contamination
- ✅ Clean helpers: maintainable and testable code

## Testing

Created test script: `scripts/tests/test_snowfall_map.py`

**Usage:**
```bash
python scripts/tests/test_snowfall_map.py --model gfs --forecast-hour 12
```

**Tests:**
1. Fetches data for specified model and forecast hour
2. Computes tp_snow_total
3. Generates snowfall map
4. Validates output file creation

## API Integration

To use the new snowfall map, specify variable `'snowfall'` when calling the data fetcher:

```python
ds = fetcher.build_dataset_for_maps(
    run_time=run_time,
    forecast_hour=forecast_hour,
    variables=['snowfall'],
    subset_region=True
)

map_path = map_gen.generate_map(
    ds=ds,
    variable='snowfall',
    model='GFS',
    run_time=run_time,
    forecast_hour=forecast_hour,
    region='pnw'
)
```

## Files Modified

1. `backend/app/models/variable_requirements.py` - Added snowfall variable definition
2. `backend/app/services/base_data_fetcher.py` - Added snowfall computation logic
3. `backend/app/services/map_generator.py` - Added snowfall visualization
4. `scripts/tests/test_snowfall_map.py` - New test script (created)

## Next Steps

1. **Test the implementation** with actual GFS/AIGFS data
2. **Validate CSNOW scale** - Verify if it's 0/1 or 0-100 in your GRIB files
3. **Tune colormap** - Adjust color breaks based on typical PNW snowfall amounts
4. **Add to scheduler** - Include 'snowfall' in automated map generation
5. **Frontend integration** - Add snowfall option to dropdown menu
6. **Documentation** - Update API docs with snowfall variable

## Notes

- The 10:1 ratio is a standard approximation (1 inch liquid = 10 inches snow)
- Actual snow ratios vary from 5:1 (wet) to 30:1 (powder) based on temperature
- For more accurate results, could implement temperature-dependent ratios
- CSNOW is categorical - areas with mixed precip may show transitional values
