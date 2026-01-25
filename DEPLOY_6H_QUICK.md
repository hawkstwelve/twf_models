# Quick Deployment Guide: 6-Hour Increments

## Summary of Changes

✅ **Step 1: Configuration Updated**
- Backend: `forecast_hours: "0,6,12,18,24,30,36,42,48,54,60,66,72"`
- Frontend: 13 forecast hour buttons (dynamically generated)

✅ **Step 2: Migration Script Created**
- `scripts/migrate_to_6h_increments.sh` - backs up, clears, restarts

✅ **Step 3: Frontend Enhanced**
- Dynamic button generation from config
- Compact styling for 13 buttons
- Responsive wrapping on mobile

## Deploy to Production

### Quick Deploy (All-in-One)

```bash
# SSH to server
ssh root@174.138.84.70

# Navigate to project
cd /opt/twf_models

# Pull changes
git pull origin main

# Run migration script (interactive - will ask for confirmation)
./scripts/migrate_to_6h_increments.sh
```

### Manual Deploy (Step-by-Step)

```bash
# SSH to server
ssh root@174.138.84.70

cd /opt/twf_models

# 1. Pull code
git pull origin main

# 2. Backup old maps
mkdir -p images_backup_$(date +%Y%m%d)
cp images/*.png images_backup_$(date +%Y%m%d)/

# 3. Clear old maps
rm images/*.png

# 4. Restart scheduler
sudo systemctl restart twf-models-scheduler

# 5. Monitor logs
sudo journalctl -u twf-models-scheduler -f
```

## What to Expect

### Immediately After Restart
- Scheduler loads new config with 13 forecast hours
- Starts generating maps at next scheduled run (or within 90 min)
- Log messages: "Worker starting for f006", "f012", "f018", etc.

### First Generation Run (~30-45 minutes)
- 13 forecast hours × 6 variables = 78 maps per run
- Downloads GRIB files for each forecast hour
- Precipitation uses `fetch_total_precipitation()` (sums files)

### Subsequent Runs (~15-20 minutes)
- 75% of files cached (much faster)
- Progressive: Maps appear as each hour is processed

### Frontend
- Visit website
- See 13 forecast hour buttons: "Now", "+6h", "+12h", ..., "+72h"
- Click through to verify all hours work
- Maps should load correctly for all hours

## Verification

```bash
# Check number of maps (should be ~78 per run, ~312 total after 4 runs)
ls /opt/twf_models/images/*.png | wc -l

# Check latest maps by forecast hour
ls /opt/twf_models/images/*_6.png   # Should exist
ls /opt/twf_models/images/*_12.png  # Should exist
ls /opt/twf_models/images/*_18.png  # Should exist

# Check disk usage
du -sh /opt/twf_models/images/
```

## Rollback (If Needed)

```bash
# Stop scheduler
sudo systemctl stop twf-models-scheduler

# Restore from backup
cp images_backup_YYYYMMDD/*.png images/

# Revert code
git revert HEAD
git push origin main

# Restart
sudo systemctl restart twf-models-scheduler
```

## Support

If issues arise:
1. Check logs: `sudo journalctl -u twf-models-scheduler -f`
2. Verify config loaded: `grep forecast_hours backend/app/config.py`
3. Check file: `ls -lh images/*.png | head`
4. Test manually: `python3 test_precip_map.py`

---

**All changes committed and pushed to GitHub!**
Ready to deploy when you are. 🚀
