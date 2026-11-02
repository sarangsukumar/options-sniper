# 09:40 / 09:42 Exact Live Production Pipeline — Historical Walk-Forward Backtest (2020–2026)

> **Folder Path:** `/home/ubuntu/live_production0940_model/exact_live_pipeline_historical_backtest_2020_2026`  
> *(Physical Path: `/home/ubuntu/live_production0942_model/exact_live_pipeline_historical_backtest_2020_2026`)*

This folder contains the standalone historical walk-forward backtest (`2020–2026`) that mirrors the **exact live production pipeline** (`live_0940_hybrid_pipeline.py` + `Neo_shortsell_mis_order.py` + `sl_near_alert_monitor.py` + `reconcile_0940_live_mimic_pnl.py`) **without modifying any live production files**.

---

## 🎯 1. Exact Live Pipeline Specifications Modeled

1. **12 Pure DB Features & LightGBM Architecture (`100` trees, `lr=0.05`, `max_depth=5`, `random_state=42`):**
   - Expanding walk-forward training on `>= ₹30.0` universe (strictly excluding Mondays).
   - Uses the exact deployed live booster (`lgb_0940_rebound_aware_audited_model.txt`) for dates from `2026-10-12` onward.
2. **Live Candidate Price Filter (`entry_price_0940 >= ₹50.0`):**
   - Matches `live_0940_hybrid_pipeline.py` Line 717 (`entry_price_0940 >= 50.0`), whereas the original historical Option A script filtered daily candidates at `>= ₹30.0`.
3. **Live Nifty % Change Baseline for Rule 2 (`nifty_prev_close`):**
   - Matches `live_0940_hybrid_pipeline.py` Lines 418–425 (`(nifty_940 - nifty_prev_close) / nifty_prev_close * 100`), whereas the original historical Option A script compared `nifty_940` against today's `nifty_open`.
4. **Option A Selection & Replacement Rules:**
   - **Rule 1 (Morning Drop Cutoff `-1.5%`):** Skip Top 4 candidate if `stock_pct_940 < -1.5%`.
   - **Rule 2 (Crash Day Protector):** Skip candidate if `nifty_pct_vs_prev_close < -0.5%` AND `stock_pct_940 < -0.5%`.
   - **Option A Qualified Replacements (Ranks 5 & 6):** Backfills **only** slots vacated by Rule 1 (`r1_dropped_count`), and strictly requires the replacement stock to have `stock_pct_940 >= -0.5%` and pass Rule 2.

---

## 🔍 2. Trade Overlap Audit: 98.3% Identical Picks (100% Identical in 2024 & 2025)

- **Total Trades Selected (`2020–2026`):** **`5,263` trades** (vs `5,269` in the Historical Option A Walk-Forward).
- **Exact Same `(date, stock)` Picks:** **`5,173` out of `5,263` trades (`98.3%`) are 100% identical**!
- **2024 (`778` trades) & 2025 (`777` trades):** **100.0% of all trades are identical** (`₹0.00` difference).
- **90 Differing Trades (`1.7%` over 7 years):** Audited in `exact_live_pipeline_90_diff_trades_audit.csv` (caused by the `₹50` vs `₹30` candidate filter in 2020–2022 and `nifty_prev_close` vs `nifty_open` on a few gap-down days).

---

## 📊 3. Side-by-Side Comparison (`SIM 3A: Active Live 4-Stage Dynamic Engine` at Flat `₹10L / Stock`)

| Year | Historical Option A Walk-Forward (`5,269` Tr) | Exact Live Pipeline Model (`5,263` Tr) | Net PnL Difference |
| :--- | :---: | :---: | :---: |
| **2020** | `768` tr \| `68.9%` WR \| **`+₹22.36 Lakhs`** \| PF `1.57` | `771` tr \| `67.8%` WR \| **`+₹20.99 Lakhs`** \| PF `1.52` | `-₹1.37 Lakhs` |
| **2021** | `784` tr \| `64.7%` WR \| **`+₹22.58 Lakhs`** \| PF `1.60` | `783` tr \| `64.6%` WR \| **`+₹23.20 Lakhs`** \| PF `1.61` | **`+₹0.61 Lakhs`** |
| **2022** | `762` tr \| `57.2%` WR \| **`+₹10.31 Lakhs`** \| PF `1.29` | `759` tr \| `57.7%` WR \| **`+₹10.58 Lakhs`** \| PF `1.30` | **`+₹0.27 Lakhs`** |
| **2023** | `788` tr \| `56.6%` WR \| **`+₹9.58 Lakhs`** \| PF `1.27` | `788` tr \| `56.6%` WR \| **`+₹9.75 Lakhs`** \| PF `1.28` | **`+₹0.18 Lakhs`** |
| **2024** | `778` tr \| `58.0%` WR \| **`+₹8.66 Lakhs`** \| PF `1.22` | `778` tr \| `58.0%` WR \| **`+₹8.66 Lakhs`** \| PF `1.22` | **`₹0.00 Lakhs` (100% Identical)** |
| **2025** | `777` tr \| `60.4%` WR \| **`+₹12.82 Lakhs`** \| PF `1.40` | `777` tr \| `60.4%` WR \| **`+₹12.82 Lakhs`** \| PF `1.40` | **`₹0.00 Lakhs` (100% Identical)** |
| **2026** | `612` tr \| `60.0%` WR \| **`+₹10.84 Lakhs`** \| PF `1.38` | `607` tr \| `59.6%` WR \| **`+₹10.15 Lakhs`** \| PF `1.36` | `-₹0.69 Lakhs` |
| **TOTAL** | **`5,269` tr \| `60.8%` WR \| `+₹97.16 Lakhs` \| PF `1.39`** | **`5,263` tr \| `60.7%` WR \| `+₹96.16 Lakhs` \| PF `1.39`** | **`-₹1.00 Lakh` (`< 1%` variance over 7 yrs)** |

---

## ⚡ 4. All Execution Simulations on the Exact Live Pipeline Model (`5,263` Trades, `2020–2026`)

| Execution Simulation | Capital Sizing | Total Net PnL (`2020–2026`) | 2026 YTD Net PnL (`607` Tr) | Win Rate | Profit Factor | Max Drawdown | Sharpe Ratio | Calmar Ratio |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **SIM 1A:** No TP \| `2.25%` SL (1-Tick) \| Exit `14:45` | `₹10L / Stock` | **`+₹103.09 Lakhs`** | `+₹10.58 Lakhs` | `55.8%` | `1.34` | `-₹4.98 Lakhs` | `2.53` | `20.7x` |
| **SIM 1B:** No TP \| `2.25%` SL (3-Min Breach) \| Exit `14:45` | `₹10L / Stock` | **`+₹98.07 Lakhs`** | `+₹9.09 Lakhs` | `56.5%` | `1.32` | `-₹5.74 Lakhs` | `2.32` | `17.1x` |
| **SIM 2A:** `2.0%` TP \| `2.25%` SL (1-Tick) \| `+0.50%` Re-Entry | `₹10L / Stock` | **`+₹99.66 Lakhs`** | `+₹10.57 Lakhs` | `58.3%` | `1.36` | `-₹3.96 Lakhs` | `2.86` | `25.2x` |
| **SIM 2B:** `2.0%` TP \| `2.25%` SL (3-Min Breach) \| `+0.50%` Re-Entry | `₹10L / Stock` | **`+₹96.25 Lakhs`** | `+₹9.22 Lakhs` | `58.8%` | `1.33` | `-₹4.40 Lakhs` | `2.65` | `21.9x` |
| **SIM 3A (Active Live 4-Stage Dynamic Engine — Decay SL)** | `₹10L / Stock` | **`+₹96.16 Lakhs`** | **`+₹10.15 Lakhs`** | **`60.7%`** | **`1.39`** | **`-₹3.05 Lakhs`** | **`3.04`** | **`31.5x`** |
| **SIM 3B:** 4-Stage Engine w/ Constant `2.25%` SL (No Decay) | `₹10L / Stock` | **`+₹93.04 Lakhs`** | `+₹10.08 Lakhs` | `62.8%` | `1.36` | `-₹3.57 Lakhs` | `2.72` | `26.1x` |
| **SIM 3A (`₹5L / Stock` Flat Sizing)** | `₹5L / Stock` | **`+₹46.62 Lakhs`** | `+₹4.90 Lakhs` | `60.6%` | `1.38` | **`-₹1.57 Lakhs`** | `2.95` | `29.7x` |
| **SIM 3A (Live Kotak Sizing: `₹30L / N`, Max `₹10L`)** | `₹7.5L–₹10L` | **`+₹72.17 Lakhs`** | **`+₹7.62 Lakhs`** | **`60.7%`** | **`1.38`** | **`-₹2.38 Lakhs`** | **`3.01`** | **`30.3x`** |

---

## 📁 Files in This Directory

- `backtest_exact_live_pipeline_2020_2026.py` — Standalone walk-forward backtest script mimicking the exact live production pipeline.
- `exact_live_pipeline_backtest_2020_2026.csv` — Complete 5,263 trade-by-trade historical ledger (`2020–2026`) across all 8 simulation configurations.
- `exact_live_pipeline_90_diff_trades_audit.csv` — Isolated audit ledger of the 90 trades (`1.7%`) that differed from the 5,269 Historical Option A walk-forward benchmark.
- `lgb_0940_rebound_aware_audited_model.txt` — Read-only copy of the active live LightGBM booster (`100` trees, `12` pure DB features).
- `README_EXACT_LIVE_PIPELINE_BACKTEST.md` — This documentation and performance report.
