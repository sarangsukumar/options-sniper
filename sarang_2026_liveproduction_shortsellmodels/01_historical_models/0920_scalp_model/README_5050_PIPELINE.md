# 09:20 Short-Sell Production Model: 100% Single-Leg 3-Stage Profit Trailing Walk-Forward Simulation

This folder contains the verified historical walk-forward replica of the **live 09:20 Short-Sell production system (`0920_SCALP`)**, updated with the **100% Single-Leg 3-Stage Profit Trailing & Stop-Loss Strategy** and **5-Second Kotak Quotes Live Execution Engine (`Option B`)**.

---

## 🎯 Architecture & 3-Stage Trailing Execution Logic (`₹5,00,000` / Stock)

| Step | Time (IST) | Action | Matching / Live Execution Logic |
| :--- | :--- | :--- | :--- |
| **1. Limit Entry** | `09:25:00` | Adaptive Sell Limit Order placed (`100%` quantity, `₹5,00,000` per stock) | Checked minute-by-minute across candle High, Open, and Close. |
| **2. Fill Confirmation & 5s Monitor Arm** | `09:27:00` | Unfilled sell orders cancelled. Confirmed fills enter `5-Second` Kotak `client.quotes()` live trailing loop (`sl_near_alert_monitor.py`). | `sl_near_alert_monitor.py` runs 3 passes (`0s, 5s, 10s`) per 20s scheduler cycle inside a single authenticated Kotak session. |
| **3. Stage 1 — Initial Stop-Loss** | `09:27:00` – `09:40:00` | Active while `Peak PnL < +₹2,000` | Initial SL at **`-₹5,000` (`1.00%`)** (`Sell Price + ₹5,000 / Qty`). Fires `100%` Limit Buy cover (`LTP + ₹0.10`) on breach. |
| **4. Stage 2 — Minimum Profit Floor** | `09:27:00` – `09:40:00` | Armed as soon as `Peak PnL` reaches **`+₹2,000`** (`+0.40%`) | Locks a guaranteed minimum profit floor at **`+₹1,000`** (`+0.20%`, `Sell Price - ₹1,000 / Qty`). |
| **5. Stage 3 — Dynamic Profit Trailing** | `09:27:00` – `09:40:00` | Armed as soon as `Peak PnL` reaches **`+₹4,000`** (`+0.80%`) | Dynamically trails **`₹750` behind Peak Profit** (`Peak PnL - ₹750`: `+₹4,000 ➔ +₹3,250`, `+₹5,000 ➔ +₹4,250`, etc.). |
| **6. Cadence Profit Lock Window** | `09:36:00` – `09:39:30` | Evaluates net unrealized profit every 30 seconds across open positions. | If Unrealized Profit $\ge ₹500$, places immediate Limit Buy cover to lock profit (`CADENCE_500`). |
| **7. Hard Square-Off** | `09:40:00` | Any remaining open short position is squared off unconditionally via Limit Chaser. | Fills at `09:40:00` market price (`HARD_EXIT_0940`). |
| **8. Institutional Friction** | Every trade | Kotak Securities MIS Cash Equity statutory charges applied per trade (`1x` Single-Leg round trip). | Brokerage (`₹40` round trip), STT (`0.025%`), Txn (`0.00322%`), SEBI, Stamp (`0.003%`), GST (`18%`). |

---

## 📊 Audited Historical Results (`2020-01-01` to `2026-10-16`)

| Metric | ₹5,00,000 Capital (Current Live Setup) | ₹10,00,000 Capital (2x Scaled Setup) |
| :--- | :--- | :--- |
| **Total Filled Trades** | **5,567** | **5,567** |
| **Net Cumulative PnL** | **+₹49.27 Lakhs** | **+₹101.38 Lakhs** |
| **Win Rate** | **77.82%** | **77.96%** |
| **Profit Factor** | **2.91** | **2.99** |
| **Average Net Trade** | **₹885.0** | **₹1,821.1** |
| **Max Drawdown** | **-₹0.51 Lakhs** | **-₹0.98 Lakhs** |
| **Sharpe Ratio** | **10.06** | **10.34** |
| **Sortino Ratio** | **16.88** | **17.40** |

---

## 📅 Yearly PnL Breakdown (`₹5,00,000` Live Sizing vs. `₹10,00,000` Scaled)

| Year | Trades | ₹5L Net PnL (₹ Lakhs) | ₹5L Win Rate (%) | ₹10L Net PnL (₹ Lakhs) | ₹10L Win Rate (%) |
| :---: | :---: | :---: | :---: | :---: | :---: |
| **2020** | 831 | +₹7.43 L | 78.82% | +₹15.29 L | 78.82% |
| **2021** | 814 | +₹7.99 L | 78.87% | +₹16.39 L | 79.24% |
| **2022** | 800 | +₹7.35 L | 78.75% | +₹15.11 L | 78.75% |
| **2023** | 813 | +₹7.79 L | 79.21% | +₹16.03 L | 79.46% |
| **2024** | 825 | +₹9.23 L | 80.61% | +₹18.89 L | 80.73% |
| **2025** | 847 | +₹5.93 L | 75.32% | +₹12.28 L | 75.32% |
| **2026** | 637 | +₹3.54 L | 71.90% | +₹7.39 L | 72.21% |
| **Total** | **5,567** | **+₹49.27 Lakhs** | **77.82%** | **+₹101.38 Lakhs** | **77.96%** |

---

## 📁 Key Files

- [`walkforward_0920_5050_pipeline.py`](walkforward_0920_5050_pipeline.py) — Core 3-Stage Single-Leg Profit Trailing walk-forward simulation script.
- [`walkforward_0920_simulation.py`](walkforward_0920_simulation.py) — Primary entry point calling the walk-forward pipeline.
- [`walkforward_0920_5050_trades_5L.csv`](walkforward_0920_5050_trades_5L.csv) — Complete trade ledger (`5,567` trades) for `₹5L` capital (`+₹49.27L` Net PnL).
- [`walkforward_0920_5050_trades_10L.csv`](walkforward_0920_5050_trades_10L.csv) — Complete trade ledger (`5,567` trades) for `₹10L` capital (`+₹101.38L` Net PnL).
- [`walkforward_0920_5050_yearly_summary.csv`](walkforward_0920_5050_yearly_summary.csv) — Year-by-year performance metrics (`2020–2026`).
- [`equity_curves_5050_comparison.png`](equity_curves_5050_comparison.png) — High-resolution comparison plot of cumulative equity curves.
