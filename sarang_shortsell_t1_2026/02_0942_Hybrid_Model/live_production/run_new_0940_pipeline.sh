#!/usr/bin/env bash
# ============================================================
#  New 0940 Hybrid Pipeline — Shell Wrapper
#  Called by cron at 09:41:30 IST Mon-Fri
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIPELINE="$SCRIPT_DIR/new_live_0940_pipeline.py"
LOG_FILE="/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_shortsell_t1_2026/02_0942_Hybrid_Model/live_production/cron_0940_hybrid.log"

echo "=======================================================" >> "$LOG_FILE"
echo "  0940 HYBRID PIPELINE START: $(date '+%Y-%m-%d %H:%M:%S')" >> "$LOG_FILE"
echo "=======================================================" >> "$LOG_FILE"

python3 "$PIPELINE" >> "$LOG_FILE" 2>&1

echo "  0940 HYBRID PIPELINE END: $(date '+%Y-%m-%d %H:%M:%S')" >> "$LOG_FILE"
