# 09:20 Short-Sell Production Model: 50/50 Split Walk-Forward Simulation

This folder contains the verified historical walk-forward replica of the **live 09:20 Short-Sell production system**, updated with the **50/50 Split Strategy**.

---

## 🎯 Architecture & Order Fill Logic

| Step | Time | Action | Matching Logic |
| :--- | :--- | :--- | :--- |
| **1. Limit Entry** | `09:25:00` | Adaptive Sell Limit Order placed based on 09:20–09:24 movement regime | Checked minute-by-minute across candle High, Open, and Close |
| **2. Fill Window Close & Leg 1 TP Placement** | `09:27:00` | Unfilled sell orders cancelled. Filled stocks split 50/50 into Leg 1 & Leg 2. Limit Buy TP order placed for Leg 1. | Leg 1 TP Price = $\text{Sell Price} - \frac{₹2,000}{\text{Total Qty}}$. Fills if candle Low $\le$ TP Price. |
| **3. Cadence Profit Lock Window** | `09:36:00` – `09:39:59` | System evaluates net unrealized profit across remaining open quantity. | If Net Profit $\ge ₹500$, open Leg 1 TP cancelled, on-the-fly Limit Buy placed to lock profit. |
| **4. Hard Square-Off** | `09:40:00` | Any remaining position (Leg 2 or unfilled Leg 1) is squared off immediately. | Fills at 09:40:00 market price. |
| **5. Stop-Loss** | Any time | 2.0% Hard Stop-Loss | Fills at SL price if candle High $\ge \text{Sell Price} \times 1.02$. |
| **6. Institutional Friction** | Every trade | Kotak Securities MIS Cash Equity statutory charges applied per leg. | Brokerage (₹40 round trip), STT (0.025%), Txn (0.00322%), SEBI, Stamp, GST (18%). |

---

## 📊 Audited Historical Results (2020-01-01 to 2026-10-16)

| Metric | ₹5,00,000 Capital (Current Live Setup) | ₹10,00,000 Capital (Walk-Forward Standard) |
| :--- | :--- | :--- |
| **Total Filled Trades** | **5,567** | **5,567** |
| **Net Cumulative PnL** | **+₹44.27 Lakhs** | **+₹70.78 Lakhs** |
| **Win Rate** | **75.59%** | **77.85%** |
| **Profit Factor** | **2.51** | **2.40** |
| **Average Net Trade** | **₹795.1** | **₹1,271.5** |
| **Max Drawdown** | **-₹0.51 Lakhs** | **-₹0.97 Lakhs** |
| **Sharpe Ratio** | **8.44** | **7.59** |
| **Sortino Ratio** | **10.32** | **8.51** |

---

## 📅 Yearly PnL Breakdown (₹5,00,000 Live Sizing)

| Year | Trades | Net PnL (₹ Lakhs) | Win Rate (%) |
| :---: | :---: | :---: | :---: |
| **2020** | 831 | +₹6.41 L | 73.65% |
| **2021** | 814 | +₹6.98 L | 76.29% |
| **2022** | 800 | +₹6.53 L | 75.88% |
| **2023** | 813 | +₹7.00 L | 78.72% |
| **2024** | 825 | +₹8.27 L | 78.67% |
| **2025** | 847 | +₹5.57 L | 74.26% |
| **2026** | 637 | +₹3.51 L | 70.64% |
| **Total** | **5,567** | **+₹44.27 Lakhs** | **75.59%** |

---

## 📁 Key Files

- [`walkforward_0920_5050_pipeline.py`](file:///home/ubuntu/live_production0920_model/walkforward_0920_5050_pipeline.py) — Core simulation script.
- [`walkforward_0920_simulation.py`](file:///home/ubuntu/live_production0920_model/walkforward_0920_simulation.py) — Primary entry point calling the 50/50 pipeline.
- [`walkforward_0920_5050_trades_5L.csv`](file:///home/ubuntu/live_production0920_model/walkforward_0920_5050_trades_5L.csv) — Complete trade ledger with leg exit reasons for ₹5L capital.
- [`walkforward_0920_5050_trades_10L.csv`](file:///home/ubuntu/live_production0920_model/walkforward_0920_5050_trades_10L.csv) — Complete trade ledger for ₹10L capital.
- [`walkforward_0920_5050_yearly_summary.csv`](file:///home/ubuntu/live_production0920_model/walkforward_0920_5050_yearly_summary.csv) — Year-by-year performance metrics.
- [`equity_curves_5050_comparison.png`](file:///home/ubuntu/live_production0920_model/equity_curves_5050_comparison.png) — High-resolution comparison plot of cumulative equity curves.
- [`walkforward_0920_simulation.py.bak_pre_5050`](file:///home/ubuntu/live_production0920_model/walkforward_0920_simulation.py.bak_pre_5050) — Preserved pre-50/50 simulation script.
