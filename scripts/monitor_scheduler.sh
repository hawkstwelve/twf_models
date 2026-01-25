#!/bin/bash
# Monitor scheduler progress for current GFS run
# Usage: ./monitor_scheduler.sh [run_hour]
# Example: ./monitor_scheduler.sh 12

set -e

# Default to current 6-hour cycle if not specified
if [ -z "$1" ]; then
    # Get current UTC hour and round down to nearest 6-hour cycle
    CURRENT_HOUR=$(date -u +%H)
    RUN_HOUR=$(( (CURRENT_HOUR / 6) * 6 ))
    RUN_HOUR=$(printf "%02d" $RUN_HOUR)
else
    RUN_HOUR=$(printf "%02d" $1)
fi

RUN_DATE=$(date -u +%Y%m%d)
STORAGE_PATH="${STORAGE_PATH:-/opt/twf_models/images}"

# Variables and forecast hours (adjust if your config differs)
VARIABLES=6  # temp, precip, wind_speed, mslp_precip, temp_850_wind_mslp, radar
FORECAST_HOURS=4  # 0, 24, 48, 72 (adjust based on your config)
EXPECTED_FILES=$((VARIABLES * FORECAST_HOURS))

echo "=========================================="
echo "TWF Models Scheduler Monitor"
echo "=========================================="
echo "Run: ${RUN_DATE} ${RUN_HOUR}z"
echo "Storage: ${STORAGE_PATH}"
echo ""

# Check service status
echo "📋 Service Status:"
if systemctl is-active --quiet twf-models-scheduler 2>/dev/null; then
    echo "   ✅ Scheduler is running"
    SERVICE_STATUS=$(systemctl show twf-models-scheduler -p ActiveState --value 2>/dev/null || echo "unknown")
    echo "   State: ${SERVICE_STATUS}"
else
    echo "   ❌ Scheduler is NOT running"
    echo "   Run: sudo systemctl start twf-models-scheduler"
fi
echo ""

# Count generated files
FILE_PATTERN="${STORAGE_PATH}/gfs_${RUN_DATE}_${RUN_HOUR}_*.png"
FILE_COUNT=$(ls -1 ${FILE_PATTERN} 2>/dev/null | wc -l || echo "0")

if [ "$FILE_COUNT" -gt 0 ]; then
    PROGRESS=$((FILE_COUNT * 100 / EXPECTED_FILES))
    echo "📊 File Generation Progress:"
    echo "   Generated: ${FILE_COUNT}/${EXPECTED_FILES} files (${PROGRESS}%)"
    
    # Show breakdown by forecast hour
    echo ""
    echo "   Breakdown by forecast hour:"
    for hour in 0 24 48 72; do
        HOUR_FILES=$(ls -1 ${STORAGE_PATH}/gfs_${RUN_DATE}_${RUN_HOUR}_*_${hour}.png 2>/dev/null | wc -l || echo "0")
        if [ "$HOUR_FILES" -eq "$VARIABLES" ]; then
            echo "     f$(printf "%03d" $hour): ✅ ${HOUR_FILES}/${VARIABLES} complete"
        elif [ "$HOUR_FILES" -gt 0 ]; then
            echo "     f$(printf "%03d" $hour): ⚠️  ${HOUR_FILES}/${VARIABLES} partial"
        else
            echo "     f$(printf "%03d" $hour): ⏳ 0/${VARIABLES} waiting"
        fi
    done
else
    echo "📊 File Generation:"
    echo "   ⏳ No files generated yet (0/${EXPECTED_FILES})"
fi
echo ""

# Show latest files
if [ "$FILE_COUNT" -gt 0 ]; then
    echo "📁 Latest Generated Files:"
    ls -lt ${FILE_PATTERN} 2>/dev/null | head -5 | while read -r line; do
        if [ -n "$line" ]; then
            FILENAME=$(echo "$line" | awk '{print $NF}' | xargs basename)
            MTIME=$(echo "$line" | awk '{print $6, $7, $8}')
            echo "   ${FILENAME} (${MTIME})"
        fi
    done
    echo ""
fi

# Show recent log activity
echo "📝 Recent Log Activity (last 15 lines):"
if [ -f /var/log/twf-models-scheduler.log ]; then
    sudo tail -n 15 /var/log/twf-models-scheduler.log 2>/dev/null | sed 's/^/   /' || echo "   (Cannot read log file)"
else
    echo "   (Log file not found at /var/log/twf-models-scheduler.log)"
fi
echo ""

# Check for errors
if [ -f /var/log/twf-models-scheduler-error.log ]; then
    ERROR_COUNT=$(sudo tail -n 100 /var/log/twf-models-scheduler-error.log 2>/dev/null | grep -c "ERROR\|Exception\|Traceback" || echo "0")
    if [ "$ERROR_COUNT" -gt 0 ]; then
        echo "⚠️  Recent Errors (last 100 lines):"
        sudo tail -n 100 /var/log/twf-models-scheduler-error.log 2>/dev/null | grep -A 2 "ERROR\|Exception\|Traceback" | head -10 | sed 's/^/   /' || true
        echo ""
    fi
fi

# Calculate time since run
RUN_DATETIME="${RUN_DATE} ${RUN_HOUR}:00:00"
NOW_UTC=$(date -u +"%Y%m%d %H:%M:%S")
ELAPSED_MINUTES=$(($(date -u -d "${RUN_DATETIME}" +%s 2>/dev/null || date -u -j -f "%Y%m%d %H:%M:%S" "${RUN_DATETIME}" +%s 2>/dev/null || echo "0") - $(date -u -d "${NOW_UTC}" +%s 2>/dev/null || date -u -j -f "%Y%m%d %H:%M:%S" "${NOW_UTC}" +%s 2>/dev/null || echo "0")))
ELAPSED_MINUTES=$((ELAPSED_MINUTES / 60))
ELAPSED_MINUTES=${ELAPSED_MINUTES#-}  # Absolute value

if [ "$ELAPSED_MINUTES" -lt 90 ]; then
    echo "⏱️  Time Since Run: ${ELAPSED_MINUTES} minutes (scheduler active for up to 90 min)"
elif [ "$ELAPSED_MINUTES" -lt 240 ]; then
    echo "⏱️  Time Since Run: ${ELAPSED_MINUTES} minutes (scheduler should be complete)"
else
    echo "⏱️  Time Since Run: ${ELAPSED_MINUTES} minutes (old run)"
fi
echo ""

# Summary
if [ "$FILE_COUNT" -eq "$EXPECTED_FILES" ]; then
    echo "✅ Status: COMPLETE - All files generated"
    exit 0
elif [ "$FILE_COUNT" -gt 0 ]; then
    echo "🔄 Status: IN PROGRESS - ${FILE_COUNT}/${EXPECTED_FILES} files generated"
    exit 0
else
    echo "⏳ Status: WAITING - No files generated yet"
    exit 1
fi
