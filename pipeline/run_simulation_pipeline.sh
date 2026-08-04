#!/bin/bash
# ==============================================================================
#                 ICICI DIRECT FUTURES (F1) AUTOMATED SIMULATION PIPELINE
# ==============================================================================
set -e

# Export Node.js and system paths to guarantee compatibility with cron
export HOME="/home/ubuntu"
export PYTHONPATH="/home/ubuntu/.local/lib/python3.10/site-packages:$PYTHONPATH"
export PATH="/home/ubuntu/.nvm/versions/node/v18.20.8/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

# Change directory to the workspace root
_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
parent_dir="$(dirname "$_DIR")"
cd "$parent_dir"

echo "======================================================================="
echo "🚀 Starting Daily Futures Simulation Pipeline"
echo "Timestamp: $(date)"
echo "======================================================================="

# --- Detect Previous Trading Date from scrapdata_F1 ---
# Query MySQL for the latest date with ticks strictly before today.
# This handles Mondays (finds Friday), mid-week holidays, etc.
echo ""
echo "[Pre-Check] Detecting previous trading date from MySQL scrapdata_F1..."
PREV_TRADING_DATE=$(/home/ubuntu/venv/bin/python3 -c "
import mysql.connector
from datetime import datetime
try:
    conn = mysql.connector.connect(host='localhost', user='root', password='root', database='markets')
    cursor = conn.cursor()
    today_str = datetime.now().date().strftime('%Y-%m-%d')
    cursor.execute('SELECT MAX(date) FROM scrapdata_F1 WHERE date < %s', (today_str,))
    row = cursor.fetchone()
    cursor.close(); conn.close()
    if row and row[0]:
        print(row[0])
    else:
        from datetime import timedelta
        print((datetime.now().date() - timedelta(days=1)).strftime('%Y-%m-%d'))
except Exception as e:
    from datetime import timedelta, datetime
    print((datetime.now().date() - timedelta(days=1)).strftime('%Y-%m-%d'))
")

echo "[Pre-Check] ✔ Previous trading date detected: $PREV_TRADING_DATE"

# --- Step 1: Generate Yesterday's Target Orders ---
echo ""
echo "[Step 1/3] Generating target orders sheet for $PREV_TRADING_DATE..."
python3 pipeline/generatetodayorders.py

# --- Step 2: Clean existing data & Ingest Previous Trading Day's Futures Ticks ---
echo ""
echo "[Step 2/3] Fetching F1 ticks from ICICI Breeze for $PREV_TRADING_DATE & updating DB scrapdata_F1..."

# Delete any existing (partial or stale) data for the prev trading date first
echo "[Step 2/3] Cleaning any stale/partial data for $PREV_TRADING_DATE from DB..."
/home/ubuntu/venv/bin/python3 -c "
import mysql.connector
conn = mysql.connector.connect(host='localhost', user='root', password='root', database='markets')
cursor = conn.cursor()
cursor.execute('DELETE FROM scrapdata_F1 WHERE date = %s', ('$PREV_TRADING_DATE',))
conn.commit()
print(f'[DB Cleanup] Deleted {cursor.rowcount} stale rows for $PREV_TRADING_DATE from scrapdata_F1.')
cursor.close(); conn.close()
"

# Clear checkpoint so downloader never skips stocks due to a stale previous run
rm -f pipeline/checkpoint_F1*.json && echo "[DB Cleanup] All checkpoint files cleared for fresh download."

# Pass the detected dates explicitly to the downloaders
# Session renewal is handled automatically inside the JS scripts (calls 2.OTP_Amrit.py if expired)
echo "[Step 2/3] Downloading futures ticks to scrapdata_F1..."
TODAY_DATE=$(date +%Y-%m-%d)
node pipeline/8.icicidatawithsession_F1.js "$PREV_TRADING_DATE" "$TODAY_DATE"

# --- Step 2.5: Ingest Today's Morning Gap Features ---
echo ""
echo "[Step 2.5] Fetching Today's Opening Gaps via Yahoo Finance & ICICI Fallback..."
node pipeline/update_today_gaps_morning.js

# --- COMMENTED OUT: Preventing next-morning deletion and downgrade of live 181-stock cash ticks ---
# echo "[Step 2/3] Re-inserting previous trading day's equity ticks to scrapdata for $PREV_TRADING_DATE..."
# node pipeline/6.icici_daily_intraday_and_gap_custom.js "$PREV_TRADING_DATE"

# --- Step 3: Run Yesterday's PnL Simulation & Append to Master Sheet ---
echo ""
echo "[Step 3/3] Simulating trades for $PREV_TRADING_DATE and updating Master PnL sheet..."
python3 pipeline/simulateyesterdaypnl.py

# --- Step 4: Dispatch Resulting PnL Report via Telegram Bot ---
echo ""
echo "[Dispatch] Text report has been successfully dispatched directly via the Python simulation script."

echo ""
echo "======================================================================="
echo "🎉 SIMULATION PIPELINE RUN COMPLETED SUCCESSFULLY!"
echo "Timestamp: $(date)"
echo "======================================================================="
