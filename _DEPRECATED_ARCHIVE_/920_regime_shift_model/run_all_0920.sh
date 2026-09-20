#!/bin/bash
set -e

echo "========================================"
echo " STEP 1: Generate Global Macro Features"
echo "========================================"
python3 0_generate_global_features.py

echo ""
echo "========================================"
echo " STEP 2: Extract 09:20 Ticks"
echo "========================================"
python3 1_extract_0920_features.py

echo ""
echo "========================================"
echo " STEP 3: Train Walk-Forward & Select Trades"
echo "========================================"
python3 2_run_0920_simulation.py

echo ""
echo "========================================"
echo " STEP 4: Bulletproof DB Audit (Neo 8L Cap)"
echo "========================================"
python3 3_bulletproof_db_audit_0920.py

echo "ALL DONE!"
