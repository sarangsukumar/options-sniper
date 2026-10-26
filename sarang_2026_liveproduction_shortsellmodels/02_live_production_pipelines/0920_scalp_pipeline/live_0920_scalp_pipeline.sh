#!/bin/bash
# live_0920_scalp_pipeline.sh
# ============================================================
# JOB 1 of 8 — Fired at 09:21 AM IST (+ 90s sleep = 09:22:30)
# Fetches morning ticks (09:15-09:19) from ICICI Breeze DB,
# runs ML prediction, sends Telegram alert, inserts orders into DB.
# ORDER PLACEMENT is handled by JOB 2 at exactly 09:25:00 AM.
# ============================================================

export HOME="/home/ubuntu"
export PYTHONPATH="/home/ubuntu/.local/lib/python3.10/site-packages:${PYTHONPATH:-}"
export PATH="/home/ubuntu/.nvm/versions/node/v18.20.8/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
export TZ="Asia/Kolkata"

DIR="/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/production_ready_two_shortsell_algos/01_scalp_0920_0940"
LOG_FILE="$DIR/cron_0920_scalp.log"

echo "==========================================================================" >> "$LOG_FILE"
echo "[$(date '+%Y-%m-%d %H:%M:%S IST')] 🚀 [JOB 1] 09:20 Scalp Prediction Pipeline Starting" >> "$LOG_FILE"
echo "==========================================================================" >> "$LOG_FILE"

# Step 1: Download live morning EQ cash ticks (09:15-09:19) from ICICI Breeze → markets.scrapdata
echo "[$(date '+%H:%M:%S')] Step 1: Fetching 09:15-09:19 Morning Cash Ticks..." >> "$LOG_FILE"
if node "$DIR/fetch_morning_eq_ticks.js" >> "$LOG_FILE" 2>&1; then
    echo "[$(date '+%H:%M:%S')] ✔ Step 1 (Morning Ticks) completed." >> "$LOG_FILE"
else
    echo "[$(date '+%H:%M:%S')] ⚠️ Step 1 warning — continuing with existing DB ticks." >> "$LOG_FILE"
fi

# Step 2: Run ML Prediction, rank Top 4, send Telegram alert, insert orders into DB
echo "[$(date '+%H:%M:%S')] Step 2: Running ML Inference + Telegram Alert + DB Insert..." >> "$LOG_FILE"
if python3 "$DIR/live_0920_scalp_pipeline.py" >> "$LOG_FILE" 2>&1; then
    echo "[$(date '+%H:%M:%S')] ✔ Step 2 (ML Pipeline) completed." >> "$LOG_FILE"
else
    echo "[$(date '+%H:%M:%S')] ❌ Step 2 FAILED." >> "$LOG_FILE"
    exit 1
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S IST')] ✅ [JOB 1] Prediction Pipeline Done. Orders ready for 09:25 execution." >> "$LOG_FILE"
echo "" >> "$LOG_FILE"
