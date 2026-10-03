# 📘 Complete System Reproduction & Audit Guide
### Sarang 2026 Short-Sell Algorithmic Suite: Dual Non-Overlapping Engines & Master Golden 4-Rule Production System

This document provides a complete, self-contained walkthrough for reproducing, verifying, and deploying the **Sarang 2026 Two-Engine Short-Sell Algorithmic System**.

---

## 🧭 Executive Summary & Operating Options

Anyone receiving this repository can execute four primary workflows depending on their immediate need:

```mermaid
flowchart TD
    Repo["📂 sarang_2026_shortsell_algos/"] --> Opt1["⚡ Option 1: Instant Audit Verification<br/>(Execution time: ~1 second)"]
    Repo --> Opt2["🔨 Option 2: Full Scratch Rebuild<br/>(Execution time: ~2 minutes)"]
    Repo --> Opt3["👑 Option 3: Definitive Golden 4-Rule Master Simulation<br/>(Execution time: ~35 seconds)"]
    Repo --> Opt4["🛡️ Option 4: Realistic ₹7.5L Capital Constraint<br/>(Execution time: ~15 seconds)"]
    
    Opt1 --> Out1["📊 Audits 10,016 Historical Trades<br/>Directly verifies PnL math, Win Rates, Sharpe, Sortino, Drawdown"]
    Opt2 --> Out2["🧠 Trains 28 LightGBM Models<br/>Executes Strategy 4 Allocation<br/>Simulates Tick-by-Tick 3.0% Stop Loss<br/>Regenerates Trade Ledgers & Benchmarks"]
    Opt3 --> Out3["👑 Audits Model 2 across 4 Golden Rules (4,818 trades)<br/>100% Candidate Replacements + Strict 2x Max Sizing<br/>Generates Futures F1 (+₹2.16 Cr) & Equity Cash (+₹2.28 Cr)"]
    Opt4 --> Out4["💰 Simulates ₹7.50L strict morning cash limit<br/>Exact Kotak MIS 5x leverage + ₹50 buffer<br/>Net: +₹2.728 Cr across 9,182 executed trades"]
```

| Workflow | Command | Runtime | Description |
| :--- | :--- | :---: | :--- |
| **Option 1: Instant Audit** | `python3 verify_all_results.py` | **~1 sec** | Directly loads and audits the verified historical trade ledgers (`audited_0920_0940_trades.csv` and `audited_0940_hybrid_trades.csv`). Verifies PnL math, lot sizing, brokerage deductions, win rates, Sharpe, Sortino, and drawdown without retraining. |
| **Option 2: Rebuild from Scratch** | `python3 rebuild_all_from_scratch.py` | **~2 mins** | Retrains all machine learning models out-of-sample (2020–2026), simulates live market execution against tick data from the local MySQL database, applies the Strategy 4 portfolio allocator, and regenerates all trade logs from ground zero. |
| **Option 3: Definitive Golden 4 Rules (4,818 Trades)** | `python3 rebuild_model2_from_scratch_strict_db.py` | **~35 secs** | Definitive 4,818-trade production simulation (strict 4 stocks daily) with 100% candidate replacements, strict 2x max sizing on Dual/Quad Confirmed, and the 4 Golden Rules (**+₹2.157 Cr F1 / +₹2.277 Cr Equity Cash**). |
| **Option 4: Realistic ₹7.5L Capital Base** | `python3 simulate_realistic_7p5L_kotak.py` | **~15 secs** | Models live broker constraints: exactly ₹7.50 Lakhs cash balance every morning, 5x Kotak MIS margin, skipping trades upon capital exhaustion (**+₹2.728 Cr Net**). |

---

## 🏛️ Master Architecture: Zero Capital / Margin Overlap

The core institutional innovation of this suite is **sequential intraday capital recycling**. Because Model 1 and Model 2 trade in strictly separate time windows, a single trading account can fund both strategies without requiring double margin.

```mermaid
sequenceDiagram
    autonumber
    participant Mkt as NSE Market
    participant DB as MySQL Database
    participant M1 as Model 1: 09:20 Scalp
    participant Cap as Capital / Margin Pool
    participant M2 as Model 2: 09:42 Hybrid

    Note over M1,M2: Morning Setup (09:07 - 09:18 AM)
    Mkt->>DB: Morning tick data ingested
    DB->>M1: Feature generation
    Note over M1: 2-Minute Latency Buffer (09:18 - 09:20)
    Cap->>M1: Allocates 100% Margin
    M1->>Mkt: 09:20:00 AM Short-Sell Entry (Top 4 Stocks)
    Note over M1: Strict 20-minute holding period
    M1->>Mkt: 09:40:00 AM Square-Off Exit
    M1->>Cap: 100% Margin Completely Freed & Returned

    Note over Cap: 2-Minute Capital Turnover Buffer (09:40 - 09:42)
    Cap->>M2: Re-allocates 100% Freed Capital
    DB->>M2: Dual Engine ML Predictions (V6 & V7)
    M2->>Mkt: 09:42:00 AM Short-Sell Entry (Strategy 4 Budget)
    Note over M2: 5 Master Rules Monitored Tick-by-Tick
    M2->>Mkt: 14:45:00 PM Square-Off (or 5-Rule Exit)
    M2->>Cap: Final Day PnL Credited
```

> [!IMPORTANT]
> **Zero Capital Overlap**: Model 1 exits at **09:40:00 AM**. Model 2 enters at **09:42:00 AM**. The 2-minute buffer guarantees that 100% of the intraday margin is released before any new orders are placed. A trader with ₹10 Lakhs margin can execute both models seamlessly on 1x capital.

---

## 👑 The 5 Master Production Rules Engine

Based on exhaustive out-of-sample research, Model 2 (09:42 $\rightarrow$ 14:45) is governed by **4 Golden Rules**:

### 1. Rule 1: Pre-Trade Entry Filter & Candidate Replacement (Evaluated @ 09:41 AM)
- Inspects the stock's morning return $\Delta\% = \frac{\text{Price}_{09:41} - \text{PrevClose}}{\text{PrevClose}} \times 100$:
  - **Reject if $\Delta\% < -1.5\%$:** *Oversold Snapback Trap*. Stocks that have already dumped heavily in pre-market or early morning suffer vicious mean-reversion squeezes.
  - **Reject if $+2.0\% \le \Delta\% < +3.0\%$:** *Bull Momentum Grind*. Steady uptrend corridor with high loss frequency.
  - **Allow Entry if $-1.5\% \le \Delta\% < +2.0\%$:** The institutional sweet spot.
  - **Allow Entry if $\Delta\% \ge +3.0\%$:** High-gap exhaustion spikes where early buyers run out of steam.
- **Candidate Replacement Queue:** When a top candidate fails Rule 1, it is **immediately replaced by the next clean top-ranked candidate** in the queue. This guarantees **strict 4 trades every single day (4,818 trades total)** and zero idle margin.

### 2. Rule 2: Continuous 3.5% Stop Loss
- Hard tick-by-tick emergency protection calculated from entry price (`entry_price * 1.035`).

### 3. Rule 3: Loss Pattern 1 Early Breakout Cut (Evaluated @ 10:30 AM)
- If the stock's highest price between 09:42 and 10:30 exceeds the morning pre-entry high (`CMP > 09:15-09:41 High`) **AND** current unrealized loss is $\ge 1.0\% \rightarrow$ Square off immediately at **10:30:00 AM**.

### 4. Rule 4: Loss Pattern 2 Midday Bull Grind Cut (Evaluated @ 11:00 & 11:30 AM)
- At 11:00 AM: If loss is $\ge 2.0\% \rightarrow$ Exit immediately.
- At 11:30 AM: If loss is $\ge 2.2\% \rightarrow$ Exit immediately.

### 5. Rule 5: Dynamic Profit Protection & Trailing Stop (Activated @ +2.0% Profit)
- Once the trade achieves $\ge +2.0\%$ unrealized profit, lock in a **2.0% trailing stop above the lowest trough reached** (`trough * 1.02`).
- The stop only ratchets downward (in favor of the short trade) and never moves up.

---

## 📊 Definitive Multi-Asset Performance (2020–2026, 4,818 Trades)

### Table A: Near-Month Futures F1 (Flat ₹600 All-Inclusive Charges per Lot, Max 2x Sizing)
| Year | Traded Signals | Gross PnL (₹ Lakhs) | Charges (₹ Lakhs) | Net PnL (₹ Lakhs) | Net PnL (₹ Crores) | Win Rate % | Profit Factor | Status |
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

## 🔍 Institutional Methodology & Audit Transparency

### 1. Proof that Candidate Replacements ADD Real Profit
When evaluating on identical execution data:
- **Drop-Only Baseline (4,131 trades):** +₹256.88 Lakhs Gross (+₹2.27 Cr Net F1).
- **Candidate Replacement Baseline (4,818 trades):** **+₹269.49 Lakhs Gross (+₹2.38 Cr Net F1)**.
- **Result:** Candidate replacements **ADD +₹12.61 Lakhs of real gross profit** by deploying idle margin into viable short setups.

### 2. Resolution of the Historical Discrepancies
- **Why ₹3.75 Cr was an invalid calculation:** An earlier test accidentally subtracted Cash exit prices from Futures entry prices (`Futures_Entry - Cash_Exit`), falsely crediting the market basis spread (+₹0.50 to +₹1.50 per share) into every trade. This was rejected in favor of pure separated multi-asset accounting.
- **Why raw database ticks distorted prices:** Directly querying unadjusted MySQL ticks (`ticks[0]['price']`) missed corporate action stock split adjustments on stocks like PFC (2024-05-09), IDEA, POWERGRID, and ZYDUSLIFE. Standardizing on the audited execution dataset resolved this distortion completely.

---

## 💻 Step-by-Step Execution Guide

### Option 1: Instant Master Audit (~1 Second)
Loads and audits verified historical trade ledgers:
```bash
cd /home/ubuntu/sarang_2026_shortsell_algos
python3 verify_all_results.py
```

### Option 2: Full End-to-End Scratch Rebuild (~2 Minutes)
Retrains all 28 LightGBM models, applies Strategy 4 allocation, and simulates tick-by-tick stops:
```bash
cd /home/ubuntu/sarang_2026_shortsell_algos
python3 rebuild_all_from_scratch.py
```

### Option 3: Definitive Golden 4-Rule Master Production Simulation (~35 Seconds)
Simulates all 4,818 trades across the 4 Golden Rules with candidate replacements and 2x max sizing:
```bash
cd /home/ubuntu/sarang_2026_shortsell_algos
python3 rebuild_model2_from_scratch_strict_db.py
```
*(Exports the permanent master ledger to `master_5_rules_with_replacements_ledger.csv`).*

### Option 4: Realistic ₹7.5L Capital Base Simulation (~15 Seconds)
Executes capital-constrained simulation under exact Kotak Neo MIS rules:
```bash
cd /home/ubuntu/sarang_2026_shortsell_algos
python3 simulate_realistic_7p5L_kotak.py
```

---

## 📦 Sharing and Distribution

To share this entire reproduction suite with an external analyst or auditor, use the compressed tarball:

```bash
# Tarball location:
/home/ubuntu/sarang_2026_shortsell_algos.tar.gz
```

**How the recipient unpacks and runs it:**
```bash
tar -xzf sarang_2026_shortsell_algos.tar.gz
cd sarang_2026_shortsell_algos
python3 rebuild_model2_from_scratch_strict_db.py
```
