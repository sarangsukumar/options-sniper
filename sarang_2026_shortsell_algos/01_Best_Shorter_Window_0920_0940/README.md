# ⚡ Best Shorter Window Model: Morning Momentum Breakdown (09:20 $\rightarrow$ 09:40 AM IST)

## 📌 Model Overview
- **Trading Window:** 09:20:00 AM IST $\rightarrow$ 09:40:00 AM IST (Exact 20-minute holding duration).
- **Latency Buffer:** Exactly **2 Minutes** (09:18:00 to 09:20:00 AM IST) for live data processing and order dispatch.
- **Capital Turnover:** 100% margin freed at 09:40:00 AM for seamless deployment into the 09:42 AM Longer Window model.
- **Universe:** All NSE F&O Stocks.
- **Combined Alpha Features:**
  1. `09:18` Morning Candlestick Dynamics (`rejection_wick_918`, `lower_wick_918`, `body_ratio_918`, `is_bearish_918`, `morn_vwap_gap_918`, `vol_accel_918`, `momentum_918`).
  2. Prior-Day Indicators (`prev_intraday_vwap_gap`, `prev_intraday_roc_last_hour`, `prev_intraday_return`, `positive_arc_ratio`, `rejection_wick`).
  3. Pre-Market Opening Gap (`gap_0907_pct`).
  4. Days to Expiry (`dte`).
- **Optimal Rules:** Exclude Mondays (filters Monday opening noise) + Select Top 3 Ranks daily.
- **Friction:** Flat ₹300.00 commission deducted per trade.

---

## 📊 Dual Table Simulation Results (2021 – 2026 Walk-Forward OOS)

| Metric | Cash Equity Table (`scrapdata`) | Near-Month Futures Table (`scrapdata_F1`) |
| :--- | :---: | :---: |
| **Total Net PnL** | **+₹33.13 Lakhs** | **+₹16.88 Lakhs** |
| **Win Rate** | **58.62%** | **54.65%** |
| **Total Trades** | 3,023 | 3,023 |
| **All Years Positive?** | **YES (100% Green)** | 5 of 6 Years Green |

### 📅 Year-by-Year Net PnL Breakdown (₹ Lakhs)
| Year | Equity Net PnL (`scrapdata`) | Futures Net PnL (`scrapdata_F1`) |
| :---: | :---: | :---: |
| **2021** | **+₹7.54 L** | -₹1.56 L |
| **2022** | **+₹6.11 L** | +₹0.57 L |
| **2023** | **+₹4.45 L** | +₹4.16 L |
| **2024** | **+₹9.75 L** | +₹8.97 L |
| **2025** | **+₹1.62 L** | +₹1.50 L |
| **2026** | **+₹3.67 L** | +₹3.25 L |
| **TOTAL** | 🏆 **+₹33.13 Lakhs** | **+₹16.88 Lakhs** |

> [!NOTE]
> **Key Institutional Insight:** Equity cash reacts faster and cleaner to opening order flow with zero contract basis roll drag, making **Equity cash the optimal execution venue for the 20-minute morning scalp**.
