# 🎯 Model V6: Flagship Intraday Mean Reversion (09:42 $\rightarrow$ 14:45 PM IST)

## Strategy Summary
- **Execution Window:** Entry at 09:42:00 AM IST $\rightarrow$ Exit at 14:45:00 PM IST (or 3.0% Stop Loss).
- **Universe:** All NSE F&O Near-Month Futures (`markets.scrapdata_F1`).
- **Feature Window:** 09:15:00 to 09:40:00 AM IST + MySQL Premarket (09:07 AM).
- **Latency Buffer:** Exactly **2 Minutes** (09:40 to 09:42) for live data processing and order dispatch.
- **Selection Rule:** Top 4 overbought mean-reversion candidates per day (excludes Mondays).
- **Risk Management:** Hard **3.0% Stop Loss** tracked tick-by-tick in `scrapdata_F1`.
- **Friction:** Flat ₹300.00 brokerage per trade.
- **Contract Lot Sizes:** Dynamically matched from `historical_lotsize_new.csv`.

## Verified Out-of-Sample Performance (2021 – 2026)
- **Total Net PnL:** **+₹91.32 Lakhs**
- **Win Rate:** **58.17%** across 4,035 trades.
- **Daily Sharpe Ratio:** **3.43**
- **Max Drawdown:** **-₹3.62 Lakhs**
- **Average Net / Trade:** **₹2,263.27**
