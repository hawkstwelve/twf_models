# Performance Optimization Plan
**Created**: January 28, 2026  
**VPS Specs**: 16GB RAM / 8 vCPU / 240GB SSD  
**Status**: Critical Performance Issues Identified

---

## 🚨 Executive Summary

Your VPS is experiencing **severe memory pressure and I/O bottleneck**:

- **99% memory utilization** (15.4GB/15.6GB used, only 143MB free)
- **63% I/O wait** - disk operations are severely bottlenecked
- **kswapd0 at 90% CPU** - kernel thrashing trying to free memory
- **4 Python workers consuming 14.8GB RAM** - exceeding available resources
- **All processes in 'D' state** - blocked waiting on I/O
- **No swap space configured** - exacerbating memory exhaustion

**Root Cause**: Parallel multiprocessing (4 workers) on memory-constrained system downloading/processing large GRIB files simultaneously.

**Impact**: System instability, potential OOM kills, extremely slow map generation, possible service failures.

---

## 📊 Diagnostic Commands Reference

Run these commands periodically to monitor VPS health:

```bash
# 1. Quick memory snapshot
free -h
cat /proc/meminfo | grep -E "MemTotal|MemFree|MemAvailable|SwapTotal"

# 2. I/O wait and disk performance
iostat -x 5 3

# 3. Top memory consumers
ps aux --sort=-%mem | head -20

# 4. Disk usage
df -h

# 5. System load averages
uptime
cat /proc/loadavg

# 6. Check for OOM killer events
dmesg | grep -i "out of memory"
dmesg | grep -i "killed process"
journalctl -k | grep -i "out of memory"

# 7. Monitor network I/O
iftop -t -s 10

# 8. Service logs
journalctl -u twf-models-scheduler -n 100 --no-pager
journalctl -u twf-models-api -n 100 --no-pager

# 9. Python memory usage over time (run in separate terminal)
while true; do 
    ps aux | grep python | grep -v grep | awk '{sum+=$6} END {print strftime("%Y-%m-%d %H:%M:%S"), "Total Python RSS:", sum/1024, "MB"}'
    sleep 10
done

# 10. Real-time top monitoring
top -d 5

# 11. Detailed process tree
ps auxf | grep -E "python|uvicorn|scheduler"

# 12. Check NOMADS download speeds
time curl -s -o /dev/null "https://nomads.ncep.noaa.gov/pub/data/nccf/com/gfs/prod/"
```

---

## 🎯 Optimization Plan by Priority

### **PRIORITY 0: EMERGENCY STABILIZATION** (Do Immediately)

These changes prevent system crashes and OOM kills:

#### 0.1 Add Swap Space (CRITICAL)
**Impact**: Prevents OOM kills, provides memory safety net  
**Risk**: Low  
**Effort**: 5 minutes  

```bash
# Create 4GB swap file
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile

# Verify swap is active
free -h
swapon --show

# Make permanent (add to /etc/fstab)
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# Set swappiness (how aggressively to use swap, 10 = conservative)
sudo sysctl vm.swappiness=10
echo 'vm.swappiness=10' | sudo tee -a /etc/sysctl.conf
```

**Expected Result**: System won't crash when memory peaks, gives breathing room

---

#### 0.2 Reduce Worker Pool Size (Dynamic)
**Impact**: -50% peak memory usage, eliminates thrashing, auto-scales for future models  
**Risk**: Low  
**Effort**: 5 minutes  

**File**: `backend/app/scheduler.py`

```python
# Line 33 - Replace static pool size with dynamic calculation:

def calculate_optimal_workers():
    """Calculate worker count based on available system memory"""
    try:
        import psutil
        mem = psutil.virtual_memory()
        mem_gb = mem.total / (1024**3)
        available_gb = mem.available / (1024**3)
        
        # Conservative: Reserve 4GB base, use 4GB per worker, max 3 workers
        # Accounts for GFS, AIGFS, and future HRRR (higher memory)
        workers = max(1, min(3, int((mem_gb - 4) / 4)))
        
        # If available memory is critically low, reduce to 1 worker
        if available_gb < 6:
            workers = 1
        
        return workers
    except ImportError:
        return 2  # Fallback if psutil not installed
    except Exception as e:
        return 2  # Safe fallback

_GLOBAL_POOL_SIZE = calculate_optimal_workers()
```

**Install psutil** (add to `backend/requirements.txt`):
```txt
psutil>=5.9.0  # System monitoring for dynamic worker calculation
```

**Reasoning**: 
- **Current (16GB RAM)**: Calculates to 3 workers, but reduces to 2 if memory tight
- **Future-proof**: Auto-scales when you add HRRR or upgrade VPS
- **Safety**: Falls back to 1 worker if memory critically low (<6GB available)
- **Smart**: GFS/AIGFS run with 2-3 workers, HRRR (larger files) may trigger 1-2 workers

---

#### 0.3 Add Memory Cleanup Between Models
**Impact**: Prevents memory accumulation, reduces leaks  
**Risk**: None  
**Effort**: 2 minutes  

**File**: `backend/app/scheduler.py`

```python
# In generate_all_models(), after line ~445, add between model generations:

for model_id in enabled_models.keys():
    if use_progressive:
        success = self.generate_forecast_for_model_progressive(...)
    else:
        success = self.generate_forecast_for_model(model_id)
    
    results[model_id] = success
    
    # 🆕 ADD THIS: Force cleanup before next model
    import gc
    logger.info(f"  Cleaning up after {model_id}...")
    gc.collect()
    time.sleep(5)  # Let OS reclaim memory
    
    logger.info(f"\n{'-'*80}\n")
```

---

#### 0.4 Restart Scheduler Service
**Impact**: Apply changes, clear accumulated memory leaks  
**Risk**: None (automatically restarts)  
**Effort**: 1 minute  

```bash
# Restart scheduler to apply changes
sudo systemctl restart twf-models-scheduler

# Monitor for first few minutes
journalctl -u twf-models-scheduler -f
```

---

### **PRIORITY 1: HIGH IMPACT OPTIMIZATIONS** (Do Next)

#### 1.1 Fix Matplotlib Memory Leaks
**Impact**: -10% memory per run, prevents accumulation  
**Risk**: None  
**Effort**: 10 minutes  

**File**: `backend/app/services/map_generator.py`

Add explicit cleanup at the end of `generate_map()` method:

```python
# After fig.savefig(...) around line ~1900+
fig.savefig(filepath, dpi=settings.map_dpi, bbox_inches='tight')
logger.info(f"Saved map to {filepath}")

# 🆕 ADD THIS: Explicit cleanup
plt.close(fig)
del fig, ax
gc.collect()

return filepath
```

Also add cleanup in the worker function:

**File**: `backend/app/scheduler.py`

```python
# In generate_maps_for_hour(), after the map generation loop (around line ~145):

for variable in variables_to_generate:
    # ... existing map generation code ...
    success_count += 1

# 🆕 ADD THIS: Clear matplotlib state
import matplotlib.pyplot as plt
plt.clf()
plt.cla()

# Cleanup
ds.close()
del ds
gc.collect()
```

---

#### 1.2 Verify NOMADS Filtering is Working
**Impact**: -70% download size, +40% download speed  
**Risk**: None (already configured)  
**Effort**: 5 minutes  

**File**: `backend/app/services/nomads_data_fetcher.py`

Add logging to verify filtered downloads:

```python
# In _download_from_nomads() method, add before download:

def _download_from_nomads(self, url: str, cache_key: str) -> str:
    """Download GRIB from NOMADS and cache locally"""
    
    # 🆕 ADD THIS: Log if using filter
    is_filtered = 'filter_' in url or 'var_' in url
    logger.info(f"  Downloading {'FILTERED' if is_filtered else 'FULL'} GRIB...")
    
    # ... existing download code ...
    
    # 🆕 ADD THIS: Log file size
    file_size_mb = os.path.getsize(tmp_path) / (1024 * 1024)
    logger.info(f"  Downloaded {file_size_mb:.1f} MB")
```

**Verify in logs**:
```bash
journalctl -u twf-models-scheduler | grep "FILTERED\|Downloaded"
```

You should see:
- `Downloading FILTERED GRIB...` (good!)
- `Downloaded 15.3 MB` (filtered) vs `Downloaded 180.5 MB` (full)

If you see "FULL" downloads, filtering is not working properly.

---

#### 1.3 Increase GRIB Cache Max Age
**Impact**: Better cache hit rate across runs  
**Risk**: +500MB disk space  
**Effort**: 1 minute  

**File**: `backend/app/services/base_data_fetcher.py`

```python
# In __init__() method:

def __init__(self, model_id: str):
    # ... existing code ...
    
    # Cache files for 6 hours (matches update_interval, covers full run cycle)
    self._cache_max_age_seconds = 6 * 3600  # Changed from 2 * 3600
```

**Reasoning**: 
- Models run every 6 hours
- Keeping cache for 6 hours allows comparison with previous run
- Minimal disk cost (~500MB max)

---

#### 1.4 Add Memory Monitoring
**Impact**: Early warning system for memory issues  
**Risk**: None  
**Effort**: 10 minutes  

**File**: `backend/app/scheduler.py`

Add memory logging to generation methods:

```python
# At top of file, add import
import psutil

# In generate_forecast_for_model(), add monitoring:

def generate_forecast_for_model(self, model_id: str):
    logger.info(f"\n{'='*80}")
    logger.info(f"🌍 Starting forecast generation for {model_id}")
    
    # 🆕 ADD THIS: Log memory before
    mem = psutil.virtual_memory()
    logger.info(f"💾 Memory: {mem.percent}% used, {mem.available / (1024**3):.1f}GB available")
    logger.info(f"{'='*80}\n")
    
    try:
        # ... existing generation code ...
        
        logger.info(f"\n✅ {model_id}: {len(successful)}/{len(forecast_hours)} forecast hours complete")
        
        # 🆕 ADD THIS: Log memory after
        mem_after = psutil.virtual_memory()
        logger.info(f"💾 Memory after: {mem_after.percent}% used, {mem_after.available / (1024**3):.1f}GB available")
        
        return len(successful) == len(forecast_hours)
```

Add `psutil` to requirements:

**File**: `backend/requirements.txt`

```txt
# Add this line
psutil>=5.9.0
```

Install:
```bash
cd /opt/twf_models/backend
source venv/bin/activate
pip install psutil
```

---

### **PRIORITY 2: MEDIUM IMPACT OPTIMIZATIONS** (Do Soon)

#### 2.1 Switch to Batch Mode (Disable Progressive Generation)
**Impact**: Simpler logic, more predictable resource usage  
**Risk**: Maps appear all at once instead of progressively  
**Effort**: 1 minute  

**File**: `backend/app/config.py`

```python
# Line 44 - Change from:
progressive_generation: bool = True

# To:
progressive_generation: bool = False  # Use batch mode for stability
```

**Reasoning**:
- Progressive mode polls NOMADS every 60s (overhead)
- Batch mode waits for all data, then generates once
- More predictable memory usage pattern
- Simpler code path

**Trade-off**: First maps appear 30-60 minutes later, but more reliable

---

#### 2.2 Optimize Station Overlays
**Impact**: -5% processing time, less matplotlib overhead  
**Risk**: None  
**Effort**: 10 minutes  

**File**: `backend/app/services/map_generator.py`

Make station overlays optional for some map types:

```python
# In generate_map() method, add condition:

def generate_map(self, ds: xr.Dataset, variable: str, model: str = "GFS", ...):
    # ... existing code ...
    
    # 🆕 ADD THIS: Skip station overlays for these types (less useful, saves time)
    skip_stations = variable in ['precip', 'radar', 'radar_reflectivity', 'mslp_precip']
    
    # Add station overlays (if enabled and useful for this variable)
    if settings.station_overlays and not skip_stations:
        station_values = self.extract_station_values(ds, variable_key, region, priority)
        if station_values:
            self.plot_station_overlays(ax, station_values, variable, region)
```

**Optional**: Reduce station priority for non-temp maps:

```python
# Adjust priority based on variable
if variable == 'temp':
    priority = settings.station_priority  # Full priority for temp
else:
    priority = min(settings.station_priority, 2)  # Max priority=2 for others
```

---

#### 2.3 Add Connection Pooling for NOMADS
**Impact**: Faster downloads, better retry handling  
**Risk**: Low  
**Effort**: 15 minutes  

**File**: `backend/app/services/base_data_fetcher.py`

```python
# At top of file
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# In __init__() method:

def __init__(self, model_id: str):
    # ... existing code ...
    
    # 🆕 ADD THIS: Configure requests session with retries and pooling
    self._session = requests.Session()
    retry_strategy = Retry(
        total=3,
        backoff_factor=2,  # 1s, 2s, 4s delays
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "HEAD"]
    )
    adapter = HTTPAdapter(
        max_retries=retry_strategy,
        pool_connections=2,  # 2 concurrent connections max
        pool_maxsize=4
    )
    self._session.mount("https://", adapter)
    self._session.mount("http://", adapter)

# In _download_from_nomads(), use self._session instead of requests:

def _download_from_nomads(self, url: str, cache_key: str) -> str:
    # Change from:
    response = requests.get(url, timeout=timeout, stream=True)
    
    # To:
    response = self._session.get(url, timeout=timeout, stream=True)
```

---

#### 2.4 Pre-cache Critical Forecast Hours
**Impact**: Better cache hits, reduces concurrent downloads  
**Risk**: +2 minutes initial delay  
**Effort**: 15 minutes  

**File**: `backend/app/scheduler.py`

```python
# In generate_forecast_for_model(), before parallel generation:

def generate_forecast_for_model(self, model_id: str):
    # ... existing setup code ...
    
    logger.info(f"📊 Variables: {variables}")
    
    # 🆕 ADD THIS: Pre-cache common forecast hours serially
    # This improves cache hit rate when workers start
    if len(forecast_hours) >= 4:
        cache_hours = forecast_hours[:4]  # First 4 hours
        logger.info(f"📥 Pre-caching {len(cache_hours)} forecast hours: {cache_hours}")
        for fh in cache_hours:
            try:
                # Just download and cache, don't generate maps yet
                _ = data_fetcher.fetch_raw_data(
                    run_time=run_time,
                    forecast_hour=fh,
                    raw_fields=set(['tmp2m', 'prate']),  # Minimal fields
                    subset_region=True
                )
                logger.info(f"  ✓ Cached f{fh:03d}")
            except Exception as e:
                logger.warning(f"  ⚠️  Failed to pre-cache f{fh:03d}: {e}")
    
    # Generate maps in parallel by forecast hour
    logger.info(f"💻 Using {_GLOBAL_POOL_SIZE} worker processes")
    # ... existing parallel generation ...
```

---

#### 2.5 Optimize xarray Memory Usage
**Impact**: -15% dataset memory usage  
**Risk**: None  
**Effort**: 10 minutes  

**File**: `backend/app/services/base_data_fetcher.py`

```python
# In _open_grib_file() method, after opening dataset:

def _open_grib_file(self, tmp_path: str, forecast_hour: int, ...):
    # ... existing open code ...
    
    # 🆕 ADD THIS: Drop unnecessary coordinates immediately
    drop_coords = []
    for coord in ['time', 'valid_time', 'step', 'heightAboveGround', 'surface']:
        if coord in ds.coords:
            drop_coords.append(coord)
    
    if drop_coords:
        ds = ds.drop_vars(drop_coords, errors='ignore')
        logger.debug(f"  Dropped coordinates: {drop_coords}")
    
    # Subset region
    if subset_region:
        ds = self._subset_dataset(ds)
    
    return ds
```

---

### **PRIORITY 3: NICE TO HAVE** (Do Later)

#### 3.1 Implement Dask for Lazy Loading
**Impact**: -30% memory for large datasets  
**Risk**: Medium (adds complexity)  
**Effort**: 2-3 hours  

Use Dask to load only needed data chunks:

```python
# In fetch_raw_data()
ds = xr.open_dataset(
    path, 
    engine='cfgrib',
    chunks={'latitude': 50, 'longitude': 50}  # Lazy load in chunks
)
```

**Note**: Only implement if you add more models or higher resolution data.

---

#### 3.2 Cache Station Grid Indices
**Impact**: -2% processing time  
**Risk**: Low  
**Effort**: 1 hour  

Pre-compute nearest grid indices for stations once per model run:

```python
# In MapGenerator.__init__()
self._station_indices_cache = {}

def _precompute_station_indices(self, ds: xr.Dataset, region: str):
    """Cache grid indices for all stations"""
    cache_key = f"{region}_{hash(tuple(ds.lon.values.tolist()))}"
    if cache_key in self._station_indices_cache:
        return self._station_indices_cache[cache_key]
    
    # Compute once
    stations = get_stations_for_region(region, 3)
    indices = {}
    for name, data in stations.items():
        lat_idx = np.argmin(np.abs(ds.lat.values - data['lat']))
        lon_idx = np.argmin(np.abs(ds.lon.values - data['lon']))
        indices[name] = {'lat': lat_idx, 'lon': lon_idx}
    
    self._station_indices_cache[cache_key] = indices
    return indices
```

---

#### 3.3 Add Disk Space Monitoring
**Impact**: Prevents disk full errors  
**Risk**: None  
**Effort**: 15 minutes  

Add to scheduler startup:

```python
# In ForecastScheduler.start()
def start(self):
    logger.info("Starting Multi-Model Forecast Scheduler...")
    
    # 🆕 ADD THIS: Check disk space
    import shutil
    disk = shutil.disk_usage(settings.storage_path)
    disk_free_gb = disk.free / (1024**3)
    disk_percent = (disk.used / disk.total) * 100
    
    logger.info(f"💾 Disk space: {disk_free_gb:.1f}GB free ({disk_percent:.1f}% used)")
    
    if disk_free_gb < 10:
        logger.warning("⚠️  Less than 10GB disk space available!")
    
    # ... rest of start() ...
```

---

## 📈 Expected Performance Improvements

| Phase | Changes | Memory Impact | Speed Impact | Stability |
|-------|---------|---------------|--------------|-----------|
| **P0: Emergency** | Swap + 2 workers + cleanup | -50% peak | +20% time | ⭐⭐⭐⭐⭐ |
| **P1: High Impact** | Matplotlib + verify filter + cache | -25% | +30% | ⭐⭐⭐⭐ |
| **P2: Medium** | Batch mode + stations + pooling | -10% | +15% | ⭐⭐⭐ |
| **P3: Nice to Have** | Dask + caching + monitoring | -10% | +5% | ⭐⭐ |
| **TOTAL (All)** | Combined optimizations | -70% | +50% | Stable ✅ |

### Before vs After (Estimated)

| Metric | Before (Current) | After P0 | After P1 | After P2 |
|--------|-----------------|----------|----------|----------|
| Peak Memory | 15.4 GB (99%) | 8.5 GB (54%) | 7.5 GB (48%) | 7.0 GB (45%) |
| I/O Wait | 63% | 15-25% | 10-15% | 5-10% |
| Total Time | ~45 min | ~55 min | ~45 min | ~35 min |
| Stability | ❌ Crashes | ✅ Stable | ✅ Stable | ✅ Stable |
| Cache Hits | 20% | 40% | 60% | 75% |

---

## 🔍 Validation & Testing

After implementing each priority level:

### Test Sequence

```bash
# 1. Restart services
sudo systemctl restart twf-models-scheduler
sudo systemctl restart twf-models-api

# 2. Monitor memory during generation
watch -n 5 'free -h && echo && ps aux | grep python | grep -v grep | awk "{sum+=\$6} END {print \"Python RSS: \" sum/1024 \" MB\"}"'

# 3. Check logs for errors
journalctl -u twf-models-scheduler -f

# 4. Verify map generation
ls -lh /opt/twf_models/backend/app/static/images/ | tail -20

# 5. Check system health after run
top -b -n 1 | head -20
free -h
df -h
```

### Success Criteria

**Priority 0 (Emergency)**:
- ✅ Swap space active (`swapon --show`)
- ✅ Peak memory < 10GB
- ✅ No OOM killer events (`dmesg | grep -i oom`)
- ✅ All maps generated successfully

**Priority 1 (High Impact)**:
- ✅ Filtered downloads confirmed (15-30MB vs 180MB)
- ✅ Memory stable across multiple runs
- ✅ Cache hit rate > 40%

**Priority 2 (Medium)**:
- ✅ Peak memory < 8GB
- ✅ I/O wait < 20%
- ✅ Generation time < 60 minutes

---

## 🚀 Implementation Timeline

### Week 1: Emergency Stabilization
- **Day 1**: P0.1-P0.4 (swap, workers, cleanup, restart)
- **Day 2-3**: Monitor and validate stability
- **Day 4**: P1.1-P1.2 (matplotlib, verify filter)
- **Day 5**: P1.3-P1.4 (cache age, monitoring)
- **Day 6-7**: Test full generation cycles

### Week 2: Optimization
- **Day 8**: P2.1 (batch mode)
- **Day 9**: P2.2 (station overlays)
- **Day 10**: P2.3 (connection pooling)
- **Day 11**: P2.4 (pre-caching)
- **Day 12**: P2.5 (xarray optimization)
- **Day 13-14**: Testing and validation

### Week 3+: Polish (Optional)
- **Day 15+**: P3 items as needed
- Ongoing: Monitor and tune based on real-world performance

---

## 📋 Quick Reference Checklist

### Emergency Actions (Do Now)
- [ ] Add 4GB swap space
- [ ] Change `_GLOBAL_POOL_SIZE` to 2
- [ ] Add `gc.collect()` between model generations
- [ ] Restart scheduler service
- [ ] Monitor first full run

### High Priority (This Week)
- [ ] Add `plt.close(fig)` in map_generator.py
- [ ] Add download size logging
- [ ] Verify NOMADS filtering working
- [ ] Increase cache max age to 6 hours
- [ ] Install and add psutil memory monitoring
- [ ] Test full generation cycle

### Medium Priority (Next Week)
- [ ] Switch to batch mode (progressive=False)
- [ ] Optimize station overlays
- [ ] Add connection pooling
- [ ] Implement pre-caching
- [ ] Optimize xarray memory usage

### Optional (Later)
- [ ] Implement Dask lazy loading
- [ ] Cache station grid indices
- [ ] Add disk space monitoring

---

## 🆘 Emergency Recovery

If system becomes unresponsive during generation:

```bash
# 1. Check if OOM killer activated
dmesg | tail -50

# 2. Kill stuck processes
sudo pkill -9 -f "python.*scheduler"

# 3. Restart services
sudo systemctl restart twf-models-scheduler

# 4. If persistent issues, reduce workers to 1
# Edit /opt/twf_models/backend/app/scheduler.py
# Set _GLOBAL_POOL_SIZE = 1

# 5. Consider disabling one model temporarily
# Edit model_registry.py, set AIGFS enabled=False
```

---

## 📞 Support Resources

- **Project Docs**: `/Users/brianaustin/twf_models/docs/`
- **Logs**: `journalctl -u twf-models-scheduler -f`
- **VPS Monitoring**: `htop`, `iotop`, `iftop`
- **Python Profiling**: Consider adding `memory_profiler` for detailed analysis

---

## 📝 Change Log

| Date | Change | Impact |
|------|--------|--------|
| 2026-01-28 | Initial performance plan created | Baseline |
| TBD | Priority 0 implemented | Critical stability fixes |
| TBD | Priority 1 implemented | High impact optimizations |
| TBD | Priority 2 implemented | Medium impact optimizations |

---

**Next Action**: Implement Priority 0 items immediately to stabilize system.
