#!/bin/bash
set -e

# Export Node.js and system paths to guarantee compatibility with cron / scheduler
export HOME="/home/ubuntu"
export PYTHONPATH="/home/ubuntu/.local/lib/python3.10/site-packages:${PYTHONPATH:-}"
export PATH="/home/ubuntu/.nvm/versions/node/v18.20.8/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

LOG_FILE="$DIR/cron_0920_reconcile.log"

echo "==========================================================================" >> "$LOG_FILE"
echo "[$(date '+%Y-%m-%d %H:%M:%S IST')] 📊 Running 09:20 Scalp Evening Reconciler" >> "$LOG_FILE"
echo "==========================================================================" >> "$LOG_FILE"

if python3 reconcile_0920_scalp_pnl.py >> "$LOG_FILE" 2>&1; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S IST')] ✔ 09:20 Scalp Reconciliation Completed Successfully." >> "$LOG_FILE"
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S IST')] ⚠️ Reconciliation encountered an issue." >> "$LOG_FILE"
fi
if python3 retrain_monthly_0920_scalp.py >> "$LOG_FILE" 2>&1; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S IST')] ✔ Daily Rolling 4-Freq Ensemble Checkpoints Refreshed." >> "$LOG_FILE"
fi
echo "" >> "$LOG_FILE"
