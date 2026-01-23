# Deployment Notes

## Deployment Timeline & Readiness

### 🎯 When to Deploy to Digital Ocean Droplet

**Deploy NOW** - You're ready for droplet deployment once you've completed:
- ✅ Basic map generation working (4 variables × 4 forecast hours) 
- ✅ GRIB caching implemented (performance optimization)
- ✅ API endpoints functional
- ✅ Local testing successful

**Current Status**: ✅ **READY FOR DROPLET DEPLOYMENT**

### 🏗️ Deployment Strategy

**Phase 1: Backend to Droplet** (Current Phase - DO THIS NOW)
- Deploy backend API and processing to Digital Ocean droplet
- Test API functionality
- Set up automated map generation every 6 hours
- Verify stability for 1-2 weeks

**Phase 2: Frontend Testing** (After backend is stable)
- Deploy test frontend to sodakweather.com
- Test slider/animation interface
- Verify map viewing functionality
- Gather feedback and refine

**Phase 3: Production Migration** (When ready)
- Move frontend from sodakweather.com to theweatherforums.com/models
- Update DNS/configuration
- Launch to forum users

---

## Digital Ocean Infrastructure

### Your Current Setup
- **Forums**: Hosted on Digital Ocean droplet (theweatherforums.com)
- **Models Backend**: ✅ Digital Ocean droplet ready (separate droplet)
- **Testing Domain**: sodakweather.com (for frontend development)
- **Production Domain**: theweatherforums.com/models (final destination)

### Deployment Options

### Option 1: Separate Droplet (Recommended)
**Pros:**
- Isolated from forum server
- Can scale independently
- Won't impact forum performance
- Easier to manage resources

**Cons:**
- Additional cost ($12-24/month)
- Separate server to maintain

**Setup:**
- Create new droplet ($12/month minimum recommended)
- Deploy API and processing on this droplet
- Configure CORS for theweatherforums.com

### Option 2: Same Droplet (Cost Saving)
**Pros:**
- No additional cost
- Simpler infrastructure

**Cons:**
- May impact forum performance during processing
- Resource contention
- More complex deployment

**Setup:**
- Deploy API on existing forum droplet
- Use different port (e.g., 8000)
- Configure nginx to proxy /models path
- Monitor resource usage closely

## Recommended Architecture

```
┌─────────────────────────────────────┐
│  Digital Ocean Droplet 1             │
│  (Existing - Forums)                 │
│  - Invision Community                │
│  - Nginx                              │
│  - PHP/MySQL                          │
└─────────────────────────────────────┘
                 │
                 │ (HTTP requests)
                 ▼
┌─────────────────────────────────────┐
│  Digital Ocean Droplet 2             │
│  (New - Weather Models)              │
│  - FastAPI (port 8000)               │
│  - Python processing                 │
│  - Image storage                     │
│  - Scheduled jobs                    │
└─────────────────────────────────────┘
```

## Nginx Configuration (Same Droplet Option)

If deploying on the same droplet as forums:

```nginx
# Add to existing nginx config
location /models {
    proxy_pass http://localhost:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    
    # For coming soon page
    # return 200 '<html>Coming Soon</html>';
    # add_header Content-Type text/html;
}
```

## Separate Droplet Configuration

### Nginx Reverse Proxy (Optional)

If you want to serve API through subdomain:

```nginx
# /etc/nginx/sites-available/models-api
server {
    listen 80;
    server_name api.theweatherforums.com;  # or models-api.theweatherforums.com

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### Direct IP Access (Simpler)

- Access API directly via droplet IP
- Configure CORS for theweatherforums.com
- No subdomain needed initially

## Resource Considerations

### Same Droplet
- **Memory**: Processing can use 1-2GB RAM
- **CPU**: Map generation is CPU-intensive
- **Disk**: Images accumulate (~50-100MB per update cycle)
- **Impact**: Processing may slow forum during map generation

### Separate Droplet
- **Recommended**: 1GB RAM minimum, 2GB optimal
- **CPU**: 1-2 vCPU sufficient
- **Disk**: 25GB SSD sufficient initially
- **Cost**: $12-24/month

## Security Considerations

### Firewall Rules
```bash
# Allow SSH
sudo ufw allow 22/tcp

# Allow HTTP/HTTPS
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

# API port (if not using nginx proxy)
sudo ufw allow 8000/tcp
```

### API Security
- Use admin API key for update endpoints
- Rate limiting (implement in FastAPI)
- CORS properly configured
- HTTPS/SSL (Let's Encrypt)

## Monitoring

### Same Droplet
- Monitor forum performance during processing
- Check disk space regularly
- Watch memory usage
- Set up alerts for high CPU

### Separate Droplet
- Monitor API response times
- Track processing job success/failure
- Monitor disk space for images
- Set up basic uptime monitoring

## Cost Comparison

### Same Droplet
- **Additional Cost**: $0
- **Risk**: Performance impact on forums

### Separate Droplet
- **Additional Cost**: $12-24/month
- **Benefit**: Isolated, scalable, safer

## Recommendation

**Start with separate droplet** ($12/month):
- Low cost
- Better isolation
- Easier to troubleshoot
- Can always consolidate later if needed

---

## 🚀 DEPLOYMENT GUIDE: Local to Digital Ocean

### Prerequisites
- ✅ Digital Ocean droplet ready (Ubuntu 22.04 recommended)
- ✅ SSH access to droplet
- ✅ Domain access to sodakweather.com (for testing)
- ✅ Local code tested and working

---

## Step-by-Step Deployment Process

### Phase 1: Initial Backend Deployment (DO THIS NOW)

#### Step 1: Prepare Your Droplet (15 minutes)

```bash
# SSH into your droplet
ssh root@YOUR_DROPLET_IP

# Update system
sudo apt update && sudo apt upgrade -y

# Install Python 3.11+
sudo apt install -y python3.11 python3.11-venv python3-pip

# Install system dependencies
sudo apt install -y \
    build-essential \
    libeccodes-dev \
    libnetcdf-dev \
    git \
    nginx \
    supervisor

# Install certbot for SSL (if using domain)
sudo apt install -y certbot python3-certbot-nginx
```

#### Step 2: Transfer Code to Droplet (10 minutes)

**Option A: Git Clone (Recommended if using GitHub/GitLab)**
```bash
# On droplet
cd /opt
sudo git clone YOUR_REPO_URL twf_models
cd twf_models
```

**Option B: Direct Transfer (If no Git repo)**
```bash
# On your local machine
cd ~/twf_models
# Create tarball excluding cache/images
tar -czf twf_models.tar.gz \
    --exclude='images/*' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.env' \
    backend/ frontend/ *.py *.txt *.md

# Transfer to droplet
scp twf_models.tar.gz root@YOUR_DROPLET_IP:/opt/

# On droplet
cd /opt
tar -xzf twf_models.tar.gz
mv twf_models.tar.gz ~/  # Move tarball out of the way
```

#### Step 3: Set Up Python Environment (10 minutes)

```bash
# On droplet
cd /opt/twf_models

# Create virtual environment
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r backend/requirements.txt

# Verify installation
python -c "import xarray, cfgrib, matplotlib; print('✅ Dependencies installed')"
```

#### Step 4: Configure Environment (5 minutes)

```bash
# On droplet
cd /opt/twf_models

# Create production .env file
cat > .env << 'EOF'
# GFS Data Source
GFS_SOURCE=aws

# Map Configuration
MAP_REGION=pnw
FORECAST_HOURS=0,24,48,72

# Storage
IMAGE_STORAGE_PATH=/opt/twf_models/images

# API Configuration
API_HOST=0.0.0.0
API_PORT=8000
API_KEY=YOUR_SECURE_API_KEY_HERE

# Logging
LOG_LEVEL=INFO
EOF

# Create images directory
mkdir -p images
chmod 755 images

# Test configuration
source venv/bin/activate
python -c "from backend.app.config import settings; print(f'✅ Config loaded: {settings.map_region}')"
```

#### Step 5: Test API Manually (5 minutes)

```bash
# On droplet
cd /opt/twf_models
source venv/bin/activate

# Run API server manually for testing
python -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000

# In another terminal/window, test from your local machine:
# curl http://YOUR_DROPLET_IP:8000/api/health
# Should return: {"status":"healthy"}

# Press Ctrl+C to stop test server
```

#### Step 6: Set Up Systemd Service (10 minutes)

```bash
# On droplet
sudo nano /etc/systemd/system/twf-models-api.service
```

**Paste this configuration:**
```ini
[Unit]
Description=TWF Models API
After=network.target

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/opt/twf_models
Environment="PATH=/opt/twf_models/venv/bin"
ExecStart=/opt/twf_models/venv/bin/uvicorn backend.app.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 2

Restart=always
RestartSec=10
StandardOutput=append:/var/log/twf-models-api.log
StandardError=append:/var/log/twf-models-api-error.log

[Install]
WantedBy=multi-user.target
```

```bash
# Set proper permissions
sudo chown -R www-data:www-data /opt/twf_models
sudo chmod -R 755 /opt/twf_models

# Create log files
sudo touch /var/log/twf-models-api.log
sudo touch /var/log/twf-models-api-error.log
sudo chown www-data:www-data /var/log/twf-models-*.log

# Enable and start service
sudo systemctl daemon-reload
sudo systemctl enable twf-models-api
sudo systemctl start twf-models-api

# Check status
sudo systemctl status twf-models-api

# View logs
sudo journalctl -u twf-models-api -f
```

#### Step 7: Set Up Automated Map Generation (15 minutes)

**Create scheduler service:**
```bash
sudo nano /etc/systemd/system/twf-models-scheduler.service
```

**Paste this:**
```ini
[Unit]
Description=TWF Models Scheduler
After=network.target

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/opt/twf_models
Environment="PATH=/opt/twf_models/venv/bin"
ExecStart=/opt/twf_models/venv/bin/python -m backend.app.scheduler

Restart=always
RestartSec=10
StandardOutput=append:/var/log/twf-models-scheduler.log
StandardError=append:/var/log/twf-models-scheduler-error.log

[Install]
WantedBy=multi-user.target
```

```bash
# Create log files
sudo touch /var/log/twf-models-scheduler.log
sudo touch /var/log/twf-models-scheduler-error.log
sudo chown www-data:www-data /var/log/twf-models-scheduler*.log

# Enable and start scheduler
sudo systemctl enable twf-models-scheduler
sudo systemctl start twf-models-scheduler

# Check status
sudo systemctl status twf-models-scheduler

# View logs
sudo tail -f /var/log/twf-models-scheduler.log
```

#### Step 8: Configure Firewall (5 minutes)

```bash
# On droplet
sudo ufw allow 22/tcp   # SSH
sudo ufw allow 80/tcp   # HTTP
sudo ufw allow 443/tcp  # HTTPS
sudo ufw allow 8000/tcp # API (if not using nginx proxy)

# Enable firewall
sudo ufw enable
sudo ufw status
```

#### Step 9: Test Everything (10 minutes)

```bash
# Test API from your local machine
curl http://YOUR_DROPLET_IP:8000/api/health
# Should return: {"status":"healthy"}

curl http://YOUR_DROPLET_IP:8000/api/maps
# Should return: {"maps": [...]}

# Check if scheduler is running
sudo systemctl status twf-models-scheduler

# Check if maps are being generated
ls -lh /opt/twf_models/images/

# Monitor logs
sudo tail -f /var/log/twf-models-scheduler.log
```

---

### Phase 2: Frontend Testing on sodakweather.com (AFTER backend is stable)

#### When to Start Phase 2
- Backend API running smoothly for 1-2 weeks
- Maps generating automatically every 6 hours
- No errors in logs
- Ready to build frontend viewer

#### Step 1: Set Up Nginx for sodakweather.com

```bash
# On droplet (or sodakweather.com's server)
sudo nano /etc/nginx/sites-available/sodakweather-models
```

**Configuration:**
```nginx
server {
    listen 80;
    server_name models.sodakweather.com;  # or sodakweather.com/models
    
    # Serve static frontend files
    location / {
        root /var/www/sodakweather-models;
        index index.html;
        try_files $uri $uri/ /index.html;
    }
    
    # Proxy API requests to models droplet
    location /api {
        proxy_pass http://YOUR_MODELS_DROPLET_IP:8000/api;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # CORS headers
        add_header Access-Control-Allow-Origin *;
        add_header Access-Control-Allow-Methods "GET, OPTIONS";
        add_header Access-Control-Allow-Headers "Content-Type";
    }
    
    # Serve map images directly from models droplet
    location /images {
        proxy_pass http://YOUR_MODELS_DROPLET_IP:8000/images;
        proxy_cache_valid 200 1h;
        expires 1h;
    }
}
```

```bash
# Enable site and restart nginx
sudo ln -s /etc/nginx/sites-available/sodakweather-models /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx

# Set up SSL
sudo certbot --nginx -d models.sodakweather.com
```

#### Step 2: Deploy Frontend Files

```bash
# Create frontend directory
sudo mkdir -p /var/www/sodakweather-models

# Transfer frontend files
# (You'll build these in Phase 3: Frontend Development)
# For now, create a simple test page:

sudo nano /var/www/sodakweather-models/index.html
```

**Simple test page:**
```html
<!DOCTYPE html>
<html>
<head>
    <title>TWF Models - Testing on SoDak Weather</title>
</head>
<body>
    <h1>Weather Models - Testing Phase</h1>
    <p>Backend API: <span id="api-status">Checking...</span></p>
    <div id="maps-list"></div>
    
    <script>
        // Test API connection
        fetch('http://YOUR_MODELS_DROPLET_IP:8000/api/health')
            .then(r => r.json())
            .then(data => {
                document.getElementById('api-status').textContent = data.status;
            });
        
        // List available maps
        fetch('http://YOUR_MODELS_DROPLET_IP:8000/api/maps')
            .then(r => r.json())
            .then(data => {
                const list = document.getElementById('maps-list');
                data.maps.forEach(map => {
                    const img = document.createElement('img');
                    img.src = `http://YOUR_MODELS_DROPLET_IP:8000/images/${map.filename}`;
                    img.style.width = '800px';
                    list.appendChild(img);
                });
            });
    </script>
</body>
</html>
```

---

### Phase 3: Production Migration to theweatherforums.com (When ready)

#### When to Start Phase 3
- Frontend working well on sodakweather.com
- Slider/animation interface complete
- User feedback incorporated
- System stable for 2-4 weeks

#### Migration Steps

**Option A: Keep API on separate droplet** (Recommended)
```nginx
# On theweatherforums.com droplet
# Add to existing nginx config

location /models {
    root /var/www/theweatherforums-models;
    index index.html;
    try_files $uri $uri/ /index.html;
}

location /models/api {
    proxy_pass http://YOUR_MODELS_DROPLET_IP:8000/api;
    # ... (same proxy config as sodakweather)
}
```

**Option B: Move everything to one droplet** (If needed)
1. Copy frontend files to theweatherforums.com droplet
2. Update API references
3. Test thoroughly
4. Update DNS if needed

#### Simple Transfer Process:
```bash
# Copy frontend files from sodakweather to theweatherforums
# On sodakweather server:
tar -czf frontend.tar.gz /var/www/sodakweather-models/*

# Transfer:
scp frontend.tar.gz root@FORUM_DROPLET_IP:/tmp/

# On forum droplet:
cd /var/www
sudo mkdir theweatherforums-models
cd theweatherforums-models
sudo tar -xzf /tmp/frontend.tar.gz --strip-components=4

# Update API URLs in frontend code:
# Change: http://YOUR_MODELS_DROPLET_IP:8000
# To: http://YOUR_MODELS_DROPLET_IP:8000 (stays same if using separate droplet)
# Or: http://localhost:8000 (if moved to same droplet)
```

---

## Deployment Checklist

### Phase 1: Backend Deployment (DO NOW)
- [x] Droplet ready and accessible
- [ ] System packages installed
- [ ] Code transferred to droplet
- [ ] Python environment configured
- [ ] Dependencies installed
- [ ] .env file configured
- [ ] API service running (systemd)
- [ ] Scheduler service running (systemd)
- [ ] Firewall configured
- [ ] API endpoints tested and working
- [ ] Maps generating automatically
- [ ] Monitor for 1-2 weeks

### Phase 2: Frontend Testing (AFTER BACKEND STABLE)
- [ ] Backend stable for 1-2 weeks
- [ ] Frontend code developed (slider interface)
- [ ] Nginx configured on sodakweather.com
- [ ] SSL certificate installed
- [ ] Test frontend deployed
- [ ] API integration working
- [ ] Map viewing functional
- [ ] Gather user feedback
- [ ] Refine based on feedback

### Phase 3: Production Migration (WHEN READY)
- [ ] Frontend tested on sodakweather.com
- [ ] User feedback incorporated
- [ ] System stable for 2-4 weeks
- [ ] Forum navigation ready for /models link
- [ ] Frontend migrated to theweatherforums.com
- [ ] DNS/config updated
- [ ] Final testing
- [ ] Launch to forum users
- [ ] Remove "Coming Soon" page
