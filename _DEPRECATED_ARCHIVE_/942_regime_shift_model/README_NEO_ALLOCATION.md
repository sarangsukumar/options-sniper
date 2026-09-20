# 👑 9:42 Regime Shift Strategy - Kotak Neo Allocation

This folder contains the complete, self-contained implementation of the **9:42 AM Expanding Window LightGBM Strategy**, specifically updated to utilize a **Fixed Capital Allocation Model** with **Kotak Neo** broker logic.

## 📊 Strategy & Capital Logic

Instead of relying on arbitrary historical F&O lot sizes (which were often too small and restricted the model's true statistical edge), this version dynamically standardizes capital utilization per trade.

### Capital Rules:
- **Maximum Daily Physical Capital:** Rs 8,00,000 (8 Lakhs)
- **Maximum Stocks Traded per Day:** 4 Stocks
- **Physical Capital Allocated per Trade:** Rs 2,00,000 (2 Lakhs)
- **MIS Margin (Leverage) Applied:** 5x
- **Max Exposure per Trade:** Rs 10,00,000 (10 Lakhs)
- **Quantity Calculation:** `Qty = Floor(10,00,000 / Entry_Price)`

### Brokerage & Tax Formula (Kotak Neo):
The auditor precisely accounts for tick-by-tick taxes based on the 10 Lakh turnover:
1. **Flat Brokerage:** Rs 40.00 (Rs 20 Buy + Rs 20 Sell)
2. **STT:** 0.025% on Sell Turnover
3. **Exchange Txn Fees:** 0.00322% on Total Turnover
4. **SEBI Charges:** 0.0001% on Total Turnover
5. **Stamp Duty:** 0.003% on Buy Turnover
6. **GST:** 18% applied to (Brokerage + Txn + SEBI)

*(Average total charge per trade evaluates to exactly **Rs 405.10** under this model).*

---

## 📈 Verified Performance Summary (2020 - 2026)

By utilizing the full 8L capital limit natively, the strategy extracts significantly more pure alpha than the legacy lot-size model.

- **Total Trades:** 4,451
- **Overall Win Rate:** 59.1%
- **Net PnL (After all charges):** + Rs 96.75 Lakhs
- **Average Monthly Return:** + Rs 1.22 Lakhs (~15% ROI on 8L capital base)

### Timeframe Consistency:
- **Daily Win Rate:** 61.6%
- **Weekly Win Rate:** 69.5%
- **Monthly Win Rate:** 84.8%
- **Quarterly Win Rate:** 92.6%

---

## 🏗️ How to Rebuild from Scratch

Everything required to reproduce this exact 96.75 Lakhs outcome is contained in this folder. No external scripts are needed.

1. **Navigate to the strategy folder:**
   ```bash
   cd /home/ubuntu/942_regime_shift_model
   ```

2. **Execute the Master Run Script:**
   ```bash
   ./run_all.sh
   ```

### What `run_all.sh` does under the hood:
1. **`0_generate_global_features.py`**: Connects to `yfinance` to download historical S&P 500 (`^GSPC`) and Nikkei (`^N225`) closing prices to derive the overnight gap advantage edge, exporting to `global_macro_features.csv`.
2. **`1_run_ml_simulation.py`**: Executes the walk-forward expanding window simulation (2020-2026) using LightGBM. It extracts exactly 4 trades per day (combining Dual-Confirmed setups with Top-Ranked Single-Confirmed remainders) and saves the raw signals to `longer_window_trades_futures_and_eq.csv`.
3. **`2_bulletproof_db_audit.py`**: The ultimate physical audit. It verifies the signals against the tick-by-tick Equity database (`scrapdata`), applies the 10L Kotak Neo Margin constraints, tracks exact 3% Stop Loss wick hits, and calculates final MIS charges.

### Output
The pipeline will generate **`final_verified_ledger_2L_Neo.csv`**, which acts as your complete, trade-by-trade receipt for the entire backtest, ready for manual verification.
