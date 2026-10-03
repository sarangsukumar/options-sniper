#!/usr/bin/env bash
# ============================================================
#  New 0920 Scalp Pipeline — Shell Wrapper
#  Called by cron at 09:20:30 IST Mon-Fri
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIPELINE="$SCRIPT_DIR/new_live_0920_pipeline.py"
LOG_FILE="/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_shortsell_t1_2026/01_0920_Scalp_Model/live_production/cron_0920_scalp.log"

echo "=======================================================" >> "$LOG_FILE"
echo "  0920 SCALP PIPELINE START: $(date '+%Y-%m-%d %H:%M:%S')" >> "$LOG_FILE"
echo "=======================================================" >> "$LOG_FILE"

python3 "$PIPELINE" >> "$LOG_FILE" 2>&1

echo "  0920 SCALP PIPELINE END: $(date '+%Y-%m-%d %H:%M:%S')" >> "$LOG_FILE"
