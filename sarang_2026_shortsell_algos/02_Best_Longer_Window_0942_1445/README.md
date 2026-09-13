# 👑 Best Longer Window Model: V6/V7 Hybrid Dual-Engine (09:42 $\rightarrow$ 14:45 PM IST, 3% SL)

## 📌 Model Overview
- **Trading Window:** 09:42:00 AM IST $\rightarrow$ 14:45:00 PM IST (Full day reversion & momentum capture).
- **Latency Buffer:** Exactly **2 Minutes** (09:40:00 to 09:42:00 AM IST) for live data processing and order dispatch.
- **Capital Turnover:** Enters at 09:42:00 AM IST—exactly 2 minutes AFTER the 09:20 $\rightarrow$ 09:40 AM Shorter Window model completely squares off. **Zero margin overlap** allowing 100% capital reuse.
- **Universe:** All NSE F&O Stocks.
- **Dual Alpha Engines:**
  1. **Model V6 (Mean Reversion Engine):** Identifies overextended gap-ups reverting to intraday VWAP.
  2. **Model V7 (Momentum Sniper Engine):** Targets pre-market gap faders (`gap_fade_0907_to_940_pct < 0`) breaking morning support.
- **Active Risk Engine:** Strict tick-by-tick **3.0% Stop Loss** to eliminate runaway short squeeze tail risk.
- **Optimal Rules:** Exclude Mondays (filters Monday opening mean-reversion chop).
- **Friction:** Flat ₹300.00 commission deducted per trade.

---

## 📊 Dual Table Simulation Results (2020 – 2026 Walk-Forward OOS)

| Metric | Near-Month Futures Table (`scrapdata_F1`) | Cash Equity Table (`scrapdata`) |
| :--- | :---: | :---: |
| **Total Net PnL** | 🏆 **+₹214.43 Lakhs (+₹2.14 CRORE)** | **+₹84.76 Lakhs (+₹0.85 CRORE)** |
| **Win Rate** | **62.37%** | **54.37%** |
| **Profit Factor** | **2.34** | **1.71** |
| **Total Trades** | 4,994 | 4,994 |
| **All Years Positive?** | **YES (100% Green)** | **YES (100% Green)** |

### 📅 Year-by-Year Net PnL Breakdown (₹ Lakhs)
| Year | Futures Net PnL (`scrapdata_F1`) | Equity Net PnL (`scrapdata`) |
| :---: | :---: | :---: |
| **2020** | **+₹21.86 L** | **+₹13.60 L** |
| **2021** | **+₹37.11 L** | **+₹25.03 L** |
| **2022** | **+₹30.21 L** | **+₹16.08 L** |
| **2023** | **+₹37.08 L** | **+₹8.80 L** |
| **2024** | **+₹49.71 L** | **+₹10.79 L** |
| **2025** | **+₹29.07 L** | **+₹9.22 L** |
| **2026** | **+₹9.38 L** | **+₹1.24 L** |
| **TOTAL** | 👑 **+₹214.43 Lakhs (+₹2.14 Cr)** | **+₹84.76 Lakhs (+₹0.85 Cr)** |

> [!NOTE]
> **Key Institutional Insight:** In longer holding windows (09:42 to 14:45), **Near-Month Futures (`scrapdata_F1`) delivers 2.5x higher returns (+₹2.14 Cr vs +₹0.85 Cr)** due to futures contract leverage, intraday discount widening, and enhanced liquidity during afternoon sell-offs.
