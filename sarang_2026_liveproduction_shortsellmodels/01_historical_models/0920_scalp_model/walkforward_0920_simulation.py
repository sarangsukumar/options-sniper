#!/usr/bin/env python3
"""
walkforward_0920_simulation.py
========================================================================================
TRUE EXPANDING WALK-FORWARD HISTORICAL SIMULATION OF CURRENT 09:20 SHORT-SELL PIPELINE
UPDATED WITH 50/50 SPLIT ORDER EXECUTION ARCHITECTURE (2020 - 2026)
========================================================================================
Note: The previous pre-50/50 implementation is backed up at:
      walkforward_0920_simulation.py.bak_pre_5050

This canonical runner executes the exact 50/50 split order fill logic matching live
production:
  - Leg 1 (50% Qty): ₹2,000 Limit TP placed at 09:27:00
  - Cadence Window (09:36:00 to 09:39:59): Monitors open position net profit >= ₹500
  - Leg 2 (50% Qty) / Open positions: Hard square-off at 09:40:00
  - Hard Stop-Loss: 2.0%
  - Realistic Kotak institutional taxes & brokerage per leg
========================================================================================
"""

import os
import sys

# Ensure current directory is on sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from walkforward_0920_5050_pipeline import main as run_5050_pipeline

if __name__ == '__main__':
    run_5050_pipeline()
