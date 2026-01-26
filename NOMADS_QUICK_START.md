# NOMADS Migration - Quick Start Guide

## ✅ Implementation Complete!

All code changes have been implemented and are ready for testing.

---

## 🧪 **STEP 1: Test Locally First**

Before deploying to production, test on your local machine:

```bash
cd /Users/brianaustin/twf_models

# Run the comprehensive test suite
python3 test_nomads_fetch.py
```

**Expected Results:**
- ✅ Availability check passes (finds data on NOMADS)
- ✅ Full fetch works
- ✅ Filtered fetch works (faster, smaller)
- ✅ Performance comparison shows NOMADS improvements
- ✅ Data quality matches AWS S3

**If any tests fail:**
- Check your internet connection
- Verify NOMADS is accessible: `curl -I https://nomads.ncep.noaa.gov/`
- Check if GFS data is available for the latest run
- Review error messages in test output

---

## 🚀 **STEP 2: Deploy to Production**

Once local testing passes:

### A. SSH into Your Droplet

```bash
ssh brian@174.138.84.70
cd /opt/twf_models
```

### B. Pull Latest Code

```bash
# Pull your changes (after you commit and push)
git pull origin main

# Or manually update files if not using git
```

### C. Update Configuration

```bash
# Edit environment file
sudo nano backend/.env

# Add these lines (or update existing):
GFS_SOURCE=nomads
NOMADS_USE_FILTER=True
NOMADS_TIMEOUT=120
NOMADS_MAX_RETRIES=3

# Save and exit (Ctrl+X, Y, Enter)
```

### D. Restart Scheduler

```bash
# Restart to apply new config
sudo systemctl restart twf-models-scheduler

# Check status
sudo systemctl status twf-models-scheduler
```

### E. Monitor First Run

```bash
# Watch logs in real-time
sudo tail -f /var/log/twf-models-scheduler.log

# Look for:
# - "Fetching GFS data from NOMADS..."
# - "✅ Downloaded X.X MB from NOMADS"
# - "✅ fXXX: All N maps generated successfully"
```

---

## 📊 **STEP 3: Verify Results**

### Check Map Generation

```bash
# List recent maps
ls -lth /opt/twf_models/images/ | head -20

# Check API
curl http://174.138.84.70:8000/api/maps | jq
```

### Monitor for Issues

Watch for the next **scheduled run** (03:30, 09:30, 15:30, or 21:30 UTC):

```bash
# Current UTC time
date -u

# Watch scheduler logs
sudo journalctl -u twf-models-scheduler -f
```

---

## 🔄 **STEP 4: Rollback if Needed**

If you encounter issues:

```bash
# Quick rollback to AWS S3
sudo nano /opt/twf_models/backend/.env

# Change:
GFS_SOURCE=aws

# Restart
sudo systemctl restart twf-models-scheduler
```

---

## ⚡ **BONUS: Further Optimizations**

After NOMADS is stable (24-48 hours), apply these for even better performance:

### 1. Start Scheduler Earlier

```python
# Edit: backend/app/scheduler.py
# Line ~427: Change schedule from 03:30 to 02:00

self.scheduler.add_job(
    self.generate_forecast_maps,
    trigger=CronTrigger(hour='2,8,14,20', minute='0'),  # Changed!
    ...
)
```

**Impact:** Get first maps 1.5 hours earlier

### 2. Increase Check Frequency

```python
# Edit: backend/app/scheduler.py
# Line 256: Change check_interval_seconds from 60 to 15

self._progressive_generation_loop(
    run_time, 
    duration_minutes=90, 
    check_interval_seconds=15  # Changed from 60!
)
```

**Impact:** Reduce average latency by 45 seconds

### 3. Extend Forecast Hours

```python
# Edit: backend/app/config.py
# Line 34: Extend to f120 or f138

forecast_hours: str = "0,6,12,18,24,30,36,42,48,54,60,66,72,78,84,90,96,102,108,114,120"
```

**Impact:** Match competitors with 5-day forecasts

---

## 📋 **File Changes Summary**

| File | Changes | Purpose |
|------|---------|---------|
| `backend/app/config.py` | Added NOMADS settings | Configure NOMADS behavior |
| `backend/app/services/data_fetcher.py` | Implemented NOMADS fetching | Download from NOMADS with filtering |
| `backend/app/scheduler.py` | Updated availability check | Support both AWS and NOMADS |
| `test_nomads_fetch.py` | NEW test script | Validate before production |
| `docs/NOMADS_MIGRATION.md` | NEW documentation | Complete migration guide |

---

## 🎯 **Expected Improvements**

### Timeline Improvements

| Metric | Before (AWS) | After (NOMADS) | Improvement |
|--------|-------------|----------------|-------------|
| First maps available | 4-5 hours | 2-3 hours | **~2 hours faster** |
| All maps complete | 5-6 hours | 3.5-4 hours | **~1.5 hours faster** |
| Download per file | 20-40 sec | 5-15 sec | **~70% faster** |
| File size | ~150 MB | ~15-20 MB | **~90% smaller** |

### Competitive Position

After NOMADS + optimizations:
- **Your site:** Maps at f72 within 3-4 hours
- **Other sites:** Maps at f138 within 2-3 hours
- **Gap:** Nearly closed! You'll be competitive

To fully match:
1. ✅ Switch to NOMADS (done!)
2. ✅ Start earlier (bonus optimization)
3. ✅ Extend to f138 (bonus optimization)

---

## 🆘 **Support & Troubleshooting**

### Common Issues

**"NOMADS filter URL returns 400 error"**
- Check `_build_nomads_filter_url()` variable mapping
- Verify region bounds are valid
- Try full download (disable filter)

**"Download times out"**
- Increase `NOMADS_TIMEOUT` to 180 or 300
- Check network connectivity to NOMADS
- Try during off-peak hours

**"Maps look different"**
- Data should be identical to AWS
- Run comparison test
- Check GRIB processing logic

**"Can't find NOMADS module"**
- No extra modules needed!
- Uses `requests` (already installed)
- Uses same `cfgrib` and `xarray` as AWS

### Getting Help

1. Check logs: `sudo journalctl -u twf-models-scheduler -n 100`
2. Run test: `python3 test_nomads_fetch.py`
3. Review documentation: `docs/NOMADS_MIGRATION.md`
4. Compare with AWS: Set `GFS_SOURCE=aws` temporarily

---

## ✅ **Checklist**

- [ ] Run local tests (`python3 test_nomads_fetch.py`)
- [ ] All tests pass
- [ ] Commit and push changes to git (optional)
- [ ] SSH into droplet
- [ ] Update configuration (`.env` or `config.py`)
- [ ] Restart scheduler
- [ ] Monitor first run
- [ ] Verify maps are generated
- [ ] Check for errors in logs
- [ ] Confirm improved timing
- [ ] Document any issues
- [ ] After 24h: Apply bonus optimizations (optional)

---

**Ready to go!** Start with **STEP 1** above. Good luck! 🚀
