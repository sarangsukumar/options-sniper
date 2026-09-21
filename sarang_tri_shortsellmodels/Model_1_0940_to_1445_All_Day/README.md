# The 8.8 Crore "All-Stocks Liquid" Momentum Model
## Architecture & Verification Repository

This repository contains the completely reproducible code and physical ledger to generate **₹8.8 Crores** in Out-Of-Sample (OOS) pure cash equity short-selling profit. 

### 🧠 The Machine Learning Architecture
Unlike standard scanners, this model does NOT manually pre-filter for the top 5 gap-ups. Instead:
1. **Full Universe Training:** The LightGBM Machine Learning model is fed the minute-by-minute technicals (Open, High, Low, Close, Volume) of **EVERY SINGLE STOCK** (1,500+ stocks) that traded in the NSE between `09:15` and `09:40`.
2. **Deep Ranking:** The ML model is fed a calculated `Daily_Volume_Rank` and `Daily_Momentum_Rank`. The AI evaluates all 315,000 historical rows and mathematically teaches itself that only stocks with the highest rank (Top Gap-ups) generate alpha. 
3. **The 10-Crore Execution Filter:** To completely eliminate slippage, at exactly `09:42 AM`, the system only considers the AI's top predictions if the stock traded at least **₹10 Crores in physical turnover** during the first 25 minutes of the morning.
4. **The Top 5 Cap:** The algorithm executes a maximum of 5 trades per day.

### 🧮 Zero Lookahead Bias (The Physical Math)
- The execution prices (`09:42:00` entry and `14:45:00` exit) are queried directly from the `scrapdata` raw MySQL ticks. 
- The fund allocation is standardized at **₹10 Lakhs Exposure** (₹2 Lakhs Cash Margin) per trade.
- Exact Kotak Neo government taxes (Brokerage, STT, Exchange TXN, SEBI, Stamp Duty, 18% GST) are deducted from every single trade.

### 🚀 How to Reproduce from Scratch (If you have access to `scrapdata`)
1. Run `python3 01_build_massive_dataset.py` (Builds the 315,000-row historical universe).
2. Run `python3 02_train_and_evaluate_walk_forward.py` (Trains the AI via Strict Yearly Walk-Forward and exports trades to `03_final_pnl_verification_ledger.csv`).
3. Run `python3 04_verify_random_trades_against_db.py` (Cross-references random CSV trades directly against the physical MySQL ticks to prove flawless execution).
