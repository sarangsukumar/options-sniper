#!/bin/bash
# run_monthly_retrain.sh
# Half-Yearly (Jan 1 & Jul 1) Expanding Window Model Retrain Runner for 09:42 Hybrid Short Sell Strategy
# Invoked by daily_schedules.txt ('00 18 1 1,7 *')

set -e

export HOME="/home/ubuntu"
export PYTHONPATH="/home/ubuntu/.local/lib/python3.10/site-packages:${PYTHONPATH:-}"
export PATH="/home/ubuntu/.nvm/versions/node/v18.20.8/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
export TZ="Asia/Kolkata"

LIVE_DIR="/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_shortsell_t1_2026/02_0942_Hybrid_Model/live_production"
cd "$LIVE_DIR"

echo "======================================================================"
echo "[$(date '+%Y-%m-%d %H:%M:%S IST')] 🔁 Starting 09:40 Hybrid Model Half-Yearly Retrain (Jan 1 / Jul 1 Cutoff)"
echo "======================================================================"

python3 "$LIVE_DIR/live_0940_hybrid_pipeline.py" --retrain

echo "[$(date '+%Y-%m-%d %H:%M:%S IST')] ✅ 09:40 Hybrid Model Half-Yearly Retrain Completed Successfully."
