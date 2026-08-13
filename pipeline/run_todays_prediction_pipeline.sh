#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

# Export Node.js and system paths to guarantee compatibility with cron
export HOME="/home/ubuntu"
export PYTHONPATH="/home/ubuntu/.local/lib/python3.10/site-packages:$PYTHONPATH"
export PATH="/home/ubuntu/.nvm/versions/node/v18.20.8/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

# Identify script directory and switch to its parent directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
PARENT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PARENT_DIR"

# --- Auto-heal and Sync CSV Data Files from MySQL ---
python3 pipeline/self_heal_production_data.py


echo "========================================================================="
echo "               ICICI DIRECT ML - UNIFIED TRADING PIPELINE"
echo "========================================================================="
echo "Started at: $(date)"
echo "Working Directory: $PARENT_DIR"
echo "========================================================================="

# Step 0: Merge yesterday's actual trade results into master files
echo -e "\n🔀 [STEP 0/4] Merging Yesterday's Actual PnL into Master Files..."
if python3 pipeline/merge_actuals.py; then
    echo "✔ Step 0 completed successfully."
else
    echo "⚠️  Warning: Step 0 (merge_actuals) encountered an error — continuing anyway."
fi

# Step 1: Run ICICI Daily Downloader (Node.js)
echo -e "\n🚀 [STEP 1/4] Fetching Live Ticks & Daily Gap Details..."
if node pipeline/6.icici_daily_intraday_and_gap.js; then
    echo "✔ Step 1 completed successfully."
else
    echo "❌ Error: Step 1 (ICICI Downloader) failed. Aborting pipeline."
    exit 1
fi

# Step 2: Compute Live Intraday Features (Python)
echo -e "\n🚀 [STEP 2/4] Computing Live Intraday Features..."
if python3 pipeline/compute_f11_intraday_features_update.py; then
    echo "✔ Step 2 completed successfully."
else
    echo "❌ Error: Step 2 (F11 Feature Computation) failed. Aborting pipeline."
    exit 1
fi

# Step 3: Run Walk-Forward Retraining & Predictions (Python)
echo -e "\n🚀 [STEP 3/4] Running Walk-Forward Predictions..."
if python3 predict_today.py --retrain-freq ensemble; then
    echo "✔ Step 3 completed successfully."
else
    echo "❌ Error: Step 3 (Predictions Generator) failed."
    exit 1
fi

echo -e "\n========================================================================="
echo "🎉 Pipeline execution finished successfully!"
echo "Completed at: $(date)"
echo "========================================================================="
