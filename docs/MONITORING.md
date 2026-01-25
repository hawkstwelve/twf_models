# Monitoring Scheduler Progress

This guide explains how to monitor the progress of GFS data pulls and map generation on your server.

## Quick Status Check

### 1. Check if Scheduler is Running

```bash
# Check service status
sudo systemctl status twf-models-scheduler

# Check if process is running
ps aux | grep scheduler
```

### 2. View Real-Time Logs

The scheduler logs to `/var/log/twf-models-scheduler.log`. You can monitor it in real-time:

```bash
# Follow logs in real-time (most recent first)
sudo tail -f /var/log/twf-models-scheduler.log

# View last 100 lines
sudo tail -n 100 /var/log/twf-models-scheduler.log

# View logs with timestamps
sudo journalctl -u twf-models-scheduler -f

# View logs for today only
sudo journalctl -u twf-models-scheduler --since today
```

### 3. Check Error Logs

```bash
# Check for errors
sudo tail -f /var/log/twf-models-scheduler-error.log

# View recent errors
sudo tail -n 50 /var/log/twf-models-scheduler-error.log
```

## Understanding Scheduler Logs

The scheduler logs include emoji indicators for easy scanning:

- 🚀 = Worker starting
- ✅ = Successfully generated maps
- ⏳ = Waiting for data
- 🔍 = Checking S3 for new data
- ⚠️ = Warning (incomplete generation)
- ❌ = Error
- 📈 = Progress update
- 💤 = Sleeping between checks

### Example Log Output

```
2026-01-25 15:30:00 - INFO - ======================================================================
2026-01-25 15:30:00 - INFO - 🚀 Starting progressive map generation
2026-01-25 15:30:00 - INFO - ======================================================================
2026-01-25 15:30:00 - INFO - 📡 Monitoring GFS 2026-01-25 12z run
2026-01-25 15:30:00 - INFO - ⏱️  Will check S3 every 60 seconds for up to 90 minutes
2026-01-25 15:30:00 - INFO - 🔍 Check #1 (elapsed: 0.0 min)
2026-01-25 15:30:05 - INFO - ✅ Found 1 new forecast hours: [0]
2026-01-25 15:30:05 - INFO - 🚀 Worker starting for f000
2026-01-25 15:30:45 - INFO -   ✓ f000: temp
2026-01-25 15:30:46 - INFO -   ✓ f000: precip
2026-01-25 15:30:48 - INFO - ✅ f000: All 6 maps generated successfully
```

## Check Generated Files

### 4. Monitor File Generation

The scheduler generates maps in the configured storage path (default: `/opt/twf_models/images` or `./images`):

```bash
# Count generated files for current 12z run
STORAGE_PATH="/opt/twf_models/images"  # Adjust if different
RUN_DATE=$(date +%Y%m%d)
ls -1 ${STORAGE_PATH}/gfs_${RUN_DATE}_12_*.png | wc -l

# List all files for 12z run
ls -lh ${STORAGE_PATH}/gfs_${RUN_DATE}_12_*.png

# Watch files being created in real-time
watch -n 5 "ls -1 ${STORAGE_PATH}/gfs_${RUN_DATE}_12_*.png | wc -l"

# Check latest file modification time
ls -lt ${STORAGE_PATH}/gfs_${RUN_DATE}_12_*.png | head -5
```

### 5. Expected File Count

For a complete run, you should see:
- **6 variables** × **forecast hours** = total files
- Variables: `temp`, `precip`, `wind_speed`, `mslp_precip`, `temp_850_wind_mslp`, `radar`
- Default forecast hours: `0, 24, 48, 72` (4 hours)
- **Expected total: 6 × 4 = 24 files** (for default config)

```bash
# Calculate expected vs actual
EXPECTED=24  # Adjust based on your forecast_hours config
ACTUAL=$(ls -1 ${STORAGE_PATH}/gfs_${RUN_DATE}_12_*.png 2>/dev/null | wc -l)
echo "Expected: ${EXPECTED}, Actual: ${ACTUAL}, Progress: $((ACTUAL * 100 / EXPECTED))%"
```

## API-Based Monitoring

### 6. Use the API to Check Progress

If your API is running, you can query it programmatically:

```bash
# Get all runs (shows latest run with map count)
curl http://localhost:8000/api/runs

# Get maps for specific run (12z today)
RUN_DATE=$(date +%Y%m%d)
curl "http://localhost:8000/api/maps?run_time=2026-01-25T12:00:00Z" | jq '.maps | length'

# Get detailed map list
curl "http://localhost:8000/api/maps?run_time=2026-01-25T12:00:00Z" | jq '.maps[] | {variable, forecast_hour, created_at}'
```

## Monitoring Script

### 7. Create a Monitoring Script

Save this as `monitor_scheduler.sh`:

```bash
#!/bin/bash
# Monitor scheduler progress for current 12z run

STORAGE_PATH="/opt/twf_models/images"  # Adjust if needed
RUN_DATE=$(date +%Y%m%d)
RUN_HOUR="12"

echo "=== TWF Models Scheduler Monitor ==="
echo "Run: ${RUN_DATE} ${RUN_HOUR}z"
echo ""

# Check service status
echo "Service Status:"
sudo systemctl is-active twf-models-scheduler && echo "✅ Running" || echo "❌ Stopped"
echo ""

# Count generated files
FILE_COUNT=$(ls -1 ${STORAGE_PATH}/gfs_${RUN_DATE}_${RUN_HOUR}_*.png 2>/dev/null | wc -l)
EXPECTED=24  # 6 variables × 4 forecast hours
PROGRESS=$((FILE_COUNT * 100 / EXPECTED))

echo "File Generation:"
echo "  Generated: ${FILE_COUNT}/${EXPECTED} files (${PROGRESS}%)"
echo ""

# Show recent log entries
echo "Recent Log Activity (last 10 lines):"
sudo tail -n 10 /var/log/twf-models-scheduler.log
echo ""

# Show latest files
echo "Latest Generated Files:"
ls -lt ${STORAGE_PATH}/gfs_${RUN_DATE}_${RUN_HOUR}_*.png 2>/dev/null | head -5 | awk '{print "  " $9 " (" $6 " " $7 " " $8 ")"}'
```

Make it executable:
```bash
chmod +x monitor_scheduler.sh
./monitor_scheduler.sh
```

## Troubleshooting

### Scheduler Not Running

```bash
# Start the service
sudo systemctl start twf-models-scheduler

# Enable auto-start on boot
sudo systemctl enable twf-models-scheduler

# Check why it failed
sudo journalctl -u twf-models-scheduler -n 50
```

### No Files Being Generated

1. **Check logs for errors:**
   ```bash
   sudo tail -n 100 /var/log/twf-models-scheduler-error.log
   ```

2. **Verify S3 connectivity:**
   ```bash
   # Test S3 access (from Python)
   python3 -c "import s3fs; s3 = s3fs.S3FileSystem(anon=True); print('S3 accessible' if s3.exists('noaa-gfs-bdp-pds') else 'S3 not accessible')"
   ```

3. **Check storage path permissions:**
   ```bash
   ls -ld /opt/twf_models/images
   sudo chown -R root:root /opt/twf_models/images
   sudo chmod 755 /opt/twf_models/images
   ```

### Incomplete Generation

If some forecast hours are missing:

1. **Check if data is available on S3:**
   The scheduler checks every 60 seconds. If data isn't available yet, it will keep checking for up to 90 minutes.

2. **Manually trigger a catch-up:**
   The scheduler has catch-up logic if started within 90 minutes of a scheduled time.

3. **Check for worker failures:**
   Look for `❌ Worker failed` messages in logs.

## Schedule Reference

The scheduler runs at:
- **03:30 UTC** (for 00z run)
- **09:30 UTC** (for 06z run)  
- **15:30 UTC** (for 12z run) ← **This is your 12z run**
- **21:30 UTC** (for 18z run)

Each run monitors for up to 90 minutes, checking S3 every 60 seconds.

## Quick Commands Reference

```bash
# One-liner to check progress
RUN_DATE=$(date +%Y%m%d) && echo "Files: $(ls -1 /opt/twf_models/images/gfs_${RUN_DATE}_12_*.png 2>/dev/null | wc -l)/24"

# Watch logs in real-time
sudo journalctl -u twf-models-scheduler -f

# Check if scheduler is active
sudo systemctl is-active twf-models-scheduler && echo "✅ Active" || echo "❌ Inactive"

# View last 20 log lines with timestamps
sudo tail -n 20 /var/log/twf-models-scheduler.log
```
