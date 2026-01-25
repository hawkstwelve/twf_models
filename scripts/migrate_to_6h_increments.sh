#!/bin/bash
#
# Migration script: Move from 24-hour to 6-hour forecast increments
#
# This script:
# 1. Backs up existing maps
# 2. Clears old maps to make room for new 6-hour increment maps
# 3. Restarts the scheduler to regenerate maps with new schedule
#
# Run this on the production server after updating the config

set -e

echo "=========================================="
echo "Migration: 24h → 6h Forecast Increments"
echo "=========================================="

# Configuration
IMAGES_DIR="/opt/twf_models/images"
BACKUP_DIR="/opt/twf_models/images_backup_$(date +%Y%m%d_%H%M%S)"

echo ""
echo "This will:"
echo "  1. Backup existing maps to: $BACKUP_DIR"
echo "  2. Clear current maps (will be regenerated with 6h increments)"
echo "  3. Restart scheduler to generate new maps"
echo ""
read -p "Continue? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 1
fi

# Step 1: Backup existing maps
echo ""
echo "Step 1: Backing up existing maps..."
if [ -d "$IMAGES_DIR" ]; then
    mkdir -p "$BACKUP_DIR"
    cp -r "$IMAGES_DIR"/* "$BACKUP_DIR/" 2>/dev/null || echo "  (No files to backup)"
    echo "  ✓ Backup created: $BACKUP_DIR"
    echo "  Backed up $(ls -1 $BACKUP_DIR 2>/dev/null | wc -l) files"
else
    echo "  ⚠ Images directory not found: $IMAGES_DIR"
fi

# Step 2: Clear old maps
echo ""
echo "Step 2: Clearing old maps..."
if [ -d "$IMAGES_DIR" ]; then
    OLD_COUNT=$(ls -1 "$IMAGES_DIR"/*.png 2>/dev/null | wc -l)
    rm -f "$IMAGES_DIR"/*.png
    echo "  ✓ Removed $OLD_COUNT old maps"
else
    echo "  ⚠ Images directory not found"
fi

# Step 3: Restart scheduler
echo ""
echo "Step 3: Restarting scheduler..."
if command -v systemctl &> /dev/null; then
    sudo systemctl restart twf-models-scheduler
    echo "  ✓ Scheduler restarted"
    echo ""
    echo "Monitoring logs (Ctrl+C to exit)..."
    sleep 2
    sudo journalctl -u twf-models-scheduler -f -n 50
else
    echo "  ⚠ systemctl not found - please restart scheduler manually"
fi

echo ""
echo "=========================================="
echo "Migration Complete!"
echo "=========================================="
echo ""
echo "New forecast hours: 0, 6, 12, 18, 24, 30, 36, 42, 48, 54, 60, 66, 72"
echo "Maps will be regenerated at next scheduled run (or within 90 minutes)"
echo ""
echo "Backup location: $BACKUP_DIR"
echo "To restore old maps: cp -r $BACKUP_DIR/* $IMAGES_DIR/"
echo ""
