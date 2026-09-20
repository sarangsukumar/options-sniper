#!/bin/bash
# Champion Analysis Pipeline — Shell Wrapper
# Survives server restarts via PM2. Logs everything to /tmp/champion_pipeline.log

LOG="/tmp/champion_pipeline.log"
DIR="/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/historical_models"
BOT_TOKEN="5350311365:AAFkTUBR4IGvgS5Z9mJngz-mgk7-HkhFEYE"
CHAT_ID="-698073972"

tg_msg() {
    curl -s -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
        -d "chat_id=${CHAT_ID}&text=$1" > /dev/null 2>&1
}

tg_file() {
    curl -s -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendDocument" \
        -F "chat_id=${CHAT_ID}" \
        -F "document=@$1" \
        -F "caption=$2" > /dev/null 2>&1
}

run_step() {
    local label="$1"; shift
    local max_retries=3
    for attempt in $(seq 1 $max_retries); do
        echo "[$(date)] [${label}] Attempt ${attempt}/${max_retries}..." | tee -a "$LOG"
        cd "$DIR" && python3 "$@" >> "$LOG" 2>&1
        if [ $? -eq 0 ]; then
            echo "[$(date)] [${label}] SUCCESS" | tee -a "$LOG"
            return 0
        fi
        echo "[$(date)] [${label}] FAILED (attempt ${attempt})" | tee -a "$LOG"
        sleep 10
    done
    tg_msg "⚠️ [${label}] failed after ${max_retries} attempts."
    return 1
}

echo "============================================================" | tee -a "$LOG"
echo " CHAMPION PIPELINE STARTED: $(date)" | tee -a "$LOG"
echo "============================================================" | tee -a "$LOG"

tg_msg "🔧 Champion Analysis Pipeline started. Rebuilding daily cache + running analysis..."

# ── STEP 1: Wait for any existing daily rebuild to finish ─────────────────────
echo "[$(date)] Checking for existing daily rebuild process..." | tee -a "$LOG"
for i in $(seq 1 30); do
    if ! pgrep -f "dynamic_threshold.py daily" > /dev/null 2>&1; then
        echo "[$(date)] No daily process running. Proceeding." | tee -a "$LOG"
        break
    fi
    echo "[$(date)] Daily rebuild running... waiting 60s (check $i/30)" | tee -a "$LOG"
    sleep 60
done

# ── STEP 2: Check if daily CSV needs rebuild ──────────────────────────────────
DAILY_DATE=$(tail -1 "$DIR/output/trades_dynamic_threshold_daily.csv" 2>/dev/null | cut -d',' -f1)
echo "[$(date)] Daily CSV last date: ${DAILY_DATE}" | tee -a "$LOG"

if [[ "$DAILY_DATE" < "2026-08-04" ]]; then
    echo "[$(date)] STEP 1: Rebuilding daily cache..." | tee -a "$LOG"
    tg_msg "⚙️ Step 1/3: Rebuilding daily frequency cache (takes ~15 min)..."
    run_step "DAILY" dynamic_threshold.py daily
else
    echo "[$(date)] STEP 1: Daily CSV already fresh (${DAILY_DATE}). Skipping." | tee -a "$LOG"
fi

# ── STEP 3: Ensemble rebuild ─────────────────────────────────────────────────
echo "[$(date)] STEP 2: Rebuilding ensemble..." | tee -a "$LOG"
tg_msg "⚙️ Step 2/3: Rebuilding ensemble (combining all 5 frequencies)..."
run_step "ENSEMBLE" test_trimmed_adaptive_hybrid_pnl_noise_removed.py

# ── STEP 4: Full analysis + PDF + Telegram ───────────────────────────────────
echo "[$(date)] STEP 3: Running full YoY analysis (Max Orders 2,3,4)..." | tee -a "$LOG"
tg_msg "⚙️ Step 3/3: Running YoY analysis for Max Orders 2, 3, 4..."
run_step "ANALYSIS" full_yoy_analysis.py

echo "[$(date)] ALL STEPS COMPLETE" | tee -a "$LOG"
echo "============================================================" | tee -a "$LOG"
