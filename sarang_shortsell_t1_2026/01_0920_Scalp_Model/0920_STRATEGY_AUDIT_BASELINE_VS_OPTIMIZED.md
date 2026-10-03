# 09:20 Scalp Model: Baseline vs. Optimized Exit Strategy Audit

This document certifies and records the comprehensive historical audit (2020–2026) of the **09:20 Scalp Short-Sell Model** comparing the original **Baseline 09:40 Hard Square-Off** against the newly discovered **Hybrid Trailing Exit Strategy**.

All simulations were executed against real tick-by-tick records from the `scrapdata` MySQL database across all **6,239 historical trades**, with standard ₹10 Lakhs margin per stock, real statutory transaction taxes, exchange turnover fees, SEBI charges, stamp duty, and GST.

---

## 1. Executive Summary: Core Results Comparison

| Metric | Baseline Strategy (09:40 Cut) | Optimized Hybrid Strategy | Net Improvement |
| :--- | :---: | :---: | :---: |
| **Strategy Logic** | Entry 09:25, 3% SL, Trail >0.05% (09:36–09:39), **Hard Exit at 09:40:00** | Entry 09:25, **2% SL**, Trail >0.05% (09:36–09:40), **Trail >0.30% (09:40–14:45)**, Hard Exit at 14:45 | Capped downside risk, allows runners to drop |
| **Total Trades** | 6,239 | 6,239 | — |
| **Total Wins** | 4,818 | **5,592** | **+774 Winning Trades** |
| **Win Rate %** | **77.22%** | **🏆 89.63% (~90%)** | **+12.41% Boost** |
| **Net Realized PnL** | **+₹123.64 Lakhs (~₹1.24 Cr)** | **💰 +₹135.29 Lakhs (~₹1.35 Cr)** | **+₹11.65 Lakhs Higher Profit** |
| **Average Trade** | ₹1,981.73 | **₹2,168.39** | +₹186.66 / trade |
| **2026 YTD PnL** | +₹8.02 Lakhs | **+₹9.00 Lakhs** | +₹0.98 Lakhs |
| **Monthly Win Consistency** | 76 / 81 months green (93.8%) | **75 / 81 months green (92.6%)** | Highly consistent |

---

## 2. Execution Flow & Exit Mechanics

Under the **Optimized Hybrid Strategy**, positions exit across four distinct stages:

```
[09:25:00] Short Sell Entry (Top 4 ranked stocks, ₹10L allocation each)
    │
    ├── [09:25 - 14:45] Continuous 2.0% Stop Loss Monitor
    │                   (Triggered on 369 trades = 5.91%, max loss ₹20k)
    │
    ├── [09:36 - 09:40] Morning Fast Scalp Window: Trail > 0.05%
    │                   (Triggered on 4,725 trades = 75.73% of all trades)
    │
    ├── [09:40 - 14:45] Mid-Day Runner Window: Trail > 0.30%
    │                   (Triggered on 857 trades = 13.74% of all trades)
    │
    └── [14:45:00]      Final Hard Square-Off
                        (Triggered on 288 trades = 4.62% of all trades)
```

- **75.7% of trades exit within the first 15 minutes** (09:36 to 09:40) at >0.05% profit, locking in quick morning scalp gains and avoiding slippage.
- **13.7% of trades** that were not in profit by 09:40 are given room across the trading day, capturing a **+0.30%** downward move as afternoon momentum builds.
- Downside risk is strictly limited by the **2.0% all-time Stop Loss** (₹20,000 maximum loss per position vs. ₹30,000 previously).

---

## 3. Year-by-Year Performance Audit

| Year | Trades | Baseline (09:40) Win Rate | **Optimized Win Rate** | Baseline Net PnL | **Optimized Net PnL** |
| :---: | :---: | :---: | :---: | :---: | :---: |
| **2020** | 935 | 74.97% (701 wins) | **88.88%** (831 wins) | +₹19.16 L | **+₹30.96 Lakhs** |
| **2021** | 922 | 79.18% (730 wins) | **90.78%** (837 wins) | +₹24.93 L | **+₹25.51 Lakhs** |
| **2022** | 917 | 77.54% (711 wins) | **90.08%** (826 wins) | +₹20.77 L | **+₹20.98 Lakhs** |
| **2023** | 928 | 80.17% (744 wins) | **90.52%** (840 wins) | +₹18.70 L | +₹18.27 Lakhs |
| **2024** | 930 | 80.97% (753 wins) | **90.97%** (846 wins) | +₹20.79 L | +₹19.48 Lakhs |
| **2025** | 934 | 74.09% (692 wins) | **88.01%** (822 wins) | +₹11.27 L | +₹11.10 Lakhs |
| **2026 (YTD)** | 673 | 72.36% (487 wins) | **87.67%** (590 wins) | +₹8.02 L | **+₹9.00 Lakhs** |
| **TOTAL** | **6,239** | **77.22% (4,818 wins)** | **🏆 89.63% (5,592 wins)** | **+₹123.64 L** | **💰 +₹135.29 Lakhs** |

---

## 4. 2026 Month-by-Month Verified Ledger (Optimized Strategy)

| Month | Trades | Wins | Win Rate % | Realized Net PnL (₹ Lakhs) |
| :---: | :---: | :---: | :---: | :---: |
| **2026-01** | 76 | 64 | 84.21% | **+₹1.09 L** |
| **2026-02** | 76 | 69 | 90.79% | **+₹1.47 L** |
| **2026-03** | 76 | 66 | 86.84% | **+₹0.40 L** |
| **2026-04** | 72 | 65 | 90.28% | **+₹1.25 L** |
| **2026-05** | 72 | 66 | 91.67% | **+₹1.77 L** |
| **2026-06** | 84 | 78 | 92.86% | **+₹2.19 L** |
| **2026-07** | 75 | 70 | 93.33% | **+₹1.24 L** |
| **2026-08** | 58 | 45 | 77.59% | –₹0.17 L |
| **2026-09** | 84 | 67 | 79.76% | –₹0.25 L |
| **2026 Total** | **673** | **590** | **87.67%** | **+₹9.00 Lakhs** |

---

## 5. Artifacts and Trade Data Files

Both strategies have their complete trade-by-trade ledger preserved:

1. **Baseline Strategy Ledger**:
   `sarang_shortsell_t1_2026/01_0920_Scalp_Model/0920_verified_pnl_sheet_monthly.csv`
   *(6,239 trades with 09:40 forced cut, 77.22% Win Rate, +₹123.64 Lakhs)*

2. **Optimized Hybrid Strategy Ledger**:
   `sarang_shortsell_t1_2026/01_0920_Scalp_Model/0920_verified_pnl_sheet_optimized.csv`
   *(6,239 trades with Morning 0.05% + Day 0.30% + SL 2%, 89.63% Win Rate, +₹135.29 Lakhs)*
