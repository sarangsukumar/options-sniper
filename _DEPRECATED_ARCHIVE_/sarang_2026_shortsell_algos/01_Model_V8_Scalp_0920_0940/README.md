# ⚡ Model V8: Morning Momentum Scalp (09:20 $\rightarrow$ 09:40 AM IST)

## Strategy Summary
- **Execution Window:** Entry at 09:20:00 AM IST $\rightarrow$ Exit at 09:40:00 AM IST (20-minute holding period).
- **Universe:** All NSE F&O Stocks (Equity `markets.scrapdata`).
- **Feature Window:** 09:15:00 to 09:18:00 AM IST.
- **Latency Buffer:** Exactly **2 Minutes** (09:18 to 09:20) for live data processing and order dispatch.
- **Selection Rule:** Top 4 highest probability short-sell candidates per day.
- **Friction:** Flat ₹300.00 brokerage per trade.
- **Contract Lot Sizes:** Dynamically matched from `historical_lotsize_new.csv`.

## Verified Out-of-Sample Performance (2021 – 2026)
- **Total Net PnL:** **+₹27.09 Lakhs** *(or +₹31.77 L with confidence filter `prob >= 0.59`)*
- **Win Rate:** **54.55%** across 5,087 trades.
- **Daily Sharpe Ratio:** **1.98**
- **Max Drawdown:** **-₹3.31 Lakhs**
- **Capital Free-Up:** Frees up 100% margin at 09:40:00 AM for immediate re-use by the 09:42:00 AM models.
