#!/bin/bash
# ==============================================================================
# run_0940_live_mimic_reconcile.sh
# --------------------------------
# Automation runner for the 09:42 Live Mimic Evening Reconciler.
# Mimics actual live execution:
#   - 2.0% TP + 2.25% SL
#   - +0.50% Rebound Re-entry
#   - 1.75% TP2 + Breakeven SL
#   - 14:30 discount cover
# Runs at 16:15 PM IST post market close (right after the 16:10 base reconciler).
# ==============================================================================

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

echo "=============================================================================="
echo "🕒 Starting 09:42 Live Mimic Evening Reconciler at $(date)"
echo "=============================================================================="

/usr/bin/python3 "$DIR/reconcile_0940_live_mimic_pnl.py" "$@"

EXIT_CODE=$?
echo "=============================================================================="
echo "🏁 Mimic Reconciler finished with exit code $EXIT_CODE at $(date)"
echo "=============================================================================="
exit $EXIT_CODE
