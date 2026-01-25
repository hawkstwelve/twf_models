# HTTP Caching Strategy

## Overview

The TWF Models API implements comprehensive HTTP caching to improve performance, reduce bandwidth usage, and provide a better user experience.

## Caching Configuration

All caching settings can be configured via environment variables or in `backend/app/config.py`:

```python
# HTTP Caching
cache_images_seconds: int = 604800  # 7 days - images are immutable
cache_maps_list_seconds: int = 300  # 5 minutes - list changes as new maps generate
cache_runs_list_seconds: int = 300  # 5 minutes - runs list changes as new runs generate
enable_etag: bool = True  # Enable ETag support for conditional requests
```

### Environment Variables

```bash
# .env file
CACHE_IMAGES_SECONDS=604800        # 7 days (default)
CACHE_MAPS_LIST_SECONDS=300        # 5 minutes (default)
CACHE_RUNS_LIST_SECONDS=300        # 5 minutes (default)
ENABLE_ETAG=true                   # Enable ETags (default)
```

## Caching Behavior by Endpoint

### 1. `/api/images/{filename}` - Map Images

**Cache Duration:** 7 days (604,800 seconds)

**Strategy:** Immutable caching with ETag support

**Headers:**
```
Cache-Control: public, max-age=604800, immutable
ETag: "1706198400.0-1234567"
Expires: Sat, 01 Feb 2026 12:00:00 GMT
```

**Why 7 days?**
- Map images are immutable once generated (filename includes timestamp)
- Historical weather data doesn't change
- Users may revisit older forecast runs
- Reduces bandwidth and server load significantly

**ETag Support:**
- ETag is generated from file modification time + size
- Browsers send `If-None-Match` header on subsequent requests
- Server returns `304 Not Modified` if content unchanged
- Saves bandwidth even when cache expires

### 2. `/api/maps` - Maps List

**Cache Duration:** 5 minutes (300 seconds)

**Strategy:** Short-term caching with public cache

**Headers:**
```
Cache-Control: public, max-age=300
```

**Why 5 minutes?**
- List changes every 6 hours when new GFS run is processed
- 5 minutes balances freshness with performance
- Multiple users can share cached responses (public)
- During active generation, users see updates within 5 minutes

### 3. `/api/runs` - Model Runs List

**Cache Duration:** 5 minutes (300 seconds)

**Strategy:** Short-term caching with public cache

**Headers:**
```
Cache-Control: public, max-age=300
```

**Why 5 minutes?**
- Runs list updates every 6 hours (new GFS run)
- Same rationale as maps list
- Provides consistent experience across API

### 4. `/api/maps/{map_id}` - Single Map Metadata

**Cache Duration:** None (no explicit caching)

**Strategy:** Default browser caching

**Note:** This endpoint returns metadata only, not the image itself. Could add caching if needed.

## Performance Benefits

### Bandwidth Savings

For a typical user session viewing 13 forecast hours × 6 variables = 78 maps:

**Without Caching:**
- 78 maps × ~1.5 MB average = 117 MB per session
- 100 users/day = 11.7 GB/day
- 351 GB/month

**With Caching:**
- First load: 117 MB
- Subsequent loads: ~0 MB (304 responses)
- **Savings: ~90% bandwidth reduction**

### Server Load Reduction

- Image requests served from browser cache: ~90% reduction
- API list requests: ~80% reduction (5-minute cache)
- Server CPU/memory usage: Minimal impact
- Disk I/O: Significant reduction

### User Experience

- **Instant page loads** after first visit
- **Smooth navigation** between forecast hours
- **Responsive interface** when switching variables
- **Reduced mobile data usage** (important for weather apps)

## CDN Compatibility

The caching headers are CDN-friendly and work well with:

- Cloudflare (free tier)
- AWS CloudFront
- DigitalOcean Spaces CDN
- Fastly
- Any RFC-compliant CDN

**Recommendation:** Add Cloudflare in front of the API for:
- Global caching
- DDoS protection
- SSL termination
- Additional performance boost

## Testing Cache Behavior

### Test Image Caching

```bash
# First request - returns full image
curl -I https://api.sodakweather.com/api/images/gfs_20260125_00_temp_0.png

# Response includes:
# Cache-Control: public, max-age=604800, immutable
# ETag: "1706198400.0-1234567"

# Second request with ETag - returns 304 Not Modified
curl -I https://api.sodakweather.com/api/images/gfs_20260125_00_temp_0.png \
  -H 'If-None-Match: "1706198400.0-1234567"'

# Response:
# HTTP/1.1 304 Not Modified
```

### Test List Caching

```bash
# Request maps list
curl -I https://api.sodakweather.com/api/maps

# Response includes:
# Cache-Control: public, max-age=300

# Repeat within 5 minutes - served from cache
curl -I https://api.sodakweather.com/api/maps
```

### Browser DevTools

1. Open Chrome/Firefox DevTools (F12)
2. Go to Network tab
3. Load a map page
4. Check "Size" column:
   - First load: "1.5 MB" (full size)
   - Reload: "(disk cache)" or "304"
5. Check "Time" column:
   - Cached requests: <10ms

## Troubleshooting

### Cache Not Working

**Issue:** Images re-download every time

**Solutions:**
1. Check browser cache is enabled (not in incognito)
2. Verify headers in DevTools Network tab
3. Check server logs for cache-related errors
4. Ensure `enable_etag` is `true` in config

### Stale Data

**Issue:** Old maps showing after new generation

**Solutions:**
1. Reduce `cache_maps_list_seconds` (e.g., to 60 seconds)
2. Implement cache invalidation (future enhancement)
3. Add version query parameter to force refresh

### 304 Not Being Returned

**Issue:** Server always returns 200 with full content

**Solutions:**
1. Verify `enable_etag=true` in config
2. Check `If-None-Match` header is sent by client
3. Ensure file hasn't actually changed (check mtime/size)

## Future Enhancements

### 1. Cache Warming

Pre-generate and cache maps before user requests:

```python
# Warm cache after generation
async def warm_cache():
    for var in variables:
        for hour in forecast_hours:
            # Generate map image
            # Store in CDN/cache
```

### 2. Smart Cache Invalidation

Invalidate specific maps when new run completes:

```python
# After new run generation
async def invalidate_old_run(old_run_time):
    # Send cache purge to CDN
    # Update metadata
```

### 3. Progressive Image Loading

Serve low-resolution placeholder while high-res loads:

```python
# Generate thumbnail
# Serve 100KB thumbnail first
# Load 1.5MB full image in background
```

### 4. Service Worker Caching

Implement offline-first strategy in frontend:

```javascript
// Cache maps for offline viewing
self.addEventListener('fetch', (event) => {
  event.respondWith(
    caches.match(event.request)
      .then(response => response || fetch(event.request))
  );
});
```

## Monitoring

### Key Metrics to Track

1. **Cache Hit Rate**
   - Target: >80% for images
   - Target: >60% for API lists

2. **Bandwidth Savings**
   - Track 304 responses vs 200
   - Monitor total bytes transferred

3. **Response Times**
   - Cached: <50ms
   - Uncached: <500ms

4. **Storage Usage**
   - Browser cache: ~100-200 MB per user
   - Server disk: ~5-10 GB for 7 days of maps

### Logging

Add cache-related logging:

```python
logger.info(f"Cache HIT: {filename} (ETag match)")
logger.info(f"Cache MISS: {filename} (new/changed)")
```

## Best Practices

1. ✅ **Use immutable for static assets** (images with timestamp)
2. ✅ **Use short TTL for dynamic content** (maps list)
3. ✅ **Implement ETags for validation** (reduces bandwidth)
4. ✅ **Set Expires header** (HTTP/1.0 compatibility)
5. ✅ **Use public cache** (allow CDN caching)
6. ✅ **Test cache behavior** (verify with curl/DevTools)

## References

- [MDN: HTTP Caching](https://developer.mozilla.org/en-US/docs/Web/HTTP/Caching)
- [RFC 7234: HTTP Caching](https://tools.ietf.org/html/rfc7234)
- [Best Practices for Cache Control](https://www.keycdn.com/blog/http-cache-headers)
