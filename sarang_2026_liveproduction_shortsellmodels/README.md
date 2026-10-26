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

2. **09:40 Hybrid Model (Option A Replacement Engine)**:
   - Trend-following longer-window short-sell pipeline.
   - **Filtering & Selection:** Rule 1 Cutoff at `-1.50%` (skips severely gap-down stocks).
   - **Option A Dynamic Replacement:** When a top-4 stock is filtered out by Rule 1, candidate stocks from Rank 5 or Rank 6 enter provided their `stock_pct_940 >= -0.50%`.
   - **Historical Performance (2020–2026):**
     - Base System: +₹93.29 Lakhs Net PnL (4,980 trades).
     - Replacements (Option A): +₹8.85 Lakhs Net PnL (289 trades, 57.44% Win Rate).
     - Combined Total: **+₹102.14 Lakhs Net PnL** across 5,269 trades.

3. **Kotak Neo Live Execution Suite**:
   - Live order placement bridge (`Neo_shortsell_mis_order.py`) with 50/50 fill execution, cadence order verification, idempotency checks against duplicate orders, and automatic open limit cancellation prior to target evaluation.
   - Stop-Loss Proximity Monitor (`sl_near_alert_monitor.py`).

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
│   │   ├── walkforward_0920_audit_report_10L.pdf      # PDF audit report
│   │   └── ... (parameter sweeps and sensitivity tests)
│   │
│   └── 0940_hybrid_model/                             # 09:40 Hybrid Option A Replacement Historical Pipeline
│       ├── README_0940_OPTION_A_PIPELINE.md           # Detailed Option A simulation documentation
│       ├── walkforward_0942_simulation.py             # Primary walk-forward simulation runner (Option A)
│       ├── walkforward_0942_simulation_10L.py         # 10L capital walk-forward runner
│       ├── simulate_rule1_replacements_pct05.py       # Option A replacement validator
│       ├── trades_system_with_rep_pct05_oct23.csv     # Combined trade ledger (+₹102.14 Lakhs)
│       ├── trades_replacements_rank5_6_pct05_oct23.csv# Replacement trade ledger (+₹8.85 Lakhs)
│       ├── trades_base_cutoff15_oct23.csv             # Base system trade ledger (+₹93.29 Lakhs)
│       ├── walkforward_0942_3strategy_audit_report.pdf# 3-strategy PDF audit report
│       └── ... (filter breakdown and research audits)
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
│       ├── reconcile_0940_hybrid_pnl.py               # Evening reconciler for hybrid pipeline
│       ├── reconcile_0940_live_mimic_pnl.py           # Tick-level live mimic reconciler
│       ├── lgb_0940_hybrid_huber_model.txt            # Production LightGBM Huber regression weights
│       ├── lgb_0940_rebound_aware_audited_model.txt   # Rebound-aware classifier weights
│       ├── run_0940_hybrid_pipeline.sh                # Shell runner for 09:40 pipeline
│       └── run_0940_evening_reconcile.sh              # Shell runner for evening reconciliation
│
└── 03_kotak_execution/                                # Broker Execution Bridge
    ├── Neo_shortsell_mis_order.py                     # Kotak Neo API MIS short sell order placer
    └── sl_near_alert_monitor.py                       # Proximity alert daemon for Telegram notifications
```

---

## 📊 Performance Benchmark Summary

### 09:20 Scalp Model (50/50 Order Fill Logic)
| Metric | ₹5 Lakhs Capital | ₹10 Lakhs Capital |
| :--- | :--- | :--- |
| **Total Trades** | 5,567 | 5,567 |
| **Gross Profit** | ₹73.57 L | ₹121.28 L |
| **Gross Loss** | -₹29.30 L | -₹50.50 L |
| **Net PnL** | **+₹44.27 Lakhs** | **+₹70.78 Lakhs** |
| **Win Rate** | **75.59%** (4,208 wins) | **77.85%** (4,334 wins) |
| **Profit Factor** | **2.51** | **2.40** |
| **Max Drawdown** | **-₹0.51 Lakhs** | **-₹0.97 Lakhs** |

### 09:40 Hybrid Model (Option A Replacement Engine)
| Strategy Segment | Trades | Win Rate | Profit Factor | Net PnL (₹) |
| :--- | :--- | :--- | :--- | :--- |
| **Base System (Rule 1 Cutoff -1.5%)** | 4,980 | 56.73% | 1.84 | **+₹93,29,190** |
| **Option A Replacements (Rank 5 & 6, pct >= -0.5%)** | 289 | 57.44% | 1.63 | **+₹8,84,650** |
| **Combined 09:40 System** | **5,269** | **56.77%** | **1.82** | **+₹1,02,13,840 (+₹1.02 Cr)** |

---

## 🚀 How to Run

### Reproducing Historical Backtests
```bash
# 09:20 Scalp 50/50 Historical Walk-Forward Simulation
python3 01_historical_models/0920_scalp_model/walkforward_0920_5050_pipeline.py

# 09:40 Hybrid Option A Walk-Forward Simulation
python3 01_historical_models/0940_hybrid_model/walkforward_0942_simulation.py
```

### Running Live Production Pipelines
```bash
# Morning 09:20 Scalp Pipeline (Triggers at 09:18 AM via cron/PM2)
bash 02_live_production_pipelines/0920_scalp_pipeline/run_0920_scalp_pipeline.sh

# Morning 09:40 Hybrid Pipeline (Triggers at 09:39 AM via cron/PM2)
bash 02_live_production_pipelines/0940_hybrid_pipeline/run_0940_hybrid_pipeline.sh

# Evening PnL Reconciliations (Triggers at 16:00 PM via cron/PM2)
bash 02_live_production_pipelines/0920_scalp_pipeline/run_0920_evening_reconcile.sh
bash 02_live_production_pipelines/0940_hybrid_pipeline/run_0940_evening_reconcile.sh
```
