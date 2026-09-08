# 🚀 Short Sell Quant Strategy & ML Model Engine (`shortsellmodel940v3`)

An end-to-end, leak-free short-selling trading strategy and Machine Learning pipeline built for Indian Equity F&O Stock Futures.

---

## 📌 Architectural Overview & Guarantees

1. **Universe Filter (Day $T-1$ Custom Limit Met Orders):**
   - Candidate stocks are filtered strictly from yesterday's executed Custom Limit sell signals (`markets_pnl0325.csv`).
2. **Prior-Day Technical Indicators ($T-1$):**
   - 23 technical indicators calculated strictly after yesterday's market close (15:30 PM IST). 100% known before market open today.
3. **Morning Feature Engineering ($T$ 09:15 to 09:40 AM):**
   - Features computed using near-month F&O stock futures tick data (`scrapdata_F1`) up to **09:40:00 AM IST** (`WHERE time <= '09:40:00'`). Zero reliance on Yahoo Finance volume data.
4. **2-Minute Real-World Execution Leeway:**
   - ML inference and stock selection run between 09:40:00 and 09:42:00 AM. Orders placed and filled at the exact **09:42:00 AM IST** close price.
5. **Zero Lookahead Monthly Walk-Forward ML Engine:**
   - Expanding monthly walk-forward training loop (`train_mask = df['year_month'] < ym`, `test_mask = df['year_month'] == ym`).
6. **Mandatory Transaction Cost Deduction:**
   - Flat **₹300 per trade** transaction cost (scaled by position sizing) deducted on all trades.

---

## 📊 Performance Summary (2018 – 2026 Walk-Forward OOS)

- **Total Net Profit:** **₹2,22,64,393 (₹2.226 Crore)**
- **Total Trades:** **7,687**
- **Overall Win Rate:** **62.34%**
- **Sharpe Ratio:** **6.60**
- **Max Drawdown:** **-₹2,68,397**
- **Positive Years:** **100% (9 out of 9 Consecutive Years)**

### 📅 Year-by-Year Walk-Forward Breakdown

| Year | Trades | Win Rate (%) | Avg PnL / Trade | Total Net PnL (₹) |
| :---: | :---: | :---: | :---: | :---: |
| **2018** | 903 | 63.8% | ₹2,685 | **+₹24,24,349** |
| **2019** | 840 | 59.6% | ₹1,455 | **+₹12,22,140** |
| **2020** | 929 | 65.8% | ₹3,420 | **+₹31,77,600** |
| **2021** | 904 | 69.5% | ₹5,997 | **+₹54,21,696** |
| **2022** | 902 | 63.7% | ₹3,523 | **+₹31,77,514** |
| **2023** | 904 | 57.7% | ₹2,218 | **+₹20,05,293** |
| **2024** | 915 | 59.3% | ₹2,395 | **+₹2,191,252** |
| **2025** *(Unseen OOS)* | 879 | 61.5% | ₹2,158 | **+₹18,96,714** |
| **2026** *(Unseen OOS - 8 Mo)* | 511 | 57.7% | ₹1,463 | **+₹7,47,835** *(Annualized ~₹11.2L)* |
| **TOTAL** | **7,687** | **62.34%** | **₹2,896** | **₹2,22,64,393** |

---

## 🛠️ Step-by-Step Historical Rebuild Instructions

### Step 1: Rebuild Dataset (`build_dataset_v3.py`)
Generates `short_sell_ml_dataset_v3.csv` by combining candidate universe filtering, prior-day indicators, and 09:15–09:40 AM morning intraday technicals.
```bash
python3 build_dataset_v3.py
```

### Step 2: Walk-Forward ML Model Training (`train_model_v3.py`)
Runs expanding monthly walk-forward LightGBM classifiers across 2018–2026 and saves top-ranked out-of-sample predictions to `predictions_top10_v3.csv`.
```bash
python3 train_model_v3.py
```

### Step 3: Run 09:42 AM PnL Simulation (`sim_golden_2026_boost.py`)
Simulates execution filled at 09:42:00 AM IST close price, applying the Conviction Alpha Engine, trailing stop loss, and ₹300 per-trade transaction cost.
```bash
python3 sim_golden_2026_boost.py
```

---

## ⏰ Daily Live Execution Schedule (Automation Workflow)

1. **Daily at 15:35 PM IST (After Market Close Day $T-1$):**
   - Extract candidate stocks where Custom Limit orders were hit (`markets_pnl0325.csv`).
   - Calculate 23 prior-day technical indicators (`prev_intraday_`) from completed tick data and store in cache.

2. **Daily at 09:40:00 AM IST (Trading Day $T$):**
   - Query 1-minute stock futures ticks from `scrapdata_F1` up to 09:40:00 AM IST.
   - Compute 09:40 AM morning indicators (`stock_ret_940`, `nifty_ret_940`, `morn_range_pct`, `rejection_wick`, `Gap_Pct`).
   - Run ML model inference to predict short-sell probabilities and rank candidate stocks.

3. **Daily at 09:42:00 AM IST:**
   - Execute short-sell orders at Market / Limit for Top 5 ranked stocks.

4. **Intraday Risk Management (09:42 AM to 14:45 PM IST):**
   - **Rank 1:** Trailing Runner (SL 5.0%, Act 1.5%, Floor 1.0%, Giveback 0.3%).
   - **Ranks 2–5 Normal Days:** Scalp TP Target 1.5% (SL 4.0%).
   - **Ranks 2–5 Bleed Days (Nifty $\le -0.10\%$):** Adaptive Trailing (SL 4.0%, Act 1.2%, Floor 0.8%, Giveback 0.3%).
   - **Auto-Square-off:** All active positions closed at **14:45 PM IST**.
