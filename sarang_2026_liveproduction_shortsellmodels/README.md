# Live Production Short-Sell Models & Historical Replicas (2026)
**Branch:** `sarang_2026_liveproduction_shortsellmodels`  
**Repository:** `sarangsukumar/daily_prediction_sytem_Dynamic_threshold.git`

---

## 📌 Executive Summary

This branch contains the exact code, models, datasets, and configurations powering the **Live Production Short-Sell Systems** as well as their **1:1 Historical Walk-Forward Simulation Replicas**:

1. **09:20 Scalp Model**:
   - High-velocity morning scalp short-selling pipeline.
   - **Order Fill Logic:** 50/50 Split (50% Market/Best-Bid Fill + 50% Passive Limit 0.10% above 09:20 open).
   - **Exit Mechanics:** 09:36 dynamic trailing profit-taking (+₹1,500 target threshold) + 09:40 mandatory time square-off.
   - **Historical Performance (2020–2026):**
     - ₹5L Capital: **+₹44.27 Lakhs Net PnL**, 75.59% Win Rate, 2.51 Profit Factor.
     - ₹10L Capital: **+₹70.78 Lakhs Net PnL**, 77.85% Win Rate, 2.40 Profit Factor.

2. **09:40 Hybrid Model (Option A Replacement Engine + 4-Stage Dynamic Exit Engine)**:
   - Trend-following longer-window short-sell pipeline (`09:42` Entry to `14:30 / 14:45` Exit) on **Cash Equities (`scrapdata`)**.
   - **Filtering & Selection:** Rule 1 Cutoff at `-1.50%` (skips severely gap-down stocks), Rule 2 Crash Day Protector (`nifty_pct < -0.5%` & `stock_pct_940 < -0.5%`), Rule 4 Breadth `< 10%`.
   - **Option A Dynamic Replacement:** When a Top-4 stock is filtered out by Rule 1, candidate stocks from Rank 5 or Rank 6 enter provided their `stock_pct_940 >= -0.50%`.
   - **Active Live Exit Architecture (`SIM 3A: 4-Stage Dynamic Engine`):**
     - **Stage 1 (Time-Decay 3-Min Cont. Breach SL):** `2.25%` (`09:42–11:00`) $\rightarrow$ `1.50%` (`11:00–12:30`) $\rightarrow$ `1.00%` (`12:30+`), requiring 3 full minutes of continuous breach before exit.
     - **Stage 2 (Pre-TP Profit Lock at `+1.25%`):** Locks protective stop at `+0.50%` profit (`EP * 0.9950`) once peak profit reaches `+1.25%`.
     - **Stage 3 (Uncapped Dynamic Trailing TP at `+2.00%`):** Sets initial trailing floor at **`+1.75%` profit** (`EP * 0.9825`) and ratchets downward `0.50%` behind peak profit (`max(1.75%, max_profit - 0.50%)`).
     - **Stage 4 (Pullback Re-Entry):** Enters Leg 2 Short on a `+0.50%` bounce after a Leg 1 profit exit before `14:00 IST` (`1.75%` TP2, Zero-Risk SL at Leg 1 Entry).
   - **Historical Performance (`2020–2026`, `5,269` Option A Trades at ₹10L/stock):**
     - **SIM 1A (No TP, 1-Tick `2.25%` SL):** **+₹102.22 Lakhs Net PnL** (`2026 YTD: +₹11.42 Lakhs`), Max DD `-₹4.58L`.
     - **SIM 1B (No TP, 3-Min `2.25%` SL):** **+₹97.62 Lakhs Net PnL** (`2026 YTD: +₹10.21 Lakhs`), Max DD `-₹5.71L`.
     - **SIM 2B (`2.0%` TP, 3-Min `2.25%` SL, `+0.50%` Re-Entry):** **+₹95.78 Lakhs Net PnL** (`2026 YTD: +₹9.82 Lakhs`), Max DD `-₹4.62L`.
     - **SIM 3A (Active Live 4-Stage Dynamic Engine):** **+₹97.16 Lakhs Net PnL** (`2026 YTD: +₹10.84 Lakhs`), **60.8% Win Rate**, **1.39 Profit Factor**, **3.07 Sharpe Ratio**, **30.1x Calmar Ratio**, and **Lowest Max Drawdown (`-₹3.23 Lakhs`)**.

3. **Kotak Neo Live Execution Suite**:
   - Live order placement bridge (`Neo_shortsell_mis_order.py`) with 50/50 fill execution, cadence order verification, Stage 4 pullback re-entry execution, idempotency checks against duplicate orders, and automatic open limit cancellation prior to target evaluation.
   - 4-Stage Real-Time Exit & Stop-Loss Proximity Monitor (`sl_near_alert_monitor.py`).

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
│   │   ├── walkforward_0920_5050_yearly_summary.csv   # Year-by-year PnL breakdown
│   │   ├── equity_curves_5050_comparison.png          # Visual equity curves comparing capital tiers
│   │   └── walkforward_0920_audit_report_10L.pdf      # PDF audit report
│   │
│   └── 0940_hybrid_model/                             # 09:40 Hybrid Option A Replacement Historical Pipeline
│       ├── README_0940_OPTION_A_PIPELINE.md           # Detailed Option A & 4-Simulation documentation
│       ├── walkforward_0942_simulation.py             # Primary walk-forward simulation runner (₹5L Option A)
│       ├── walkforward_0942_simulation_10L.py         # ₹10L capital walk-forward runner (Option A)
│       ├── simulate_rule1_replacements_pct05.py       # Option A replacement validator
│       ├── trades_system_with_rep_pct05_oct23.csv     # Combined Option A trade ledger (5,269 trades, +₹102.14L)
│       ├── option_a_5269_4sims_comparison.csv         # Complete 4-Simulation comparison across 5,269 trades
│       ├── trades_replacements_rank5_6_pct05_oct23.csv# Replacement trade ledger (289 trades, +₹8.85L)
│       ├── trades_base_cutoff15_oct23.csv             # Base system trade ledger (4,980 trades, +₹93.29L)
│       └── walkforward_0942_3strategy_audit_report.pdf# 3-strategy PDF audit report
│
├── 02_live_production_pipelines/                      # Live Automated Production Runners
│   ├── 0920_scalp_pipeline/
│   │   ├── live_0920_scalp_pipeline.py                # Main morning scalp orchestrator (09:18 - 09:25)
│   │   ├── new_live_0920_pipeline.py                  # Live predictor & ranking engine
│   │   ├── confirm_0925_fills.py                      # 09:25 fill confirmator with 50/50 split tracking
│   │   ├── exit_0936_check.py                         # 09:36 trailing profit taking check
│   │   ├── exit_0940_cover.py                         # 09:40 full cover exit manager
│   │   ├── reconcile_0920_scalp_pnl.py                # Evening PnL reconciler with 50/50 split calculations
│   │   ├── lgb_0920_scalp_model.txt                   # Production LightGBM model weights
│   │   ├── live_0920_scalp_pipeline.sh                # Shell runner for 09:20 pipeline
│   │   └── run_0920_evening_reconcile.sh              # Shell runner for evening reconciliation
│   │
│   └── 0940_hybrid_pipeline/
│       ├── live_0940_hybrid_pipeline.py               # Main 09:40 orchestrator with Option A replacements
│       ├── confirm_0942_fills.py                      # 09:42 entry confirmation
│       ├── reconcile_0940_hybrid_pnl.py               # Evening reconciler (Cash Equity scrapdata primary)
│       ├── reconcile_0940_live_mimic_pnl.py           # 3-Simulation tick-level live mimic reconciler (16:15 IST)
│       ├── daily_0940_live_ledger.csv                 # Master Option A + Live trade ledger (5,277 trades)
│       ├── daily_0940_live_mimic_ledger.csv           # Master 3-Simulation trade ledger (5,277 trades)
│       ├── lgb_0940_rebound_aware_audited_model.txt   # Production 12-feature Rebound-Aware LightGBM weights
│       ├── run_0940_hybrid_pipeline.sh                # Shell runner for 09:41 AM pipeline
│       ├── run_0940_evening_reconcile.sh              # Shell runner for 16:10 PM reconciliation
│       └── run_0940_live_mimic_reconcile.sh           # Shell runner for 16:15 PM 3-Sim reconciliation
│
└── 03_kotak_execution/                                # Broker Execution Bridge
    ├── Neo_shortsell_mis_order.py                     # Kotak Neo API MIS short sell order & Leg 2 placer
    ├── sl_near_alert_monitor.py                       # Real-time 4-Stage Exit & Proximity Alert Daemon
    └── notify_pipeline_armed.py                       # Morning pipeline armed Telegram notifier
```

---

## 📊 Performance Benchmark Summary

### 1. 09:20 Scalp Model (50/50 Order Fill Logic)
| Metric | ₹5 Lakhs Capital | ₹10 Lakhs Capital |
| :--- | :--- | :--- |
| **Total Trades** | 5,567 | 5,567 |
| **Gross Profit** | ₹73.57 L | ₹121.28 L |
| **Gross Loss** | -₹29.30 L | -₹50.50 L |
| **Net PnL** | **+₹44.27 Lakhs** | **+₹70.78 Lakhs** |
| **Win Rate** | **75.59%** (4,208 wins) | **77.85%** (4,334 wins) |
| **Profit Factor** | **2.51** | **2.40** |
| **Max Drawdown** | **-₹0.51 Lakhs** | **-₹0.97 Lakhs** |

### 2. 09:40 Hybrid Model — 4-Simulation Comparison (`5,269` Option A Trades, `2020–2026`, ₹10L/Stock)
| Strategy Configuration | Total Net PnL (`2020–2026`) | **2026 YTD Net PnL (`612` Trades)** | Win Rate | Profit Factor | Max Drawdown | Sharpe | Calmar |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **SIM 1A:** No TP \| SL `2.25%` (1-Tick) \| Exit `14:45` | **`+₹102.22 Lakhs`** | **`+₹11.42 Lakhs`** | `55.8%` | `1.34` | `-₹4.58 Lakhs` | `2.51` | `22.3x` |
| **SIM 1B:** No TP \| SL `2.25%` (**3-Min Cont. Breach**) \| Exit `14:45` | **`+₹97.62 Lakhs`** | **`+₹10.21 Lakhs`** | `56.4%` | `1.31` | `-₹5.71 Lakhs` | `2.32` | `17.1x` |
| **SIM 2B:** `2.0%` TP \| SL `2.25%` (**3-Min Cont. Breach**) \| `+0.50%` Re-Entry | **`+₹95.78 Lakhs`** | **`+₹9.82 Lakhs`** | `58.9%` | `1.33` | `-₹4.62 Lakhs` | `2.65` | `20.7x` |
| **SIM 3A (Active Live 4-Stage Engine):** Time-Decay SL + `1.25%` Lock + `1.75%` Trail Floor + Re-Entry | **`+₹97.16 Lakhs`** | **`+₹10.84 Lakhs`** | **`60.8%`** | **`1.39`** | **`-₹3.23 Lakhs`** | **`3.07`** | **`30.1x`** |
| **SIM 3B (4-Stage w/ Constant `2.25%` SL):** No SL Decay + `1.25%` Lock + `1.75%` Trail Floor + Re-Entry | **`+₹94.41 Lakhs`** | **`+₹10.94 Lakhs`** | **`63.0%`** | `1.36` | `-₹3.71 Lakhs` | `2.76` | `25.5x` |

---

## 🚀 How to Run

### Reproducing Historical Backtests
```bash
# 09:20 Scalp 50/50 Historical Walk-Forward Simulation
python3 01_historical_models/0920_scalp_model/walkforward_0920_5050_pipeline.py

# 09:40 Hybrid Option A Walk-Forward Simulation (₹5L & ₹10L)
python3 01_historical_models/0940_hybrid_model/walkforward_0942_simulation.py
python3 01_historical_models/0940_hybrid_model/walkforward_0942_simulation_10L.py
```

### Running Live Production Pipelines
```bash
# Morning 09:20 Scalp Pipeline (Triggers at 09:18 AM via cron/PM2)
bash 02_live_production_pipelines/0920_scalp_pipeline/run_0920_scalp_pipeline.sh

# Morning 09:40 Hybrid Pipeline (Triggers at 09:41 AM via cron/PM2)
bash 02_live_production_pipelines/0940_hybrid_pipeline/run_0940_hybrid_pipeline.sh

# Evening PnL Reconciliations (Triggers at 16:00 / 16:10 / 16:15 PM via cron/PM2)
bash 02_live_production_pipelines/0920_scalp_pipeline/run_0920_evening_reconcile.sh
bash 02_live_production_pipelines/0940_hybrid_pipeline/run_0940_evening_reconcile.sh
bash 02_live_production_pipelines/0940_hybrid_pipeline/run_0940_live_mimic_reconcile.sh
```
