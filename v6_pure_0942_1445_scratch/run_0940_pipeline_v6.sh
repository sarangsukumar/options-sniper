#!/bin/bash
# run_0940_pipeline_v6.sh
# Triggers Model v6 Live Prediction & Telegram Bot Alert at 09:41 AM IST Mon-Fri
cd /home/ubuntu/daily_prediction_sytem_Dynamic_threshold/v6_pure_0942_1445_scratch/src/
python3 5_send_telegram_v6.py >> /home/ubuntu/daily_prediction_sytem_Dynamic_threshold/v6_pure_0942_1445_scratch/output/cron_0940_pipeline.log 2>&1
