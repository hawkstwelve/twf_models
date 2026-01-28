# Troubleshooting: Map Generation Hanging

## Problem
Map generation hangs at the "Added station overlays" step, specifically during `plt.savefig()`.

## Root Causes

### 1. **Matplotlib Backend Issues**
- The 'Agg' backend should work headless but can hang in some environments
- Threading issues with cartopy + matplotlib

### 2. **Memory Pressure**
- Large datasets being held in memory during rendering
- Not enough RAM available

### 3. **Cartopy Shapefile Issues**
- Missing or corrupted Natural Earth shapefiles
- Network timeout when downloading cartopy data

### 4. **File System Issues**
- Permission problems writing to output directory
- Disk full or quota exceeded
- NFS/network filesystem latency

## Fixes Applied

### Code Changes Made:

1. **Enhanced `plt.savefig()` call** (`map_generator.py`)
   - Added explicit `format='png'` parameter
   - Added `edgecolor='none'` parameter
   - Added logging before/after savefig
   - Added try/except block with detailed error logging

2. **Additional matplotlib configuration** (`map_generator.py`)
   - Set `matplotlib.rcParams['figure.max_open_warning'] = 0`
   - Set `matplotlib.rcParams['agg.path.chunksize'] = 10000`
   - Set `os.environ['CARTOPY_OFFLINE'] = '0'`

3. **Created debug script** (`debug_map_generation.py`)
   - Tests single map with timeout protection
   - Helps identify if truly hanging vs. just slow

## Immediate Actions to Try

### 1. Check Disk Space
```bash
df -h /opt/twf_models
df -h /tmp
```

### 2. Check Memory Usage
```bash
free -h
htop  # or top
```

### 3. Check Output Directory Permissions
```bash
ls -ld /opt/twf_models/backend/app/static/images
touch /opt/twf_models/backend/app/static/images/test.txt
rm /opt/twf_models/backend/app/static/images/test.txt
```

### 4. Test Single Map with Timeout
```bash
cd /opt/twf_models
python3 debug_map_generation.py --model GFS --variable temp --hour 6 --timeout 120
```

### 5. Check Cartopy Data
```bash
# Check if cartopy data directory exists
ls -la ~/.local/share/cartopy
# Or
ls -la /root/.local/share/cartopy

# Check cartopy version
python3 -c "import cartopy; print(cartopy.__version__)"
```

### 6. Reduce Worker Processes
Edit `backend/app/scheduler.py`, reduce `_GLOBAL_POOL_SIZE`:
```python
# Change from:
_GLOBAL_POOL_SIZE = min(4, os.cpu_count() or 4)

# To:
_GLOBAL_POOL_SIZE = 1  # Single worker to reduce memory pressure
```

## Workarounds

### Option 1: Disable Station Overlays Temporarily
If stations are causing issues, disable them:

Edit `backend/app/config.py`:
```python
station_overlays: bool = False  # Temporarily disable
```

### Option 2: Use Lower DPI
Reduce memory usage by using lower DPI:

Edit `backend/app/config.py`:
```python
map_dpi: int = 100  # Down from 150
```

### Option 3: Generate Maps Sequentially
Instead of using multiprocessing, generate one at a time:

```bash
# Use the debug script to generate maps one by one
for hour in 6 12 18 24 30 36 42 48; do
    python3 debug_map_generation.py --model GFS --variable temp --hour $hour
    python3 debug_map_generation.py --model GFS --variable precip --hour $hour
    # etc.
done
```

### Option 4: Increase Timeout for Slow Systems
If system is just slow (not hanging), increase timeouts:

Edit `backend/app/models/model_registry.py`:
```python
timeout: int = 300  # Up from 120
```

## Diagnostic Commands

### Check what's running:
```bash
ps aux | grep python
ps aux | grep scheduler
```

### Check system load:
```bash
uptime
cat /proc/loadavg
```

### Check for zombie processes:
```bash
ps aux | grep defunct
```

### Monitor in real-time:
```bash
# Watch memory and CPU
watch -n 1 'free -h && echo "" && ps aux | grep python | head -10'
```

### Check matplotlib backend:
```bash
python3 -c "import matplotlib; print(matplotlib.get_backend())"
```

### Test matplotlib directly:
```bash
python3 << 'EOF'
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
plt.figure()
plt.plot([1,2,3], [1,2,3])
plt.savefig('/tmp/test_plot.png')
plt.close()
print("Success! File saved to /tmp/test_plot.png")
EOF
```

## Known Issues

### Issue: Cartopy downloading data during first run
**Symptom:** Hangs on first map, works on subsequent maps
**Solution:** Pre-download cartopy data:
```bash
python3 << 'EOF'
import cartopy
from cartopy.io.shapereader import natural_earth
natural_earth(resolution='110m', category='physical', name='coastline')
natural_earth(resolution='110m', category='physical', name='land')
natural_earth(resolution='110m', category='cultural', name='admin_0_countries')
natural_earth(resolution='50m', category='physical', name='lakes')
print("Cartopy data pre-downloaded")
EOF
```

### Issue: NFS filesystem latency
**Symptom:** Hangs during file writes
**Solution:** Use local disk for output:
```python
# In config.py
storage_path: str = "/tmp/weather_maps"  # Local disk
# Then rsync to final location
```

### Issue: Too many open files
**Symptom:** Random failures or hangs
**Solution:** Increase file descriptor limit:
```bash
ulimit -n 4096
# Or permanently in /etc/security/limits.conf
```

## After Fixes, Test Again

1. Pull latest code:
```bash
cd /opt/twf_models
git pull origin main
```

2. Restart scheduler:
```bash
sudo systemctl restart twf-models-scheduler.service
```

3. Monitor logs:
```bash
sudo journalctl -u twf-models-scheduler.service -f
```

4. Or test manually:
```bash
cd /opt/twf_models
python3 debug_map_generation.py --timeout 180
```

## If Still Hanging

### Nuclear Option: Bypass plt.savefig timeout
Add this to `map_generator.py` before `plt.savefig()`:

```python
import signal

def alarm_handler(signum, frame):
    raise TimeoutError("savefig timeout")

# Set 60 second timeout for savefig
signal.signal(signal.SIGALRM, alarm_handler)
signal.alarm(60)

try:
    plt.savefig(filepath, format='png', ...)
    signal.alarm(0)  # Cancel alarm
except TimeoutError:
    logger.error("savefig timed out after 60 seconds")
    raise
```

## Contact for Help

If none of these work, gather this info:
```bash
# System info
uname -a
free -h
df -h
python3 --version

# Package versions
pip list | grep -E "matplotlib|cartopy|numpy|xarray"

# Recent logs
sudo journalctl -u twf-models-scheduler.service --since "30 minutes ago" > /tmp/scheduler.log

# Process info
ps aux | grep python > /tmp/processes.log
```

Then share:
- `/tmp/scheduler.log`
- `/tmp/processes.log`
- Description of when it hangs
- Output of test script
