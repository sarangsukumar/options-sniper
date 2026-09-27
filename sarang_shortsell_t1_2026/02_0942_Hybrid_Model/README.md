# 09:42 Hybrid Model (T1 Audit)

This directory contains the mathematically strict, tick-by-tick verified audit of the **09:42 Hybrid Short-Sell Model**. 

Unlike the live production simulation which aggressively compounds lot sizes, this specific repository enforces a strict, flat **₹10 Lakhs Capital** limit per trade to provide a realistic, unexaggerated historical performance baseline.

## 🛠️ The 5 Defensive Filters
To protect against market crashes, short-squeezes, and Monday whipsaws, the raw predictions are passed through 5 strict production filters:
1. **Gap Down Protector:** Always skip if Stock gapped down > 1.0%
2. **Crash Day Protector:** If Nifty is down > 0.5%, skip if Stock is down > 0.5%
3. **Monday Danger Rule:** If it's Monday, skip if Stock is down > 0.5%
4. **Market Breadth:** Skip if overall market breadth win rate is < 10%
5. **VWAP Exhaustion:** Skip if previous day's close was > 0.52% below its intraday VWAP.

## 🏆 Final Audited Results (2020 - 2026)
*Configuration: Fixed ₹10 Lakhs Capital | Realistic Brokerage & STT Deducted | 3% Hard Stop-Loss*

| Year  | Baseline (Raw) | After 5 Filters applied |
|-------|----------------|-------------------------|
| 2020  | ₹ 21.40 Lakhs  | ₹ 20.23 Lakhs           |
| 2021  | ₹ 17.99 Lakhs  | ₹ 16.27 Lakhs           |
| 2022  | ₹ 10.55 Lakhs  | ₹  9.93 Lakhs           |
| 2023  | ₹ 10.73 Lakhs  | ₹ 10.56 Lakhs           |
| 2024  | ₹  7.16 Lakhs  | ₹  9.50 Lakhs           |
| 2025  | ₹  7.01 Lakhs  | ₹ 10.47 Lakhs           |
| 2026  | ₹  2.62 Lakhs  | ₹  5.56 Lakhs           |
| **TOTAL** | **₹ 77.50 Lakhs** | **₹ 82.54 Lakhs** |

*Note: The VWAP Exhaustion filter (Rule 5) alone saved massive drawdowns in 2025 and 2026, boosting 2026 Out-Of-Sample performance to over ₹5.5 Lakhs.*

## 📂 Directory Structure
- `1_build_features_and_train.py`: Trains the LightGBM models walk-forward and generates `0942_predictions.csv`.
- `2_db_tick_verification.py`: Queries the local MySQL `scrapdata` database to verify exact entry/exit ticks and strict 10L PnL.
- `filter_research/`: Subdirectory containing chronological Python scripts analyzing the impact of individual filters on the historical baseline.

