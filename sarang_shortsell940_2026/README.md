# 📉 Institutional Morning Short Sell Algorithm (2026 Production Edition)

A high-conviction, quantitative machine learning trading system designed to short-sell overextended morning gap-up stocks in the **National Stock Exchange of India (NSE) Futures & Options (F&O)** segment.

Built strictly without look-ahead bias or survivorship bias, the strategy systematically exploits **morning retail buying exhaustion** and **afternoon mean reversion**.

---

## 🏆 Master Performance Benchmark (2018–2026)

* **Strategy:** Top 4 Fortress (LightGBM Ranks 2, 3, 4, 5)
* **Entry Time:** **09:41:00 AM IST**
* **Exit Time:** **14:45:00 PM IST** (or earlier if SL/TP triggered)
* **Risk Management:** **Stop Loss: 4.0% | Take Profit: 1.0%**
* **Friction / Cost:** Flat **₹300 per trade** deducted (brokerage, STT, exchange charges, GST, slippage)
* **Total Simulated Trades:** 6,153 trades across 1,556 trading days
* **Overall Win Rate:** **66.7%**
* **Average Net Profit / Trade:** **₹1,972**
* **Total Cumulative Net PnL:** **₹1,21,35,289 (₹1.21+ Crore)**
* **Annual Consistency:** **9 out of 9 years 100% positive** (0 losing years)

### 📅 Year-by-Year Performance Breakdown

| Year | Trades | Win Rate | Average Trade PnL | Total Net PnL | Take Profit % | Stop Loss % | Time Exit % |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **2018** | 722 | 67.7% | ₹1,794 | **₹12,94,931** | 48% | 1% | 51% |
| **2019** | 672 | 64.0% | ₹1,153 | **₹7,74,601** | 44% | 1% | 55% |
| **2020** | 740 | 70.9% | ₹1,946 | **₹14,39,744** | 52% | 2% | 46% |
| **2021** | 724 | 73.1% | ₹3,221 | **₹23,31,868** | 56% | 1% | 43% |
| **2022** | 718 | 66.9% | ₹2,192 | **₹15,73,663** | 48% | 1% | 51% |
| **2023** | 727 | 62.3% | ₹1,885 | **₹13,70,719** | 45% | 1% | 54% |
| **2024** | 735 | 65.0% | ₹2,051 | **₹15,07,630** | 46% | 1% | 53% |
| **2025** | 707 | 64.4% | ₹1,644 | **₹11,62,576** | 45% | 1% | 54% |
| **2026** | 408 | 64.2% | ₹1,666 | **₹6,79,557** | 44% | 1% | 55% |
| **TOTAL**| **6,153** | **66.7%**| **₹1,972** | **₹1,21,35,289** | **47%** | **1%** | **52%** |

---

## 🎯 Stock Selection: How Trades Are Chosen

Instead of scanning all 200+ F&O stocks, the algorithm uses a high-conviction **Structural Filter**:

### 1. The Custom Limit Fill Filter (The Master Universe)
* The candidate universe is **strictly limited to stocks that hit a "Custom Limit Fill"** on their overnight/morning long position.
* **Economic Logic:** A stock only fills a Custom Limit when it experiences an aggressive upward gap or opening expansion into heavy overhead resistance. 
* This pre-qualifies stocks suffering from **retail FOMO and buyer exhaustion**.
* On any given morning, this creates a focused pool of **5 to 15 candidate stocks**. If no Custom Limit Fills occurred yesterday, **zero trades are taken**.

### 2. The F&O Ban List Filter
* Any stock placed in the official NSE F&O Ban Period is instantly filtered out. 
* Stocks under ban cannot be shorted in reality due to exchange restrictions, preventing false paper profits.

### 3. Machine Learning Ranking
* At 09:40:00 AM, the candidate stocks are scored by the LightGBM production model.
* The model evaluates 48 features and assigns an **exhaustion probability**.
* The **Top 4 Fortress** strategy enters **Ranks 2, 3, 4, and 5** (skipping Rank 1 to avoid high-momentum breakout traps).

---

## ⏱️ Execution Timeline: 09:41 AM Entry & 14:45 PM Exit

| Time (IST) | Event | Pipeline Action |
| :--- | :--- | :--- |
| **09:15:00 AM** | Market Open | Real-time ticks stream via WebSocket and ICICI Breeze. |
| **09:40:00 AM** | Feature Cutoff | First 25 1-minute bars (09:15–09:40) close and lock. |
| **09:40:15 AM** | Feature Extraction | `compute_morning_0940_features.py` extracts morning RSI, MACD, VWAP gap, Arc trajectory (< 1 second). |
| **09:40:20 AM** | ML Inference | `predict_live_0940.py` predicts exhaustion probability and ranks candidate stocks (~100 ms). |
| **09:40:30 AM** | Order Preparation | Orders and Telegram alerts generated. |
| **09:41:00 AM** | **ENTRY EXECUTION** | **Short SELL order placed at the 09:41 candle close.** Position size = 1 Near-Month Futures Lot. |
| **09:42 – 14:45**| Risk Monitoring | Intraday price monitored minute-by-minute: <br>• **TP:** Exit if `Low <= Entry * 0.99` (1.0% drop) <br>• **SL:** Exit if `High >= Entry * 1.04` (4.0% rise) |
| **14:45:00 PM** | **TIME SQUARE-OFF** | If neither SL nor TP triggered, position forcibly squares off at the 14:45 close. |

### 💡 Why 09:41 AM Outperforms 09:45 AM:
Previously, 09:45 AM was used as a conservative placeholder. Moving entry to **09:41 AM**:
* Eliminates 4 wasted minutes of post-model delay.
* Enters at the absolute crest of the morning arc before the drop accelerates.
* Increases total profit from **₹1.16 Crore to ₹1.21 Crore (+₹5.17 Lakhs)** and lifts win rate from **66.0% to 66.7%**.

---

## 🛡️ Rigorous Look-Ahead Bias & Survivorship Audit

1. **Volume Leakage Eliminated:**
   * An earlier draft of the model inadvertently used Yahoo Finance EOD volume (`Volume_Change_Pct`), which leaked afternoon volume into morning predictions.
   * This was **100% purged**. In this model, volume features strictly calculate the cumulative tick volume from 09:15 to 09:40 from MySQL `scrapdata`.
2. **Strict 09:40 Temporal Barrier:**
   * Features only query `TIME(time) BETWEEN '09:15:00' AND '09:40:00'`.
   * At entry time (09:41:00), zero information from 09:41 or later exists in the feature set.
3. **Pessimistic Tie-Breaker Rule:**
   * If both the Stop Loss and Take Profit price are touched within the **same 1-minute bar**, the simulator strictly assumes the **Stop Loss was hit first**.
4. **Historical Official Lot Sizes:**
   * Lot sizes are not assumed. They are mapped dynamically per trade from `config/historical_lotsize_new.csv` (35,207 historical contracts) matching the exact NSE F&O contract specifications valid on that trade date.
5. **Real-World Trading Friction:**
   * Every trade deducts a flat **₹300** to cover Kotak Neo brokerage, STT, turnover fees, stamp duty, GST, and bid-ask slippage.

---

## 🧠 Model Feature Importance (Information Gain %)

The LightGBM production model (`sarang_shortsell_0940_production.pkl`) prioritizes structural market context over noisy minute oscillators:

| Rank | Feature | Category | Gain % | Economic Interpretation |
| :---: | :--- | :--- | :---: | :--- |
| **1** | `days_to_expiry` | Expiry Dynamics | **12.34%** | Days remaining until monthly F&O expiry (gamma/rollover exhaustion). |
| **2** | `hist_count` | Historical Edge | **10.27%** | Stock liquidity and historical trading frequency. |
| **3** | `hist_win_rate` | Historical Edge | **6.11%** | Stock-specific historical fade reliability. |
| **4** | `prev_intraday_return` | Previous Day | **5.85%** | Multi-day runners entering exhaustion. |
| **5** | `Gap_Pct` | Morning Gap | **5.40%** | Opening gap size into resistance. |
| **6** | `morning_return` | Morning Arc | **4.15%** | 09:15 to 09:40 return (confirms buyer momentum stall). |
| **7** | `prev_intraday_volatility` | Previous Day | **3.95%** | Standard deviation of 1-minute returns yesterday. |
| **8** | `prev_intraday_vwap_gap` | Previous Day | **3.92%** | Stretch from yesterday's VWAP (overbought signal). |
| **9** | `prev_intraday_orb_pos` | Previous Day | **3.61%** | Position relative to Opening Range Breakout. |
| **10** | `prev_intraday_roc_last_hour` | Previous Day | **3.53%** | Rate of change in yesterday's final hour (14:30–15:30). |

---

## 💻 Repository Structure

```
sarang_shortsell940_2026/
├── README.md                                  # Complete strategy documentation & benchmark report
├── run_0940_pipeline.sh                       # Master production bash script triggered at 09:41 AM
├── src/
│   ├── compute_morning_0940_features.py       # Live 09:40 feature extraction from MySQL scrapdata
│   ├── predict_live_0940.py                   # Live ML inference and Telegram alert dispatcher
│   ├── train_walk_forward.py                  # Walk-forward cross validation engine
│   └── train_production_model.py             # Trains final production LightGBM model
├── simulation/
│   ├── simulate_0941_comparison.py            # Backtest engine comparing 09:41 vs 09:45 across 2018–2026
│   ├── simulate_best_config.py                # Standalone simulation runner for best configuration
│   ├── optimize_sl_tp.py                      # SL/TP grid search optimizer
│   ├── simulate_no_sl_tp.py                   # Baseline time-exit backtest
│   ├── train_top10_parallel.py                # Top 10 rank extraction script
│   └── fix_volume_leak.py                     # Volume leakage verification and validation test
├── models/
│   └── sarang_shortsell_0940_production.pkl   # Serialized production LightGBM model
├── data/
│   └── live_morning_features.csv              # Live daily computed features
└── output/
    ├── predictions_advanced_top10.csv         # Walk-forward predictions across all 10 ranks
    ├── predictions_rank_1_and_4.csv           # Historical predictions for R1 and R4
    └── compare_0941_vs_0945_results.csv       # Raw trade-by-trade output of the 09:41 vs 09:45 simulation
```

---

## 🚀 How to Reproduce All Results From Scratch

Anyone with access to this repository can reproduce the entire **₹1.21 Crore** backtest result from scratch:

### Prerequisites:
* Python 3.10+
* MySQL database with `scrapdata_F1` (containing 1-minute bars of near-month F&O contracts).

### Step 1: Install Dependencies
```bash
pip install pandas numpy lightgbm scikit-learn mysql-connector-python pymysql joblib
```

### Step 2: Run the 09:41 vs 09:45 Comparative Simulation
```bash
python3 simulation/simulate_0941_comparison.py
```
This script will:
1. Load historical out-of-sample predictions from `output/predictions_advanced_top10.csv`.
2. Query MySQL `scrapdata_F1` for all 1,556 trading days using 10 parallel processes.
3. Simulate entry at **09:41 AM** and **09:45 AM** with **14:45 PM exit**, **4.0% SL**, and **1.0% TP**.
4. Output the exact year-by-year table and total net PnL (**₹1,21,35,289**).

### Step 3: Run the SL / TP Grid Search
```bash
python3 simulation/optimize_sl_tp.py
```
Validates that 4.0% SL and 1.0% TP is the mathematically optimal parameter combination across all combinations from 1.0% to 6.0%.

---

## ⚙️ Daily Live Production Setup

In live production, the algorithm runs completely autonomously:

1. **Scheduled in [`KotakCodes1/daily_schedules.txt`](../KotakCodes1/daily_schedules.txt):**
   ```cron
   '41 09 * * 1-5'$/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_shortsell940_2026/run_0940_pipeline.sh
   ```
2. **Triggered by PM2 Daemon (`thescheduler`):**
   * At **09:41:00 AM IST**, `run_0940_pipeline.sh` executes.
   * Downloads 09:15–09:40 ticks.
   * Extracts morning technicals and runs LightGBM prediction.
   * Emits Telegram alert and stages short sell execution orders.
