#!/bin/bash
# ==============================================================================
# run_0940_evening_reconcile.sh
# -----------------------------
# Automation runner for the 09:40-14:45 Hybrid Short-Sell Evening Reconciler.
# Runs at 14:48 PM / 15:30 PM IST post market close.
# ==============================================================================

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

echo "=============================================================================="
echo "🕒 Starting 09:40 Hybrid Evening Reconciler at $(date)"
echo "=============================================================================="

TODAY_IST=$(TZ=Asia/Kolkata date '+%Y-%m-%d')

if [ $# -eq 0 ]; then
    ARGS=(--date "$TODAY_IST" --force-all)
else
    ARGS=("$@")
fi

/usr/bin/python3 "$DIR/reconcile_0940_hybrid_pnl.py" --no-telegram "${ARGS[@]}"
/usr/bin/python3 "$DIR/reconcile_0940_live_mimic_pnl.py" "${ARGS[@]}"

EXIT_CODE=$?
echo "=============================================================================="
echo "🏁 Reconciler finished with exit code $EXIT_CODE at $(date)"
echo "=============================================================================="
exit $EXIT_CODE
