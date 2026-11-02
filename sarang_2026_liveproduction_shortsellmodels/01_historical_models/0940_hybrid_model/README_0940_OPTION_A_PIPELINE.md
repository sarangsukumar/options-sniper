# 09:40 / 09:42 Short-Sell Hybrid Model: Option A Production Pipeline & Half-Yearly Walk-Forward Engine

This directory is the verified historical walk-forward replica repository of the **live 09:40 Short-Sell production system** (entry at `09:42:00`, exit at `14:30:00 / 14:45:00`).

> Path: `/home/ubuntu/live_production0942_model` (also accessible via symlink `/home/ubuntu/live_production0940_model`)

---

## 🔁 1. Half-Yearly Expanding Walk-Forward Retraining (`Jan 1` & `Jul 1` Cutoffs)

Both the historical walk-forward simulation and the live production pipeline ([`live_0940_hybrid_pipeline.py`](file:///home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_2026_liveproduction_shortsellmodels/02_live_production_pipelines/0940_hybrid_pipeline/live_0940_hybrid_pipeline.py)) use **Strict Half-Yearly Expanding Window Retraining**:

- **Retraining Schedule (`2x / Year` — `14` Out-of-Sample Fits across `2020–2026`):**
  - **H1 Window (`Jan 1 – Jun 30`):** Trained on all historical F&O mornings strictly `< YYYY-01-01` (`2018-01-01` to `Dec 31` of prior year).
  - **H2 Window (`Jul 1 – Dec 31`):** Trained on all historical F&O mornings strictly `< YYYY-07-01` (`2018-01-01` to `Jun 30` of current year).
- **Automated Cron / Shell Execution:**
  - Triggered automatically via [`run_monthly_retrain.sh`](file:///home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_2026_liveproduction_shortsellmodels/02_live_production_pipelines/0940_hybrid_pipeline/run_monthly_retrain.sh) (`00 18 1 1,7 *` — Jan 1 & Jul 1 at 18:00 IST) calling:
    ```bash
    python3 live_0940_hybrid_pipeline.py --retrain
    ```
- **Model Specification (`lgb_0940_rebound_aware_audited_model.txt`):**
  - **Algorithm:** LightGBM Regressor (`n_estimators=250`, `learning_rate=0.03`, `num_leaves=31`, `subsample=0.8`, `colsample_bytree=0.8`, `random_state=42`).
  - **12 Features (`FEATURES_12`):** `stock_pct_940`, `rel_weakness_940`, `gap_pct`, `morn_range_pct`, `pullback_from_high`, `gap_fade_0907_to_940_pct`, `prev_intraday_return`, `prev_intraday_vwap_gap`, `prev_intraday_roc_last_hour`, `positive_arc_ratio`, `rejection_wick`, `nifty_pct`.
  - **Rebound-Aware Target:**
    $$\text{target\_adj} = \text{short\_return} - 0.50 \times \max(0, \; \text{max\_rebound} - 1.50\%)$$

### Retraining Frequency Benchmark (`2020–2026`, Verified via [`test_retraining_frequencies_2020_2026.py`](file:///home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_2026_liveproduction_shortsellmodels/01_historical_models/0940_hybrid_model/test_retraining_frequencies_2020_2026.py))

| Retraining Cadence | Total Model Fits (`2020–2026`) | Overlap w/ Half-Yearly Picks | Why Half-Yearly (`Jan 1` / `Jul 1`) Is Optimal |
| :--- | :---: | :---: | :--- |
| **Half-Yearly (`Jan 1` & `Jul 1` — Active Production)** | **14 Fits** | **`100.0%` (Baseline)** | Captures regime shifts cleanly twice a year without overfitting to short-term monthly noise; highest risk-adjusted stability (`3.29` Sharpe, `30.2x` Calmar). |
| **Quarterly (`Jan/Apr/Jul/Oct`)** | 28 Fits | `85.0%` | Similar gross return (`+0.214%` vs `+0.213%`), higher turnover of weights with no statistically significant gain. |
| **Monthly (`1st of Every Month`)** | 82 Fits | `82.6%` | More sensitive to single-month squeezes; slightly lower consistency in choppy transitions. |
| **Bi-Weekly (`Every 15 Days`)** | 164 Fits | `81.9%` | Unnecessary compute churn (`11.7x` more fits) with identical long-term mean alpha (`+0.211%`). |

---

## 🎯 2. Architecture & Option A Replacement Rules

The live system and its historical replica implement **Option A Qualified Replacements**:

### A. Initial Top 4 Evaluation (at `09:40:00`)
- The LightGBM Rebound-Aware Model ranks all candidate stocks by predicted short return.
- The Top 4 candidates are evaluated against safety filters:
  - **RULE 1 (Morning Drop Cutoff `-1.5%`):** Skip if `stock_pct_940 < -1.5%` (avoids severe rebound traps).
  - **RULE 2 (Crash Day Protector):** Skip if `nifty_pct < -0.5%` AND `stock_pct_940 < -0.5%`.
  - **RULE 4 (Extreme Oversold Protector):** Skip all trades if market breadth $< 10.0\%$.

### B. Qualified Replacements from Rank 5 and Rank 6
- Replacements are **ONLY** permitted to backfill slots vacated by **Rule 1** drops (`r1_dropped_count`).
- Slots dropped due to Rule 2 (Nifty Crash) or Rule 4 remain **EMPTY** to protect capital on dangerous market-wide plunge days.
- **Strict Quality Gate:** Candidate from Rank 5 or Rank 6 must satisfy `stock_pct_940 >= -0.5%` (strictly prevents chasing down moves) and pass Rules 2 & 4.

---

## 🔬 3. Pure Model (`Zero SL, Zero Limit`) vs. Current `09:40` 4-Stage Dynamic SL (`3.00% -> 1.50% -> 1.00%`)

Verified via [`sim_0940_pure_1445.py`](file:///home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_2026_liveproduction_shortsellmodels/01_historical_models/0940_hybrid_model/sim_0940_pure_1445.py), [`sim_0940_pure_no_sl_no_limit.py`](file:///home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_2026_liveproduction_shortsellmodels/01_historical_models/0940_hybrid_model/sim_0940_pure_no_sl_no_limit.py), and [`exact_live_pipeline_historical_backtest_2020_2026/backtest_exact_live_pipeline_2020_2026.py`](file:///home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_2026_liveproduction_shortsellmodels/01_historical_models/0940_hybrid_model/exact_live_pipeline_historical_backtest_2020_2026/backtest_exact_live_pipeline_2020_2026.py) across all **`5,279` Out-of-Sample Trades (`1,468` Trading Days, `2020-01-01` to `2026-10-30`)** using Half-Yearly Retraining (`14` fits) on `scrapdata` Cash Equity ticks:

### A. Layer 1 — Pure ML Directional Alpha (Zero Stop-Loss, Zero Limit/Target, Hold `09:42 -> 14:45:00`)
- **Unfiltered F&O Universe (`09:42 -> 14:45`):** `48.61%` Net Win Rate (`54.14%` gross to `15:24`, `+0.060%` / trade).
- **`09:40` ML Top-4 Pure Hold (`09:42 -> 14:45`, No SL, No Limit):**
  - **Gross Win Rate (`14:45 < 09:42`):** **`58.31%`** (`+9.70%` edge over random F&O stocks).
  - **Net Win Rate (After Kotak Taxes + ₹40 Brok):** **`56.92%`** (`3,005` Wins / `2,274` Losses).
  - **Mean / Median Unstopped Short Return:** **`+0.213%` (`+21.3 bps`) Mean** | **`+0.289%` (`+28.9 bps`) Median**.
  - **Cumulative Net PnL (`@ ₹10L/stock`):** **`+₹90.96 Lakhs`** (`+₹112.35L` Gross `- ₹21.39L` Taxes) | **`+₹68.22 Lakhs` `@ ₹7.5L/stock`**.
  - **Intraday MFE (Peak Drop $\le 14:45$):** Mean **`+1.49%`** | Median **`+1.14%`** (`46.4%` of picks drop $\ge +1.25\%$; `25.5%` drop $\ge +2.00\%$).
  - **Intraday MAE (Adverse Squeeze $\le 14:45$ without SL):** Mean `+1.28%` | `95th Pct`: `+4.26%` | `99th Pct`: `+7.28%` | Worst Single Squeeze: `+16.20%` (`-₹1,49,121` on a single trade).

### B. 5-Way Architecture Comparison (`2020–2026`, `5,279` Strict OOS Trades, `@ ₹10,00,000 / Stock`)

| Metric (`2020–2026` Strict OOS, `5,279` Trades) | **1. Pure Baseline (`09:42 -> 14:45`)** *(Zero SL, Zero Limit)* | **2. Flat `3.0%` SL Only** *(3-Min Breach, No Limit)* | **3. Flat `2.25%` SL Only** *(3-Min Breach, No Limit)* | **4. 4-Stage Dynamic Engine (`3.0%->1.5%->1.0%` SL, `14:30` Exit)** | **5. 4-Stage Dynamic Engine (`3.0%->1.5%->1.0%` SL, `14:45` Exit)** |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Stop-Loss Rule (3-Min Cont. Breach)** | **None (`∞`)** | Flat `3.00%` All Day | Flat `2.25%` All Day | **`3.00%` $\rightarrow$ `1.50%` (11:00) $\rightarrow$ `1.00%` (12:30)** | **`3.00%` $\rightarrow$ `1.50%` (11:00) $\rightarrow$ `1.00%` (12:30)** |
| **Profit Lock / Trailing TP / Re-Entry** | **None** | None | None | **Stage 2 Lock + Stage 3 Trail + Stage 4 Leg 2** | **Stage 2 Lock + Stage 3 Trail + Stage 4 Leg 2** |
| **Gross PnL (Before Taxes)** | `+₹112.35 Lakhs` | `+₹110.68 Lakhs` | `+₹117.69 Lakhs` | `+₹120.79 Lakhs` | **`+₹123.02 Lakhs`** |
| **Total Kotak Taxes & Brokerage** | `-₹21.39 Lakhs` | `-₹21.39 Lakhs` | `-₹21.39 Lakhs` | `-₹24.01 Lakhs` | `-₹24.01 Lakhs` |
| **Total Net PnL (`@ ₹10L / stock`)** | **`+₹90.96 Lakhs`** | `+₹89.29 Lakhs` | `+₹96.30 Lakhs` | `+₹96.78 Lakhs` | **`+₹99.00 Lakhs`** *(+₹130.72L exact ticks)* |
| **Total Net PnL (`@ ₹7.5L` Live Scale)** | **`+₹68.22 Lakhs`** | `+₹66.97 Lakhs` | `+₹72.22 Lakhs` | `+₹72.58 Lakhs` | **`+₹74.25 Lakhs`** *(+₹98.04L exact ticks)* |
| **Net Trade Win Rate (%)** | **`56.92%`** | `56.49%` | `56.07%` | `61.79%` | **`61.53%`** *(`66.84%` exact ticks)* |
| **Profit Factor** | `1.28` | `1.28` | `1.31` | `1.38` | **`1.38`** *(`1.94` exact ticks)* |
| **Avg Net PnL / Trade (`@ ₹10L`)** | **`+₹1,723`** | `+₹1,691` | `+₹1,824` | `+₹1,833` | **`+₹1,875`** |
| **Worst Single Trade Loss** | `-₹1,49,121` | `-₹61,982` | `-₹61,982` | `-₹54,089` | **`-₹54,089` (`-64%` tail cut)** |
| **Worst Single Day PnL (4 Stocks)** | `-₹2,49,931` | `-₹1,63,065` | `-₹1,30,300` | `-₹1,10,248` | **`-₹1,10,248` (`-56%` tail cut)** |
| **Max Portfolio Drawdown (`@ ₹10L`)** | `-₹5.73 Lakhs` | `-₹5.25 Lakhs` | `-₹4.85 Lakhs` | `-₹3.20 Lakhs` | **`-₹3.28 Lakhs` (`-43%` DD cut)** |
| **Longest Drawdown Duration** | `111 days` | `95 days` | `95 days` | `75 days` | **`74 days`** |
| **Annualized Sharpe Ratio** | **`2.21`** | `2.27` | `2.55` | `3.26` | **`3.29`** |
| **Annualized Sortino Ratio** | **`3.60`** | `3.88` | `4.56` | `5.74` | **`5.83`** |
| **Calmar Ratio (`Net PnL / MaxDD`)** | `15.9x` | `17.0x` | `19.9x` | `30.2x` | **`30.2x`** |

### C. Year-by-Year Net PnL (`@ ₹10L / Stock`, `14:45:00` Exit): Pure Model vs. 4-Stage Dynamic Engine (`3.0% -> 1.5% -> 1.0%` SL)

| Year / Period | Trades | **Pure Model (`09:42 -> 14:45`)** *(No SL, No Limit)* | **Pure Net WR%** | **Pure MaxDD** | **Flat `3.0%` SL Only** *(No Limit)* | **Live 4-Stage Dynamic (`3.0%->1.5%->1.0%` SL)** | **4-Stage Net WR%** | **4-Stage MaxDD** |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **2020** | 768 | `+₹19.62L` | `59.3%` | `-₹3.47L` | `+₹14.40L` | **`+₹20.67L`** | **`67.4%`** | **`-₹1.48L`** |
| **2021** | 784 | `+₹24.52L` | `61.8%` | `-₹5.49L` | `+₹25.99L` | **`+₹26.78L`** | **`67.5%`** | **`-₹1.44L`** |
| **2022** | 762 | `+₹9.61L` | `55.7%` | `-₹5.73L` | `+₹9.81L` | **`+₹9.98L`** | **`59.0%`** | **`-₹3.03L`** |
| **2023** | 788 | `+₹7.76L` | `55.0%` | `-₹3.13L` | `+₹9.05L` | **`+₹9.68L`** | **`57.8%`** | **`-₹1.69L`** |
| **2024** | 778 | `+₹4.78L` | `53.8%` | `-₹4.21L` | `+₹6.26L` | **`+₹7.14L`** | **`58.0%`** | **`-₹2.89L`** |
| **2025** | 777 | **`+₹13.08L`** | `57.3%` | `-₹4.10L` | `+₹12.83L` | `+₹11.07L` *(+₹12.65L @ 14:30)* | **`60.0%`** | **`-₹3.28L`** |
| **2026 YTD (to Oct 30)** | 622 | `+₹11.60L` | `55.3%` | `-₹2.99L` | `+₹10.95L` | **`+₹13.69L`** | **`60.7%`** | **`-₹1.67L`** |
| **TOTAL (`2020–2026`)** | **5,279** | **`+₹90.96L`** | **`56.92%`** | **`-₹5.73L`** | **`+₹89.29L`** | **`+₹99.00L`** *(+₹130.72L exact ticks)* | **`61.53%`** | **`-₹3.28L`** |
| **2026-H2 OOS (`Jul 1 – Oct 30`)** | 305 | **`+₹8.09L`** | `55.7%` | `-₹2.46L` | `+₹7.22L` | **`+₹6.60L`** | **`61.0%`** | **`-₹1.00L`** |
| **Last Week (`Oct 27 – Oct 30`)** | 15 | `-₹1.30L` | `33.3%` | `-₹1.48L` | `-₹1.30L` | **`-₹0.71L` (`+₹0.59L` saved)** | **`46.7%`** | **`-₹0.74L`** |

---

## 🛡️ 4. Detailed Working of Active Live Engine (`4-Stage Dynamic Engine: 3.00% -> 1.50% -> 1.00% SL`)

Implemented in [`03_kotak_execution/sl_near_alert_monitor.py`](file:///home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_2026_liveproduction_shortsellmodels/03_kotak_execution/sl_near_alert_monitor.py) and [`03_kotak_execution/Neo_shortsell_mis_order.py`](file:///home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_2026_liveproduction_shortsellmodels/03_kotak_execution/Neo_shortsell_mis_order.py), and reconciled daily at `16:15 IST` by [`02_live_production_pipelines/0940_hybrid_pipeline/reconcile_0940_live_mimic_pnl.py`](file:///home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_2026_liveproduction_shortsellmodels/02_live_production_pipelines/0940_hybrid_pipeline/reconcile_0940_live_mimic_pnl.py):

1. **Stage 1 — Time-Decaying 3-Minute Continuous Breach Stop-Loss (Active when $\text{Max Profit} < +1.25\%$):**
   - **Morning Tier (`09:42 – 11:00 IST`):** Stop-Loss at **`+3.00%`** above Entry (`EP * 1.0300`), giving morning volatility room to breathe before fading.
   - **Mid-Morning Tier (`11:00 – 12:30 IST`):** Stop-Loss tightens to **`+1.50%`** above Entry (`EP * 1.0150`).
   - **Afternoon Tier (`12:30 – 14:45 IST`):** Stop-Loss tightens to **`+1.00%`** above Entry (`EP * 1.0100`).
   - **3-Minute Continuous Breach Filter:** Requires LTP to remain continuously above the active SL level for **3 full minutes** (`180 seconds` / `12 consecutive 15s checks`) before firing an exit. If LTP dips back below SL within 3 minutes, the breach counter resets to 0.
2. **Stage 2 — Pre-TP Profit Lock (Activates as soon as $\text{Max Profit} \ge +1.25\%$):**
   - Permanently upgrades from Stage 1 to Stage 2 and moves the protective stop to **`EP * 0.9950` (`+0.50%` locked profit)**, ensuring a trade that reached `+1.25%` profit can never turn into a stop-loss.
3. **Stage 3 — Uncapped Dynamic Profit Trailing (Activates as soon as $\text{Max Profit} \ge +2.00\%$):**
   - Permanently upgrades to Stage 3 and activates a one-way downward-ratcheting trailing floor:
     $$\text{Trailing Floor \%} = \max\left(1.75\%, \; \text{Max Profit \%} - 0.50\%\right)$$
     $$\text{Trailing Trigger Price} = \min\left(\text{EP} \times 0.9825, \; \text{Min LTP Seen} \times 1.0050\right)$$
   - Gives the trade a `0.25%` initial breathing buffer (`2.00%` $\rightarrow$ `1.75%` floor), and once profit exceeds `+2.25%`, trails penny-for-penny `0.50%` behind peak profit all the way down.
4. **Stage 4 — Tactical Pullback Re-Entry (`Before 14:00 IST`):**
   - When Leg 1 exits via Stage 3 Trailing TP before `14:00 IST`, monitors for a **`+0.50%` bounce** from the Leg 1 exit price (`Leg1_Exit * 1.0050`).
   - Upon trigger, enters **Leg 2 Short** with **`+1.50% / +1.75%` Trailing TP** and a tight protective Stop-Loss (`Leg2_Entry * 1.015` / original Leg 1 Entry `EP`).
5. **End-of-Day Square-Off (`14:30 – 14:45 IST`):**
   - Places a limit discount cover order at `14:30 IST`, followed by a mandatory market/chaser sweep at `14:45 IST`.

---

## 📁 Key Files in This Directory

- [`sim_0940_pure_1445.py`](file:///home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_2026_liveproduction_shortsellmodels/01_historical_models/0940_hybrid_model/sim_0940_pure_1445.py) — Head-to-head comparison of Pure Model (`09:42 -> 14:45`, No SL, No Limit) vs Flat `3.0%`/`2.25%` SL vs Live 4-Stage Dynamic Engine (`3.0% -> 1.5% -> 1.0%` SL).
- [`sim_0940_pure_no_sl_no_limit.py`](file:///home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_2026_liveproduction_shortsellmodels/01_historical_models/0940_hybrid_model/sim_0940_pure_no_sl_no_limit.py) — Pure unstopped directional edge analysis (`09:42 -> 15:24` and intraday checkpoints) with MFE/MAE distributions.
- [`test_retraining_frequencies_2020_2026.py`](file:///home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_2026_liveproduction_shortsellmodels/01_historical_models/0940_hybrid_model/test_retraining_frequencies_2020_2026.py) — Walk-forward benchmark comparing Half-Yearly (`Jan 1` & `Jul 1`), Quarterly, Monthly, and Bi-Weekly retraining cadences.
- [`compare_103L_vs_current_all_metrics.py`](file:///home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_2026_liveproduction_shortsellmodels/01_historical_models/0940_hybrid_model/compare_103L_vs_current_all_metrics.py) — Full multi-metric audit comparing SIM 1A, SIM 1B, and the Live 4-Stage Dynamic Engine.
- [`exact_live_pipeline_historical_backtest_2020_2026/`](file:///home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_2026_liveproduction_shortsellmodels/01_historical_models/0940_hybrid_model/exact_live_pipeline_historical_backtest_2020_2026/README_EXACT_LIVE_PIPELINE_BACKTEST.md) — Complete 1:1 exact tick-by-tick historical backtest (`5,279` trades, `+₹130.72L` @ ₹10L / `+₹98.04L` @ ₹7.5L).
- [`walkforward_0942_simulation.py`](file:///home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_2026_liveproduction_shortsellmodels/01_historical_models/0940_hybrid_model/walkforward_0942_simulation.py) & [`walkforward_0942_simulation_10L.py`](file:///home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_2026_liveproduction_shortsellmodels/01_historical_models/0940_hybrid_model/walkforward_0942_simulation_10L.py) — Master walk-forward simulation scripts (₹5L & ₹10L capital).
- [`option_a_5269_4sims_comparison.csv`](file:///home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_2026_liveproduction_shortsellmodels/01_historical_models/0940_hybrid_model/option_a_5269_4sims_comparison.csv) — Trade-by-trade 4-simulation comparison across all Option A trades.
