# Live Production Short-Sell Models & Historical Replicas (2026)
**Branch:** `sarang_2026_liveproduction_shortsellmodels`  
**Repository:** `sarangsukumar/daily_prediction_sytem_Dynamic_threshold.git`

---

## 📌 Executive Summary

This branch contains the exact code, models, datasets, and configurations powering the **Live Production Short-Sell Systems** as well as their **1:1 Historical Walk-Forward Simulation Replicas**:

1. **09:20 Scalp Model (Half-Yearly Expanding Retraining + 50/50 Split Execution)**:
   - High-velocity morning scalp short-selling pipeline (`09:20` Entry to `09:36 / 09:40` Exit).
   - **Retraining Cadence:** **Half-Yearly Expanding Walk-Forward (`Jan 1` & `Jul 1` Cutoffs)** via `retrain_monthly_0920_scalp.py` and `run_monthly_retrain.sh` (`00 18 1 1,7 *`).
   - **Order Fill Logic:** 50/50 Split (50% Market/Best-Bid Fill + 50% Passive Limit 0.10% above 09:20 open).
   - **Exit Mechanics:** 09:36 dynamic trailing profit-taking (+₹1,500 target threshold) + 09:40 mandatory time square-off.
   - **Historical Performance (2020–2026):**
     - ₹5L Capital: **+₹44.27 Lakhs Net PnL**, 75.59% Win Rate, 2.51 Profit Factor.
     - ₹10L Capital: **+₹70.78 Lakhs Net PnL**, 77.85% Win Rate, 2.40 Profit Factor.

2. **09:40 Hybrid Model (Half-Yearly Expanding Retraining + Option A Replacements + 4-Stage Dynamic `3.00% -> 1.50% -> 1.00%` SL Engine)**:
   - Trend-following longer-window short-sell pipeline (`09:42` Entry to `14:30 / 14:45` Exit) on **Cash Equities (`scrapdata`)**.
   - **Retraining Cadence:** **Half-Yearly Expanding Walk-Forward (`Jan 1` & `Jul 1` Cutoffs — `14` OOS Fits across `2020–2026`)** via `live_0940_hybrid_pipeline.py --retrain` and `run_monthly_retrain.sh` (`00 18 1 1,7 *`).
     - `H1 (Jan–Jun)` trained on `< YYYY-01-01`; `H2 (Jul–Dec)` trained on `< YYYY-07-01`.
   - **Filtering & Option A Selection:**
     - **Rule 1 Cutoff (`-1.50%`):** Skips stocks already down `< -1.50%` by `09:40` to avoid rebound traps.
     - **Rule 2 Crash Day Protector:** Skips if `nifty_pct < -0.50%` & `stock_pct_940 < -0.50%`.
     - **Rule 4 Breadth Filter:** Skips all trades if market breadth `< 10%`.
     - **Option A Dynamic Replacement:** Slots vacated by Rule 1 are backfilled from Rank 5 or Rank 6 provided `stock_pct_940 >= -0.50%`.
   - **Active Live Exit Architecture (`4-Stage Dynamic Engine: 3.00% -> 1.50% -> 1.00% SL`):**
     - **Stage 1 (Time-Decay 3-Min Cont. Breach SL):** **`3.00%` (`09:42–11:00`) $\rightarrow$ `1.50%` (`11:00–12:30`) $\rightarrow$ `1.00%` (`12:30–14:45`)**, requiring 3 full minutes (`180s`) of continuous breach before exit.
     - **Stage 2 (Pre-TP Profit Lock at `+1.25%`):** Locks protective stop at `+0.50%` profit (`EP * 0.9950`) once peak profit reaches `+1.25%`.
     - **Stage 3 (Uncapped Dynamic Trailing TP at `+2.00%`):** Sets initial trailing floor at **`+1.75%` profit** (`EP * 0.9825`) and ratchets downward `0.50%` behind peak profit (`max(1.75%, max_profit - 0.50%)`).
     - **Stage 4 (Pullback Re-Entry):** Enters Leg 2 Short on a `+0.50%` bounce after a Leg 1 Stage 3 profit exit before `14:00 IST`.
   - **Pure Model (`Zero SL, Zero Limit`) vs. Current 4-Stage Dynamic Engine (`2020–2026`, `5,279` Strict OOS Trades at `₹10L/stock`, `14:45:00` Exit):**
     - **Pure Model (`09:42 -> 14:45`, No SL, No Limit):** **`+₹90.96 Lakhs Net PnL`** (`+₹68.22L` @ ₹7.5L), **`58.31%` Gross WR (`56.92%` Net WR)**, `+0.213%` (`+21.3 bps`) mean unstopped return, Max DD `-₹5.73L`, Sharpe `2.21`, Worst Trade `-₹1,49,121`.
     - **Active 4-Stage Dynamic Engine (`3.0% -> 1.5% -> 1.0%` 3-Min SL, `14:45` Exit):** **`+₹99.00 Lakhs Net PnL`** (`+₹74.25L` @ ₹7.5L; **`+₹130.72L` @ ₹10L / `+₹98.04L` @ ₹7.5L** on exact 1:1 tick backtest), **`61.53%` Net WR** (`66.84%` exact ticks), **Max DD `-₹3.28L` (`-43%` drawdown reduction)**, **Sharpe `3.29`**, **Sortino `5.83`**, **Calmar `30.2x`**, Worst Trade capped at **`-₹54,089` (`-64%` tail risk cut)**.

3. **Kotak Neo Live Execution Suite**:
   - Live order placement bridge (`Neo_shortsell_mis_order.py`) with 50/50 fill execution, cadence order verification, Stage 4 pullback re-entry execution, DB + CSV model ownership checks during square-off, and idempotency checks.
   - 4-Stage Real-Time Exit & Stop-Loss Proximity Monitor (`sl_near_alert_monitor.py`) enforcing `3.00% -> 1.50% -> 1.00%` 3-minute continuous breach stop-loss and Stages 2–4 profit trailing.

---

## 📂 Directory Layout

```
sarang_2026_liveproduction_shortsellmodels/
├── README.md                                          # Master documentation
├── 01_historical_models/                              # 1:1 Backtest and Walk-Forward Verification Replicas
│   ├── 0920_scalp_model/                              # 09:20 Scalp 50/50 Split Historical Pipeline
│   │   ├── README_5050_PIPELINE.md                    # Detailed 09:20 simulation documentation
│   │   ├── walkforward_0920_5050_pipeline.py          # Primary walk-forward simulation runner (₹5L & ₹10L)
│   │   ├── walkforward_0920_simulation.py             # 50/50 verification entrypoint
│   │   ├── walkforward_0920_5050_trades_5L.csv        # Trade-by-trade ledger (5,567 trades, ₹5L)
│   │   ├── walkforward_0920_5050_trades_10L.csv       # Trade-by-trade ledger (5,567 trades, ₹10L)
│   │   └── walkforward_0920_5050_yearly_summary.csv   # Year-by-year PnL breakdown
│   │
│   └── 0940_hybrid_model/                             # 09:40 Hybrid Option A + Half-Yearly Walk-Forward Replicas
│       ├── README_0940_OPTION_A_PIPELINE.md           # Full documentation: Half-Yearly Retrain + Pure vs 4-Stage Dynamic SL
│       ├── sim_0940_pure_1445.py                      # Pure Model (No SL, No Limit, 14:45) vs 4-Stage Dynamic (3.0->1.5->1.0% SL)
│       ├── sim_0940_pure_no_sl_no_limit.py            # Pure unstopped directional edge & MFE/MAE distribution (09:42 -> 15:24)
│       ├── test_retraining_frequencies_2020_2026.py   # Half-Yearly vs Quarterly vs Monthly vs Bi-Weekly retraining benchmark
│       ├── compare_103L_vs_current_all_metrics.py     # Multi-metric comparison across SIM 1A, SIM 1B, and 4-Stage Dynamic
│       ├── backtest_exact_live_pipeline_2020_2026.py  # 1:1 Exact live pipeline tick-level walk-forward backtest (2020-2026)
│       ├── exact_live_pipeline_backtest_2020_2026.csv # 5,279-trade ledger from exact live pipeline backtest
│       ├── exact_live_pipeline_historical_backtest_2020_2026/ # Full exact live pipeline audit folder & README
│       ├── walkforward_0942_simulation.py             # Primary walk-forward simulation runner (₹5L Option A)
│       ├── walkforward_0942_simulation_10L.py         # ₹10L capital walk-forward runner (Option A)
│       ├── option_a_5269_4sims_comparison.csv         # 4-Simulation comparison across 5,269 Option A trades
│       └── trades_system_with_rep_pct05_oct23.csv     # Combined Option A trade ledger
│
├── 02_live_production_pipelines/                      # Live Automated Production Runners
│   ├── 0920_scalp_pipeline/
│   │   ├── live_0920_scalp_pipeline.py                # Main morning scalp orchestrator (09:18 - 09:25)
│   │   ├── retrain_monthly_0920_scalp.py              # Half-Yearly (Jan 1 & Jul 1) Expanding Retrainer for 09:20
│   │   ├── confirm_0925_fills.py                      # 09:25 fill confirmator with 50/50 split tracking
│   │   ├── exit_0936_check.py                         # 09:36 trailing profit taking check
│   │   ├── exit_0940_cover.py                         # 09:40 full cover exit manager
│   │   ├── reconcile_0920_scalp_pnl.py                # Evening PnL reconciler with 50/50 split calculations
│   │   └── lgb_0920_scalp_model.txt                   # Production LightGBM model weights (Half-Yearly cutoff)
│   │
│   └── 0940_hybrid_pipeline/
│       ├── live_0940_hybrid_pipeline.py               # Main 09:40 orchestrator + Half-Yearly (`--retrain`) engine
│       ├── run_monthly_retrain.sh                     # Half-Yearly (Jan 1 & Jul 1) cron runner (`00 18 1 1,7 *`)
│       ├── retrain_monthly_0940_hybrid.py             # Python wrapper invoking Half-Yearly `retrain_model()`
│       ├── confirm_0942_fills.py                      # 09:42 entry confirmation (updates 3.0% initial SL to filled price)
│       ├── reconcile_0940_hybrid_pnl.py               # Evening reconciler (Cash Equity scrapdata primary)
│       ├── reconcile_0940_live_mimic_pnl.py           # 3-Simulation tick-level live mimic reconciler (3.0->1.5->1.0% SL)
│       ├── daily_0940_live_ledger.csv                 # Master Option A + Live trade ledger
│       ├── daily_0940_live_mimic_ledger.csv           # Master 3-Simulation trade ledger
│       ├── lgb_0940_rebound_aware_audited_model.txt   # Production 12-feature Rebound-Aware LightGBM weights
│       ├── filter_research/                           # Dynamic SL (`3.0->1.5->1.0%`) & SL sweep research scripts
│       ├── run_0940_hybrid_pipeline.sh                # Shell runner for 09:41 AM pipeline
│       ├── run_0940_evening_reconcile.sh              # Shell runner for 16:10 PM reconciliation
│       └── run_0940_live_mimic_reconcile.sh           # Shell runner for 16:15 PM 3-Sim reconciliation
│
└── 03_kotak_execution/                                # Broker Execution Bridge
    ├── Neo_shortsell_mis_order.py                     # Kotak Neo API MIS short sell order & Leg 2 placer
    ├── sl_near_alert_monitor.py                       # Real-time 4-Stage Exit & Proximity Alert Daemon (3.0->1.5->1.0% SL)
    └── notify_pipeline_armed.py                       # Morning pipeline armed Telegram notifier
```

---

## 📊 Performance Benchmark Summary

### 1. 09:40 Hybrid Model — Pure Model (`No SL, No Limit`) vs. Active 4-Stage Dynamic Engine (`3.00% -> 1.50% -> 1.00%` SL)
Evaluated across all **`5,279` Out-of-Sample Trades (`2020-01-01` to `2026-10-30`, `14` Half-Yearly Walk-Forward Retrains)** at **`₹10,00,000` Notional / Stock** (`14:45:00` EOD Exit):

| Metric (`2020–2026` Strict OOS, `5,279` Trades) | **1. Pure Baseline (`09:42 -> 14:45`)** *(No SL, No Limit)* | **2. Flat `3.0%` SL Only** *(3-Min Breach, No Limit)* | **3. Flat `2.25%` SL Only** *(3-Min Breach, No Limit)* | **4. 4-Stage Dynamic Engine (`3.0%->1.5%->1.0%` SL, `14:30` Exit)** | **5. 4-Stage Dynamic Engine (`3.0%->1.5%->1.0%` SL, `14:45` Exit)** |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Gross PnL (Before Taxes)** | `+₹112.35 Lakhs` | `+₹110.68 Lakhs` | `+₹117.69 Lakhs` | `+₹120.79 Lakhs` | **`+₹123.02 Lakhs`** |
| **Total Kotak Taxes** | `-₹21.39 Lakhs` | `-₹21.39 Lakhs` | `-₹21.39 Lakhs` | `-₹24.01 Lakhs` | `-₹24.01 Lakhs` |
| **Total Net PnL (`@ ₹10L/stock`)** | **`+₹90.96 Lakhs`** | `+₹89.29 Lakhs` | `+₹96.30 Lakhs` | `+₹96.78 Lakhs` | **`+₹99.00 Lakhs`** *(+₹130.72L exact ticks)* |
| **Total Net PnL (`@ ₹7.5L` Live Scale)** | **`+₹68.22 Lakhs`** | `+₹66.97 Lakhs` | `+₹72.22 Lakhs` | `+₹72.58 Lakhs` | **`+₹74.25 Lakhs`** *(+₹98.04L exact ticks)* |
| **Net Trade Win Rate (%)** | **`56.92%`** *(58.31% Gross)* | `56.49%` | `56.07%` | `61.79%` | **`61.53%`** *(66.84% exact ticks)* |
| **Profit Factor** | `1.28` | `1.28` | `1.31` | `1.38` | **`1.38`** *(1.94 exact ticks)* |
| **Worst Single Trade Loss** | `-₹1,49,121` | `-₹61,982` | `-₹61,982` | `-₹54,089` | **`-₹54,089` (`-64%` tail cut)** |
| **Worst Single Day PnL** | `-₹2,49,931` | `-₹1,63,065` | `-₹1,30,300` | `-₹1,10,248` | **`-₹1,10,248` (`-56%` tail cut)** |
| **Max Portfolio Drawdown (`@ ₹10L`)** | `-₹5.73 Lakhs` | `-₹5.25 Lakhs` | `-₹4.85 Lakhs` | `-₹3.20 Lakhs` | **`-₹3.28 Lakhs` (`-43%` DD cut)** |
| **Annualized Sharpe / Sortino** | `2.21` / `3.60` | `2.27` / `3.88` | `2.55` / `4.56` | `3.26` / `5.74` | **`3.29` / `5.83`** |
| **Calmar Ratio (`Net / MaxDD`)** | `15.9x` | `17.0x` | `19.9x` | `30.2x` | **`30.2x`** |

### 2. Year-by-Year Net PnL (`@ ₹10L/Stock`, `14:45:00` Exit): Pure Model vs. Live 4-Stage Dynamic Engine (`3.0% -> 1.5% -> 1.0%` SL)
| Period | Trades | **Pure Model (`09:42 -> 14:45`, No SL, No Limit)** | **Live 4-Stage Dynamic (`3.0% -> 1.5% -> 1.0%` SL)** |
| :--- | :---: | :---: | :---: |
| **2020** | 768 | `+₹19.62L` (`59.3%` WR, `-₹3.47L` DD) | **`+₹20.67L` (`67.4%` WR, `-₹1.48L` DD)** |
| **2021** | 784 | `+₹24.52L` (`61.8%` WR, `-₹5.49L` DD) | **`+₹26.78L` (`67.5%` WR, `-₹1.44L` DD)** |
| **2022** | 762 | `+₹9.61L` (`55.7%` WR, `-₹5.73L` DD) | **`+₹9.98L` (`59.0%` WR, `-₹3.03L` DD)** |
| **2023** | 788 | `+₹7.76L` (`55.0%` WR, `-₹3.13L` DD) | **`+₹9.68L` (`57.8%` WR, `-₹1.69L` DD)** |
| **2024** | 778 | `+₹4.78L` (`53.8%` WR, `-₹4.21L` DD) | **`+₹7.14L` (`58.0%` WR, `-₹2.89L` DD)** |
| **2025** | 777 | **`+₹13.08L` (`57.3%` WR, `-₹4.10L` DD)** | `+₹11.07L` (`60.0%` WR, `-₹3.28L` DD) *(+₹12.65L @ 14:30)* |
| **2026 YTD (to Oct 30)** | 622 | `+₹11.60L` (`55.3%` WR, `-₹2.99L` DD) | **`+₹13.69L` (`60.7%` WR, `-₹1.67L` DD)** |
| **2026-H2 OOS (`Jul 1 – Oct 30`)** | 305 | **`+₹8.09L` (`55.7%` WR, `-₹2.46L` DD)** | **`+₹6.60L` (`61.0%` WR, `-₹1.00L` DD)** |
| **Last Week (`Oct 27 – Oct 30`)** | 15 | `-₹1.30L` (`33.3%` WR, `-₹1.48L` DD) | **`-₹0.71L` (`46.7%` WR, `-₹0.74L` DD — saved `+₹0.59L`)** |

### 3. 09:20 Scalp Model (50/50 Order Fill Logic)
| Metric | ₹5 Lakhs Capital | ₹10 Lakhs Capital |
| :--- | :--- | :--- |
| **Total Trades** | 5,567 | 5,567 |
| **Net PnL** | **+₹44.27 Lakhs** | **+₹70.78 Lakhs** |
| **Win Rate** | **75.59%** (4,208 wins) | **77.85%** (4,334 wins) |
| **Profit Factor** | **2.51** | **2.40** |
| **Max Drawdown** | **-₹0.51 Lakhs** | **-₹0.97 Lakhs** |

---

## 🚀 How to Run

### Reproducing Historical Backtests & Pure vs. Dynamic SL Comparisons
```bash
# Pure Model (No SL, No Limit, 14:45 Exit) vs Live 4-Stage Dynamic SL (3.0% -> 1.5% -> 1.0%)
python3 01_historical_models/0940_hybrid_model/sim_0940_pure_1445.py

# Pure Model Unstopped Edge (09:42 -> 15:24) & Intraday MFE/MAE Quantiles
python3 01_historical_models/0940_hybrid_model/sim_0940_pure_no_sl_no_limit.py

# Half-Yearly (Jan 1 & Jul 1) vs Quarterly / Monthly / Bi-Weekly Retraining Benchmark
python3 01_historical_models/0940_hybrid_model/test_retraining_frequencies_2020_2026.py

# Exact 1:1 Live Pipeline Historical Walk-Forward Backtest (2020-2026)
python3 01_historical_models/0940_hybrid_model/backtest_exact_live_pipeline_2020_2026.py
```

### Running Live Production Pipelines & Half-Yearly Retraining
```bash
# Half-Yearly Expanding Window Model Retrain (Jan 1 & Jul 1 at 18:00 IST)
bash 02_live_production_pipelines/0940_hybrid_pipeline/run_monthly_retrain.sh

# Morning 09:20 Scalp Pipeline (Triggers at 09:18 AM via cron/PM2)
bash 02_live_production_pipelines/0920_scalp_pipeline/run_0920_scalp_pipeline.sh

# Morning 09:40 Hybrid Pipeline (Triggers at 09:41 AM via cron/PM2)
bash 02_live_production_pipelines/0940_hybrid_pipeline/run_0940_hybrid_pipeline.sh

# Evening PnL Reconciliations (Triggers at 16:00 / 16:10 / 16:15 PM via cron/PM2)
bash 02_live_production_pipelines/0920_scalp_pipeline/run_0920_evening_reconcile.sh
bash 02_live_production_pipelines/0940_hybrid_pipeline/run_0940_evening_reconcile.sh
bash 02_live_production_pipelines/0940_hybrid_pipeline/run_0940_live_mimic_reconcile.sh
```
