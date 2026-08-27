#!/bin/bash
set -e

DIR="/home/ubuntu/daily_prediction_system_Dynamic_threshold_Backtest_Dev/historical_models"
cd "$DIR"

echo "Clearing all old prediction caches to force clean retrain..."
rm -f output/wf_predictions_cache_*.pkl

export START_YEAR=2019
export END_YEAR=2026
export REMOVE_EXTREME_TRAINING_LOSSES=True
export NOISE_CLEANING_METHOD=static_10
export DISABLE_PDF=True

echo "=========================================================================="
echo "          REBUILDING ALL HISTORICAL CACHES FROM SCRATCH IN PARALLEL"
echo "=========================================================================="

echo "[$(date)] Spawning 5 parallel frequency rebuilds..."

python3 dynamic_threshold.py yearly > /tmp/dev_rebuild_yearly.log 2>&1 &
python3 dynamic_threshold.py quarterly > /tmp/dev_rebuild_quarterly.log 2>&1 &
python3 dynamic_threshold.py monthly > /tmp/dev_rebuild_monthly.log 2>&1 &
python3 dynamic_threshold.py weekly > /tmp/dev_rebuild_weekly.log 2>&1 &
python3 dynamic_threshold.py daily > /tmp/dev_rebuild_daily.log 2>&1 &

wait

echo "[$(date)] All frequency rebuilds complete!"
echo "[$(date)] Running ensemble..."
python3 test_trimmed_adaptive_hybrid_pnl_noise_removed.py > /tmp/dev_rebuild_ensemble.log 2>&1

echo "[$(date)] Running full YoY analysis..."
python3 full_yoy_analysis.py > /tmp/dev_rebuild_analysis.log 2>&1

echo "[$(date)] Done!"
