#!/bin/bash
# Script to restart the scheduler service and clear Python cache

echo "Restarting TWF Models Scheduler service..."
sudo systemctl restart twf-models-scheduler

echo "Clearing Python cache files..."
find /opt/twf_models -type d -name __pycache__ -exec rm -r {} + 2>/dev/null
find /opt/twf_models -name "*.pyc" -delete 2>/dev/null

echo "Checking scheduler status..."
sudo systemctl status twf-models-scheduler --no-pager -l

echo ""
echo "To view scheduler logs:"
echo "  sudo journalctl -u twf-models-scheduler -f"
