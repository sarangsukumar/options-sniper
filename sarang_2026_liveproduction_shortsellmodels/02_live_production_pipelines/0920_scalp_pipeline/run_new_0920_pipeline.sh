#!/usr/bin/env bash
set -euo pipefail

export HOME="/home/ubuntu"
export PYTHONPATH="/home/ubuntu/.local/lib/python3.10/site-packages:${PYTHONPATH:-}"
export PATH="/home/ubuntu/.nvm/versions/node/v18.20.8/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
export TZ="Asia/Kolkata"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIPELINE="$SCRIPT_DIR/new_live_0920_pipeline.py"
LOG_FILE="$SCRIPT_DIR/cron_0920_scalp.log"

echo "=======================================================" >> "$LOG_FILE"
echo "  0920 SCALP PIPELINE START: $(date '+%Y-%m-%d %H:%M:%S')" >> "$LOG_FILE"
echo "=======================================================" >> "$LOG_FILE"

# Broadcast Pipeline Armed Alert to Telegram (has 120s cooldown against duplicate)
python3 /home/ubuntu/KotakCodes1/notify_pipeline_armed.py 0920 >> "$LOG_FILE" 2>&1 || true

echo "[Step 1] Fetching 09:15 - 09:23 Morning Cash Ticks into scrapdata..." >> "$LOG_FILE"
cd "$SCRIPT_DIR"
if node fetch_morning_eq_ticks.js >> "$LOG_FILE" 2>&1; then
    echo "✔ Step 1 completed successfully." >> "$LOG_FILE"
else
    echo "⚠️ Warning: Step 1 failed, continuing with existing DB ticks." >> "$LOG_FILE"
fi

echo "[Step 2] Running 09:20 Pipeline (ML Prediction + DB Insert)..." >> "$LOG_FILE"
if python3 "$PIPELINE" >> "$LOG_FILE" 2>&1; then
    echo "✔ Step 2 completed successfully." >> "$LOG_FILE"
else
    echo "❌ Error: Step 2 failed." >> "$LOG_FILE"
fi

echo "  0920 SCALP PIPELINE END: $(date '+%Y-%m-%d %H:%M:%S')" >> "$LOG_FILE"
