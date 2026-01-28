# Manual Map Generation Test Scripts

These scripts allow you to manually generate weather forecast maps for testing purposes, without waiting for the scheduler.

## Available Scripts

### 1. `run_latest_gfs_now.py` - GFS Only
Generates maps for the latest available GFS run.

**Usage:**
```bash
# On your VPS:
cd /opt/twf_models
python3 run_latest_gfs_now.py

# Or locally:
cd /path/to/twf_models
python3 run_latest_gfs_now.py
```

**What it does:**
- Removes all existing GFS maps (`gfs_*.png`)
- Downloads latest GFS data using filtered requests (small files)
- Generates all configured forecast maps
- Takes ~10-20 minutes

**Output location:**
- VPS: `/opt/twf_models/backend/app/static/images/gfs_*.png`
- Local: `./backend/app/static/images/gfs_*.png` (or `./images/` depending on config)

---

### 2. `run_latest_aigfs_now.py` - AIGFS Only
Generates maps for the latest available AIGFS run.

**Usage:**
```bash
# On your VPS:
cd /opt/twf_models
python3 run_latest_aigfs_now.py

# Or locally:
cd /path/to/twf_models
python3 run_latest_aigfs_now.py
```

**What it does:**
- Removes all existing AIGFS maps (`aigfs_*.png`)
- Downloads latest AIGFS data (full GRIB2 files - **~2-3 GB total**)
- Generates all configured forecast maps (excluding radar)
- Takes ~20-40 minutes depending on connection speed

**Output location:**
- VPS: `/opt/twf_models/backend/app/static/images/aigfs_*.png`
- Local: `./backend/app/static/images/aigfs_*.png` (or `./images/` depending on config)

---

### 3. `run_latest_now.py` - All Models
Generates maps for all enabled models (GFS + AIGFS).

**Usage:**
```bash
# On your VPS:
cd /opt/twf_models
python3 run_latest_now.py

# Or locally:
cd /path/to/twf_models
python3 run_latest_now.py
```

**What it does:**
- Removes all existing maps (all `*.png` files)
- Generates maps for all enabled models sequentially
- Takes ~30-60 minutes total

**When to use:**
- Testing the full production workflow
- Generating a complete set of maps
- Verifying all models work together

---

## Configuration

All scripts use the same configuration from `backend/app/config.py`:

- **Forecast hours**: Set by `forecast_hours` config (default: 0,6,12,18,24,30,36,42,48,54,60,66,72)
- **Variables**: Set in `ForecastScheduler` class (temp, precip, wind_speed, mslp_precip, temp_850_wind_mslp, radar)
- **Storage path**: Set by `storage_path` config

## Common Use Cases

### Test AIGFS After Code Changes
```bash
python3 run_latest_aigfs_now.py
```

### Test GFS with Small Downloads
```bash
python3 run_latest_gfs_now.py
```

### Generate Complete Map Set
```bash
python3 run_latest_now.py
```

### Test Specific Forecast Hours
Edit the script and modify the `forecast_hours` before running:
```python
# In run_latest_aigfs_now.py, before calling generate_forecast_for_model:
settings.forecast_hours = "6,12,18"  # Only these hours
```

## Monitoring Progress

All scripts output detailed logs to the console:
- 📥 Data downloads
- 🗺️ Map generation progress
- ✅ Completion status
- ❌ Error messages

**Example output:**
```
🤖 AIGFS Map Generator
=============================================
🧹 CLEANING UP OLD AIGFS MAPS
📁 Directory: /opt/twf_models/backend/app/static/images
🗑️  Found 78 AIGFS PNG files to remove
✅ Cleanup complete: 78 removed, 0 failed
=============================================

🌍 Starting forecast generation for AIGFS
📅 AIGFS Run Time: 2026-01-28 06Z
🎯 Forecast hours: [0, 6, 12, 18, 24, 30, 36, 42, 48, 54, 60, 66, 72]
📊 Variables: ['temp', 'precip', 'wind_speed', 'mslp_precip', 'temp_850_wind_mslp']
💻 Using 4 worker processes

🚀 Worker starting for AIGFS f006
  📥 Building dataset for 5 variables...
  ...
```

## Troubleshooting

### Script says "No maps generated"
- Data may not be available yet on NOMADS
- Wait 3.5 hours after model run time (00z, 06z, 12z, 18z)
- Check NOMADS availability manually (see AIGFS_FIXES_APPLIED.md)

### Connection errors / timeouts
- NOMADS servers may be slow or overloaded
- Try again in a few minutes
- Check your internet connection

### Disk space errors
- AIGFS requires ~2-3 GB per run
- GFS requires ~500 MB per run
- Clean up old maps: `rm /opt/twf_models/backend/app/static/images/*.png`

### Import errors
- Make sure you're running from the project root: `/opt/twf_models`
- Ensure all dependencies are installed: `pip install -r backend/requirements.txt`

## Notes

- **Scripts are safe to run multiple times** - they clean up old maps first
- **Scripts use the same code as the scheduler** - what works here will work in production
- **Interrupt anytime with Ctrl+C** - partial progress is saved
- **Check file sizes** - GFS files (~5-10 MB), AIGFS files (~50-150 MB per GRIB)

## Production Scheduler

These scripts are for testing. The production scheduler runs automatically:
- **Service**: `twf-models-scheduler.service`
- **Schedule**: 03:30, 09:30, 15:30, 21:30 UTC
- **Logs**: `journalctl -u twf-models-scheduler.service -f`

To restart scheduler after changes:
```bash
sudo systemctl restart twf-models-scheduler.service
```
