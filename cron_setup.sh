#!/bin/bash
# ═══════════════════════════════════════════════════════════
# Morning Brief — Cron Setup
# Installs a daily cron job at 10:00 AM Pacific Time
# ═══════════════════════════════════════════════════════════

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_PATH=$(which python3)
MAIN_SCRIPT="${SCRIPT_DIR}/src/main.py"
LOG_DIR="${SCRIPT_DIR}/logs"

echo "Morning Brief — Cron Setup"
echo "=========================="
echo ""
echo "Project directory: ${SCRIPT_DIR}"
echo "Python:           ${PYTHON_PATH}"
echo "Main script:      ${MAIN_SCRIPT}"
echo ""

# Create logs directory
mkdir -p "${LOG_DIR}"

# Detect timezone offset for Pacific Time
# PDT (Mar-Nov) = UTC-7, PST (Nov-Mar) = UTC-8
# 10:00 AM PDT = 17:00 UTC, 10:00 AM PST = 18:00 UTC
# We'll use 17:00 UTC (10 AM PDT) as default; adjust manually if needed
UTC_HOUR=17

echo "Scheduling for 10:00 AM Pacific Time (${UTC_HOUR}:00 UTC)"
echo ""

# Build the cron line
# Include ANTHROPIC_API_KEY if set
CRON_ENV=""
if [ -n "$ANTHROPIC_API_KEY" ]; then
    CRON_ENV="ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY} "
fi

CRON_LINE="0 ${UTC_HOUR} * * * cd ${SCRIPT_DIR} && ${CRON_ENV}${PYTHON_PATH} ${MAIN_SCRIPT} >> ${LOG_DIR}/morning-brief.log 2>&1"

echo "Cron entry to add:"
echo "  ${CRON_LINE}"
echo ""

read -p "Add this to your crontab? (y/n) " -n 1 -r
echo ""

if [[ $REPLY =~ ^[Yy]$ ]]; then
    # Add to crontab without duplicates
    (crontab -l 2>/dev/null | grep -v "morning-brief" || true; echo "${CRON_LINE}") | crontab -
    echo "✅ Cron job installed!"
    echo ""
    echo "Verify with: crontab -l"
    echo "Logs will be at: ${LOG_DIR}/morning-brief.log"
else
    echo "Skipped. You can add it manually:"
    echo "  crontab -e"
    echo "  # Add: ${CRON_LINE}"
fi

echo ""
echo "To test immediately:"
echo "  python3 src/main.py --dry-run"
echo ""
echo "To uninstall:"
echo "  crontab -l | grep -v morning-brief | crontab -"
