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

---

## Multi-Run Selection & Comparison (Backend ✅ Implemented)

### Overview
Users can view and compare the last 4 GFS model runs (24 hours of data). This allows them to:
- See how forecasts have evolved over time
- Check forecast consistency between runs
- Identify when models are "locked in" vs uncertain
- Compare current run with previous runs

**Backend Status**: ✅ Fully implemented and ready  
**Frontend Status**: ⏳ To be built in Phase 2

---

### Backend API (Already Implemented)

#### 1. Get Available Runs
```
GET /api/runs
Query Parameters:
  - model: string (default: "GFS") - Filter by model

Response: {
  "runs": [
    {
      "run_time": "2026-01-24T00:00:00Z",
      "run_time_formatted": "00Z Jan 24",
      "date": "2026-01-24",
      "hour": "00Z",
      "is_latest": true,
      "maps_count": 16,
      "generated_at": "2026-01-24T03:35:12Z",
      "age_hours": 6.5
    },
    {
      "run_time": "2026-01-23T18:00:00Z",
      "run_time_formatted": "18Z Jan 23",
      "date": "2026-01-23",
      "hour": "18Z",
      "is_latest": false,
      "maps_count": 16,
      "generated_at": "2026-01-23T21:35:45Z",
      "age_hours": 12.5
    }
    // ... up to 4 most recent runs
  ],
  "total_runs": 4
}
```

#### 2. Filter Maps by Run
```
GET /api/maps?run_time=2026-01-24T00:00:00Z
Query Parameters:
  - run_time: string (ISO format) - Only return maps from this run
  - variable: string (optional) - Further filter by variable
  - forecast_hour: int (optional) - Further filter by forecast hour

Response: {
  "maps": [
    // Only maps from the specified run
  ]
}
```

#### 3. Automatic Cleanup
- Backend automatically keeps last 4 runs (24 hours)
- Older runs are deleted after each successful generation
- Prevents unlimited disk space growth
- ~22 MB storage for 4 complete runs

---

### Frontend Implementation (To Be Built in Phase 2)

#### HTML Structure

```html
<div class="map-viewer-container">
    <!-- Run Selector -->
    <div class="controls-panel">
        <div class="control-group">
            <label for="run-selector">Model Run:</label>
            <select id="run-selector" class="run-dropdown">
                <!-- Populated dynamically from /api/runs -->
            </select>
        </div>
        
        <div class="control-group">
            <label for="variable-selector">Variable:</label>
            <select id="variable-selector">
                <option value="temp">Temperature</option>
                <option value="precip">Precipitation</option>
                <option value="wind_speed">Wind Speed</option>
                <option value="precip_type">Precip Type</option>
            </select>
        </div>
        
        <div class="control-group">
            <label>Forecast Hour:</label>
            <div class="hour-slider">
                <button data-hour="0">Now</button>
                <button data-hour="24">24h</button>
                <button data-hour="48">48h</button>
                <button data-hour="72">72h</button>
            </div>
        </div>
        
        <!-- Comparison Toggle -->
        <div class="control-group">
            <label>
                <input type="checkbox" id="comparison-mode"> 
                Compare with previous run
            </label>
        </div>
    </div>
    
    <!-- Map Display -->
    <div class="map-display-area">
        <!-- Single Map View -->
        <div id="single-map-view" class="map-container">
            <img id="current-map" src="" alt="Weather Map">
            <div class="map-metadata">
                <span id="map-run-label">00Z Jan 24</span>
                <span id="map-valid-time">Valid: Jan 24 6:00 PM CST</span>
            </div>
        </div>
        
        <!-- Comparison View (hidden by default) -->
        <div id="comparison-view" class="comparison-container" style="display: none;">
            <div class="map-container">
                <img id="current-run-map" src="" alt="Current Run">
                <div class="map-label">Current: <span id="current-label"></span></div>
            </div>
            <div class="map-container">
                <img id="previous-run-map" src="" alt="Previous Run">
                <div class="map-label">Previous: <span id="previous-label"></span></div>
            </div>
        </div>
    </div>
</div>
```

#### JavaScript Implementation

```javascript
class MapViewer {
    constructor(apiBaseUrl) {
        this.apiBaseUrl = apiBaseUrl;
        this.availableRuns = [];
        this.currentRun = null;
        this.currentVariable = 'temp';
        this.currentForecastHour = 0;
        this.comparisonMode = false;
    }
    
    async init() {
        // Fetch available runs
        await this.loadAvailableRuns();
        
        // Setup event listeners
        this.setupEventListeners();
        
        // Load initial map
        await this.loadMap();
    }
    
    async loadAvailableRuns() {
        try {
            const response = await fetch(`${this.apiBaseUrl}/api/runs`);
            const data = await response.json();
            
            this.availableRuns = data.runs;
            this.currentRun = this.availableRuns[0]; // Latest run
            
            // Populate dropdown
            this.populateRunDropdown();
        } catch (error) {
            console.error('Failed to load runs:', error);
        }
    }
    
    populateRunDropdown() {
        const selector = document.getElementById('run-selector');
        selector.innerHTML = '';
        
        this.availableRuns.forEach((run, index) => {
            const option = document.createElement('option');
            option.value = run.run_time;
            
            // Format: "00Z Jan 24 (Latest)" or "18Z Jan 23 (6h ago)"
            let label = run.run_time_formatted;
            if (run.is_latest) {
                label += ' ⭐ Latest';
            } else {
                label += ` (${Math.round(run.age_hours)}h ago)`;
            }
            
            option.textContent = label;
            option.selected = (index === 0);
            selector.appendChild(option);
        });
    }
    
    setupEventListeners() {
        // Run selector
        document.getElementById('run-selector').addEventListener('change', (e) => {
            const selectedRun = this.availableRuns.find(r => r.run_time === e.target.value);
            if (selectedRun) {
                this.currentRun = selectedRun;
                this.loadMap();
            }
        });
        
        // Variable selector
        document.getElementById('variable-selector').addEventListener('change', (e) => {
            this.currentVariable = e.target.value;
            this.loadMap();
        });
        
        // Forecast hour buttons
        document.querySelectorAll('.hour-slider button').forEach(btn => {
            btn.addEventListener('click', (e) => {
                this.currentForecastHour = parseInt(e.target.dataset.hour);
                this.loadMap();
            });
        });
        
        // Comparison mode toggle
        document.getElementById('comparison-mode').addEventListener('change', (e) => {
            this.comparisonMode = e.target.checked;
            this.toggleComparisonView();
        });
    }
    
    async loadMap() {
        if (!this.currentRun) return;
        
        if (this.comparisonMode) {
            await this.loadComparisonMaps();
        } else {
            await this.loadSingleMap();
        }
    }
    
    async loadSingleMap() {
        try {
            // Fetch maps for current run, variable, and forecast hour
            const params = new URLSearchParams({
                run_time: this.currentRun.run_time,
                variable: this.currentVariable,
                forecast_hour: this.currentForecastHour
            });
            
            const response = await fetch(`${this.apiBaseUrl}/api/maps?${params}`);
            const data = await response.json();
            
            if (data.maps.length > 0) {
                const map = data.maps[0];
                document.getElementById('current-map').src = `${this.apiBaseUrl}${map.image_url}`;
                document.getElementById('map-run-label').textContent = this.currentRun.run_time_formatted;
                
                // Calculate valid time
                const validTime = this.calculateValidTime(this.currentRun.run_time, this.currentForecastHour);
                document.getElementById('map-valid-time').textContent = `Valid: ${validTime}`;
            }
        } catch (error) {
            console.error('Failed to load map:', error);
        }
    }
    
    async loadComparisonMaps() {
        // Load current run map
        await this.loadMapForRun(this.currentRun, 'current-run-map', 'current-label');
        
        // Load previous run map (if available)
        if (this.availableRuns.length > 1) {
            const previousRun = this.availableRuns[1];
            await this.loadMapForRun(previousRun, 'previous-run-map', 'previous-label');
        }
    }
    
    async loadMapForRun(run, imgElementId, labelElementId) {
        try {
            const params = new URLSearchParams({
                run_time: run.run_time,
                variable: this.currentVariable,
                forecast_hour: this.currentForecastHour
            });
            
            const response = await fetch(`${this.apiBaseUrl}/api/maps?${params}`);
            const data = await response.json();
            
            if (data.maps.length > 0) {
                const map = data.maps[0];
                document.getElementById(imgElementId).src = `${this.apiBaseUrl}${map.image_url}`;
                document.getElementById(labelElementId).textContent = run.run_time_formatted;
            }
        } catch (error) {
            console.error(`Failed to load map for ${run.run_time_formatted}:`, error);
        }
    }
    
    toggleComparisonView() {
        const singleView = document.getElementById('single-map-view');
        const comparisonView = document.getElementById('comparison-view');
        
        if (this.comparisonMode) {
            singleView.style.display = 'none';
            comparisonView.style.display = 'flex';
            this.loadComparisonMaps();
        } else {
            singleView.style.display = 'block';
            comparisonView.style.display = 'none';
            this.loadSingleMap();
        }
    }
    
    calculateValidTime(runTime, forecastHour) {
        // Convert ISO run time to Date
        const runDate = new Date(runTime);
        runDate.setHours(runDate.getHours() + forecastHour);
        
        // Format for display
        return runDate.toLocaleString('en-US', {
            month: 'short',
            day: 'numeric',
            hour: 'numeric',
            minute: '2-digit',
            timeZoneName: 'short'
        });
    }
}

// Initialize when page loads
document.addEventListener('DOMContentLoaded', () => {
    const viewer = new MapViewer('http://174.138.84.70:8000');
    viewer.init();
});
```

#### CSS Styling

```css
.map-viewer-container {
    max-width: 1400px;
    margin: 0 auto;
    padding: 20px;
}

.controls-panel {
    display: flex;
    gap: 20px;
    margin-bottom: 20px;
    padding: 15px;
    background: #f5f5f5;
    border-radius: 8px;
    flex-wrap: wrap;
}

.control-group {
    display: flex;
    flex-direction: column;
    gap: 5px;
}

.control-group label {
    font-weight: 600;
    font-size: 14px;
}

.run-dropdown,
#variable-selector {
    padding: 8px 12px;
    border: 1px solid #ddd;
    border-radius: 4px;
    font-size: 14px;
    min-width: 200px;
}

.hour-slider {
    display: flex;
    gap: 10px;
}

.hour-slider button {
    padding: 8px 16px;
    border: 1px solid #ddd;
    background: white;
    border-radius: 4px;
    cursor: pointer;
    transition: all 0.2s;
}

.hour-slider button:hover {
    background: #e0e0e0;
}

.hour-slider button.active {
    background: #2196F3;
    color: white;
    border-color: #2196F3;
}

.map-display-area {
    background: white;
    border: 1px solid #ddd;
    border-radius: 8px;
    padding: 20px;
}

.map-container {
    position: relative;
    width: 100%;
}

.map-container img {
    width: 100%;
    height: auto;
    border-radius: 4px;
}

.map-metadata {
    margin-top: 10px;
    display: flex;
    justify-content: space-between;
    font-size: 14px;
    color: #666;
}

.comparison-container {
    display: flex;
    gap: 20px;
}

.comparison-container .map-container {
    flex: 1;
}

.map-label {
    margin-top: 10px;
    font-weight: 600;
    font-size: 14px;
    text-align: center;
}

/* Mobile responsive */
@media (max-width: 768px) {
    .controls-panel {
        flex-direction: column;
    }
    
    .comparison-container {
        flex-direction: column;
    }
}
```

---

### User Experience Flow

**1. Page Load:**
```
→ Fetch /api/runs
→ Populate dropdown with last 4 runs
→ Select latest run by default
→ Load maps for latest run
```

**2. User Changes Run:**
```
User selects "18Z Jan 23" from dropdown
→ Update currentRun
→ Fetch maps: /api/maps?run_time=2026-01-23T18:00:00Z&variable=temp&forecast_hour=0
→ Display map from 18Z run
→ Update metadata labels
```

**3. User Enables Comparison:**
```
User checks "Compare with previous run"
→ Switch to split-screen view
→ Load current run map (left)
→ Load previous run map (right)
→ Display both side-by-side
```

**4. User Changes Variable:**
```
User selects "Precipitation"
→ Reload maps for selected variable
→ Update both panels if in comparison mode
```

---

### Benefits

✅ **Forecast Evolution** - See how predictions change run-to-run  
✅ **Confidence Assessment** - Consistent forecasts = higher confidence  
✅ **User Education** - Understand model uncertainty  
✅ **Professional Feature** - Matches TropicalTidbits, Pivotal Weather  
✅ **Storage Efficient** - Only ~22 MB for 4 complete runs  
✅ **Auto-Cleanup** - No manual maintenance required  

---

### Implementation Priority

**Phase 2A: Basic Dropdown** (3-4 hours)
1. Fetch and display available runs in dropdown
2. Load maps when run selection changes
3. Show run metadata (time, age)

**Phase 2B: Comparison View** (1-2 days)
4. Side-by-side comparison interface
5. Toggle between single/comparison views
6. Sync variables and forecast hours across panels

**Phase 2C: Advanced Features** (optional)
7. Animation between runs to show forecast evolution
8. Highlight differences between runs
9. "Diff map" showing changes

---

**Backend is ready!** Frontend can be built any time in Phase 2.
