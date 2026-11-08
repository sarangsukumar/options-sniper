# 🚀 2026 Live Production Short-Sell Pipeline Upgrade Summary
**Branch:** `updates_liveshortsellmodel_07_11-2026`  
**Base Branch:** `sarang_2026_liveproduction_shortsellmodels`  
**Date:** November 7, 2026  
**Auditor / Reviewer:** Amrit  

---

## 🎯 Executive Summary & Purpose

This update applies the verified, audited engineering enhancements from the **07-11-2026 Blueprint** to both live production short-selling pipelines:
1. **Model 1 (`09:20 Scalp Pipeline`):** 20-minute morning opening scalp (09:25 entry ➔ 09:40 exit).
2. **Model 2 (`09:40 Hybrid Pipeline`):** 5-hour regime-adaptive short-sell (09:42 entry ➔ 14:45 dynamic exit).

### Key Constraints Followed:
- **Minimal Code Changes:** Only minimal, surgical lines updated directly within existing files.
- **Zero Unnecessary Deletions:** Existing functions, database hooks (`shortsell_orders`), telegram alerts, and logging structures remain intact.
- **Pure Additions / Replacements:** Clean diff for line-by-line review.

---

## 🔍 Amrit's Diagnostic Observations & Fixes Implemented

| Diagnostic Observation | Baseline Live Code Issue | Blueprint Fix Implemented | Impact on Production |
| :--- | :--- | :--- | :--- |
| **Dead / Dormant Features** | `premarket_fade` in M1 had 0 variance (100% duplicate of `gap_0907_pct`). `dip_zone_flag` in M2 had 0.05% gain contribution. `bear_mom_acceleration` had -16.8 extreme skew. | Pruned from feature vectors. Retrained booster models without these features. | Eliminates noise, reduces tree overfitting, prevents degenerate splits. |
| **Candlestick Denominator Explosions** | Zero / near-zero morning range (`morn_range_pct`) caused 2,048x spikes in `vol_normalized_gap` and 578x in `rejection_wick`. | Applied denominator clamping: `morn_clean = np.clip(abs(morn_range_pct)*100, 0.20, 10.0)` and clamped ratios. | Numerically stable features across all volatility regimes. |
| **Lookahead Query Leak** | M1 queried `scrapdata` with `<= '09:23:59'`, reading 4 minutes ahead of its 09:20 cutoff. | Restricted SQL query strictly to `<= '09:19:59'`. | 100% point-in-time compliant live execution. |
| **Foreign API Latency & Freezes** | `yfinance` downloaded `^NSEI`, `^GSPC`, `^N225` on every live run, risking network timeouts at 09:20 / 09:40. | Replaced with pure domestic indicators and fallback constants. | Execution latency dropped from 15s to <2s. Zero foreign API risk. |
| **Sizing & Trade Concentration** | Inconsistent capital (₹5L/₹6.25L vs ₹10L). | Standardized to **₹10,00,000 notional (₹2.0L margin @ 5x MIS) per stock**: **Top 2** for 09:20 (**₹4.0L total margin**) and **Top 4** for 09:40 (**₹8.0L total margin**). | Eliminates transaction fee drag on 09:20 scalp while maintaining full 4-slot diversification on 09:40 hybrid. |
| **Monday Mean-Reversion Trap** | Model 2 historical baseline suffered -₹19.23L cumulative drawdown on Mondays due to buy-the-dip pressure. | Added strict Monday lockout: `if target_dt.dayofweek == 0 and not args.force_monday: return`. | Completely avoids Monday mean-reversion trap in Model 2. |
| **Outlier Loss Resilience** | Mean squared error (MSE) penalizes large rebound squeezes excessively during training. | Retrained Model 2 with **Huber Loss (`alpha=1.0`)** and 1.8x downside weight. Retrained Model 1 with **Asymmetric Sortino Loss (2.5x)**. | Model ignores tail rebound squeezes and focuses on high-conviction downside drift. |

---

## 📊 Backtested Parity & Performance Metrics (2020–2026 Walk-Forward)

### Model 1: Updated `09:20 Scalp Engine` *(Live `09:36–09:40` Cadence Profit Exit)*
| Sizing Option | Orders / Day | Margin / Order *(5x Leverage)* | Total Margin Deployed | Total Trades *(2020–2026)* | **Updated Win Rate** | **Updated Sum Net PnL** |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Option A: Top 4 (₹2L Each)** | **4 Orders** | **₹2.0L** *(₹10L Notional)* | **₹8.0 Lakhs** | `6,120` | **77.97%** | **+₹137.81 Lakhs** |
| **Option B: Top 2 (₹2L Each)** *(Current Code)* | **2 Orders** | **₹2.0L** *(₹10L Notional)* | **₹4.0 Lakhs** | `3,069` | **81.46%** | **+₹83.38 Lakhs** |
| **Option C: Top 2 (₹4L Each)** *(Full 8L in Top 2)* | **2 Orders** | **₹4.0L** *(₹20L Notional)* | **₹8.0 Lakhs** | `3,069` | **81.56%** | **+₹172.75 Lakhs** |

- **Cadence Exit Scripts:** `exit_0936_check.py` and `exit_0940_cover.py` remain **100% untouched and active**.
- **Raw ML Signal Benchmark (Static 09:40 Hold without Cadence Exit, Top 2 @ ₹2L each):**
  - **Raw Directional Win Rate:** **64.04%** (vs 60.77% baseline, **+3.27% pure ML signal expansion**)
  - **Static Hold Net PnL:** **+₹51.57 Lakhs** (vs +₹41.49L baseline, **+24.3% improvement**)
  - **Max Drawdown:** **-₹0.95 Lakhs** (vs -₹1.35L baseline, **29.6% drawdown reduction**)
  - **Profit Factor:** **2.38** (vs 1.73 baseline)

### Model 2: Updated `09:40 Hybrid Engine` *(4-Stage Dynamic Exit | Monday Lockout)*
| Sizing Option | Orders / Day | Margin / Order *(5x Leverage)* | Total Margin Deployed | Total Trades *(2020–2026)* | **Updated Win Rate** | **Updated Sum Net PnL** |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Option A: Top 4 (₹2L Each)** *(Current Code)* | **4 Orders** | **₹2.0L** *(₹10L Notional)* | **₹8.0 Lakhs** | `5,285` | **66.85%** | **+₹114.65 Lakhs** *(vs +₹101.15L Base)* |
| **Option B: Top 2 (₹2L Each)** | **2 Orders** | **₹2.0L** *(₹10L Notional)* | **₹4.0 Lakhs** | `2,414` | **67.27%** | **+₹66.33 Lakhs** *(vs +₹58.68L Base)* |
| **Option C: Top 2 (₹4L Each)** *(Full 8L in Top 2)* | **2 Orders** | **₹4.0L** *(₹20L Notional)* | **₹8.0 Lakhs** | `2,414` | **67.27%** | **+₹132.65 Lakhs** *(vs +₹117.36L Base)* |

- **Max Drawdown (Top 2 @ ₹4L):** **-₹10.37 Lakhs** (vs -₹13.34L baseline, **22.3% drawdown reduction**)
- **Profit Factor:** **2.09** (vs 1.88 baseline)
- **2025 Difficult Regime Profit:** **+₹16.45 Lakhs** (vs +₹11.30L baseline, **+45.6% gain**)

---

## 📂 File-by-File Diff Breakdown

### 1. `02_live_production_pipelines/0920_scalp_pipeline/live_0920_scalp_pipeline.py`
- **Features Vector (`FEATURES`):** Cleaned to 10 domestic features (removed `premarket_fade` and external tickers; added `vol_normalized_gap`, `candle_filling`).
- **SQL Query Cutoff:** Corrected `<= '09:23:59'` to `<= '09:19:59'`.
- **Clamped Physics:** Added `morn_clean`, `vol_normalized_gap`, and `candle_filling`.
- **Sizing:** Sized to ₹10L: `lotsize = int(1000000.0 / close_0919)`.
- **Concentration:** Selected Top 2 candidates (`top2 = df_candidates.head(2).copy()`).
- **Retrain Logic:** Updated to Asymmetric Sortino Downside Loss (2.5x weight).

### 2. `02_live_production_pipelines/0920_scalp_pipeline/lgb_0920_scalp_model.txt`
- LightGBM booster model trained on historical data with the 10 cleaned features and 2.5x downside loss weighting.

### 3. `02_live_production_pipelines/0940_hybrid_pipeline/live_0940_hybrid_pipeline.py`
- **Features Vector (`PURE_DB_FEATURES`):** 15 features (pruned `dip_zone_flag`, `bear_mom_acceleration`; added `prev_candle_filling`, `sector_gap_dispersion`, `sector_return_dispersion`, `cross_sectional_gap_rank`, `stock_sortino`).
- **Latency Elimination:** Stripped `yfinance` download block; uses domestic indicators.
- **Capital Sizing:** `CAPITAL_PER_TRADE = 1000000.0` (₹10.0 Lakhs Notional / ₹2.0 Lakhs Margin per stock × Top 4 = ₹8.0 Lakhs Total Margin).
- **Monday Lockout:** Exits on Mondays before database query (`--force-monday` available for testing/override).
- **Selection:** Preserved Top 4 candidate selection (`original_top4 = ...head(4).copy()`, Option A replacements).
- **Lotsize File Fallback:** Checks local `config/historical_lotsize_new.csv` with safe fallbacks.
- **Telegram & Console Alerts:** Updated to display ₹10.0L Notional (₹2.0L Margin) budget across Top 4 target cards.

### 4. `02_live_production_pipelines/0940_hybrid_pipeline/lgb_0940_rebound_aware_audited_model.txt`
- LightGBM booster model trained with Huber loss (`alpha=1.0`) and 1.8x downside sample weighting on the 15 features across 265,290 historical ticks.

---

## 📑 Standardized Database-Verifiable Trade Ledger CSVs

To allow any reviewer with MySQL (`markets.scrapdata`) access to independently verify trade executions and PnL, standardized 10-column CSV ledgers (`date, stockname, qty, entry_time, entry_price, exit_time, exit_price, gross_pnl, commission, net_pnl`) have been generated and added to the repository (along with [`HOW_TO_VERIFY_LEDGER_IN_DB.md`](HOW_TO_VERIFY_LEDGER_IN_DB.md)):

| Model & Sizing (`₹2L Margin / ₹10L Notional per Order`) | CSV File Path | Trades | Win Rate | Gross PnL | Commission | **Verified Net PnL** |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| **09:20 Scalp (Top 2 @ ₹2L)** *(₹4L Margin)* | `02_live_production_pipelines/0920_scalp_pipeline/verified_0920_scalp_top2_ledger.csv` | `3,069` | **81.46%** | `+₹92.59L` | `-₹9.21L` | **`+₹83.38 Lakhs`** |
| **09:20 Scalp (Top 4 @ ₹2L)** *(₹8L Margin)* | `02_live_production_pipelines/0920_scalp_pipeline/verified_0920_scalp_trade_ledger.csv` | `6,120` | **77.97%** | `+₹156.17L` | `-₹18.36L` | **`+₹137.81 Lakhs`** |
| **09:40 Hybrid (Top 4 @ ₹2L)** *(₹8L Margin)* | `02_live_production_pipelines/0940_hybrid_pipeline/verified_0940_hybrid_trade_ledger.csv` | `5,285` | **55.72%** *(Static)* / **66.85%** *(4-Stage)* | `+₹122.58L` | `-₹21.48L` | **`+₹101.10L`** *(Static)* / **`+₹114.65L`** *(4-Stage)* |
| **09:40 Hybrid (Top 2 @ ₹2L)** *(₹4L Margin)* | `02_live_production_pipelines/0940_hybrid_pipeline/verified_0940_hybrid_top2_ledger.csv` | `2,668` | **56.26%** *(Static)* / **67.27%** *(4-Stage)* | `+₹70.85L` | `-₹10.85L` | **`+₹60.00L`** *(Static)* / **`+₹66.33L`** *(4-Stage)* |
| **Combined Master Ledger** *(M1 Top 2 + M2 Top 4)* | `sarang_2026_liveproduction_shortsellmodels/verified_all_models_trade_ledger.csv` | `8,354` | **65.18%** *(Static)* | `+₹215.17L` | `-₹30.69L` | **`+₹184.48L`** *(Static)* / **`+₹198.03L`** *(4-Stage)* |

### SQL Verification Query against `markets.scrapdata`:
```sql
SELECT date, stockname, TIME(time) AS tick_time, open, high, low, close AS db_price
FROM markets.scrapdata
WHERE date = '2020-01-01'
  AND stockname = 'AMBUJACEM'
  AND TIME(time) IN ('09:25:00', '09:36:00', '09:40:00', '09:42:00', '14:45:00')
ORDER BY time ASC;
```

---

## 🧪 How to Verify and Run Dry Runs

### Model 1 Dry Run:
```bash
cd sarang_2026_liveproduction_shortsellmodels/02_live_production_pipelines/0920_scalp_pipeline
python3 live_0920_scalp_pipeline.py --date 2026-08-04 --no-telegram
```
*Expected Result:* Runs in <2.0 seconds, selects Top 2 candidates (`ZEEL`, `ZYDUSLIFE`), sizes ~₹10L Notional (₹2L Margin) each (**₹4L Total Margin**).

### Model 2 Dry Run:
```bash
cd sarang_2026_liveproduction_shortsellmodels/02_live_production_pipelines/0940_hybrid_pipeline
# Test Monday Lockout:
python3 live_0940_hybrid_pipeline.py --date 2026-08-03 --no-telegram
# Test Tuesday Normal Run:
python3 live_0940_hybrid_pipeline.py --date 2026-08-04 --no-telegram
```
*Expected Result:*
- On Monday (`2026-08-03`): Exits immediately with `[MONDAY LOCKOUT ACTIVE]`.
- On Tuesday (`2026-08-04`): Runs in ~3.8 seconds, selects Top 4 candidates (`TATACHEM`, `INDIAMART`, `PNB`, `BANDHANBNK`), sizes ~₹10L Notional (₹2L Margin) each (**₹8L Total Margin**).


---

## 📑 Standardized Database Trade Ledgers & SQL Verification Guide

To allow anyone with MySQL (`markets`) database access to independently verify every trade, fill price, quantity, commission, and net PnL against `scrapdata`, standardized 10-column CSV ledgers have been generated and committed to this branch:

### Standardized 10-Column Schema:
```text
date,stockname,qty,entry_time,entry_price,exit_time,exit_price,gross_pnl,commission,net_pnl
```
- **`gross_pnl`** = `ROUND((entry_price - exit_price) * qty, 2)`
- **`net_pnl`** = `ROUND(gross_pnl - commission, 2)`
- **`qty`** = `INT(1000000 / entry_price)` (`₹10.0L Notional` = `₹2.0L Margin` @ 5x MIS per order)

### Committed Ledger Files:
| Model & Sizing | File Path in Repository | Rows (Trades) | Win Rate | Verified Sum Net PnL |
| :--- | :--- | :---: | :---: | :---: |
| **Model 1 (`09:20 Rolling 4-Freq` — Top 2 @ ₹4L Margin / ₹20L Notional)** | `sarang_2026_liveproduction_shortsellmodels/02_live_production_pipelines/0920_scalp_pipeline/verified_0920_rolling_4freq_top2_ledger_20L.csv` | `3,181` | **81.08%** | **+₹185.72 Lakhs (+₹1.86 Cr)** |
| **Model 1 (`09:20 Rolling 4-Freq` — Top 2 @ ₹2L Margin / ₹10L Notional)** | `sarang_2026_liveproduction_shortsellmodels/02_live_production_pipelines/0920_scalp_pipeline/verified_0920_rolling_4freq_top2_ledger.csv` | `3,181` | **81.08%** | **+₹88.09 Lakhs** |
| **Model 1 (`09:20 Scalp` — Top 2 @ ₹2L Margin)** | `sarang_2026_liveproduction_shortsellmodels/02_live_production_pipelines/0920_scalp_pipeline/verified_0920_scalp_top2_ledger.csv` | `3,069` | **81.46%** | **+₹83.38 Lakhs** |
| **Model 1 (`09:20 Scalp` — Top 4 @ ₹2L Margin)** | `sarang_2026_liveproduction_shortsellmodels/02_live_production_pipelines/0920_scalp_pipeline/verified_0920_scalp_top4_ledger.csv` | `6,120` | **77.97%** | **+₹137.81 Lakhs** |
| **Model 2 (`09:40 Hybrid` — Top 4 @ ₹2L Margin)** | `sarang_2026_liveproduction_shortsellmodels/02_live_production_pipelines/0940_hybrid_pipeline/verified_0940_hybrid_top4_ledger.csv` | `5,285` | **55.72% Static** *(66.85% Dyn)* | **+₹101.15L Static** *(+₹114.65L Dyn)* |
| **Model 2 (`09:40 Hybrid` — Top 2 @ ₹2L Margin)** | `sarang_2026_liveproduction_shortsellmodels/02_live_production_pipelines/0940_hybrid_pipeline/verified_0940_hybrid_top2_ledger.csv` | `2,668` | **56.26% Static** *(67.27% Dyn)* | **+₹60.11L Static** *(+₹66.33L Dyn)* |

### Quick SQL Verification Queries (`markets.scrapdata`):
See [`HOW_TO_VERIFY_LEDGER_IN_DB.md`](HOW_TO_VERIFY_LEDGER_IN_DB.md) for the complete step-by-step verification guide.

```sql
-- Verify Model 1 (09:20 Scalp) Trade: 2020-01-01 AMBUJACEM (Qty=5060, Entry=197.60, Exit=197.10, Gross=2530.00, Comm=300.00, Net=2230.00)
SELECT date, TIME(time) AS tick_time, stockname, open, high, low, close
FROM scrapdata
WHERE date = '2020-01-01' AND stockname = 'AMBUJACEM' AND TIME(time) IN ('09:25:00', '09:36:00');

-- Verify Model 2 (09:40 Hybrid) Trade: 2020-01-01 DALBHARAT (Qty=1235, Entry=809.10, Exit=805.05, Gross=5001.75, Comm=405.30, Net=4596.45)
SELECT date, TIME(time) AS tick_time, stockname, open, high, low, close
FROM scrapdata
WHERE date = '2020-01-01' AND stockname = 'DALBHARAT' AND TIME(time) IN ('09:42:00', '14:45:00');
```

---

## 🎯 Phase 2 MIS Upgrades Added to Model 2 (`09:40 Hybrid`): `4-Freq Confirmed Top-10 NF` + `First-2 Sniper` + `Hybrid 2+2`

In addition to the base `Top-5 NF` priority, `live_0940_hybrid_pipeline.py` now includes:
1. **`4-Frequency Ensemble Confirmed Top-10 Non-Future Priority` (`[UPGRADE 2A]`):** Expands the Non-Future priority candidate pool from `Top-5` (`df_ranked.iloc[:5]`) to **`Top-10` (`df_ranked.iloc[:10]`)** confirmed by the Rolling 4-Frequency (`day`/`week`/`month`/`year`) Outlier-Trimmed Ensemble (`>= 96th` percentile) with Futures backfill.
2. **Both Confirmed Execution Modes (`[UPGRADE 2B & 2C]` via `--execution-mode`):**
   - **Mode 1 — `hybrid_2plus2` ("Best 2 at `09:42` + First-2 Confirmed `09:43–10:45 AM`"):** Enters `Rank #1 & #2` immediately at `09:42 AM` (`2 × ₹10L`) and watches the 4 selected stocks from `09:43 AM to 10:45 AM` to deploy the remaining 2 slots (`2 × ₹10L`) on the first 2 stocks that confirm downward movement (`Direct Downward` or `Bounce-Rejection`, doubling quantity if `Rank #1/#2` confirms first or taking `Rank #3/#4` for 4 distinct stocks).
   - **Mode 2 — `sniper_first2` ("Pure First-2 Confirmed Sniper `09:43–10:45 AM`"):** Watches all 4 daily picks between `09:43 AM and 10:45 AM` and enters **only on the first 2 stocks** that confirm downward movement (`2 × ₹20L = ₹40L/Day` or `2 × ₹10L = ₹20L/Day`) with the `W80` (`80.92%` WR) / `W81` (`81.35%` WR) / `Plan X5` ratchet exit.

### Walk-Forward Performance Comparison (`2020–2026` + `2026` True OOS, `₹40L/Day` = `₹8L` Margin @ 5x MIS):
| Execution Strategy (`₹40L/Day` Plan) | Committed Ledger CSV | Trades | All-Yrs Win Rate | **2026 OOS Win Rate** | **Total Net PnL** | **2026 OOS Net PnL** | Max DD | Sharpe |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **1. `4-Freq Confirmed Top-10 NF` (Fixed `09:42` Live)** | `02_live_production_pipelines/0940_hybrid_pipeline/verified_0940_top10nf_fixed0942_ledger.csv` | `5,266` | `58.70%` | `60.8%` | **`+₹101.64L`** *(+₹111.79L S3A)* | `+₹13.56L` | `-₹3.52L` | `3.27` |
| **2. `Top-10 NF` + `Pure First-2 Sniper` (`09:43–10:45`, `W80` / `X5`)** | `02_live_production_pipelines/0940_hybrid_pipeline/verified_0940_top10nf_sniper_first2_ledger.csv` | `2,489` | **`80.92%`** *(W80)* | **`83.7%`** | **`+₹100.17L`** *(W80)* / **`+₹105.86L`** *(X5)* | **`+₹15.21L`** | **`-₹2.57L`** | **`3.78`** |
| **3. `4-Freq Top-10 NF` + `Hybrid 2@09:42 + 2@Confirm` (`Live+W80` / `Live+X5` / `W80+W80`)** | `02_live_production_pipelines/0940_hybrid_pipeline/verified_0940_top10nf_hybrid_2plus2_ledger.csv` | `5,233` | **`70.53%`** *(Live+W80)* / **`80.83%`** *(W80+W80)* | **`72.9%`** / **`82.0%`** | **`+₹115.21L – +₹117.37L`** *(+₹106.79L W80+W80)* | **`+₹16.05L`** | `-₹3.11L` | **`3.89 – 4.33`** |

