#!/bin/bash
echo "Starting experimental option targets download for all years..."
node download_experiment_options.js 2024 > download_experiment_2024.log 2>&1
node download_experiment_options.js 2025 > download_experiment_2025.log 2>&1
node download_experiment_options.js 2026 > download_experiment_2026.log 2>&1
echo "Download complete. Running backtest simulation..."
python3 backtest_experiment.py > backtest_experiment.log 2>&1
echo "Backtest complete. Generating PDF and pushing to Telegram..."
python3 make_experiment_pdf_and_send.py > telegram_push.log 2>&1
echo "Done!"
