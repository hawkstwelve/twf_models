# Quick Fix: Map Generation Hanging

## What's Happening
Your script hangs at "Added station overlays: X stations" during `plt.savefig()`.

## Quick Fixes (Try in Order)

### 1. Check Disk Space (Most Common)
```bash
df -h /opt/twf_models
df -h /tmp
```
If disk is >90% full, clean up old maps or increase disk space.

### 2. Test Single Map with Timeout
```bash
cd /opt/twf_models
python3 debug_map_generation.py --model GFS --variable temp --hour 6 --timeout 120
```
This will tell you if it's hanging or just slow.

### 3. Reduce Workers (Memory Issue)
Edit `/opt/twf_models/backend/app/scheduler.py`:
```python
# Line ~32, change:
_GLOBAL_POOL_SIZE = 1  # Down from 4
```
Then restart:
```bash
sudo systemctl restart twf-models-scheduler.service
```

### 4. Disable Station Overlays Temporarily
Edit `/opt/twf_models/backend/app/config.py`:
```python
station_overlays: bool = False
```

### 5. Pre-Download Cartopy Data
```bash
python3 -c "
import cartopy
from cartopy.io.shapereader import natural_earth
natural_earth(resolution='110m', category='physical', name='coastline')
natural_earth(resolution='110m', category='physical', name='land')
natural_earth(resolution='110m', category='cultural', name='admin_0_countries')
print('Done')
"
```

## Already Applied Fixes

I've updated the code with:
- ✅ Better logging around `plt.savefig()`
- ✅ Explicit format parameter
- ✅ Enhanced matplotlib configuration
- ✅ Created debug script with timeout

## Pull Latest Code
```bash
cd /opt/twf_models
git pull origin main
sudo systemctl restart twf-models-scheduler.service
```

## Still Hanging?

See `TROUBLESHOOTING_HANGING.md` for detailed diagnostics.
