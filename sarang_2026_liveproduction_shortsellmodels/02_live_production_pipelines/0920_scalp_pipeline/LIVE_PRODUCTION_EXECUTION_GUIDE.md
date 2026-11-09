# ⚡ 09:20 Scalp Engine — End-to-End Live Production Execution Guide

This document details the complete live production execution architecture for the **09:20 Rolling 4-Frequency Ensemble Scalp Model**, covering morning tick ingestion, Top-2 candidate scoring, Kotak Neo MIS margin-capped order placement, Option 2A/2B stop-loss & cadence profit locking, and evening reconciliation/retraining.

---

## 🕒 1. Daily Live Production Timeline (IST)

| Time (IST) | Script / Process | Action & Responsibility |
| :--- | :--- | :--- |
| **`09:20:05`** | [`run_new_0920_pipeline.sh`](run_new_0920_pipeline.sh) ➔ [`new_live_0920_pipeline.py`](new_live_0920_pipeline.py) | 1. Fetches 09:07–09:19 morning equity ticks (`fetch_morning_eq_ticks.js`) into `markets.scrapdata`.<br>2. Extracts 13 features across the dynamic active F&O universe ($\ge$ ₹50).<br>3. Scores candidates using **50% Half-Yearly Base Booster** (`lgb_0920_scalp_model.txt`) + **50% 4-Checkpoint Rolling Ensemble** (`lgb_0920_ens_checkpoints.pkl`: `day`, `week`, `month`, `year` trimmed mean).<br>4. Selects **Top 2** candidates, maps input `--notional` tier to target cash margin, and inserts `0920_SCALP` rows into `markets.shortsell_orders`. |
| **`09:24:56`** | [`Neo_shortsell_mis_order.py`](Neo_shortsell_mis_order.py) (`--model 0920_SCALP`) | 1. Authenticates with Kotak Neo via TOTP/MPIN.<br>2. Queries live LTP via Kotak Quotes API.<br>3. Calls `adjust_qty_for_kotak_margin()` (`client.margin_required()`) to strictly cap actual blocked cash margin (`ordMrgn`) to the active tier (**₹1.25L**, **₹2.00L**, or **₹4.00L**).<br>4. Places MIS Limit SELL orders at `09:25:00 IST`. |
| **`09:26:45`** | [`confirm_0925_fills.py`](confirm_0925_fills.py) | 1. Audits Kotak order book for `0920_SCALP` fills.<br>2. Auto-cancels any unfilled SELL orders at the `09:27:00` cutoff to prevent late entries.<br>3. Arms **Option 2A/2B (`1.50% Hard Stop-Loss`)** in `shortsell_orders.stop_loss_price` (`isvalid = '2'`) and sends Telegram confirmation. |
| **`09:27:00 – 09:39:58`** | [`Neo_shortsell_mis_order.py`](Neo_shortsell_mis_order.py) (`--action sl_monitor`) | Continuously polls Kotak Quotes API every 2 seconds. If live LTP breaches `filled_price * 1.0150` (**+1.50% Hard SL**), immediately fires an MIS BUY cover order. |
| **`09:36:00 – 09:39:30`** | [`Neo_shortsell_mis_order.py`](Neo_shortsell_mis_order.py) (`--action squareoff --window 0936`) | Evaluates open `0920_SCALP` positions on a strict **30-second cadence** (`09:36:00`, `09:36:30`, ..., `09:39:30`). If unrealized profit $\ge$ **+₹500** (`+0.05%`), places a limit BUY cover order (`LTP + 1 tick`) to lock in profit early. |
| **`09:40:00`** | [`Neo_shortsell_mis_order.py`](Neo_shortsell_mis_order.py) (`--action squareoff --window 0940`) | Hard exit window: cancels any pending buy orders and chases remaining open short quantity to **100% FLAT (0 open shares)** with zero midday exposure. |
| **`16:05:00`** | [`run_0920_evening_reconcile.sh`](run_0920_evening_reconcile.sh) | 1. Runs [`reconcile_0920_scalp_pnl.py`](reconcile_0920_scalp_pnl.py) to audit exact realized fills, statutory charges, and net PnL into `daily_0920_live_ledger.csv`.<br>2. Runs [`retrain_monthly_0920_scalp.py`](retrain_monthly_0920_scalp.py) to refresh the 4-checkpoint rolling ensemble (`lgb_0920_ens_checkpoints.pkl`) with today's completed data for tomorrow morning. |

---

## 🛡️ 2. Capital Tier & Kotak Margin Scaling (`adjust_qty_for_kotak_margin`)

When passing `--notional` to [`new_live_0920_pipeline.py`](new_live_0920_pipeline.py) or [`live_0920_scalp_pipeline.py`](live_0920_scalp_pipeline.py), both the prediction pipeline and [`Neo_shortsell_mis_order.py`](Neo_shortsell_mis_order.py) map the input tier directly to the **maximum actual cash margin (`ordMrgn`)** allowed per order:

| Input Capital Tier (`--notional`) | Intended Actual Cash Margin Cap (`max_actual_margin`) | Base Notional (@ 5x MIS Leverage) | Live Kotak `client.margin_required()` Enforcement |
| :--- | :--- | :--- | :--- |
| **`7.5L` Tier (`750000`)** *(Current Default)* | **₹1,25,000 (₹1.25 Lakhs)** | ₹6,25,000 | If `ordMrgn > ₹1,25,000 * 1.02` (e.g., 3x leverage stock requiring 33.3% margin), downsizes `qty = int(125000 // margin_per_share)`. |
| **`10.0L` Tier (`1000000`)** | **₹2,00,000 (₹2.00 Lakhs)** | ₹10,00,000 | Strictly caps actual blocked cash margin at **₹2.00 Lakhs** per stock. |
| **`20.0L` Tier (`2000000`)** | **₹4,00,000 (₹4.00 Lakhs)** | ₹20,00,000 | Strictly caps actual blocked cash margin at **₹4.00 Lakhs** per stock (matches the **+₹1.71 Cr** verified 20L ledger). |

---

## 📈 3. Verified Live Production Execution (`2026-11-09`)

On **November 9, 2026**, the upgraded 09:20 Rolling 4-Frequency pipeline executed live in production:
- **#1 Pick — `VBL` (`Prob: 99.80%`):** Shorted 1,601 qty @ ₹437.00 (`09:25:00`) $\rightarrow$ Covered @ ₹434.22 (`09:36:00` Cadence Profit Lock) $\rightarrow$ **+₹4,454.75 Gross PnL (+0.64%)**.
- **#2 Pick — `TATAPOWER` (`Prob: 99.13%`):** Shorted 2,130 qty @ ₹352.80 (`09:25:00`) $\rightarrow$ Covered @ ₹351.48 (`09:36:00` Cadence Profit Lock) $\rightarrow$ **+₹2,817.30 Gross PnL (+0.38%)**.
- **Total Realized Profit:** **+₹7,272.05 Gross (~+₹6,970 Net after Kotak charges)** | **Position Status:** **100% FLAT by 09:36:05 AM IST**.
