#!/usr/bin/env bash
set -e

export HOME="/home/ubuntu"
export PYTHONPATH="/home/ubuntu/.local/lib/python3.10/site-packages:$PYTHONPATH"
export PATH="/home/ubuntu/.nvm/versions/node/v18.20.8/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
export TZ="Asia/Kolkata"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIPELINE="$SCRIPT_DIR/new_live_0940_pipeline.py"
LOG_FILE="$SCRIPT_DIR/cron_0940_hybrid.log"

TODAY_DATE=$(date +%Y-%m-%d)

echo "=======================================================" >> "$LOG_FILE"
echo "  0940 HYBRID PIPELINE START: $(date '+%Y-%m-%d %H:%M:%S')" >> "$LOG_FILE"
echo "=======================================================" >> "$LOG_FILE"

echo "[Step 1A] Fetching F1 ticks up to 09:40 AM into scrapdata_F1..." >> "$LOG_FILE"
cd /home/ubuntu/daily_prediction_sytem_Dynamic_threshold
rm -f pipeline/checkpoint_F1*.json
if node pipeline/8.icicidatawithsession_F1.js "$TODAY_DATE" "$TODAY_DATE" >> "$LOG_FILE" 2>&1; then
    echo "✔ Step 1A completed successfully." >> "$LOG_FILE"
else
    echo "⚠️ Warning: Step 1A failed." >> "$LOG_FILE"
fi

echo "[Step 1B] Fetching Cash (EQ) ticks up to 09:40 AM into scrapdata..." >> "$LOG_FILE"
rm -f /home/ubuntu/live_trading_setup_2026/checkpoint*.json
if node /home/ubuntu/live_trading_setup_2026/3.icicidatawithsession_EQ.js "$TODAY_DATE" "$TODAY_DATE" "EQ" >> "$LOG_FILE" 2>&1; then
    echo "✔ Step 1B completed successfully." >> "$LOG_FILE"
else
    echo "⚠️ Warning: Step 1B failed." >> "$LOG_FILE"
fi

echo "[Step 2] Running 09:40 Pipeline (ML Prediction + DB Insert)..." >> "$LOG_FILE"
cd "$SCRIPT_DIR"
if python3 "$PIPELINE" >> "$LOG_FILE" 2>&1; then
    echo "✔ Step 2 completed successfully." >> "$LOG_FILE"
else
    echo "❌ Error: Step 2 failed." >> "$LOG_FILE"
fi

echo "⏳ Waiting until exactly 09:42:00 IST to place orders..." >> "$LOG_FILE"
while [[ $(date +%H:%M:%S) < "09:42:00" ]]; do
    sleep 0.2
done

echo "[Step 3] Triggering Kotak Order Execution Script (09:42 SELL Entry)..." >> "$LOG_FILE"
cd /home/ubuntu/KotakCodes1
if python3 Neo_shortsell_mis_order.py 0942_HYBRID >> "$LOG_FILE" 2>&1; then
    echo "✔ Step 3 completed successfully." >> "$LOG_FILE"
else
    echo "❌ Error: Step 3 failed." >> "$LOG_FILE"
fi

echo "  0940 HYBRID PIPELINE END: $(date '+%Y-%m-%d %H:%M:%S')" >> "$LOG_FILE"
