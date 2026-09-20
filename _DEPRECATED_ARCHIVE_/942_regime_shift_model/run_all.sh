#!/bin/bash
set -e

echo "========================================"
echo " STEP 1: Generate Global Macro Features"
echo "========================================"
python3 0_generate_global_features.py

echo ""
echo "========================================"
echo " STEP 2: Train ML & Run Strategy Simulation"
echo "========================================"
python3 1_run_ml_simulation.py

echo ""
echo "========================================"
echo " STEP 3: Tick-by-Tick DB Physical Audit"
echo "========================================"
python3 2_bulletproof_db_audit.py

echo "ALL DONE!"
