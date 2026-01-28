# NOMADS Deployment Checklist

**Date:** January 27, 2026  
**Status:** Backend deployed & stable; focus shifting to frontend and map expansion.

---

## ✅ Pre-Deployment (Complete)

- [x] NOMADS implementation coded
- [x] Local testing completed (4/4 tests passed)
- [x] Performance validated (26x faster)
- [x] Documentation created
- [x] Changes committed to git
- [x] Changes pushed to GitHub

---

## 🚀 Deployment Steps

### Step 1: SSH into Droplet

```bash
ssh brian@174.138.84.70
```

### Step 2: Pull Latest Code

```bash
cd /opt/twf_models
sudo git pull origin main
```

**Expected output:**
```
Updating bf02ce3..bffbac5
Fast-forward
 NOMADS_QUICK_START.md                    | 234 ++++++++++
 backend/app/config.py                    |   6 +
 backend/app/scheduler.py                 |  58 ++-
 backend/app/services/data_fetcher.py     | 289 ++++++++++--
 docs/NOMADS_MIGRATION.md                 | 301 ++++++++++++
 test_nomads_fetch.py                     | 316 +++++++++++++
 6 files changed, 1389 insertions(+), 28 deletions(-)
```

### Step 3: Update Environment Configuration

```bash
cd /opt/twf_models/backend
sudo nano .env
```

**Add or update these lines:**
```bash
# Data source
GFS_SOURCE=nomads

# NOMADS settings
NOMADS_USE_FILTER=True
NOMADS_TIMEOUT=120
NOMADS_MAX_RETRIES=3
```

**Save and exit:** Press `Ctrl+X`, then `Y`, then `Enter`

### Step 4: Verify Configuration

```bash
# Check that the file was updated correctly
cat .env | grep -E "(GFS_SOURCE|NOMADS)"
```

**Expected output:**
```
GFS_SOURCE=nomads
NOMADS_USE_FILTER=True
NOMADS_TIMEOUT=120
NOMADS_MAX_RETRIES=3
```

### Step 5: Restart Scheduler

```bash
sudo systemctl restart twf-models-scheduler
```

### Step 6: Check Service Status

```bash
sudo systemctl status twf-models-scheduler
```

**Expected:** Should show "active (running)" in green

### Step 7: Monitor Logs

```bash
sudo tail -f /var/log/twf-models-scheduler.log
```

**Look for these indicators:**
- ✅ "Fetching GFS data from NOMADS..."
- ✅ "Using NOMADS filter for selective download"
- ✅ "NOMADS filter URL built with N variables"
- ✅ "✅ Downloaded X.X MB from NOMADS"
- ✅ "✅ fXXX: All N maps generated successfully"

**Red flags (if you see these, rollback):**
- ❌ "Failed to download from NOMADS after 3 attempts"
- ❌ Multiple "Error" messages in succession
- ❌ "Could not extract any variables from GRIB file"

### Step 8: Wait for Next Scheduled Run

**Next run times (UTC):**
- 02:00 (after 18z GFS run)
- 08:00 (after 00z GFS run)
- 14:00 (after 06z GFS run)
- 20:00 (after 12z GFS run)

**Or manually trigger:**
```bash
# Check current time
date -u

# If within 90 minutes of a scheduled run, it will auto-trigger
# Otherwise, wait for next scheduled time
```

### Step 9: Verify Maps Generated

After the run completes (~10-15 minutes):

```bash
# Check latest maps
ls -lth /opt/twf_models/images/ | head -20

# Count total maps
ls -1 /opt/twf_models/images/*.png | wc -l

# Check API
curl http://localhost:8000/api/maps | jq '.maps | length'
```

### Step 10: Verify via Web Browser

Visit: `https://sodakweather.com/models`

**Check:**
- [ ] Maps are displaying
- [ ] Timestamps look correct
- [ ] Temperature values are reasonable
- [ ] No obvious visual artifacts

---

## 🔄 Rollback Plan (If Needed)

If you encounter issues:

### Quick Rollback

```bash
# Edit config
cd /opt/twf_models/backend
sudo nano .env

# Change back:
GFS_SOURCE=aws

# Save and restart
sudo systemctl restart twf-models-scheduler

# Verify
sudo systemctl status twf-models-scheduler
sudo tail -f /var/log/twf-models-scheduler.log
```

### Full Rollback (Revert Code)

```bash
cd /opt/twf_models
sudo git revert HEAD
sudo systemctl restart twf-models-scheduler
```

---

## 📊 Success Metrics

After 24 hours of operation, verify:

### Performance Improvements

```bash
# Check logs for download times
sudo grep "Downloaded.*MB from NOMADS" /var/log/twf-models-scheduler.log | tail -20
```

**Expected:** Download times should be **1-5 seconds** per file (vs 20-40 seconds with AWS)

### Data Availability

```bash
# Check when first maps appear after run time
sudo grep "f000.*maps generated" /var/log/twf-models-scheduler.log
```

**Expected:** First maps within **2-3 hours** of run time (vs 4-5 hours with AWS)

### Error Rate

```bash
# Count errors in last 100 lines
sudo tail -100 /var/log/twf-models-scheduler.log | grep -c "❌"
```

**Expected:** **0-2 errors** (occasional NOMADS 503 errors are normal, retry handles them)

### Bandwidth Usage

```bash
# Check downloaded file sizes
sudo grep "Downloaded.*MB from NOMADS" /var/log/twf-models-scheduler.log | tail -10
```

**Expected:** **2-10 MB per file** with filter (vs 150+ MB with AWS full files)

---

## 🎯 Optimization Opportunities (After Stable 24-48h)

Once NOMADS is proven stable, consider these additional improvements:

### 1. Start Earlier (Get maps 1.5 hours sooner)

```bash
sudo nano /opt/twf_models/backend/app/scheduler.py
```

**Change line ~427:**
```python
# From:
trigger=CronTrigger(hour='3,9,15,21', minute='30')

# To:
trigger=CronTrigger(hour='2,8,14,20', minute='0')
```

### 2. Check More Frequently (Reduce latency by 45 seconds)

**Change line ~256:**
```python
# From:
check_interval_seconds=60

# To:
check_interval_seconds=15
```

### 3. Extend Forecast Hours (Match competitors)

```bash
sudo nano /opt/twf_models/backend/app/config.py
```

**Change line ~34:**
```python
# From:
forecast_hours: str = "0,6,12,18,24,30,36,42,48,54,60,66,72"

# To:
forecast_hours: str = "0,6,12,18,24,30,36,42,48,54,60,66,72,78,84,90,96,102,108,114,120"
```

**After any changes:**
```bash
sudo systemctl restart twf-models-scheduler
```

---

## 📱 Monitoring Commands

### Real-time Log Monitoring
```bash
sudo tail -f /var/log/twf-models-scheduler.log
```

### Check Service Status
```bash
sudo systemctl status twf-models-scheduler
```

### View Recent Errors
```bash
sudo journalctl -u twf-models-scheduler -n 50 --no-pager
```

### Check Disk Usage
```bash
df -h /opt/twf_models
du -sh /opt/twf_models/images/
```

### List Recent Maps
```bash
ls -lth /opt/twf_models/images/ | head -20
```

---

## ✅ Deployment Completion Checklist

- [ ] SSH into droplet
- [ ] Pull latest code (`git pull`)
- [ ] Update `.env` file with NOMADS settings
- [ ] Restart scheduler (`systemctl restart`)
- [ ] Verify service is running
- [ ] Monitor logs for first run
- [ ] Verify maps are generated
- [ ] Check maps via web interface
- [ ] Monitor for 24 hours
- [ ] Document any issues
- [ ] Apply optimizations (optional)

---

## 🆘 Support

**Documentation:**
- Quick Start: `NOMADS_QUICK_START.md`
- Technical Details: `docs/NOMADS_MIGRATION.md`
- Test Script: `test_nomads_fetch.py`

**Logs:**
- Scheduler: `/var/log/twf-models-scheduler.log`
- Error log: `/var/log/twf-models-scheduler-error.log`
- System journal: `journalctl -u twf-models-scheduler`

**Commands:**
- Service status: `systemctl status twf-models-scheduler`
- Restart: `systemctl restart twf-models-scheduler`
- View logs: `tail -f /var/log/twf-models-scheduler.log`

---

**Ready to Deploy!** Follow the steps above in order. 🚀

**Estimated deployment time:** 10-15 minutes  
**Expected improvement:** Maps available 2-3 hours earlier than current
