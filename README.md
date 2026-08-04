# 🏹 Sniper Trading System: Dynamic Threshold Multi-Frequency Ensemble

This repository houses the final production code for the **Sniper Algorithmic Trading System**. The engine utilizes a **Multi-Frequency Walk-Forward Ridge Regression Ensemble** (combining Daily, Weekly, Monthly, Quarterly, and Yearly models) equipped with a lookahead-free **Dual-Metric Hybrid Regime Switcher** and **Dynamic Threshold Gates** to identify high-probability F&O intraday cash breakout candidates on the NSE.

---

## 📂 Repository Layout

```
.
├── data/
│   ├── data_input_files.tar.gz         # Compressed 78MB archive containing all clean historical CSVs
│   ├── package.json                    # Node.js dependencies for ICICI Breeze client downloads
│   └── package-lock.json
│
├── pipeline/
│   ├── update_today_gaps_morning.js    # Morning gaps downloader (Yahoo Primary + ICICI Fallback Backup)
│   ├── 6.icici_daily_intraday_and_gap.js# Daily afternoon Cash 1-minute tick downloader
│   ├── 7.compute_intraday_features.py  # Standalone features computation engine
│   ├── compute_f11_intraday_features_update.py # Incremental features computation engine (Pipeline Version)
│   └── run_todays_prediction_pipeline.sh # Unified cron/runner shell script (Executed daily at 3:19 PM)
│
├── historical_models/
│   ├── dynamic_threshold.py            # Primary Walk-Forward Model Fitter and Simulation Core
│   ├── test_trimmed_adaptive_hybrid_pnl_noise_removed.py # Noise-removed dual-metric ensemble model simulator
│   ├── analyze_2026_profits.py         # Year-to-date (2026) diagnostic utility
│   ├── rebuild_historical_caches.sh   # Background script to regenerate all walk-forward caches
│   └── output/                         # Stores model prediction cache pickles and trading csv logs
│
└── README.md                           # This premium instruction manual
```

---

## ⚡ Setup & Extraction

Because raw CSV tables inside `data/` exceed GitHub's strict **100MB size limit**, all master input datasets are stored as a highly compressed 78MB archive.

### 1. Extract the Data Files
Before running any script or backtest, navigate to the `data` folder and extract the master database files:
```bash
cd data/
tar -xzvf data_input_files.tar.gz
cd ..
```
*This extracts:*
*   `f11_intraday_features_all.csv` (~144MB) - clean, deduplicated intraday features from 2015-present.
*   `markets_pnl0325.csv` (~24MB) - complete simulated trading P&L logs.
*   `yahoo_finance_all_stocks_2015_2026_gap_features.csv` (~20MB) - master historical gap analysis dataset.
*   `yahoo_finance_all_stocks_2015_2026_ohlc.csv` (~37MB) - daily candle master candles.
*   `masterfile.csv` - full stock metadata lists.

### 2. Install Node.js Dependencies
Install the required ICICI Breeze client dependencies for connection feeds:
```bash
cd data/
npm install
cd ..
```

---

## ⏰ Production Execution Pipeline

The live daily prediction system executes automatically in two daily phases:

### Phase 1: Morning Gap Collection (9:32 AM)
Immediately after the market open, trigger the morning downloader to compute daily stock opening gaps:
```bash
node pipeline/update_today_gaps_morning.js
```
*   **Yahoo Finance (Primary):** Concurrent HTTP chart downloads (super fast).
*   **ICICI Breeze (Fallback):** Authenticates and backfills and fills missing gaps on index and stock names.

### Phase 2: Afternoon Prediction Run (3:19 PM)
Execute the unified shell script to fetch live intraday ticks, calculate cash features, retrain models, select breakout candidates, and dispatch orders to Telegram:
```bash
./pipeline/run_todays_prediction_pipeline.sh
```
*This runs three sequential steps under the hood:*
1.  **Step 1:** Downloads live 1-minute minute-ticks up to 15:19 PM from ICICI Breeze.
2.  **Step 2:** Calculates F11 intraday cash features with robust weekly-chunk deduplication.
3.  **Step 3:** Retrains Ridge Regression models in walk-forward, runs dual-metric regime switcher thresholds, selects picks, and dispatches them via `OrderInfoBot` to Telegram.

---

## 📊 Backtesting & Model Simulation

To recreate the backtest results and rebuild walk-forward training cache files completely from scratch:

### 1. Rebuild Walk-Forward Prediction Caches
Because walk-forward fitting groups a decade of 1-minute tick data, retraining is cached as binary pickles (`.pkl`) to make execution instantaneous. To purge old caches and rebuild them on the fresh, clean database:
```bash
./historical_models/rebuild_historical_caches.sh
```
*This sequentially retrains and compiles lookahead-free prediction caches for:*
*   `yearly` / `quarterly` / `monthly` / `weekly` / `daily` Ridge ensembles.

### 2. Run Ensemble Simulation & Audited Reports
Execute the primary hybrid simulator to compute trailing win rates, drawdowns, CAGR, and annual Sharpe ratios:
```bash
python3 historical_models/test_trimmed_adaptive_hybrid_pnl_noise_removed.py
```

### 3. Diagnose YTD 2026 Trades
Print monthly breakdowns, win rates, and top gains/losses for 2026 completed trades:
```bash
python3 historical_models/analyze_2026_profits.py
```
