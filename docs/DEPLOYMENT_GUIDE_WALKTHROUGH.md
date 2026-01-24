# 🚀 Complete Step-by-Step Deployment Walkthrough

**Target Environment**: Ubuntu 24.04 LTS on Digital Ocean  
**Method**: Git deployment with root access  
**Skill Level**: Intermediate - detailed guidance provided  
**Estimated Time**: ~45-60 minutes (excluding waiting for map generation)

---

## Overview

This guide will walk you through deploying the TWF Models backend to your Digital Ocean droplet. You'll set up:
- FastAPI server (serves maps via API)
- Automated scheduler (generates maps every 6 hours at 00:00, 06:00, 12:00, 18:00 UTC)
- GRIB file caching (75% bandwidth reduction, 70% faster)
- 4 map types: temperature, precipitation, wind speed, precipitation type
- 4 forecast hours: 0h, 24h, 48h, 72h

**This does NOT include the frontend viewer yet** - that comes in Phase 2 on sodakweather.com.

---

## Prerequisites

Before starting, ensure you have:
- ✅ Digital Ocean droplet running Ubuntu 24.04
- ✅ SSH root access to the droplet
- ✅ Git repository (GitHub/GitLab) with your code
- ✅ Droplet IP address
- ✅ ~1 hour of uninterrupted time

---

## STEP 1: Push Code to Git Repository (5 minutes)

**Location**: Your local machine (~/twf_models)

Make sure all your latest code is in your Git repository:

```bash
cd ~/twf_models

# Check current status
git status

# Add all project files
git add backend/ frontend/ *.py *.txt *.md .env.example

# Create commit with GRIB caching improvements
git commit -m "Ready for production deployment - GRIB caching implemented"

# Push to your repository (use 'main' or 'master' depending on your setup)
git push origin main
```

**What you should see:**
```
[main abc1234] Ready for production deployment - GRIB caching implemented
 X files changed, Y insertions(+), Z deletions(-)
```

**✅ Checkpoint**: Code is pushed to Git and ready to clone on the droplet.

---

## STEP 2: Connect to Your Droplet (1 minute)

**Location**: Your local machine, new terminal window

```bash
ssh brian@174.138.84.70
```

**What you should see:**
```
Welcome to Ubuntu 24.04 LTS...
brian@your-droplet:~$
```

**✅ Checkpoint**: You're now connected to the droplet.

**Keep this terminal open** - you'll use it for all remaining steps.

---

## STEP 3: Check Python Version (2 minutes)

**Location**: Droplet terminal

First, let's see what Python version is installed:

```bash
python3 --version
```

**If you see `Python 3.10.x`, `3.11.x`, or `3.12.x`**: ✅ Perfect! Skip to Step 4.

**If you see `Python 3.9.x` or lower, or "command not found"**: Install Python 3.11:

```bash
# Update package lists
sudo apt update

# Install Python 3.11 and tools
sudo apt install -y python3.11 python3.11-venv python3-pip

# Verify installation
python3.11 --version
```

**Expected output**: `Python 3.11.x`

**✅ Checkpoint**: Python 3.10+ is confirmed installed.

---

## STEP 4: Install System Dependencies (10 minutes)

**Location**: Droplet terminal

These packages are required for GRIB processing, map generation, and server operations:

```bash
sudo apt install -y \
    build-essential \
    libeccodes-dev \
    libnetcdf-dev \
    git \
    nginx \
    curl \
    htop
```

**What's being installed:**
- `build-essential`: C/C++ compilers needed by Python packages
- `libeccodes-dev`: GRIB2 file decoding library (ECMWF's eccodes)
- `libnetcdf-dev`: NetCDF file support library
- `git`: Version control (to clone your repository)
- `nginx`: Web server (for future frontend/reverse proxy)
- `curl`: Command-line HTTP testing
- `htop`: Interactive process viewer

**This will take 5-10 minutes** to download and install.

**What you should see:**
```
Reading package lists... Done
Building dependency tree... Done
...
Setting up libeccodes-dev...
...
Processing triggers for...
```

**✅ Checkpoint**: All system dependencies installed successfully.

---

## STEP 5: Clone Your Repository (2 minutes)

**Location**: Droplet terminal

```bash
# Navigate to /opt directory (standard location for applications)
cd /opt

# Clone your repository
sudo git clone https://github.com/hawkstwelve/twf_models.git twf_models
```

**If you get an authentication error:**
- For HTTPS: Git will prompt for username/password or token
- For SSH: Make sure your droplet's SSH key is added to GitHub/GitLab

**Verify the clone worked:**
```bash
cd /opt/twf_models
ls -la
```

**What you should see:**
```
backend/
frontend/
test_all_maps_all_hours.py
test_fetch.py
requirements.txt
README.md
...
```

**✅ Checkpoint**: Repository cloned successfully to `/opt/twf_models`.

---

## STEP 6: Set Up Python Virtual Environment (5 minutes)

**Location**: Droplet terminal

Create an isolated Python environment for the project:

```bash
cd /opt/twf_models

# Create virtual environment
# Use python3.11 if that's what you installed, otherwise python3
python3.11 -m venv venv

# Activate the virtual environment
source venv/bin/activate
```

**Your prompt should change** to show `(venv)`:
```
(venv) root@your-droplet:/opt/twf_models#
```

**Upgrade pip and install dependencies:**
```bash
# Upgrade pip to latest version
pip install --upgrade pip

# Install all Python packages
pip install -r backend/requirements.txt
```

**This will take 3-5 minutes** as it downloads and compiles packages like:
- xarray, numpy, pandas (data processing)
- matplotlib, cartopy (map generation)
- fastapi, uvicorn (API server)
- cfgrib, eccodes (GRIB processing)
- s3fs, boto3 (AWS S3 access)

**What you should see:**
```
Collecting fastapi==0.109.0
...
Successfully installed fastapi-0.109.0 uvicorn-0.27.0 xarray-2024.1.1 ...
```

**✅ Checkpoint**: Virtual environment created and all dependencies installed.

---

## STEP 7: Create Production Configuration (3 minutes)

**Location**: Droplet terminal

```bash
cd /opt/twf_models

# Create production .env file
nano .env
```

**Paste this configuration** (Ctrl+Shift+V to paste):

```env
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
API_KEY=CHANGE_THIS_TO_SECURE_RANDOM_STRING

# Logging
LOG_LEVEL=INFO
```

**IMPORTANT**: Change `API_KEY` to a secure random string!

**Save and exit:**
1. Press `Ctrl+X`
2. Press `Y` (yes, save changes)
3. Press `Enter` (confirm filename)

**Create images directory:**
```bash
mkdir -p /opt/twf_models/images
chmod 755 /opt/twf_models/images
```

**Verify configuration:**
```bash
cat .env
```

**✅ Checkpoint**: Production `.env` file created and images directory ready.

---

## STEP 8: Test the Setup Manually (5 minutes)

**Location**: Droplet terminal

Before setting up automated services, let's verify everything works:

```bash
cd /opt/twf_models
source venv/bin/activate

# Test 1: Verify configuration loads
python3 -c "from backend.app.config import settings; print(f'✅ Config loaded: region={settings.map_region}, hours={settings.forecast_hours}')"
```

**Expected output:**
```
✅ Config loaded: region=pnw, hours=[0, 24, 48, 72]
```

**Test 2: Start API server manually**
```bash
python3 -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
```

**Expected output:**
```
INFO:     Started server process [12345]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

**✅ Server is running!** Now test it...

---

## STEP 9: Test API from Local Machine (2 minutes)

**Location**: Your local machine, **NEW terminal window** (keep droplet terminal running)

```bash
# Replace YOUR_DROPLET_IP with actual IP
curl http://YOUR_DROPLET_IP:8000/api/health
```

**Expected response:**
```json
{"status":"healthy","timestamp":"2026-01-23T..."}
```

**✅ If you see this**: Perfect! The API is working.

**❌ If connection fails**: The firewall might be blocking port 8000 (we'll fix that in Step 10).

**Test maps endpoint:**
```bash
curl http://YOUR_DROPLET_IP:8000/api/maps
```

**Expected response:**
```json
{"maps":[],"total":0,"run_time":null}
```

(Empty list is normal - no maps generated yet)

**Go back to droplet terminal** and press `Ctrl+C` to stop the manual server:
```
^C
INFO:     Shutting down
```

**✅ Checkpoint**: API server tested successfully in manual mode.

---

## STEP 10: Create Systemd Services (15 minutes)

**Location**: Droplet terminal

Now we'll set up the services to run automatically and restart on failure.

### API Service

```bash
sudo nano /etc/systemd/system/twf-models-api.service
```

**Paste this entire configuration:**

```ini
[Unit]
Description=TWF Models API
After=network.target

[Service]
Type=simple
User=root
Group=root
WorkingDirectory=/opt/twf_models
Environment="PATH=/opt/twf_models/venv/bin"
ExecStart=/opt/twf_models/venv/bin/uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --workers 2
Restart=always
RestartSec=10
StandardOutput=append:/var/log/twf-models-api.log
StandardError=append:/var/log/twf-models-api-error.log

[Install]
WantedBy=multi-user.target
```

**Save**: `Ctrl+X`, then `Y`, then `Enter`

### Scheduler Service

```bash
sudo nano /etc/systemd/system/twf-models-scheduler.service
```

**Paste this configuration:**

```ini
[Unit]
Description=TWF Models Scheduler
After=network.target

[Service]
Type=simple
User=root
Group=root
WorkingDirectory=/opt/twf_models
Environment="PATH=/opt/twf_models/venv/bin"
ExecStart=/opt/twf_models/venv/bin/python3 -m backend.app.scheduler
Restart=always
RestartSec=10
StandardOutput=append:/var/log/twf-models-scheduler.log
StandardError=append:/var/log/twf-models-scheduler-error.log

[Install]
WantedBy=multi-user.target
```

**Save**: `Ctrl+X`, then `Y`, then `Enter`

### Create Log Files

```bash
sudo touch /var/log/twf-models-api.log
sudo touch /var/log/twf-models-api-error.log
sudo touch /var/log/twf-models-scheduler.log
sudo touch /var/log/twf-models-scheduler-error.log
```

**✅ Checkpoint**: Systemd service files created and ready.

---

## STEP 11: Configure Firewall (3 minutes)

**Location**: Droplet terminal

**⚠️ CRITICAL**: Do these steps in order to avoid locking yourself out!

```bash
# Check current firewall status
sudo ufw status
```

**If it says "Status: inactive"**: Configure and enable it:

```bash
# Allow SSH first (CRITICAL - don't lock yourself out!)
sudo ufw allow 22/tcp

# Allow HTTP/HTTPS for future frontend
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

# Allow API port
sudo ufw allow 8000/tcp

# Enable the firewall
sudo ufw enable
```

It will ask: `Command may disrupt existing ssh connections. Proceed with operation (y|n)?`

Type `y` and press `Enter`.

**Verify rules are active:**
```bash
sudo ufw status
```

**Expected output:**
```
Status: active

To                         Action      From
--                         ------      ----
22/tcp                     ALLOW       Anywhere
80/tcp                     ALLOW       Anywhere
443/tcp                    ALLOW       Anywhere
8000/tcp                   ALLOW       Anywhere
```

**✅ Checkpoint**: Firewall configured with proper rules.

---

## STEP 12: Start the Services (3 minutes)

**Location**: Droplet terminal

```bash
# Reload systemd to recognize new services
sudo systemctl daemon-reload

# Enable services to start automatically on boot
sudo systemctl enable twf-models-api
sudo systemctl enable twf-models-scheduler

# Start both services now
sudo systemctl start twf-models-api
sudo systemctl start twf-models-scheduler
```

**Check if they're running:**
```bash
sudo systemctl status twf-models-api
```

**What to look for:**
```
● twf-models-api.service - TWF Models API
     Loaded: loaded (/etc/systemd/system/twf-models-api.service; enabled)
     Active: active (running) since Thu 2026-01-23 10:15:32 UTC; 5s ago
   Main PID: 12345 (uvicorn)
```

Look for **"Active: active (running)"** in **green text**.

**Check scheduler:**
```bash
sudo systemctl status twf-models-scheduler
```

**Should also show**: `Active: active (running)`

**✅ If both show "active (running)"**: Perfect!

**❌ If either shows "failed" in red**: Check the troubleshooting section at the end.

**✅ Checkpoint**: Both services are running automatically.

---

## STEP 13: Verify Everything Works (5 minutes)

**Location**: Local machine terminal

### Test 1: API Health Check

```bash
curl http://YOUR_DROPLET_IP:8000/api/health
```

**Expected:** `{"status":"healthy",...}`

### Test 2: Maps Endpoint

```bash
curl http://YOUR_DROPLET_IP:8000/api/maps
```

**Expected:** `{"maps":[],...}` (empty until first generation)

### Test 3: View Logs

**Location**: Droplet terminal

```bash
# View scheduler logs in real-time
sudo tail -f /var/log/twf-models-scheduler.log
```

Press `Ctrl+C` to exit.

**What you should see:**
```
INFO:     Scheduler initialized
INFO:     Next scheduled run: 2026-01-23 18:00:00 UTC
INFO:     Waiting for next run...
```

**Note**: The scheduler runs every 6 hours at **00:00, 06:00, 12:00, 18:00 UTC**. If it's not one of those times, you won't see map generation yet.

---

## STEP 14: Test Map Generation Manually (Optional, 2 minutes)

**Location**: Droplet terminal

To test without waiting for the next scheduled run:

```bash
cd /opt/twf_models
source venv/bin/activate

# Generate one map manually
python3 -c "
from backend.app.services.map_generator import MapGenerator
from datetime import datetime, timedelta

# Calculate most recent GFS run time
now = datetime.utcnow()
run_hour = ((now.hour // 6) * 6) - 6
if run_hour < 0:
    run_hour = 18
    now = now - timedelta(days=1)
run_time = now.replace(hour=run_hour, minute=0, second=0, microsecond=0)

print(f'Generating map for run time: {run_time}')
gen = MapGenerator()
path = gen.generate_map('temp', 'GFS', run_time, 0, 'pnw')
print(f'✅ Generated: {path}')
"
```

**This will take ~30-60 seconds** (downloading GRIB file from AWS).

**Expected output:**
```
Generating map for run time: 2026-01-23 06:00:00
INFO:     Fetching GFS data...
INFO:     GRIB file opened successfully
INFO:     Data extracted for temperature
INFO:     Map rendered successfully
✅ Generated: /opt/twf_models/images/temp_GFS_2026012306_000.png
```

**Check that the file was created:**
```bash
ls -lh /opt/twf_models/images/
```

**You should see:**
```
-rw-r--r-- 1 root root 487K Jan 23 10:25 temp_GFS_2026012306_000.png
```

**✅ Checkpoint**: Map generation works successfully!

---

## 🎉 Success Checklist

Verify all these items:

- ✅ Both services show "active (running)" in systemctl status
- ✅ API health check returns `{"status":"healthy"}`
- ✅ Manual map generation works
- ✅ No errors in `/var/log/twf-models-*-error.log` files
- ✅ Images directory contains at least one PNG file

**If all are checked**: 🎊 **Congratulations! Your backend is successfully deployed!**

---

## 📊 Monitoring Your Deployment

### Useful Commands

**Check service status:**
```bash
sudo systemctl status twf-models-api
sudo systemctl status twf-models-scheduler
```

**View logs in real-time:**
```bash
# Scheduler (map generation)
sudo tail -f /var/log/twf-models-scheduler.log

# API (HTTP requests)
sudo tail -f /var/log/twf-models-api.log

# Error logs
sudo tail -f /var/log/twf-models-api-error.log
sudo tail -f /var/log/twf-models-scheduler-error.log
```

**View last 50 lines of logs:**
```bash
sudo tail -50 /var/log/twf-models-scheduler.log
```

**Restart services:**
```bash
sudo systemctl restart twf-models-api
sudo systemctl restart twf-models-scheduler
```

**Check disk usage:**
```bash
df -h /opt/twf_models
du -sh /opt/twf_models/images/
```

**View running processes:**
```bash
htop  # Press Q to quit
```

**Check generated maps:**
```bash
ls -lth /opt/twf_models/images/ | head -20
```

### What to Watch For

**First 24 Hours:**
- Scheduler should generate maps at next run time (00:00, 06:00, 12:00, or 18:00 UTC)
- Each run should generate 16 maps (4 types × 4 forecast hours)
- Total ~2 GB will be downloaded per run (with caching, reused across maps)
- No errors in error logs

**Ongoing:**
- Maps generated every 6 hours
- Images directory growing (cleanup old maps periodically)
- API responding quickly (< 100ms for health check)
- System resources reasonable (use `htop` to check)

---

## 🚨 Troubleshooting

### API Service Won't Start

**Check error logs:**
```bash
sudo tail -50 /var/log/twf-models-api-error.log
```

**Check systemd journal:**
```bash
sudo journalctl -u twf-models-api -n 50
```

**Common issues:**
- **Port 8000 already in use**: Change `API_PORT` in `.env` or stop conflicting service
- **Module import errors**: Verify `pip install -r backend/requirements.txt` completed successfully
- **Permission errors**: Check ownership with `ls -la /opt/twf_models`

**Test manually to see actual error:**
```bash
cd /opt/twf_models
source venv/bin/activate
python3 -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
```

### Scheduler Service Won't Start

**Check error logs:**
```bash
sudo tail -50 /var/log/twf-models-scheduler-error.log
```

**Test scheduler module import:**
```bash
cd /opt/twf_models
source venv/bin/activate
python3 -c "from backend.app.scheduler import WeatherScheduler; print('✅ Import successful')"
```

**Run scheduler once manually:**
```bash
cd /opt/twf_models
source venv/bin/activate
python3 -c "from backend.app.scheduler import WeatherScheduler; s = WeatherScheduler(); s.run_once()"
```

### Scheduler Running But Not Generating Maps

**Check schedule timing:**
```bash
sudo tail -20 /var/log/twf-models-scheduler.log
```

Look for: `Next scheduled run: ...`

The scheduler runs at **00:00, 06:00, 12:00, 18:00 UTC**. Check current UTC time:
```bash
date -u
```

**Force a generation manually** (see Step 14 above).

### Can't Connect to API from Local Machine

**Verify firewall rules:**
```bash
sudo ufw status | grep 8000
```

Should show: `8000/tcp    ALLOW    Anywhere`

**Verify API is listening:**
```bash
sudo netstat -tlnp | grep 8000
```

Should show: `tcp ... 0.0.0.0:8000 ... LISTEN ... uvicorn`

**Test from droplet itself:**
```bash
curl http://localhost:8000/api/health
```

If this works but remote connection doesn't, it's a firewall/network issue.

### Permission Errors

**Fix ownership and permissions:**
```bash
sudo chown -R root:root /opt/twf_models
sudo chmod -R 755 /opt/twf_models
sudo chmod 644 /opt/twf_models/.env
```

### GRIB Download Errors

**Check internet connectivity:**
```bash
curl -I https://noaa-gfs-bdp-pds.s3.amazonaws.com
```

Should return: `HTTP/1.1 200 OK` or `403 Forbidden` (403 is OK for bucket root)

**Check S3 access in logs:**
```bash
sudo grep -i "s3" /var/log/twf-models-scheduler.log
```

### Service Keeps Restarting

**Check if it's crashlooping:**
```bash
sudo systemctl status twf-models-scheduler
```

Look for restart counts: `Active: active (running) since ... (5 restarts)`

**View last crash logs:**
```bash
sudo journalctl -u twf-models-scheduler -n 100
```

**Common cause**: Configuration error in `.env` or missing dependency.

---

## 🔄 Updating the Deployment

When you push code updates to Git:

```bash
# On droplet
cd /opt/twf_models
sudo git pull origin main

# Restart services to load new code
sudo systemctl restart twf-models-api
sudo systemctl restart twf-models-scheduler

# Verify services restarted
sudo systemctl status twf-models-api
sudo systemctl status twf-models-scheduler
```

---

## 📈 What's Next?

### Immediate (Next 1-2 Weeks)

**Monitor Stability:**
- Check logs daily for first week
- Verify maps generating every 6 hours
- Ensure no errors or crashes
- Monitor disk usage

**Success Criteria Before Moving to Phase 2:**
- ✅ 7+ days uptime with no manual intervention
- ✅ Maps generating consistently (4 runs/day, 16 maps/run)
- ✅ No errors in logs
- ✅ API responding reliably

### Phase 2: Frontend Testing on sodakweather.com

**After backend is stable** (1-2 weeks from now):

1. **Build Interactive Frontend**
   - Slider/animation interface
   - Map type selector
   - Run time selector
   - Mobile-responsive design

2. **Deploy to sodakweather.com**
   - Set up separate frontend droplet or static hosting
   - Connect to backend API
   - Beta testing with selected users

3. **Gather Feedback**
   - Test on different devices/browsers
   - Identify usability issues
   - Iterate on design

### Phase 3: Production on theweatherforums.com

**After frontend testing is complete**:

1. **Migrate Frontend**
   - Copy tested code to forum droplet/hosting
   - Configure at theweatherforums.com/models
   - Add to forum navigation

2. **Public Launch**
   - Announce to forum users
   - Monitor usage/performance
   - Gather feedback

3. **Future Enhancements**
   - Higher resolution (0.25° GFS)
   - More map types (10-15 new types)
   - Extended forecast hours (up to 120h)
   - Additional models (Graphcast, HRRR, etc.)

---

## 📚 Additional Resources

- **Quick Reference**: [/DEPLOY_NOW.md](../DEPLOY_NOW.md)
- **Detailed Technical Notes**: [DEPLOYMENT_NOTES.md](DEPLOYMENT_NOTES.md)
- **Project Roadmap**: [ROADMAP.md](ROADMAP.md)
- **Integration Planning**: [INTEGRATION.md](INTEGRATION.md)
- **Common Issues**: [GOTCHAS.md](GOTCHAS.md)

---

## 🆘 Getting Help

**Before asking for help:**

1. Check error logs:
   ```bash
   sudo tail -100 /var/log/twf-models-api-error.log
   sudo tail -100 /var/log/twf-models-scheduler-error.log
   ```

2. Check service status:
   ```bash
   sudo systemctl status twf-models-api
   sudo systemctl status twf-models-scheduler
   ```

3. Review [docs/GOTCHAS.md](GOTCHAS.md) for known issues

**When reporting issues, include:**
- Which step you're on
- Exact error message
- Relevant log excerpts
- Output of `python3 --version` and `uname -a`

---

## ✅ Deployment Verification Checklist

Print this or copy to a notes file to track your progress:

```
[ ] Step 1: Code pushed to Git repository
[ ] Step 2: Connected to droplet via SSH
[ ] Step 3: Python 3.10+ verified/installed
[ ] Step 4: System dependencies installed (eccodes, netcdf, etc.)
[ ] Step 5: Repository cloned to /opt/twf_models
[ ] Step 6: Virtual environment created and dependencies installed
[ ] Step 7: .env configuration file created
[ ] Step 8: Manual API test successful
[ ] Step 9: API accessible from local machine
[ ] Step 10: Systemd service files created
[ ] Step 11: Firewall configured with proper rules
[ ] Step 12: Services started and showing "active (running)"
[ ] Step 13: Health check returning successful response
[ ] Step 14: Manual map generation successful

FINAL VERIFICATION:
[ ] Both services running for 24+ hours with no errors
[ ] At least one automated map generation cycle completed
[ ] Images directory contains 16+ map files
[ ] API responding to health checks reliably
[ ] No errors in any log files
```

---

**Last Updated**: 2026-01-23  
**Document Version**: 1.0  
**For TWF Models**: Backend Deployment (Phase 1)
