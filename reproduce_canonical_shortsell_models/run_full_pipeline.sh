#!/bin/bash
set -e

echo "=========================================================================================="
echo "👑 CANONICAL SHORT-SELL MODELS: PURE MYSQL REBUILD & CERTIFICATION PIPELINE (2018 - 2026)"
echo "=========================================================================================="
echo "Zero Pre-existing Files. Zero Lookahead Bias. 100% Extracted from MySQL 'scrapdata'."
echo "=========================================================================================="

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo ""
echo ">>> STEP 1/5: Extracting 09:20 Scalp Features from MySQL (2018 - 2026)..."
python3 "$DIR/01_0920_scalp/01_extract_0920_from_mysql.py"

echo ""
echo ">>> STEP 2/5: Running 09:20 Walk-Forward Training & MySQL Tick Audit (2020 - 2026)..."
python3 "$DIR/01_0920_scalp/02_train_and_audit_0920.py"

echo ""
echo ">>> STEP 3/5: Extracting 09:40 Hybrid Features from MySQL (2018 - 2026)..."
python3 "$DIR/02_0940_hybrid/01_extract_0940_from_mysql.py"

echo ""
echo ">>> STEP 4/5: Running 09:40 Strategy 4 Walk-Forward Training & Tick Audit..."
python3 "$DIR/02_0940_hybrid/02_train_and_audit_0940.py"

echo ""
echo ">>> STEP 5/5: Running 09:40 14:00 (2:00 PM) 50/50 Profit Booking Verification..."
python3 "$DIR/02_0940_hybrid/03_verify_1400_5050.py"

echo ""
echo "=========================================================================================="
echo "✅ PIPELINE COMPLETE: Both models successfully extracted, trained, and certified!"
echo "=========================================================================================="
