#!/bin/bash
# Master Multi-Strike Options Downloader (2026, 2025, 2024)

cd /home/ubuntu/daily_prediction_sytem_Dynamic_threshold/options_backtest

echo "=============================================="
echo "  MULTI-STRIKE OPTIONS DATA DOWNLOAD (2024-2026)"
echo "=============================================="
echo "Started at: $(date)"
echo ""

for YEAR in 2026 2025 2024; do
    echo "=============================="
    echo "  Downloading Multi-Strikes: $YEAR"
    echo "=============================="
    node download_multi_strike_options.js $YEAR
    echo ""
    echo "[$YEAR] Multi-strike download done. Sleeping 10s..."
    sleep 10
done

echo ""
echo "=============================================="
echo "  ALL MULTI-STRIKE DOWNLOADS COMPLETE! $(date)"
echo "=============================================="
