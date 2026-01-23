#!/bin/bash
# Setup script for Digital Ocean droplet

set -e

echo "Setting up Digital Ocean droplet for TWF Weather Models..."

# Update system
echo "Updating system packages..."
sudo apt-get update
sudo apt-get upgrade -y

# Install Python 3.10+
echo "Installing Python..."
sudo apt-get install -y python3.10 python3.10-venv python3-pip

# Install system dependencies for cartopy and geospatial libraries
echo "Installing geospatial libraries..."
sudo apt-get install -y \
    python3-dev \
    libproj-dev \
    proj-data \
    proj-bin \
    libgeos-dev \
    libgdal-dev \
    gdal-bin \
    libnetcdf-dev \
    libhdf5-dev

# Install other utilities
sudo apt-get install -y \
    git \
    nginx \
    supervisor \
    curl \
    wget

# Create application user
echo "Creating application user..."
sudo useradd -m -s /bin/bash twfmodels || true

# Create application directory
sudo mkdir -p /var/www/twf_models
sudo chown twfmodels:twfmodels /var/www/twf_models

# Create images directory
sudo mkdir -p /var/www/twf_models/images
sudo chown twfmodels:twfmodels /var/www/twf_models/images

# Create log directory
sudo mkdir -p /var/log/twf_models
sudo chown twfmodels:twfmodels /var/log/twf_models

# Set up firewall
echo "Configuring firewall..."
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw --force enable

echo "Setup complete!"
echo "Next steps:"
echo "1. Clone the repository to /var/www/twf_models"
echo "2. Set up virtual environment and install dependencies"
echo "3. Configure .env file"
echo "4. Set up systemd service"
echo "5. Configure nginx reverse proxy"
