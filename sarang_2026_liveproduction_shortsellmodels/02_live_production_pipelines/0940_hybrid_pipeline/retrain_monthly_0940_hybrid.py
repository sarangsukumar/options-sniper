#!/usr/bin/env python3
"""
retrain_monthly_0940_hybrid.py
------------------------------
Half-Yearly Expanding Walk-Forward Retraining Wrapper for the 09:40 / 09:42 Hybrid Short-Sell Model.
Delegates directly to `live_0940_hybrid_pipeline.retrain_model()`, which enforces:
  - Half-Yearly Cutoff (`< YYYY-01-01` for H1 Jan–Jun; `< YYYY-07-01` for H2 Jul–Dec)
  - 12 Rebound-Aware Features (`FEATURES_12`)
  - Rebound-Aware Target (`target_adj = short_return - 0.50 * max(0, max_rebound - 1.50)`)
  - Saves production booster to `lgb_0940_rebound_aware_audited_model.txt`
"""
import os
import sys

DIR = os.path.dirname(os.path.abspath(__file__))
if DIR not in sys.path:
    sys.path.insert(0, DIR)

from live_0940_hybrid_pipeline import retrain_model

if __name__ == "__main__":
    retrain_model()
