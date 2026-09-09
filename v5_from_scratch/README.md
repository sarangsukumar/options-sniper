# 🚀 SHORT SELL MODEL v5 — PRE-MARKET ENRICHED TRADING SYSTEM

---

## 📌 Executive Overview

**Short Sell Model v5** is a production-grade intraday machine learning quantitative trading system designed for the Indian Equity & F&O Markets (NSE). 

The system operates at **09:40:00 AM** daily, analyzing previous day technical indicators, **09:07:00 AM Pre-Market Auction Ticks**, and opening **09:15–09:40 AM morning price action** to select high-probability short-sell candidates for execution at **09:42:00 AM** with exit at **02:45:00 PM (14:45)**.

---

## 📁 Repository & Directory Structure (`/home/ubuntu/shortsellmodel940v5/`)

```
/home/ubuntu/shortsellmodel940v5/
├── README.md                      <-- Comprehensive Deployment & Operating Manual
├── data/                          <-- Datasets & Pre-Market Checkpoint Caches
│   ├── premarket_ticks_cache.csv  <-- 190,000+ cached 09:07 AM auction ticks
│   └── short_sell_ml_dataset_v5.csv <-- Enriched 149,883 trade ML dataset
├── src/                           <-- Executable Production Python Pipeline
│   ├── 1_extract_premarket_data.py <-- Multi-threaded pre-market DB extractor
│   ├── 2_build_dataset_v5.py      <-- Feature engineering & de-leaking builder
│   ├── 3_train_model_v5.py        <-- Walk-forward LightGBM trainer
│   ├── 4_simulate_v5_pnl.py       <-- Simulation & portfolio performance evaluator
│   └── 5_live_prediction_0940_v5.py <-- Daily live 09:40 AM production runner
├── models/                        <-- Saved Production Model Boosters
│   └── model_v5_lgb.txt           <-- Trained LightGBM booster model
└── output/                        <-- Simulation Logs & Trade Logs
    ├── predictions_top10_v5.csv   <-- Out-of-sample prediction probability logs
    └── simulated_trades_v5_top3.csv <-- Top 3 daily trade execution log
```

---

## 🛠️ Step-by-Step Reproduction Guide

To reproduce all datasets, trained models, predictions, and simulation PnL results from scratch:

### **Step 1: Extract Pre-Market Auction Ticks**
Extracts `09:07:00 AM` pre-market prices across 1,967 trading dates (2018–2026) using 32 parallel database threads:
```bash
python3 /home/ubuntu/shortsellmodel940v5/src/1_extract_premarket_data.py
```

### **Step 2: Build Leak-Free Dataset v5**
Merges pre-market ticks with intraday indicators and engineers 0% lookahead bias features:
```bash
python3 /home/ubuntu/shortsellmodel940v5/src/2_build_dataset_v5.py
```

### **Step 3: Walk-Forward LightGBM Training**
Trains monthly expanding walk-forward LightGBM models (2021–2026 out-of-sample) and saves `model_v5_lgb.txt`:
```bash
python3 /home/ubuntu/shortsellmodel940v5/src/3_train_model_v5.py
```

### **Step 4: Simulate Trade Performance & PnL**
Evaluates portfolio returns across Top 1, Top 2, Top 3, Top 5, and Top 10 daily trade limits:
```bash
python3 /home/ubuntu/shortsellmodel940v5/src/4_simulate_v5_pnl.py
```

---

## ⚡ Daily Production Deployment (Cron Setup)

To deploy **Model v5** as an automated daily trading system:

1. Open crontab editor:
   ```bash
   crontab -e
   ```

2. Add the following cron schedule entry to trigger the live inference runner every trading day at **09:40:05 AM**:
   ```cron
   40 9 * * 1-5 /usr/bin/python3 /home/ubuntu/shortsellmodel940v5/src/5_live_prediction_0940_v5.py >> /home/ubuntu/shortsellmodel940v5/output/daily_runner.log 2>&1
   ```

3. Configure Telegram Bot API keys (Optional):
   ```bash
   export TELEGRAM_BOT_TOKEN="your_bot_token"
   export TELEGRAM_CHAT_ID="your_chat_id"
   ```

---

## 🛡️ Leak-Free Compliance Summary
- **No Full-Day Volume:** `Volume_Change_Pct` is strictly excluded.
- **Strict 09:40 AM Feature Cutoff:** All 15 model inputs are computed using data available at or before 09:40:00 AM.
- **09:42 AM Execution:** Trade entry happens at 09:42:00 AM, leaving a 2-minute buffer between prediction and execution.
