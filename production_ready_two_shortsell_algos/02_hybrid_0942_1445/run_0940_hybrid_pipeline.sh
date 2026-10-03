#!/bin/bash
# run_0940_hybrid_pipeline.sh
# Production Master Runner for V6/V7 Hybrid Short Sell Strategy (09:42 - 14:45)
# Invoked at 09:41 AM IST Mon-Fri by daily_schedules.txt

set -e

# Export Node.js and system paths to guarantee compatibility with cron / scheduler
export HOME="/home/ubuntu"
export PYTHONPATH="/home/ubuntu/.local/lib/python3.10/site-packages:$PYTHONPATH"
export PATH="/home/ubuntu/.nvm/versions/node/v18.20.8/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
export TZ="Asia/Kolkata"

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

LOG_FILE="$DIR/cron_0940_hybrid.log"

echo "======================================================================" >> "$LOG_FILE"
echo "[$(date '+%Y-%m-%d %H:%M:%S IST')] 🚀 Starting 09:41 AM Hybrid Short-Sell Production Pipeline" >> "$LOG_FILE"
echo "======================================================================" >> "$LOG_FILE"

# Detect trading dates
TODAY_DATE=$(date +%Y-%m-%d)
PREV_TRADING_DATE=$(python3 -c "
import pymysql
conn = pymysql.connect(host='localhost', user='root', password='root', database='markets')
c = conn.cursor()
c.execute(\"SELECT MAX(date) FROM scrapdata_F1 WHERE date < '$TODAY_DATE'\")
row = c.fetchone()
print(str(row[0]) if row and row[0] else '$TODAY_DATE')
conn.close()
")

echo "• Today Date        : $TODAY_DATE" >> "$LOG_FILE"
echo "• Prev Trading Date : $PREV_TRADING_DATE" >> "$LOG_FILE"

# Step 1A: Download latest F1 ticks up to 09:40 into scrapdata_F1
echo "[Step 1A/2] Fetching F1 ticks up to 09:40 AM into scrapdata_F1..." >> "$LOG_FILE"
cd /home/ubuntu/daily_prediction_sytem_Dynamic_threshold
rm -f pipeline/checkpoint_F1*.json
if node pipeline/8.icicidatawithsession_F1.js "$TODAY_DATE" "$TODAY_DATE" >> "$LOG_FILE" 2>&1; then
    echo "✔ Step 1A (F1 Ticks Downloader) completed successfully." >> "$LOG_FILE"
else
    echo "⚠️ Warning: Step 1A encountered an issue — continuing with existing F1 DB ticks." >> "$LOG_FILE"
fi

# Step 1B: Download latest Cash (EQ) ticks up to 09:40 into scrapdata
echo "[Step 1B/2] Fetching Cash (EQ) ticks up to 09:40 AM into scrapdata (for Rule 1 simulation consistency)..." >> "$LOG_FILE"
rm -f /home/ubuntu/live_trading_setup_2026/checkpoint*.json
# Run the EQ downloader sequentially to avoid ICICI session/rate limit conflicts
if node /home/ubuntu/live_trading_setup_2026/3.icicidatawithsession_EQ.js "$TODAY_DATE" "$TODAY_DATE" "EQ" >> "$LOG_FILE" 2>&1; then
    echo "✔ Step 1B (EQ Ticks Downloader) completed successfully." >> "$LOG_FILE"
else
    echo "⚠️ Warning: Step 1B encountered an issue — Cash Rule 1 filter might skip stocks." >> "$LOG_FILE"
fi

# Step 2: Run 09:40 Hybrid ML Pipeline & Dispatch Telegram Alert
echo "[Step 2/2] Running 09:40 Hybrid ML Pipeline & Order Formulator..." >> "$LOG_FILE"
cd "$DIR"
if python3 live_0940_hybrid_pipeline.py >> "$LOG_FILE" 2>&1; then
    echo "✔ Step 2 (09:40 Hybrid ML Pipeline) completed successfully." >> "$LOG_FILE"
else
    echo "❌ Error: Step 2 failed." >> "$LOG_FILE"
    exit 1
fi

# Wait until exactly 09:42:00 before placing orders
echo "⏳ Waiting until exactly 09:42:00 IST to place orders..." >> "$LOG_FILE"
while [[ $(date +%H:%M:%S) < "09:42:00" ]]; do
    sleep 0.2
done

# Step 3: Trigger Kotak Order Placer
echo "[Step 3/3] Triggering Kotak Order Execution Script at $(date +%H:%M:%S)..." >> "$LOG_FILE"
cd /home/ubuntu/KotakCodes1
if python3 Neo_shortsell_mis_order.py 0942_HYBRID >> "$LOG_FILE" 2>&1; then
    echo "✔ Step 3 (Order Placement) completed successfully." >> "$LOG_FILE"
else
    echo "❌ Error: Step 3 (Order Placement) failed." >> "$LOG_FILE"
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S IST')] 🎉 09:41 AM Hybrid Short-Sell Pipeline Finished Successfully." >> "$LOG_FILE"
echo "" >> "$LOG_FILE"
