#!/bin/bash
# ==============================================================================
# run_1600_daily_data_fill.sh
# -----------------------------
# Automation runner for filling the complete day's ticks from 09:15 to 15:30.
# Runs at 16:00 PM IST post market close.
# ==============================================================================

set -e

# Export Node.js and system paths to guarantee compatibility with cron
export HOME="/home/ubuntu"
export PYTHONPATH="/home/ubuntu/.local/lib/python3.10/site-packages:$PYTHONPATH"
export PATH="/home/ubuntu/.nvm/versions/node/v18.20.8/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
PARENT_DIR="$(dirname "$(dirname "$DIR")")"
cd "$PARENT_DIR"

TARGET_DATE="${1:-$(date +%Y-%m-%d)}"

echo "=============================================================================="
echo "🕒 Starting 16:00 Daily Data Fill Pipeline at $(date)"
echo "Target Date: $TARGET_DATE"
echo "=============================================================================="

# Clear any stale evening checkpoint files
rm -f pipeline/checkpoint_F1_evening*.json

echo -e "\n[STEP 1/2] Fetching complete Futures (F1) ticks into scrapdata_F1..."
node pipeline/1600_daily_data_fill_F1.js "$TARGET_DATE" "$TARGET_DATE"

echo -e "\n[STEP 2/2] Fetching complete Cash Equity ticks into scrapdata..."
node pipeline/1600_daily_data_fill_EQ.js "$TARGET_DATE"

echo "=============================================================================="
echo "🏁 Daily Data Fill Pipeline completed successfully at $(date)"
echo "=============================================================================="
