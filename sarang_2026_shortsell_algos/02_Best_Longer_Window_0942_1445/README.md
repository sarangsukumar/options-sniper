# 09:40 -> 14:45 Dual Confirmed 2x Hybrid Model with 5 Master Production Rules

This standalone directory contains the complete scratch reproduction suite for the **09:40 -> 14:45 Dual Confirmed 2x Hybrid Engine**, which generates over **+₹2.157 Crore Net (Futures F1)** and **+₹2.277 Crore Net (Equity Cash)** across 4,818 trades with 100% of years green (2020–2026).

---

## 🧠 System Architecture & Edge

### 1. Execution Window
- **Entry Time:** Exactly `09:42:00 IST` (2 minutes after the 09:40 candle close to allow full order execution).
- **Exit Time:** Exactly `14:45:00 IST` (or immediate tick-by-tick continuous Stop Loss or Pattern cut).
- **Daily Capacity:** Exactly **4 trades every single day** via the 100% Candidate Replacement Queue (total 4,818 trades).

### 2. Dual Engine Machine Learning
- **Engine 1 (V6 Momentum Breakdown):** LightGBM Regressor trained on opening gaps, VWAP divergence, previous day closing momentum, and morning range.
- **Engine 2 (V7 Gap Fade Specialist):** Dedicated LightGBM Regressor trained exclusively on stocks fading opening gap spikes (`gap_fade_0907_to_940_pct < 0.0`).
- **Walk-Forward Validation:** Trained strictly out-of-sample using expanding historical windows ($Year < Y$ for test year $Y \in [2020..2026]$, excluding Mondays). Zero lookahead bias.

### 3. Portfolio Allocation & 4-Slot Daily Budget
- **Strict 4-Slot Daily Cap:** The portfolio never holds more than 4 concurrent lots per day, keeping margin requirements predictable and risk strictly capped.
- **2x Multiplier on Dual-Confirmed:** When a stock ranks in the Top 4 of *both* Engine V6 and Engine V7, it is classified as **DUAL CONFIRMED ⚡⚡** and allocated **strict 2x lot size MAX**.
- **50/50 Remainder Fill:** Any slots remaining up to the 4-slot daily budget are filled alternating 50/50 between:
  1. Top candidate from **Custom Limit Fills** (historical high-probability limit fills).
  2. Top candidate from **Full Market Universe** (best momentum breakdown across all F&O stocks).

---

## 🛡️ The 5 Master Production Rules

Model 2 incorporates **5 Golden Rules** evaluated tick-by-tick:

1. **Rule 1 (Pre-Trade Entry Filter & Candidate Replacement @ 09:41 AM):**
   - Skip stock if morning return $\Delta\% < -1.5\%$ (*Oversold Snapback Trap*) or $+2.0\% \le \Delta\% < +3.0\%$ (*Bull Momentum Grind*).
   - Any rejected trade is immediately replaced by the next-ranked candidate in the queue to maintain 100% daily capital efficiency.
2. **Rule 2 (Continuous 3.5% Stop Loss):**
   - Tick-by-tick emergency protection calculated from entry price (`entry_price * 1.035`).
3. **Rule 3 (Loss Pattern 1 Early Breakout Cut @ 10:30 AM):**
   - If stock makes a new high of the day (`CMP > 09:15-09:41 High`) **AND** current loss is $\ge 1.0\% \rightarrow$ Exit immediately at 10:30 AM.
4. **Rule 4 (Loss Pattern 2 Midday Bull Grind Cut @ 11:00 / 11:30 AM):**
   - If loss is $\ge 2.0\%$ at 11:00 AM OR $\ge 2.2\%$ at 11:30 AM $\rightarrow$ Exit immediately.
5. **Rule 5 (Dynamic Trailing Profit Stop):**
   - Once a position achieves $\ge +2.0\%$ unrealized profit, lock in a **2.0% trailing stop above the lowest trough reached** (`trough * 1.02`). The stop only ratchets downward.

---

## 📊 Definitive Multi-Asset Audited Performance (2020–2026, 4,818 Trades)

### Table A: Near-Month Futures F1 (Flat ₹600 All-Inclusive Charges per Lot, Max 2x Sizing)
| Year | Traded Signals | Gross PnL (₹ Lakhs) | Brokerage & Slip (₹ Lakhs) | Net PnL (₹ Lakhs) | Net PnL (₹ Crores) | Win Rate % | Profit Factor | Status |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **2020** | 746 | +₹21.35 L | -₹4.48 L | **+₹16.88 L** | +₹0.169 Cr | 61.53% | 1.58 | 🟢 All-Green |
| **2021** | 724 | +₹39.50 L | -₹4.53 L | **+₹34.97 L** | +₹0.350 Cr | 69.75% | 2.28 | 🟢 All-Green |
| **2022** | 724 | +₹44.71 L | -₹4.88 L | **+₹39.82 L** | +₹0.398 Cr | 65.06% | 3.08 | 🟢 All-Green |
| **2023** | 736 | +₹43.17 L | -₹5.09 L | **+₹38.07 L** | +₹0.381 Cr | 61.28% | 2.00 | 🟢 All-Green |
| **2024** | 748 | +₹57.90 L | -₹5.31 L | **+₹52.59 L** | +₹0.526 Cr | 61.50% | 2.03 | 🟢 All-Green |
| **2025** | 728 | +₹32.82 L | -₹4.84 L | **+₹27.98 L** | +₹0.280 Cr | 61.54% | 1.68 | 🟢 All-Green |
| **2026 (YTD)** | 412 | +₹7.99 L | -₹2.63 L | **+₹5.36 L** | +₹0.054 Cr | 57.52% | 1.34 | 🟢 All-Green |
| **TOTAL** | **4,818** | **+₹247.43 L** | **-₹31.76 L** | **👑 +₹215.67 L** | **👑 +₹2.157 Cr** | **62.91%** | **1.97** | **100% Green** |

### Table B: Equity Cash (Kotak MIS Statutory Charges + ₹50 Buffer, Max 2x Sizing)
| Year | Traded Signals | Gross PnL (₹ Lakhs) | Kotak Charges (₹ Lakhs) | Net PnL (₹ Lakhs) | Net PnL (₹ Crores) | Win Rate % | Profit Factor | Status |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **2020** | 746 | +₹21.35 L | -₹2.55 L | **+₹18.80 L** | +₹0.188 Cr | 62.73% | 1.66 | 🟢 All-Green |
| **2021** | 724 | +₹39.50 L | -₹3.13 L | **+₹36.37 L** | +₹0.364 Cr | 70.30% | 2.35 | 🟢 All-Green |
| **2022** | 724 | +₹44.71 L | -₹3.06 L | **+₹41.65 L** | +₹0.416 Cr | 65.61% | 3.25 | 🟢 All-Green |
| **2023** | 736 | +₹43.17 L | -₹3.15 L | **+₹40.02 L** | +₹0.400 Cr | 63.59% | 2.07 | 🟢 All-Green |
| **2024** | 748 | +₹57.90 L | -₹3.61 L | **+₹54.29 L** | +₹0.543 Cr | 62.30% | 2.07 | 🟢 All-Green |
| **2025** | 728 | +₹32.82 L | -₹2.73 L | **+₹30.09 L** | +₹0.301 Cr | 63.05% | 1.75 | 🟢 All-Green |
| **2026 (YTD)** | 412 | +₹7.99 L | -₹1.52 L | **+₹6.47 L** | +₹0.065 Cr | 58.01% | 1.42 | 🟢 All-Green |
| **TOTAL** | **4,818** | **+₹247.43 L** | **-₹19.75 L** | **👑 +₹227.68 L** | **👑 +₹2.277 Cr** | **64.01%** | **2.05** | **100% Green** |

---

## 🎯 Trade Dynamics Breakdown (4,818 Trades)

- **Exit Reason Breakdown:**
  - **14:45 EOD Scheduled Exit:** 3,928 trades (81.53%)
  - **Audited Exit (Fallback):** 440 trades (9.13%)
  - **Dynamic Trailing Stop (+2% Lock):** 188 trades (3.90%)
  - **Pattern 1 Breakout Cut (10:30 AM):** 169 trades (3.51%)
  - **Hard 3.5% Stop Loss:** 74 trades (1.54%)
  - **Pattern 2 Midday Cut (11:00 / 11:30 AM):** 19 trades (0.39%)
- **Allocation Sizing:**
  - **1x Lots Multiplier:** 4,342 trades (90.12%) — All single engine setups.
  - **2x Lots Multiplier:** 476 trades (9.88%) — Dual & Quad Confirmed setups (strict 2x ceiling).

---

## 🚀 How to Reproduce & Audit from Scratch

### 1. Definitive 5-Rule Master Production Simulation (Runtime: ~35 seconds)
```bash
python3 /home/ubuntu/sarang_2026_shortsell_algos/simulate_master_5_rules_with_replacements.py
```
*(Writes full trade-by-trade ledger to `master_5_rules_with_replacements_ledger.csv`).*

### 2. Full End-to-End Walk-Forward Machine Learning Simulation
Trains all 28 LightGBM models across 2020–2026, executes Strategy 4 portfolio selection, and recalculates all baseline metrics:
```bash
python3 run_model.py
```
*(Execution finishes in ~12 seconds on the local server).*

### 3. Instant Audit Verification (Reads baseline trade log)
```bash
python3 verify_scratch_pnl.py
```
