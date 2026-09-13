#!/bin/bash
# run_0940_hybrid_pipeline.sh
# Production Master Runner for V6/V7 Hybrid Short Sell Strategy (09:42 - 14:45)
# Invoked at 09:41 AM IST Mon-Fri by daily_schedules.txt

set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

echo "======================================================================"
echo "[$(date '+%Y-%m-%d %H:%M:%S IST')] Triggering 09:40 AM Hybrid Pipeline"
echo "======================================================================"

python3 live_0940_hybrid_pipeline.py >> "$DIR/cron_0940_hybrid.log" 2>&1

echo "[$(date '+%Y-%m-%d %H:%M:%S IST')] Pipeline finished with exit code $?"
