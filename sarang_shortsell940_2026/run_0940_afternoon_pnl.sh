#!/bin/bash
# ==============================================================================
#      AFTERNOON SHORT SELL PNL SIMULATION & TELEGRAM DISPATCH PIPELINE
#                      Scheduled Daily at 14:48 IST
# ==============================================================================
set -e

# Export paths for cron compatibility
export HOME="/home/ubuntu"
export PYTHONPATH="/home/ubuntu/.local/lib/python3.10/site-packages:$PYTHONPATH"
export PATH="/home/ubuntu/.nvm/versions/node/v18.20.8/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
parent_dir="$(dirname "$_DIR")"
cd "$parent_dir"

TODAY_DATE=$(date +%Y-%m-%d)

echo "======================================================================="
echo "🚀 Starting Afternoon Short Sell PnL Pipeline for $TODAY_DATE"
echo "Timestamp: $(date)"
echo "======================================================================="

# --- Step 1: Clean Today's data in scrapdata_F1 (Leaves yesterday untouched!) ---
echo ""
echo "[Step 1/3] Cleaning partial morning data for $TODAY_DATE from scrapdata_F1..."
/home/ubuntu/venv/bin/python3 -c "
import mysql.connector
from datetime import datetime
today_str = datetime.now().date().strftime('%Y-%m-%d')
conn = mysql.connector.connect(host='localhost', user='root', password='root', database='markets')
cursor = conn.cursor()
cursor.execute('DELETE FROM scrapdata_F1 WHERE date = %s', (today_str,))
conn.commit()
print(f'[DB Cleanup] Deleted {cursor.rowcount} rows for {today_str} from scrapdata_F1. (Previous day data remains 100% untouched).')
cursor.close(); conn.close()
"

# Clear any lingering checkpoint files
rm -f pipeline/checkpoint_F1*.json && echo "[DB Cleanup] Checkpoint files cleared for fresh download."

# --- Step 2: Ingest Today's F1 Data up to 14:45 using official F1 loader ---
echo ""
echo "[Step 2/3] Fetching full F1 ticks for $TODAY_DATE from ICICI Breeze & inserting into scrapdata_F1..."
node pipeline/8.icicidatawithsession_F1.js "$TODAY_DATE" "$TODAY_DATE"

# --- Step 3: Run Today's Simulation & Dispatch Report to Telegram ---
echo ""
echo "[Step 3/3] Simulating today's 09:41 short sell targets & generating Telegram report..."
python3 sarang_shortsell940_2026/src/simulate_today_shortsell.py

echo ""
echo "======================================================================="
echo "🎉 AFTERNOON SHORT SELL PNL PIPELINE COMPLETED SUCCESSFULLY!"
echo "Timestamp: $(date)"
echo "======================================================================="
