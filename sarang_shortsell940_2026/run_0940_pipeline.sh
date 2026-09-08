#!/bin/bash
# ==============================================================================
# 09:40 AM SHORT SELL PIPELINE (F&O FUTURES SCRAPDATA_F1)
# ==============================================================================

echo "--------------------------------------------------------"
echo "Starting 09:40 AM Short Sell Pipeline at $(date)"
echo "--------------------------------------------------------"

# 1. Download live Equity Cash ticks and F1 Futures ticks
echo "[1/3a] Downloading live Equity Cash ticks to scrapdata..."
node /home/ubuntu/daily_prediction_sytem_Dynamic_threshold/pipeline/6.icici_daily_intraday_and_gap.js

echo "[1/3b] Downloading live near-month F&O Futures ticks to scrapdata_F1..."
node /home/ubuntu/daily_prediction_sytem_Dynamic_threshold/pipeline/8.icicidatawithsession_F1.js
if [ $? -ne 0 ]; then
    echo "ERROR: ICICI F1 Futures Downloader failed!"
    exit 1
fi

# 2. Calculate Morning Technicals for Custom Limit Candidates from scrapdata_F1
echo "[2/3] Calculating 09:40 Morning Features from scrapdata_F1..."
python3 /home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_shortsell940_2026/src/compute_morning_0940_features.py
if [ $? -ne 0 ]; then
    echo "ERROR: Morning feature calculation failed!"
    exit 1
fi

# 3. Predict R1 to R5 Targets and Send to Telegram
echo "[3/3] Running ML Predictor & Sending Telegram Alerts..."
python3 /home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_shortsell940_2026/src/predict_live_0940.py
if [ $? -ne 0 ]; then
    echo "ERROR: ML Prediction failed!"
    exit 1
fi

echo "--------------------------------------------------------"
echo "09:40 AM Pipeline Completed Successfully!"
echo "--------------------------------------------------------"
