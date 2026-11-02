#!/bin/bash
set -e
cd /home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_shortsell_t1_2026/01_0920_Scalp_Model
echo "=== [$(date)] Starting 09:20 Scalp Half-Yearly Retrain ===" >> retrain_half_yearly.log
python3 0_extract_0920_dataset.py >> retrain_half_yearly.log 2>&1
python3 1_build_features_and_train.py >> retrain_half_yearly.log 2>&1
python3 live_production/retrain_monthly_0920_scalp.py >> retrain_half_yearly.log 2>&1
echo "=== [$(date)] Completed 09:20 Scalp Half-Yearly Retrain ===" >> retrain_half_yearly.log
