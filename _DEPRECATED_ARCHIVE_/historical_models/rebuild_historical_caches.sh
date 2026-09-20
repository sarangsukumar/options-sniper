#!/bin/bash
set -e

# Activate python virtual environment
if [ -f "/home/ubuntu/venv/bin/activate" ]; then
    source /home/ubuntu/venv/bin/activate
fi

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

cd "$DIR"

echo "=========================================================================="
echo "          REBUILDING HISTORICAL CACHES FROM SCRATCH"
echo "=========================================================================="

export REMOVE_EXTREME_TRAINING_LOSSES=False
export NOISE_CLEANING_METHOD=static_10
export START_YEAR=2019
export END_YEAR=2026
export DISABLE_PDF=True

echo "[1/5] Rebuilding 'yearly' cache..."
python3 dynamic_threshold.py yearly

echo "[2/5] Rebuilding 'quarterly' cache..."
python3 dynamic_threshold.py quarterly

echo "[3/5] Rebuilding 'monthly' cache..."
python3 dynamic_threshold.py monthly

echo "[4/5] Rebuilding 'weekly' cache..."
python3 dynamic_threshold.py weekly

echo "[5/5] Rebuilding 'daily' cache..."
python3 dynamic_threshold.py daily

echo "=========================================================================="
echo "          ALL FREQUENCY CACHES SUCCESSFULLY REBUILT!"
echo "=========================================================================="
echo "Running final ensemble simulation and generating the premium report..."
python3 test_trimmed_adaptive_hybrid_pnl_noise_removed.py

echo "🎉 Historical Model Rebuild Completed Successfully!"
