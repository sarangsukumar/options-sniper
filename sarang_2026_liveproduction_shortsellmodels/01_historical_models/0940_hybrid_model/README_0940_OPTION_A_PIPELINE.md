# 09:40 / 09:42 Short-Sell Hybrid Model: Option A Production Pipeline

This directory is the verified historical walk-forward replica repository of the **live 09:40 Short-Sell production system** (entry at 09:42:00).

> Path: `/home/ubuntu/live_production0942_model` (also accessible via symlink `/home/ubuntu/live_production0940_model`)

---

## 🎯 Architecture & Option A Replacement Rules

The live system and its historical replica implement **Option A Qualified Replacements**:

### 1. Initial Top 4 Evaluation (at 09:40:00)
- The LightGBM Rebound-Aware Model ranks all candidate stocks by predicted short return.
- The Top 4 candidates are evaluated against safety filters:
  - **RULE 1 (Morning Drop Cutoff -1.5%):** Skip if `stock_pct_940 < -1.5%` (avoids severe rebound traps).
  - **RULE 2 (Crash Day Protector):** Skip if `nifty_pct < -0.5%` AND `stock_pct_940 < -0.5%`.
  - **RULE 4 (Extreme Oversold Protector):** Skip all trades if market breadth $< 10.0\%$.

### 2. Qualified Replacements from Rank 5 and Rank 6
- Replacements are **ONLY** permitted to backfill slots vacated by **Rule 1** drops (`r1_dropped_count`).
- Slots dropped due to Rule 2 (Nifty Crash) or Rule 4 remain **EMPTY** to protect capital on dangerous market-wide plunge days.
- Maximum replacements allowed = `r1_dropped_count` (capped so total portfolio never exceeds 4 stocks).
- **Strict Quality Gate:** Candidate from Rank 5 or Rank 6 must satisfy:
  1. `stock_pct_940 >= -0.5%` (Strictly prevents chasing down moves / catching falling knives).
  2. Passes Rule 2 Crash Day Protector.
  3. Passes Rule 4 Market Breadth Filter.

---

## 📊 Audited Historical Results (2020-01-01 to 2026-10-23)

Verified via [`simulate_rule1_replacements_pct05.py`](file:///home/ubuntu/live_production0942_model/simulate_rule1_replacements_pct05.py):

| Metric | Overall System (Base + Option A Reps) | Standalone Replacements (Rank 5 & 6) |
| :--- | :--- | :--- |
| **Total Trades** | **5,269** | **289** |
| **Cumulative Net PnL** | **+₹102.14 Lakhs** | **+₹8.85 Lakhs** |
| **Win Rate** | **55.80%** | **57.44%** |
| **Friction Included** | Kotak MIS Cash Equity Taxes + ₹40 Brokerage | Kotak MIS Cash Equity Taxes + ₹40 Brokerage |

---

## 📁 Key Files

- [`live_0940_hybrid_pipeline.py`](file:///home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_shortsell_t1_2026/02_0942_Hybrid_Model/live_production/live_0940_hybrid_pipeline.py) — The live production runner executing every morning.
- [`simulate_rule1_replacements_pct05.py`](file:///home/ubuntu/live_production0942_model/simulate_rule1_replacements_pct05.py) — The dedicated backtest script for Option A replacements.
- [`trades_system_with_rep_pct05_oct23.csv`](file:///home/ubuntu/live_production0942_model/trades_system_with_rep_pct05_oct23.csv) — Complete 5,269 trade ledger.
- [`trades_replacements_rank5_6_pct05_oct23.csv`](file:///home/ubuntu/live_production0942_model/trades_replacements_rank5_6_pct05_oct23.csv) — Isolated 289 replacement trades ledger.
- [`walkforward_0942_simulation.py`](file:///home/ubuntu/live_production0942_model/walkforward_0942_simulation.py) — Master walk-forward simulation script (₹5L capital).
- [`walkforward_0942_simulation_10L.py`](file:///home/ubuntu/live_production0942_model/walkforward_0942_simulation_10L.py) — Master walk-forward simulation script (₹10L capital).
