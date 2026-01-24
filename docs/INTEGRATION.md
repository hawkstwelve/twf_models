# Integration with theweatherforums.com

## Phased Deployment Strategy

### Overview
This project uses a 3-phase deployment approach to ensure stability before public launch:

1. **Phase 1 (COMPLETED)**: Backend API on Digital Ocean droplet ✅
2. **Phase 2 (NEXT)**: Complete ALL development and testing on sodakweather.com
3. **Phase 3 (FINAL)**: Launch production-ready system on theweatherforums.com/models

**CRITICAL**: theweatherforums.com will receive the COMPLETE, POLISHED product. All enhancements (higher resolution, 15+ map types, extended hours, interactive UI) must be finished and tested on sodakweather.com first.

---

### Phase 1: Backend Only ✅ READY TO DEPLOY

**What**: Deploy backend API and automated map generation to Digital Ocean droplet  
**When**: NOW - You're ready for this phase  
**Where**: Backend droplet (API accessible via IP:8000)  
**Purpose**: Get backend stable before building frontend

**Steps**: See [DEPLOYMENT_NOTES.md](DEPLOYMENT_NOTES.md) for detailed instructions

**Success Criteria**:
- API responds to health checks
- Maps generated every 6 hours automatically  
- System stable for 1-2 weeks

---

### Phase 2: Complete Development & Testing on sodakweather.com

**What**: Complete ALL features and enhancements, deploy and test on sodakweather.com  
**When**: After backend stable 1-2 weeks  
**Where**: models.sodakweather.com (or sodakweather.com/models)  
**Purpose**: Build, enhance, and thoroughly test the COMPLETE production system before public launch

**This Phase Includes**:
- ✅ Backend enhancements (0.25° resolution, 15+ map types, extended hours)
- ✅ Interactive frontend development (slider, animation, TropicalTidbits-style)
- ✅ Comprehensive testing with beta users
- ✅ Iterate and polish based on feedback
- ✅ Performance optimization
- ✅ Bug fixes and refinement

**Why develop on sodakweather.com?**
- ✅ Develop and test without forum dependencies
- ✅ Iterate quickly without affecting forum users
- ✅ Easy rollback during development
- ✅ Verify performance with real beta users
- ✅ No impact on forum if issues arise during development
- ✅ Proves system is production-ready before forum launch

**Configuration Example**:
```nginx
# Nginx config on sodakweather.com server
server {
    listen 80;
    server_name models.sodakweather.com;
    
    location / {
        root /var/www/sodakweather-models;
        index index.html;
    }
    
    location /api {
        proxy_pass http://YOUR_MODELS_DROPLET_IP:8000/api;
        # ... proxy headers
    }
}
```

**Success Criteria**:
- Frontend loads quickly (< 2 seconds)
- Slider/animation works smoothly
- Responsive on mobile/tablet/desktop
- Positive feedback from beta testers
- Stable for 1-2 weeks

---

### Phase 3: Production Launch on theweatherforums.com

**What**: Launch complete, production-ready system on theweatherforums.com/models  
**When**: After complete system tested successfully on sodakweather.com (6-8+ weeks)  
**Where**: theweatherforums.com/models (FINAL PRODUCTION)  
**Purpose**: Public launch of polished, feature-complete product to forum users

**Prerequisites (ALL Must Be Complete)**:
- ✅ All 15+ map types working perfectly
- ✅ Interactive slider with 40+ forecast hours per variable
- ✅ 0.25° resolution (high quality maps)
- ✅ System thoroughly tested on sodakweather.com for 2-4 weeks
- ✅ Beta user feedback incorporated
- ✅ No known major bugs
- ✅ Performance verified under load
- User feedback incorporated
- System stable for 2-4 weeks total
- Ready to add /models link to forum navigation

**Migration is Simple**:
1. Copy tested frontend files from sodakweather to forum droplet
2. Update nginx config (same as sodakweather, different domain)
3. Test on production domain
4. Add link to forum navigation
5. Announce to users

**Benefits of This Approach**:
- ✅ Reduced risk (tested on sodakweather first)
- ✅ Known working configuration
- ✅ Smooth migration (same code, different domain)
- ✅ Can reference sodakweather if issues arise

---

## Frontend Integration Options (Phase 3 - Production)

### Option 1: Iframe Embed (Simplest)
Embed the maps directly in your forum pages using iframes:

```html
<iframe 
    src="https://your-droplet-ip/api/maps" 
    width="100%" 
    height="600px"
    frameborder="0">
</iframe>
```

### Option 2: Direct Image Links
Link directly to map images in your forum posts:

```html
<img src="https://your-droplet-ip/api/images/gfs_20250123_00_temp_2m_0.png" 
     alt="GFS Temperature Forecast" />
```

### Option 3: Custom Frontend (Recommended)
Build a custom frontend page at `theweatherforums.com/models` that:
- Fetches map list from API
- Displays maps in a gallery
- Allows filtering by model, variable, forecast hour
- Shows map metadata

## CORS Configuration

The API is configured to allow requests from `theweatherforums.com`. Make sure:
1. Your domain matches exactly in `CORS_ORIGINS`
2. If using subdomain, include both `https://theweatherforums.com` and `https://www.theweatherforums.com`

## Nginx Reverse Proxy Setup

If you want to serve the API through your existing domain:

```nginx
# /etc/nginx/sites-available/twf-models
server {
    listen 80;
    server_name api.theweatherforums.com;  # or models.theweatherforums.com

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

## Authentication (Optional)

If you want to restrict access:
1. Add API key authentication to admin endpoints
2. Use forum session tokens for user authentication
3. Implement rate limiting

## Example Frontend Code

### Simple HTML/JavaScript

```html
<!DOCTYPE html>
<html>
<head>
    <title>TWF Weather Models</title>
    <style>
        .map-gallery {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
            gap: 20px;
            padding: 20px;
        }
        .map-card {
            border: 1px solid #ddd;
            border-radius: 8px;
            overflow: hidden;
        }
        .map-card img {
            width: 100%;
            height: auto;
        }
        .map-info {
            padding: 10px;
            background: #f5f5f5;
        }
    </style>
</head>
<body>
    <h1>TWF Weather Models</h1>
    <div id="filters">
        <select id="model-filter">
            <option value="">All Models</option>
            <option value="GFS">GFS</option>
        </select>
        <select id="variable-filter">
            <option value="">All Variables</option>
            <option value="temperature_2m">Temperature</option>
            <option value="precipitation">Precipitation</option>
            <option value="wind_speed_10m">Wind Speed</option>
        </select>
    </div>
    <div id="map-gallery" class="map-gallery"></div>

    <script>
        const API_BASE = 'https://your-droplet-ip/api';
        
        async function loadMaps() {
            const model = document.getElementById('model-filter').value;
            const variable = document.getElementById('variable-filter').value;
            
            const params = new URLSearchParams();
            if (model) params.append('model', model);
            if (variable) params.append('variable', variable);
            
            const response = await fetch(`${API_BASE}/maps?${params}`);
            const data = await response.json();
            
            const gallery = document.getElementById('map-gallery');
            gallery.innerHTML = '';
            
            data.maps.forEach(map => {
                const card = document.createElement('div');
                card.className = 'map-card';
                card.innerHTML = `
                    <img src="${API_BASE}${map.image_url}" alt="${map.variable}">
                    <div class="map-info">
                        <h3>${map.variable.replace('_', ' ')}</h3>
                        <p>Model: ${map.model}</p>
                        <p>Forecast: +${map.forecast_hour}h</p>
                        <p>Run: ${map.run_time}</p>
                    </div>
                `;
                gallery.appendChild(card);
            });
        }
        
        document.getElementById('model-filter').addEventListener('change', loadMaps);
        document.getElementById('variable-filter').addEventListener('change', loadMaps);
        
        loadMaps();
    </script>
</body>
</html>
```

## WordPress Integration (if your forum uses WordPress)

If theweatherforums.com uses WordPress, you can:
1. Create a custom page template
2. Use WordPress REST API to fetch map data
3. Embed maps using shortcodes
4. Use WordPress caching for performance

---

## Progressive Loading Implementation

### Overview
Maps should appear dynamically as they're generated rather than all at once. This provides a better user experience, similar to TropicalTidbits.com behavior.

**Current Backend Behavior** (already implemented):
- Progressive generation: f000 maps generated first (~1 min), then f024, f048, f072
- Maps saved immediately after generation
- API serves maps as soon as they're available

**Frontend Implementation Strategy**:
Frontend polls for new maps and updates the UI dynamically without page refresh.

---

### Backend Components (To Be Implemented)

#### 1. manifest.json Generation
**Location**: `backend/app/services/map_generator.py`

After each map is saved, update `manifest.json`:

```python
# Pseudo-code - to be implemented in Phase 2
def _update_manifest(self, maps_completed, total_maps, available_maps):
    manifest = {
        "run_time": "2026-01-24T00:00:00Z",
        "generated_at": datetime.utcnow().isoformat(),
        "status": "generating" if maps_completed < total_maps else "complete",
        "progress": {
            "completed": maps_completed,
            "total": total_maps,
            "percentage": (maps_completed / total_maps) * 100,
            "current_hour": 24  # Which forecast hour is currently generating
        },
        "forecast_hours_available": [0, 24],  # Which hours are complete
        "maps": [
            {
                "id": "gfs_20260124_00_temp_0",
                "variable": "temp",
                "forecast_hour": 0,
                "image_url": "/api/images/gfs_20260124_00_temp_0.png",
                "created_at": "2026-01-24T00:01:23Z"
            },
            # ... more maps
        ]
    }
    
    with open("/opt/twf_models/images/manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)
```

**Why manifest.json?**
- Lightweight (~2-5KB vs full API call)
- Can be served as static file (faster, cacheable)
- No authentication needed
- Easy to parse in frontend JavaScript

#### 2. Generation Status API Endpoint
**Location**: `backend/app/api/routes.py`

```python
@router.get("/api/generation/status")
def get_generation_status():
    """
    Returns real-time status of current generation run.
    Provides more detail than manifest.json.
    """
    return {
        "in_progress": True,
        "run_time": "2026-01-24T00:00:00Z",
        "started_at": "2026-01-24T00:00:15Z",
        "elapsed_seconds": 87,
        "estimated_remaining_seconds": 153,
        "progress": {
            "completed": 8,
            "total": 16,
            "percentage": 50.0,
            "current_forecast_hour": 24,
            "current_variable": "precip"
        },
        "forecast_hours": {
            "0": {"status": "complete", "maps_count": 4},
            "24": {"status": "generating", "maps_count": 2},
            "48": {"status": "pending", "maps_count": 0},
            "72": {"status": "pending", "maps_count": 0}
        },
        "last_completed_map": {
            "variable": "wind_speed",
            "forecast_hour": 24,
            "completed_at": "2026-01-24T00:01:42Z"
        }
    }
```

---

### Frontend Implementation (To Be Built in Phase 2)

#### 1. Polling Strategy

**manifest.json Approach** (Recommended - lightweight):
```javascript
class MapMonitor {
    constructor(apiBaseUrl) {
        this.apiBaseUrl = apiBaseUrl;
        this.pollInterval = 60000; // 60 seconds
        this.knownMaps = new Set();
        this.isPolling = false;
    }
    
    async startMonitoring() {
        this.isPolling = true;
        while (this.isPolling) {
            await this.checkForNewMaps();
            await this.sleep(this.pollInterval);
        }
    }
    
    async checkForNewMaps() {
        try {
            const response = await fetch(`${this.apiBaseUrl}/images/manifest.json`);
            const manifest = await response.json();
            
            // Check if generation is in progress
            if (manifest.status === "generating") {
                this.updateProgressBar(manifest.progress);
                
                // Check for new maps
                const newMaps = manifest.maps.filter(map => 
                    !this.knownMaps.has(map.id)
                );
                
                if (newMaps.length > 0) {
                    this.addMapsToUI(newMaps);
                    newMaps.forEach(map => this.knownMaps.add(map.id));
                }
            } else if (manifest.status === "complete") {
                this.updateProgressBar({ percentage: 100 });
                this.isPolling = false; // Stop polling
            }
        } catch (error) {
            console.error("Error checking for new maps:", error);
        }
    }
    
    updateProgressBar(progress) {
        const bar = document.getElementById('progress-bar');
        const text = document.getElementById('progress-text');
        
        bar.style.width = `${progress.percentage}%`;
        text.textContent = `Generating maps... ${progress.completed}/${progress.total} complete`;
    }
    
    addMapsToUI(newMaps) {
        // Group by forecast hour
        const hourGroups = this.groupByForecastHour(newMaps);
        
        // Update slider with new forecast hours
        Object.keys(hourGroups).forEach(hour => {
            this.addForecastHourToSlider(hour, hourGroups[hour]);
        });
    }
    
    sleep(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }
}

// Usage
const monitor = new MapMonitor('http://174.138.84.70:8000');
monitor.startMonitoring();
```

#### 2. Progressive UI Updates

**HTML Structure**:
```html
<div class="map-viewer">
    <!-- Progress indicator (shown during generation) -->
    <div id="generation-progress" class="progress-container">
        <div class="progress-bar" id="progress-bar"></div>
        <div class="progress-text" id="progress-text">
            Generating maps... 0/16 complete
        </div>
    </div>
    
    <!-- Map slider/viewer -->
    <div class="map-display">
        <img id="current-map" src="" alt="Weather Map">
    </div>
    
    <!-- Forecast hour slider -->
    <div class="forecast-slider">
        <button class="hour-button" data-hour="0">Now</button>
        <!-- Additional hour buttons appear as maps become available -->
    </div>
    
    <!-- Variable selector -->
    <div class="variable-selector">
        <button data-variable="temp">Temperature</button>
        <button data-variable="precip">Precipitation</button>
        <button data-variable="wind_speed">Wind Speed</button>
        <button data-variable="precip_type">Precip Type</button>
    </div>
</div>
```

**CSS (Progressive Loading States)**:
```css
.hour-button {
    opacity: 0.3;
    cursor: not-allowed;
    transition: opacity 0.3s ease;
}

.hour-button.available {
    opacity: 1.0;
    cursor: pointer;
    animation: fadeIn 0.5s ease;
}

@keyframes fadeIn {
    from { opacity: 0.3; transform: scale(0.95); }
    to { opacity: 1.0; transform: scale(1.0); }
}

.progress-container {
    margin: 20px 0;
    transition: opacity 0.5s ease;
}

.progress-container.hidden {
    opacity: 0;
    height: 0;
    overflow: hidden;
}
```

#### 3. User Experience Flow

**Timeline (User Perspective)**:
```
00:00 UTC - User visits page
  ↓
  Display: "Loading latest forecast..."
  Backend: Starting generation
  
00:01 UTC - First maps available (f000)
  ↓
  Display: Progress bar "4/16 complete (25%)"
  Slider: f000 button now enabled and highlighted
  User: Can immediately view f000 maps
  
00:02 UTC - f024 maps available
  ↓
  Display: Progress bar "8/16 complete (50%)"
  Slider: f024 button appears and animates in
  User: Can now toggle between f000 and f024
  
00:03 UTC - f048 maps available
  ↓
  Display: Progress bar "12/16 complete (75%)"
  Slider: f048 button appears
  
00:04 UTC - f072 maps complete
  ↓
  Display: Progress bar "16/16 complete (100%)"
  Progress bar fades out after 2 seconds
  User: Full forecast available, can animate through all hours
```

---

### Benefits of This Approach

✅ **Keeps Current Backend** - No rewrite needed  
✅ **Lightweight** - manifest.json is small (~2-5KB)  
✅ **Fast** - Static file served by nginx  
✅ **Scalable** - Can add more complex API endpoint later  
✅ **Flexible** - Frontend can poll manifest OR use API  
✅ **User-Friendly** - Maps appear progressively, not all at once  
✅ **Professional** - Matches TropicalTidbits.com UX  

---

### Implementation Priority

**Phase 2A: Backend Additions** (1-2 hours)
1. Add manifest.json generation to `map_generator.py`
2. Add `/api/generation/status` endpoint to `routes.py`
3. Test with current 4-variable, 4-hour setup

**Phase 2B: Frontend Development** (3-5 days)
1. Build polling mechanism
2. Create responsive UI with slider
3. Implement progressive loading animation
4. Add loading indicators
5. Test across browsers/devices

**Phase 2C: Testing on sodakweather.com** (1-2 weeks)
1. Deploy to sodakweather.com
2. Beta test with select users
3. Gather feedback
4. Polish and optimize

---

### Alternative: Server-Sent Events (SSE)

For real-time updates without polling:

```python
# Backend (routes.py)
@router.get("/api/generation/stream")
async def generation_stream():
    async def event_generator():
        while generation_in_progress:
            yield f"data: {json.dumps(get_current_status())}\n\n"
            await asyncio.sleep(5)
    
    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

```javascript
// Frontend
const eventSource = new EventSource('/api/generation/stream');
eventSource.onmessage = (event) => {
    const status = JSON.parse(event.data);
    updateUI(status);
};
```

**Trade-offs**:
- ✅ True real-time (no 60s delay)
- ✅ Server pushes updates
- ❌ More complex backend
- ❌ Keeps connection open
- ❌ Overkill for 60s polling

**Recommendation**: Start with manifest.json polling, add SSE later if needed.
