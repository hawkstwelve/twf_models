#!/bin/bash
# Script to delete old precipitation maps and regenerate with new colormap

echo "Deleting old precipitation maps..."
cd /opt/twf_models

# Find and delete all precipitation maps
IMAGES_DIR="${IMAGES_DIR:-./images}"
if [ -d "$IMAGES_DIR" ]; then
    find "$IMAGES_DIR" -name "*precip*.png" -type f -delete
    echo "Deleted old precipitation maps from $IMAGES_DIR"
else
    echo "Images directory not found: $IMAGES_DIR"
    echo "Checking common locations..."
    for dir in "./images" "/opt/twf_models/images" "/opt/twf_models/backend/app/static/images"; do
        if [ -d "$dir" ]; then
            find "$dir" -name "*precip*.png" -type f -delete
            echo "Deleted old precipitation maps from $dir"
        fi
    done
fi

echo ""
echo "Old maps deleted. Now you need to regenerate them."
echo ""
echo "Option 1: Wait for the scheduler to regenerate them automatically"
echo "Option 2: Run the test script to regenerate manually:"
echo "  python3 test_precip_map.py"
echo ""
echo "Option 3: Restart the scheduler to trigger regeneration:"
echo "  sudo systemctl restart twf-models-scheduler"
echo ""
echo "After regeneration, clear your browser cache or do a hard refresh (Ctrl+Shift+R)"
