#!/bin/bash
# Deployment script for TWF Weather Models

set -e

APP_DIR="/var/www/twf_models"
APP_USER="twfmodels"

echo "Deploying TWF Weather Models..."

# Check if running as root or with sudo
if [ "$EUID" -ne 0 ]; then 
    echo "Please run as root or with sudo"
    exit 1
fi

# Navigate to app directory
cd $APP_DIR

# Pull latest code
echo "Pulling latest code..."
sudo -u $APP_USER git pull origin main || echo "Git pull failed or not a git repo"

# Activate virtual environment and install dependencies
echo "Installing dependencies..."
sudo -u $APP_USER bash -c "source venv/bin/activate && pip install -r backend/requirements.txt"

# Restart service
echo "Restarting service..."
sudo systemctl restart twf-models || echo "Service not yet configured"

echo "Deployment complete!"
