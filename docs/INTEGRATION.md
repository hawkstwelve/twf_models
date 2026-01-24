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
