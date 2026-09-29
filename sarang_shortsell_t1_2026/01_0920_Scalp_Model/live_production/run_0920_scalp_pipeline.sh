#!/bin/bash
set -e

# Export Node.js and system paths to guarantee compatibility with cron / scheduler
export HOME="/home/ubuntu"
export PYTHONPATH="/home/ubuntu/.local/lib/python3.10/site-packages:$PYTHONPATH"
export PATH="/home/ubuntu/.nvm/versions/node/v18.20.8/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
export TZ="Asia/Kolkata"

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

# Wait 15 seconds to ensure ICICI has the 09:23 minute candle
sleep 15

LOG_FILE="$DIR/cron_0920_scalp.log"

echo "==========================================================================" >> "$LOG_FILE"
echo "[$(date '+%Y-%m-%d %H:%M:%S IST')] 🚀 Starting 09:24:15 AM Scalp Production Pipeline" >> "$LOG_FILE"
echo "==========================================================================" >> "$LOG_FILE"

# Step 1: Download live morning EQ cash ticks (09:15:00 - 09:19:59) from ICICI Breeze into markets.scrapdata
echo "[Step 1/2] Fetching 09:15 - 09:23 Morning Cash Ticks into scrapdata..." >> "$LOG_FILE"
if node fetch_morning_eq_ticks.js >> "$LOG_FILE" 2>&1; then
    echo "✔ Step 1 (Morning Ticks Downloader) completed successfully." >> "$LOG_FILE"
else
    echo "⚠️ Warning: Step 1 encountered an issue — continuing with existing DB ticks." >> "$LOG_FILE"
fi

# Step 2: Run Machine Learning Prediction, Rank Top 4, and Dispatch Telegram Alert
echo "[Step 2/2] Running Scalp ML Inference, Top 4 Selection, and Telegram Alert..." >> "$LOG_FILE"
if python3 live_0920_scalp_pipeline.py >> "$LOG_FILE" 2>&1; then
    echo "✔ Step 2 (ML Scalp Pipeline & Telegram Alert) completed successfully." >> "$LOG_FILE"
else
    echo "❌ Error: Step 2 failed." >> "$LOG_FILE"
    exit 1
fi

# Step 3: Wait until exactly 09:25:00 IST to hit the Goldilocks execution peak
echo "[Step 3/4] Waiting until exactly 09:25:00 IST to execute orders..." >> "$LOG_FILE"
while [[ $(date +%H:%M:%S) < "09:25:00" ]]; do
    sleep 0.5
done
echo "✔ Reached 09:25:00 IST. Firing Kotak API." >> "$LOG_FILE"

# Step 4: Trigger Kotak Order Placer
echo "[Step 4/4] Triggering Kotak Order Execution Script..." >> "$LOG_FILE"
cd /home/ubuntu/KotakCodes1
if python3 Neo_shortsell_mis_order.py 0920_SCALP >> "$LOG_FILE" 2>&1; then
    echo "✔ Step 4 (Order Placement) completed successfully." >> "$LOG_FILE"
else
    echo "❌ Error: Step 4 (Order Placement) failed." >> "$LOG_FILE"
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S IST')] 🎉 09:20 Scalp Production Pipeline Finished Successfully." >> "$LOG_FILE"
echo "" >> "$LOG_FILE"
