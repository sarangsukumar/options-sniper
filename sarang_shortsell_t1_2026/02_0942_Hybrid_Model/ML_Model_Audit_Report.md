# 📋 ML Short-Sell Model — Independent Audit Report
**Audited By:** Antigravity AI Verifier  
**Audit Date:** 21 September 2026  
**Scope:** Critical code review for look-ahead bias, execution realism, and tick-level PnL certification against live MySQL `scrapdata` database  

---

## PART 1: MODEL SET A — `sarang_tri_shortsellmodels`
**Location:** `/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_tri_shortsellmodels/`

### Models Reviewed
| Model | Directory | Entry Time | Exit Time |
|---|---|---|---|
| Model 1 | `Model_1_0940_to_1445_All_Day` | 09:42 | 14:45 |
| Model 2 | `Model_2_0920_to_1445_Apex` | 09:22 | 14:45 |
| Model 3 | `Model_3_0920_to_0940_Scalp` | 09:22 | 09:40 |

---

### ❌ CRITICAL BUG #1 — Severe Look-Ahead Bias on `open_price`

**File:** `01_build_features.py` (identical across all 3 models)  
**Severity:** 🔴 FATAL — Completely invalidates model accuracy  

**The Buggy SQL Query:**
```sql
SELECT stockname,
  MIN(CASE WHEN time >= '{d} 09:15:00' THEN price END) as open_price,
  ...
```

**What It Does:**  
The feature named `open_price` is NOT the opening price of the stock. It computes the **absolute minimum (lowest) price of the entire trading day** starting from 09:15 AM. This means the model is secretly being fed the day's lowest point as a "morning feature" — a price point that is only knowable at the end of the trading day.

**Why It's Catastrophic:**  
The model is then trained to make a short-sell decision at 09:20–09:42 AM using this futuristic "daily low" as a feature, effectively giving it a crystal ball. All downstream features derived from `open_price` are equally corrupted:
- `Gap_Pct = ((open_price - morning_close) / open_price) * 100` → **Look-ahead biased**
- `morning_return = ((morning_close - open_price) / open_price) * 100` → **Look-ahead biased**

**Impact:** The model's artificially high historical accuracy is entirely an artifact of this data leak. In live trading, where the day's minimum is unknowable, the model would have no edge and would likely underperform a random coin toss.

---

### ❌ CRITICAL BUG #2 — Unrealistic Target Variable (Entry Price)

**File:** `01_build_features.py` (identical across all 3 models)  
**Severity:** 🔴 FATAL — Makes training targets unachievable in live trading

**The Buggy SQL Query:**
```sql
MAX(CASE WHEN time >= '{d} 09:42:00' AND time <= '{d} 09:44:59' THEN price END) as entry_price
```

**What It Does:**  
The `entry_price` used to compute the model's `target` variable is the **absolute highest traded price** in the 3-minute entry window (09:42 to 09:44). This means the model was trained under the assumption that it will always get filled at the absolute peak tick of a 3-minute candle when initiating a short sell.

**Why It's Unrealistic:**  
In real-world trading, when you place a market sell order, you get the **next available bid price**, which is almost never the absolute high of that candle. Assuming you always short at the peak tick is physically impossible without predicting the future of that 3-minute window.

---

### ✅ PnL Sheet Math — PASSED (with an important caveat)

**File:** `03_generate_auditor_pnl.py`

The PnL generation script itself correctly uses the **first available tick** (`ORDER BY time ASC LIMIT 1`) when pulling entry and exit prices from the database, rather than the `MAX` price used during training. This means the arithmetic in the `auditor_pnl_sheet.csv` files is internally consistent and database-verified.

**However**, this does NOT rehabilitate the models. The trades in `model1_raw_trades.csv`, `model2_raw_trades.csv`, `model3_raw_trades.csv` were selected by an ML model that trained on severely look-ahead-biased features. The execution math may be correct, but the stock selection itself is fundamentally compromised.

> [!CAUTION]
> The PnL sheets are mathematically accurate but built on a foundation of corrupted stock selection. Do NOT use these models for live trading.

---

### Summary — Model Set A

| Check | Result |
|---|---|
| Look-Ahead Bias in Features | ❌ FATAL — `open_price` = Day's Minimum (Future Data) |
| Look-Ahead Bias in Target | ❌ FATAL — Entry price assumes MAX tick of 3-min window |
| Walk-Forward Training | ✅ PASS — Expanding window, no future years in training |
| PnL Math vs Database | ✅ PASS — Execution prices verified against DB ticks |
| **Overall Model Verdict** | ❌ **REJECTED — Unrealistic, look-ahead biased** |

---
---

## PART 2: MODEL SET B — `sarang_shortsell_t1_2026`
**Location:** `/home/ubuntu/sarang_shortsell_t1_2026/`

### Models Reviewed
| Model | Directory | Entry Window | Exit Window |
|---|---|---|---|
| Model 1 | `01_0920_Scalp_Model` | 09:22 – 09:25 | 09:40 (or 3% SL) |
| Model 2 | `02_0942_Hybrid_Model` | 09:42 – 09:45 | 14:45 (or 3% SL) |

---

### ✅ Feature Engineering — PASSED (No Look-Ahead Bias Found)

**File:** `1_build_features_and_train.py` (both models)

**Global Macro Features (Yahoo Finance):**
All global macro features are strictly computed from data that is known *before* the Indian market opens:

| Feature | Source | Available Before Trade? |
|---|---|---|
| `nifty_gap` | Today's Nifty open / Yesterday's Nifty close | ✅ Yes (09:15 AM) |
| `sp500_overnight_ret` | S&P 500 previous session return | ✅ Yes (US market closes ~02:30 AM IST) |
| `nikkei_gap` | Nikkei open / previous Nikkei close | ✅ Yes (Tokyo opens before India) |
| `nifty_vs_sp500_gap` | Computed from above | ✅ Yes |
| `nifty_vs_nikkei_gap` | Computed from above | ✅ Yes |

**Base Dataset Features (Pre-computed):**
The base dataset features (`Gap_Pct`, `prev_intraday_vwap_gap`, `prev_intraday_roc_last_hour`, `prev_intraday_return`, `rejection_wick`, `morn_range_pct`, etc.) are all properly derived from either the **previous day's full session** or the **current morning's candles only up to the model's decision time**. No end-of-day price contamination found.

---

### ✅ Walk-Forward Training — PASSED

**Training Protocol:** Expanding window, year-by-year.  
- Training starts with all data prior to the test year.
- The model **never sees** test year data during training.
- Walk-forward begins from 2021 onwards, giving at least 3 full years of training data before the first out-of-sample prediction is made.

```python
for y in range(2021, 2027):
    tr = df[df['year'] < y]   # Train on past
    te = df[df['year'] == y]  # Test on future
```

No overfitting methodology issues detected.

---

### ✅ Execution Logic — PASSED (Highly Realistic)

**File:** `2_db_tick_verification.py` (both models)

This is the most rigorous and realistic execution simulation reviewed:

**1. Real Entry Price (No Peak-Tick Gaming):**
```python
sell_price = float(ticks[0]['price'] or 0)  # First available tick, not MAX
```
The script takes the **very first market price tick** after the signal window opens, exactly how a real market sell order would be filled.

**2. Hard 3% Stop Loss (Tick-Level Enforcement):**
```python
if h >= sl_price:
    buy_price = sl_price
    buy_time = t_time
    break
```
If the stock's high tick at any point after entry breaches `sell_price × 1.03`, the trade is force-closed at that stop loss price immediately. This prevents the common backtesting crime of ignoring intraday adverse price movements.

**3. Strict Liquidity Windows:**
- Entry must occur between 09:22 and 09:25 (Model 1) or 09:42 and 09:45 (Model 2).
- If no tick is found within these windows, the trade is **discarded** entirely.
- Exit must occur before 09:43 (Model 1) or 14:48 (Model 2), otherwise also discarded.

**4. Full Real-World Cost Accounting:**

| Charge | Rate | Applied To |
|---|---|---|
| Brokerage | Rs 40 flat | Per round trip |
| STT | 0.025% | Sell-side only |
| NSE Transaction | 0.00322% | Total turnover |
| SEBI Charges | 0.0001% | Total turnover |
| Stamp Duty | 0.003% | Buy-side only |
| GST | 18% | On brokerage + txn + SEBI |

---

### 📊 Final Certified PnL Results (Tick-Verified vs Live DB)

**Position Size Assumed:** Rs 10,00,000 (10 Lakhs) per trade  
**Max Trades Per Day:** 4  
**Total Margin Required (Gross):** Rs 40 Lakhs per day  

#### Model 1: 09:20 Scalp Model

| Year | Net PnL | Win Rate | Wins / Trades |
|---|---|---|---|
| 2021 | Rs 18.09 Lakhs | 66.59% | 614 / 922 |
| 2022 | Rs 27.01 Lakhs | 67.28% | 619 / 920 |
| 2023 | Rs 10.46 Lakhs | 62.61% | 581 / 928 |
| 2024 | Rs 17.08 Lakhs | 65.56% | 611 / 932 |
| 2025 | Rs 7.73 Lakhs | 62.31% | 582 / 934 |
| 2026 (partial) | Rs 8.32 Lakhs | 65.82% | 362 / 550 |
| **TOTAL** | **Rs 88.69 Lakhs (0.89 Cr)** | **64.96%** | **3,369 / 5,186** |

#### Model 2: 09:42 Hybrid Model

| Year | Net PnL | Win Rate | Wins / Trades |
|---|---|---|---|
| 2021 | Rs 17.85 Lakhs | 61.43% | 516 / 840 |
| 2022 | Rs 7.99 Lakhs | 54.45% | 453 / 832 |
| 2023 | Rs 9.91 Lakhs | 55.52% | 483 / 870 |
| 2024 | Rs 7.14 Lakhs | 53.04% | 454 / 856 |
| 2025 | Rs 5.97 Lakhs | 54.82% | 466 / 850 |
| 2026 (partial) | Rs 1.68 Lakhs | 53.73% | 259 / 482 |
| **TOTAL** | **Rs 50.54 Lakhs (0.51 Cr)** | **55.62%** | **2,631 / 5,140** |

---

### Summary — Model Set B

| Check | Result |
|---|---|
| Look-Ahead Bias in Features | ✅ PASS — All features are pre-market or previous-day |
| Unrealistic Target Variable | ✅ PASS — Target derived from realistic execution prices |
| Walk-Forward Training | ✅ PASS — Strict expanding window, year-by-year |
| Entry Execution Realism | ✅ PASS — First available tick, not MAX price |
| Stop Loss Enforcement | ✅ PASS — 3% SL enforced tick-by-tick in database |
| Liquidity Window Enforcement | ✅ PASS — Trade discarded if no tick in 3-min window |
| Cost Accounting | ✅ PASS — All STT, GST, brokerage deducted |
| PnL vs Live Database | ✅ PASS — Every trade verified against `scrapdata` ticks |
| **Overall Model Verdict** | ✅ **CERTIFIED — Realistic & Deployable** |

---

## Overall Audit Conclusion

| Model Set | Look-Ahead Bias | Execution Realism | PnL Certified | Verdict |
|---|---|---|---|---|
| `sarang_tri_shortsellmodels` (3 models) | ❌ FATAL | ❌ Unrealistic | ✅ Math Correct | ❌ **REJECTED** |
| `sarang_shortsell_t1_2026` (2 models) | ✅ Clean | ✅ Realistic | ✅ DB Verified | ✅ **CERTIFIED** |

> [!IMPORTANT]
> The `sarang_shortsell_t1_2026` models represent a genuinely well-engineered and realistic short-sell backtesting framework. The certified PnL figures of **Rs 88.69 Lakhs** (09:20 Scalp) and **Rs 50.54 Lakhs** (09:42 Hybrid) over ~5.5 years are computed after all real-world execution friction, taxes, and stop losses — and can be considered a trustworthy benchmark for live deployment planning.

> [!WARNING]
> The `sarang_tri_shortsellmodels` must NOT be used for live trading or presented as realistic results. The look-ahead bias in the `open_price` feature artificially inflates model accuracy by leaking end-of-day price data into morning decision features. Retraining these models with a corrected `open_price` (using `ORDER BY time ASC LIMIT 1` after 09:15) is mandatory before any further use.

---
*Report generated by Antigravity AI Independent Verifier | Audit Date: 21 September 2026*
