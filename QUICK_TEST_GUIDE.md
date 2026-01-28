# Quick Reference: Testing Individual Models

## Test Scripts Created

### For VPS Server Testing:

```bash
# Test GFS only (fast, ~10-20 min)
cd /opt/twf_models
python3 run_latest_gfs_now.py

# Test AIGFS only (slower, ~20-40 min, downloads ~2-3 GB)
cd /opt/twf_models
python3 run_latest_aigfs_now.py

# Test all models (complete production simulation)
cd /opt/twf_models
python3 run_latest_now.py
```

## Script Summary

| Script | Purpose | Download Size | Time | Cleans Up |
|--------|---------|---------------|------|-----------|
| `run_latest_gfs_now.py` | GFS only | ~500 MB | 10-20 min | `gfs_*.png` |
| `run_latest_aigfs_now.py` | AIGFS only | ~2-3 GB | 20-40 min | `aigfs_*.png` |
| `run_latest_now.py` | All models | ~3-4 GB | 30-60 min | `*.png` (all) |

## What Each Script Does

1. **Cleanup Phase**
   - Removes old maps for that model
   - Frees disk space

2. **Generation Phase**
   - Gets latest run time (00z, 06z, 12z, or 18z)
   - Downloads GRIB data from NOMADS
   - Generates all forecast hours
   - Saves PNG maps to `/opt/twf_models/backend/app/static/images/`

3. **Summary Phase**
   - Reports success/failure
   - Shows file count and location

## Output Examples

### GFS Maps:
```
gfs_20260128_12_temp_6.png
gfs_20260128_12_temp_12.png
gfs_20260128_12_precip_6.png
gfs_20260128_12_precip_12.png
gfs_20260128_12_wind_speed_6.png
gfs_20260128_12_mslp_precip_6.png
gfs_20260128_12_temp_850_wind_mslp_6.png
gfs_20260128_12_radar_6.png
```

### AIGFS Maps:
```
aigfs_20260128_12_temp_6.png
aigfs_20260128_12_temp_12.png
aigfs_20260128_12_precip_6.png
aigfs_20260128_12_precip_12.png
aigfs_20260128_12_wind_speed_6.png
aigfs_20260128_12_mslp_precip_6.png
aigfs_20260128_12_temp_850_wind_mslp_6.png
# Note: No radar maps (AIGFS doesn't have radar data)
```

## Verify Maps Were Created

```bash
# Count GFS maps
ls -1 /opt/twf_models/backend/app/static/images/gfs_*.png | wc -l

# Count AIGFS maps
ls -1 /opt/twf_models/backend/app/static/images/aigfs_*.png | wc -l

# View most recent maps
ls -lht /opt/twf_models/backend/app/static/images/*.png | head -20

# Check disk usage
du -sh /opt/twf_models/backend/app/static/images/
```

## Expected Map Counts

For 13 forecast hours (0,6,12,18,24,30,36,42,48,54,60,66,72):
- **GFS**: 78 maps (6 variables × 13 hours, but f000 skips 4 vars = 78)
- **AIGFS**: 65 maps (5 variables × 13 hours, no radar, f000 skips 4 vars = 65)

## Interrupting Scripts

Press `Ctrl+C` to stop any script. Partial progress is saved.

## When to Use Each Script

### Use `run_latest_gfs_now.py` when:
- Testing GFS changes
- Quick verification (small downloads)
- Checking baseline functionality

### Use `run_latest_aigfs_now.py` when:
- Testing AIGFS after fixes
- Verifying multi-product fetching
- Testing with full file downloads

### Use `run_latest_now.py` when:
- Testing production workflow
- Generating complete map set
- Verifying multi-model integration
- Before deploying to production

## After Running Tests

### Check the API endpoint:
```bash
# On VPS
curl http://localhost:8000/api/runs | jq

# Should show both GFS and AIGFS runs
```

### View in frontend:
```
https://yourdomain.com/models/
```

## Troubleshooting

If maps don't generate:
1. Check if data is available yet (3.5 hours after run time)
2. Verify disk space: `df -h`
3. Check logs for specific errors
4. Try the other model (if AIGFS fails, try GFS)

## Advanced: Custom Test Runs

Edit the script before running to customize:

```python
# Change forecast hours
settings.forecast_hours = "6,12,18"  # Just these 3 hours

# Change variables
scheduler.variables = ['temp', 'precip']  # Only these 2 maps
```

## See Also
- `TEST_SCRIPTS_README.md` - Full documentation
- `AIGFS_FIXES_APPLIED.md` - AIGFS implementation details
- `deploy_aigfs_fixes.sh` - Deployment script
