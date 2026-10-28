# 09:40 / 09:42 Short-Sell Hybrid Model: Option A Production Pipeline

This directory is the verified historical walk-forward replica repository of the **live 09:40 Short-Sell production system** (entry at 09:42:00).

> Path: `/home/ubuntu/live_production0942_model` (also accessible via symlink `/home/ubuntu/live_production0940_model`)

---

## 🎯 Architecture & Option A Replacement Rules

The live system and its historical replica implement **Option A Qualified Replacements**:

### 1. Initial Top 4 Evaluation (at 09:40:00)
- The LightGBM Rebound-Aware Model ranks all candidate stocks by predicted short return.
- The Top 4 candidates are evaluated against safety filters:
  - **RULE 1 (Morning Drop Cutoff -1.5%):** Skip if `stock_pct_940 < -1.5%` (avoids severe rebound traps).
  - **RULE 2 (Crash Day Protector):** Skip if `nifty_pct < -0.5%` AND `stock_pct_940 < -0.5%`.
  - **RULE 4 (Extreme Oversold Protector):** Skip all trades if market breadth $< 10.0\%$.

### 2. Qualified Replacements from Rank 5 and Rank 6
- Replacements are **ONLY** permitted to backfill slots vacated by **Rule 1** drops (`r1_dropped_count`).
- Slots dropped due to Rule 2 (Nifty Crash) or Rule 4 remain **EMPTY** to protect capital on dangerous market-wide plunge days.
- Maximum replacements allowed = `r1_dropped_count` (capped so total portfolio never exceeds 4 stocks).
- **Strict Quality Gate:** Candidate from Rank 5 or Rank 6 must satisfy:
  1. `stock_pct_940 >= -0.5%` (Strictly prevents chasing down moves / catching falling knives).
  2. Passes Rule 2 Crash Day Protector.
  3. Passes Rule 4 Market Breadth Filter.

---

## 📊 Audited Historical Results (2020-01-01 to 2026-10-23)

Verified via [`simulate_rule1_replacements_pct05.py`](file:///home/ubuntu/live_production0942_model/simulate_rule1_replacements_pct05.py):

| Metric | Overall System (Base + Option A Reps) | Standalone Replacements (Rank 5 & 6) |
| :--- | :--- | :--- |
| **Total Trades** | **5,269** | **289** |
| **Cumulative Net PnL (₹10L/stock)** | **+₹102.14 Lakhs** | **+₹8.85 Lakhs** |
| **Win Rate** | **55.80%** | **57.44%** |
| **Friction Included** | Kotak MIS Cash Equity Taxes + ₹40 Brokerage | Kotak MIS Cash Equity Taxes + ₹40 Brokerage |

---

## ⚡ 4-Simulation Exit Architecture Comparison (Cash Equities `scrapdata`, 5,269 Trades)

Evaluated across all **5,269 Option A Walk-Forward trades (`2020–2026`)** on 1-minute Cash Equity (`scrapdata`) ticks (`option_a_5269_4sims_comparison.csv`):

### A. Overall Risk-Adjusted Comparison (at ₹10,00,000 Notional Per Stock)

| Strategy Configuration | Total Net PnL (`2020–2026`) | **2026 YTD Net PnL (`612` Trades)** | Win Rate | Profit Factor | Max Drawdown | Sharpe Ratio | Calmar Ratio |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **SIM 1A (Baseline):** No TP \| SL `2.25%` (1-Tick) \| Exit `14:45` | **`+₹102.22 Lakhs`** | **`+₹11.42 Lakhs`** | `55.8%` | `1.34` | `-₹4.58 Lakhs` | `2.51` | `22.3x` |
| **SIM 1B:** No TP \| SL `2.25%` (**3-Min Cont. Breach**) \| Exit `14:45` | **`+₹97.62 Lakhs`** | **`+₹10.21 Lakhs`** | `56.4%` | `1.31` | `-₹5.71 Lakhs` | `2.32` | `17.1x` |
| **SIM 2A:** `2.0%` TP \| SL `2.25%` (1-Tick) \| `+0.50%` Re-Entry | **`+₹98.77 Lakhs`** | **`+₹10.91 Lakhs`** | `58.3%` | `1.35` | `-₹4.18 Lakhs` | `2.74` | `23.6x` |
| **SIM 2B:** `2.0%` TP \| SL `2.25%` (**3-Min Cont. Breach**) \| `+0.50%` Re-Entry | **`+₹95.78 Lakhs`** | **`+₹9.82 Lakhs`** | `58.9%` | `1.33` | `-₹4.62 Lakhs` | `2.65` | `20.7x` |
| **SIM 3A (Live 4-Stage Engine — Active Production):** Time-Decay SL (`2.25/1.5/1.0%`) + `1.25%` Lock + `2.0%` Trail (`1.75%` floor) + Re-Entry | **`+₹97.16 Lakhs`** | **`+₹10.84 Lakhs`** | **`60.8%`** | **`1.39`** | **`-₹3.23 Lakhs`** | **`3.07`** | **`30.1x`** |
| **SIM 3B (4-Stage w/ Constant `2.25%` SL):** No SL Decay + `1.25%` Lock + `2.0%` Trail (`1.75%` floor) + Re-Entry | **`+₹94.41 Lakhs`** | **`+₹10.94 Lakhs`** | **`63.0%`** | `1.36` | `-₹3.71 Lakhs` | `2.76` | `25.5x` |

### B. Year-by-Year Net PnL Breakdown (`2020–2026`, ₹10 Lakhs / Stock Capital)

| Year | Trades | **SIM 1A** (No TP, 1-Tick `2.25%` SL) | **SIM 1B** (No TP, 3-Min `2.25%` SL) | **SIM 2B** (`2%` TP, 3-Min `2.25%` SL, Re-Entry) | **SIM 3A (Live 4-Stage, Decay SL)** | **SIM 3B (4-Stage, Constant `2.25%` SL)** |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **2020** | 768 | `+₹21.77L` | `+₹17.79L` | `+₹17.18L` | **`+₹22.36L`** | `+₹17.46L` |
| **2021** | 784 | `+₹24.23L` | `+₹26.59L` | **`+₹27.45L`** | `+₹22.58L` | `+₹25.43L` |
| **2022** | 762 | `+₹11.48L` | `+₹11.13L` | **`+₹12.25L`** | `+₹10.31L` | `+₹9.09L` |
| **2023** | 788 | `+₹10.46L` | **`+₹10.49L`** | `+₹7.64L` | `+₹9.58L` | `+₹9.34L` |
| **2024** | 778 | `+₹8.57L` | `+₹7.72L` | `+₹6.74L` | **`+₹8.66L`** | `+₹7.79L` |
| **2025** | 777 | `+₹14.29L` | `+₹13.70L` | **`+₹14.69L`** | `+₹12.82L` | `+₹14.36L` |
| **2026** | 612 | **`+₹11.42L`** | `+₹10.21L` | `+₹9.82L` | `+₹10.84L` | **`+₹10.94L`** |
| **TOTAL** | **5,269** | **`+₹102.22L`** | **`+₹97.62L`** | **`+₹95.78L`** | **`+₹97.16L`** | **`+₹94.41L`** |

### C. Year-by-Year Net PnL Breakdown (`2020–2026`, ₹5 Lakhs / Stock Capital)

| Year | Trades | **SIM 1A** (No TP, 1-Tick `2.25%` SL) | **SIM 1B** (No TP, 3-Min `2.25%` SL) | **SIM 2B** (`2%` TP, 3-Min `2.25%` SL, Re-Entry) | **SIM 3A (Live 4-Stage, Decay SL)** | **SIM 3B (4-Stage, Constant `2.25%` SL)** |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **2020** | 768 | `+₹10.70L` | `+₹8.71L` | `+₹8.35L` | **`+₹10.95L`** | `+₹8.51L` |
| **2021** | 784 | `+₹11.92L` | `+₹13.10L` | **`+₹13.49L`** | `+₹11.05L` | `+₹12.48L` |
| **2022** | 762 | `+₹5.55L` | `+₹5.37L` | **`+₹5.91L`** | `+₹4.95L` | `+₹4.34L` |
| **2023** | 788 | `+₹5.04L` | **`+₹5.06L`** | `+₹3.62L` | `+₹4.59L` | `+₹4.47L` |
| **2024** | 778 | `+₹4.10L` | `+₹3.68L` | `+₹3.17L` | **`+₹4.14L`** | `+₹3.70L` |
| **2025** | 777 | `+₹6.95L` | `+₹6.66L` | **`+₹7.13L`** | `+₹6.20L` | `+₹6.97L` |
| **2026** | 612 | **`+₹5.55L`** | `+₹4.94L` | `+₹4.74L` | `+₹5.25L` | **`+₹5.30L`** |
| **TOTAL** | **5,269** | **`+₹49.81L`** | **`+₹47.52L`** | **`+₹46.40L`** | **`+₹47.11L`** | **`+₹45.74L`** |
| **Max DD** | — | `-₹2.32L` | `-₹2.89L` | `-₹2.36L` | **`-₹1.66L`** | `-₹1.90L` |

---

## 🛡️ Detailed Working of Active Live Engine (`SIM 3A: 4-Stage Dynamic Engine`)

Implemented in `03_kotak_execution/sl_near_alert_monitor.py` and `03_kotak_execution/Neo_shortsell_mis_order.py`, and reconciled daily at `16:15 IST` by `02_live_production_pipelines/0940_hybrid_pipeline/reconcile_0940_live_mimic_pnl.py`:

1. **Stage 1 — Time-Decaying 3-Minute Continuous Breach Stop-Loss (Active when $\text{Max Profit} < +1.25\%$):**
   - **Morning Tier (`09:42 – 11:00 IST`):** Stop-Loss at **`+2.25%`** above Entry (`EP * 1.0225`).
   - **Mid-Morning Tier (`11:00 – 12:30 IST`):** Stop-Loss tightens to **`+1.50%`** above Entry (`EP * 1.0150`).
   - **Afternoon Tier (`12:30 – 14:30 IST`):** Stop-Loss tightens to **`+1.00%`** above Entry (`EP * 1.0100`).
   - **3-Minute Continuous Breach Filter:** Requires LTP to remain continuously above the active SL level for **3 full minutes** (`180 seconds` / `12 consecutive 15s checks`) before firing an exit. If LTP dips back below SL within 3 minutes, the breach counter resets to 0.
2. **Stage 2 — Pre-TP Profit Lock (Activates as soon as $\text{Max Profit} \ge +1.25\%$):**
   - Permanently upgrades from Stage 1 to Stage 2 and moves the protective stop to **`EP * 0.9950` (`+0.50%` locked profit)** (or `+0.10%` net buffer), ensuring a trade that reached `+1.25%` profit can never turn into a stop-loss.
3. **Stage 3 — Uncapped Dynamic Profit Trailing (Activates as soon as $\text{Max Profit} \ge +2.00\%$):**
   - Permanently upgrades to Stage 3 and activates a one-way downward-ratcheting trailing floor:
     $$\text{Trailing Floor \%} = \max\left(1.75\%, \; \text{Max Profit \%} - 0.50\%\right)$$
     $$\text{Trailing Trigger Price} = \min\left(\text{EP} \times 0.9825, \; \text{Min LTP Seen} \times 1.0050\right)$$
   - Gives the trade a `0.25%` initial breathing buffer (`2.00%` $\rightarrow$ `1.75%` floor) instead of `1.90%`, and once profit exceeds `+2.25%`, trails penny-for-penny `0.50%` behind peak profit all the way down.
4. **Stage 4 — Tactical Pullback Re-Entry (`Before 14:00 IST`):**
   - When Leg 1 exits via Stage 3 Trailing TP before `14:00 IST`, monitors for a **`+0.50%` bounce** from the Leg 1 exit price (`Leg1_Exit * 1.0050`).
   - Upon trigger, enters **Leg 2 Short** with **`+1.75%` TP2** (`Leg2_Entry * 0.9825`) and a **Zero-Capital-Risk Stop-Loss** at the original Leg 1 Entry price (`EP`).
5. **End-of-Day Square-Off (`14:30 – 14:45 IST`):**
   - Places a limit discount cover order at `14:30 IST`, followed by a mandatory market/chaser sweep at `14:45 IST`.

---

## 📁 Key Files

- `live_0940_hybrid_pipeline.py` — The live production runner executing every morning.
- `simulate_rule1_replacements_pct05.py` — The dedicated backtest script for Option A replacements.
- `trades_system_with_rep_pct05_oct23.csv` — Complete 5,269 trade ledger.
- `option_a_5269_4sims_comparison.csv` — Trade-by-trade 4-simulation (`SIM 1`, `SIM 2`, `SIM 3A`, `SIM 3B`) comparison across all 5,269 trades at ₹5L and ₹10L capital.
- `trades_replacements_rank5_6_pct05_oct23.csv` — Isolated 289 replacement trades ledger.
- `walkforward_0942_simulation.py` — Master walk-forward simulation script (₹5L capital).
- `walkforward_0942_simulation_10L.py` — Master walk-forward simulation script (₹10L capital).
