# 09:20 Scalp Model

This folder contains the complete, isolated rebuild logic and database tick verification for the 09:20 Morning Scalp Model.

## Steps to Reproduce
1. Run `python3 1_build_features_and_train.py`
   - This script pulls fresh S&P 500, Nikkei, and Nifty index data using `yfinance`.
   - It builds the historical gap features and runs the Walk-Forward Expanding Window LightGBM model.
   - It outputs the top 4 ranked predictions for every single day to `0920_predictions.csv`.

2. Run `python3 2_db_tick_verification.py`
   - This script takes the predictions and physically queries the local MySQL `scrapdata` table tick-by-tick.
   - **Liquidity Filters:** It enforces a strict maximum 3-minute liquidity gap for entry (entry at 09:22:00, skips if no tick before 09:25:59) and a 3-minute gap for the time exit (at 09:40:00).
   - It calculates Kotak taxes and strict 3% Stop-Loss hits.
   - It outputs the final tick-level verified ledger to `0920_verified_pnl_sheet.csv`.

## Results
* **Total Audited Profit:** ~Rs 9.00 Crores
* **Win Rate:** ~66%
