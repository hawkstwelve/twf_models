#!/bin/bash
# Quick deployment script for AIGFS fixes
# Run this on your VPS server

set -e

echo "=================================="
echo "AIGFS Fixes Deployment Script"
echo "=================================="
echo ""

# Navigate to project directory
cd /opt/twf_models

echo "1. Pulling latest code from repository..."
git pull origin main

echo ""
echo "2. Restarting scheduler service..."
sudo systemctl restart twf-models-scheduler.service

echo ""
echo "3. Checking service status..."
sudo systemctl status twf-models-scheduler.service --no-pager -l

echo ""
echo "4. Showing recent logs..."
sudo journalctl -u twf-models-scheduler.service --since "1 minute ago" --no-pager

echo ""
echo "=================================="
echo "Deployment Complete!"
echo "=================================="
echo ""
echo "To monitor AIGFS map generation:"
echo "  sudo journalctl -u twf-models-scheduler.service -f | grep -i aigfs"
echo ""
echo "To check for generated maps:"
echo "  ls -lh /opt/twf_models/backend/app/static/images/aigfs_*"
echo ""
echo "Next scheduled run times (UTC):"
echo "  03:30, 09:30, 15:30, 21:30"
echo ""
