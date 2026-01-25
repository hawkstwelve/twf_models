# TWF Models Frontend - Deployment Guide

## 📁 Files Overview

```
models/
├── index.html          # Main map viewer page
├── config.js           # Configuration (API URL)
├── css/
│   └── style.css       # Styling
└── js/
    ├── api-client.js   # API communication
    └── map-viewer.js   # Main app logic
```

---

## 🚀 Deploy to sodakweather.com

### Step 1: Upload Files via FTP

1. Connect to sodakweather.com via FTP
2. Navigate to your web root directory (usually `public_html/` or `www/`)
3. Create a folder called `models`
4. Upload ALL files maintaining the folder structure:
   ```
   public_html/
   └── models/
       ├── index.html
       ├── config.js
       ├── css/
       │   └── style.css
       └── js/
           ├── api-client.js
           └── map-viewer.js
   ```

### Step 2: Test

Visit: `https://sodakweather.com/models/`

You should see:
- Header: "Pacific Northwest Weather Models"
- Control buttons for variables and forecast hours
- Latest GFS map displayed

---

## 🔄 Migrate to theweatherforums.com (Later)

When ready to move to production:

### Step 1: Update API URL

Edit `config.js` line 10:

**Option A**: Keep using droplet IP
```javascript
API_BASE_URL: 'http://174.138.84.70:8000',
```

**Option B**: Set up subdomain (recommended)
```javascript
API_BASE_URL: 'https://api.theweatherforums.com',
```

### Step 2: Upload to theweatherforums.com

1. Connect via FTP to theweatherforums.com
2. Upload the `models/` folder to your web root
3. Done!

### Step 3: Update Forum Navigation

Add link to forum navigation menu pointing to:
`https://theweatherforums.com/models/`

---

## ⚙️ Configuration Options

### Change API URL

Edit `config.js`:
```javascript
const CONFIG = {
    API_BASE_URL: 'YOUR_API_URL_HERE',
    // ...
}
```

### Add/Remove Variables

Edit `config.js`:
```javascript
VARIABLES: {
    'temp': { label: 'Temperature', units: '°F', ... },
    'your_new_variable': { label: 'Your Label', ... }
}
```

### Change Forecast Hours

Edit `config.js`:
```javascript
FORECAST_HOURS: [0, 6, 12, 24, 48, 72],
```

### Adjust Auto-Refresh Rate

Edit `config.js`:
```javascript
REFRESH_INTERVAL: 30000,  // 30 seconds (in milliseconds)
```

---

## 🎨 Customization

### Colors

Edit `css/style.css` (lines 6-17):
```css
:root {
    --primary-color: #2196F3;  /* Change this */
    --primary-dark: #1976D2;
    /* ... */
}
```

### Header Text

Edit `index.html` (lines 23-25):
```html
<h1>Your Custom Title</h1>
<p>Your custom subtitle</p>
```

### Footer Links

Edit `index.html` (lines 89-96)

---

## 🐛 Troubleshooting

### Maps Not Loading

**Check 1**: Open browser console (F12) - any errors?

**Check 2**: Is API accessible?
```javascript
// In browser console:
fetch('http://174.138.84.70:8000/health')
  .then(r => r.json())
  .then(d => console.log(d))
```

**Check 3**: Are there maps available?
```javascript
// In browser console:
fetch('http://174.138.84.70:8000/api/maps')
  .then(r => r.json())
  .then(d => console.log(d))
```

### CORS Errors

If you see "CORS policy" errors, the API needs to allow your domain.

On the droplet, edit `/opt/twf_models/backend/.env`:
```env
CORS_ORIGINS=https://sodakweather.com,https://theweatherforums.com
```

Then restart API:
```bash
sudo systemctl restart twf-models-api
```

### Images Not Displaying

**Check**: Network tab in browser devtools (F12) - are images loading?

The image URLs should look like:
`http://174.138.84.70:8000/images/gfs_20260124_00_temp_0.png`

---

## 📱 Mobile Responsive

The viewer is fully responsive and works on:
- Desktop (1920px+)
- Tablet (768px - 1920px)
- Mobile (< 768px)

Test on your phone by visiting `https://sodakweather.com/models/`

---

## 🔒 HTTPS / SSL

**Current**: Using `http://` for API (works but not secure)

**Recommended** (Phase 3):
1. Set up subdomain: `api.theweatherforums.com`
2. Point to droplet IP: `174.138.84.70`
3. Add SSL certificate on droplet
4. Update config.js to use `https://api.theweatherforums.com`

---

## ✅ What Works Now (Phase 2A - MVP)

- ✅ Display latest GFS maps
- ✅ Variable selector (temp, precip, wind, precip_type)
- ✅ Forecast hour selector (0, 24, 48, 72)
- ✅ Auto-refresh every minute
- ✅ Mobile responsive
- ✅ Loading indicators
- ✅ Error handling

## ⏳ Coming in Phase 2B

- Run time dropdown (view last 4 runs)
- Side-by-side comparison
- Progressive loading indicators
- Animation controls
- GIF generation

---

## 📞 Need Help?

If something isn't working:
1. Check browser console (F12) for errors
2. Verify API is running: `curl http://174.138.84.70:8000/health`
3. Check if maps exist: `curl http://174.138.84.70:8000/api/maps`
