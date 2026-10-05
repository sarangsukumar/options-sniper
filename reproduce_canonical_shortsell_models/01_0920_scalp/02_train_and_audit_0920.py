#!/usr/bin/env python3
"""
Master runner for 09:20 Scalp Model walk-forward training and tick-by-tick audit.
"""
import subprocess
import sys
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

print(">>> [09:20 STEP 1/2] Training Expanding Window Walk-Forward LightGBM Model...", flush=True)
cmd1 = [sys.executable, os.path.join(SCRIPT_DIR, '1_build_features_and_train.py')] + sys.argv[1:]
res1 = subprocess.run(cmd1, cwd=SCRIPT_DIR)
if res1.returncode != 0:
    sys.exit(res1.returncode)

print("\n>>> [09:20 STEP 2/2] Auditing Trades Tick-by-Tick Against MySQL scrapdata...", flush=True)
res2 = subprocess.run([
    sys.executable,
    os.path.join(SCRIPT_DIR, '2_db_tick_verification.py'),
    '0920_predictions.csv',
    '0920_verified_pnl_sheet.csv'
], cwd=SCRIPT_DIR)
if res2.returncode != 0:
    sys.exit(res2.returncode)

print("\n✅ 09:20 Scalp Model Walk-Forward Audit Complete!")
