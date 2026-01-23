# 🚀 QUICK START: Deploy Backend to Digital Ocean NOW

**Status**: ✅ You're ready to deploy the backend!

---

## What You're Deploying

**Backend API + Automated Map Generation** to your Digital Ocean droplet:
- FastAPI server (serves maps via API)
- Automated scheduler (generates maps every 6 hours)
- GRIB file caching (4x faster performance)
- 4 map types (temp, precip, wind speed, precip type)
- 4 forecast hours (0, 24, 48, 72)

**NOT deploying yet**: Frontend viewer (that comes in Phase 2 on sodakweather.com)

---

## Prerequisites

✅ Digital Ocean droplet ready  
✅ SSH access to droplet  
✅ Local code tested (comprehensive test passed)  
✅ ~2 hours for setup

---

## Deployment Steps (Summary)

### 1. Prepare Droplet (15 min)
```bash
ssh root@YOUR_DROPLET_IP

# Update and install packages
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3.11 python3.11-venv python3-pip \
    build-essential libeccodes-dev libnetcdf-dev git nginx supervisor
```

### 2. Transfer Code (10 min)

**Option A - Git** (if using GitHub/GitLab):
```bash
cd /opt
sudo git clone YOUR_REPO_URL twf_models
```

**Option B - Direct Transfer**:
```bash
# On local machine:
cd ~/twf_models
tar -czf twf_models.tar.gz --exclude='images/*' --exclude='__pycache__' backend/ frontend/ *.py *.txt
scp twf_models.tar.gz root@YOUR_DROPLET_IP:/opt/

# On droplet:
cd /opt
tar -xzf twf_models.tar.gz
```

### 3. Set Up Python Environment (10 min)
```bash
cd /opt/twf_models
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r backend/requirements.txt
```

### 4. Configure Environment (5 min)
```bash
cd /opt/twf_models
cat > .env << 'EOF'
GFS_SOURCE=aws
MAP_REGION=pnw
FORECAST_HOURS=0,24,48,72
IMAGE_STORAGE_PATH=/opt/twf_models/images
API_HOST=0.0.0.0
API_PORT=8000
API_KEY=YOUR_SECURE_API_KEY_HERE
LOG_LEVEL=INFO
EOF

mkdir -p images
chmod 755 images
```

### 5. Test Manually (5 min)
```bash
cd /opt/twf_models
source venv/bin/activate
python -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000

# In another terminal, test:
# curl http://YOUR_DROPLET_IP:8000/api/health
# Press Ctrl+C to stop
```

### 6. Set Up Systemd Services (20 min)

**API Service**:
```bash
sudo nano /etc/systemd/system/twf-models-api.service
```

Paste:
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
ExecStart=/opt/twf_models/venv/bin/uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --workers 2
Restart=always
RestartSec=10
StandardOutput=append:/var/log/twf-models-api.log
StandardError=append:/var/log/twf-models-api-error.log

[Install]
WantedBy=multi-user.target
```

**Scheduler Service**:
```bash
sudo nano /etc/systemd/system/twf-models-scheduler.service
```

Paste:
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

**Start Services**:
```bash
sudo chown -R www-data:www-data /opt/twf_models
sudo chmod -R 755 /opt/twf_models

sudo touch /var/log/twf-models-api.log /var/log/twf-models-api-error.log
sudo touch /var/log/twf-models-scheduler.log /var/log/twf-models-scheduler-error.log
sudo chown www-data:www-data /var/log/twf-models-*.log

sudo systemctl daemon-reload
sudo systemctl enable twf-models-api twf-models-scheduler
sudo systemctl start twf-models-api twf-models-scheduler
```

### 7. Configure Firewall (5 min)
```bash
sudo ufw allow 22/tcp   # SSH
sudo ufw allow 80/tcp   # HTTP
sudo ufw allow 443/tcp  # HTTPS
sudo ufw allow 8000/tcp # API
sudo ufw enable
```

### 8. Verify Everything Works (10 min)
```bash
# Check services
sudo systemctl status twf-models-api
sudo systemctl status twf-models-scheduler

# Test API
curl http://YOUR_DROPLET_IP:8000/api/health
curl http://YOUR_DROPLET_IP:8000/api/maps

# Check logs
sudo tail -f /var/log/twf-models-scheduler.log

# Wait for first map generation (next GFS run)
# Check images directory
ls -lh /opt/twf_models/images/
```

---

## Success Criteria

✅ API responds to health checks  
✅ Scheduler service running  
✅ Maps generating every 6 hours  
✅ No errors in logs for 24 hours  

---

## Monitoring Commands

```bash
# Check service status
sudo systemctl status twf-models-api
sudo systemctl status twf-models-scheduler

# View logs (live)
sudo tail -f /var/log/twf-models-api.log
sudo tail -f /var/log/twf-models-scheduler.log

# View last 50 lines
sudo tail -50 /var/log/twf-models-scheduler.log

# Restart services if needed
sudo systemctl restart twf-models-api
sudo systemctl restart twf-models-scheduler

# Check disk space
df -h /opt/twf_models

# Check generated maps
ls -lh /opt/twf_models/images/
```

---

## Troubleshooting

**API won't start?**
```bash
# Check logs for errors
sudo journalctl -u twf-models-api -n 50

# Test manually
cd /opt/twf_models
source venv/bin/activate
python -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
```

**Scheduler not generating maps?**
```bash
# Check logs
sudo tail -100 /var/log/twf-models-scheduler.log

# Test manually
cd /opt/twf_models
source venv/bin/activate
python -c "from backend.app.scheduler import WeatherScheduler; s = WeatherScheduler(); s.run_once()"
```

**Permission errors?**
```bash
sudo chown -R www-data:www-data /opt/twf_models
sudo chmod -R 755 /opt/twf_models
```

---

## What's Next?

### After Backend is Stable (1-2 weeks):

**Phase 2**: Deploy frontend to sodakweather.com for testing
- Build interactive slider/animation interface
- Test with beta users
- Gather feedback

**Phase 3**: Migrate to theweatherforums.com/models when ready
- Copy tested frontend
- Add to forum navigation
- Public launch

---

## Full Documentation

- **Detailed Steps**: [docs/DEPLOYMENT_NOTES.md](docs/DEPLOYMENT_NOTES.md)
- **Roadmap**: [docs/ROADMAP.md](docs/ROADMAP.md)
- **Integration Plan**: [docs/INTEGRATION.md](docs/INTEGRATION.md)

---

## Need Help?

Check logs first:
```bash
sudo tail -100 /var/log/twf-models-api-error.log
sudo tail -100 /var/log/twf-models-scheduler-error.log
```

Common issues are in [docs/GOTCHAS.md](docs/GOTCHAS.md)
