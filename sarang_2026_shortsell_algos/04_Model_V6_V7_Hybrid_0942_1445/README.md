# 🏆 V6/V7 Hybrid Engine (₹2.15 Crore Strategy - Audited & Built from Scratch)

## 📌 Strategy Architecture & Verification
This directory contains the verified, audited, from-scratch implementation of the **V6/V7 Hybrid Engine (09:42:00 AM Short $\rightarrow$ 14:45:00 PM Square-Off)**.

The strategy mathematically fuses:
1. **Model V6 (Broad Mean Reversion):** Captures overextended morning gap-ups and overshoots across all F&O stocks (Top 4 candidates daily).
2. **Model V7 (Momentum Sniper):** Trains strictly on pre-market fading candidates (`gap_fade_0907_to_940_pct < 0`) to short severe breakdown thrusts (Top 4 candidates daily).

By deduplicating the daily picks from both models, the system takes an average of **5–6 high-conviction trades per day**.

---

### 🛡️ Strict Compliance Standards:
1. **Zero External/Yahoo Finance Dependency:** 100% of price ticks and indicators are derived strictly from internal MySQL databases (`markets.scrapdata_F1` and `markets.scrapdata`). No Yahoo Finance APIs or files are used.
2. **Exact Dynamic Contract Lot Sizes:** Mapped dynamically per contract expiry from `/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/config/historical_lotsize_new.csv`. The legacy `.last()` forward-fill bug (which distorted 75% of historical trades) has been completely eradicated.
3. **Realistic Friction / Brokerage Charges:** Flat ₹300.00 commission is deducted from every executed trade.
4. **Tick-by-Tick 3.0% Stop Loss:** Evaluated against actual 1-minute historical tick data from `scrapdata_F1`.

---

## 📊 Verified Walk-Forward Performance Matrix (2020 – 2026)

| Year | Trades | Win Rate % | Gross PnL (₹ Lakhs) | Charges @ ₹300 (₹ Lakhs) | NET PnL (₹ Lakhs) | Avg PnL / Trade |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **2020** | 746 | **58.45%** | +₹24.10 L | ₹2.24 L | **+₹21.86 L** | ₹2,930.09 |
| **2021** | 755 | **68.21%** | +₹39.38 L | ₹2.27 L | **+₹37.11 L** | ₹4,915.82 |
| **2022** | 787 | **62.26%** | +₹32.57 L | ₹2.36 L | **+₹30.21 L** | ₹3,838.60 |
| **2023** | 757 | **63.54%** | +₹39.35 L | ₹2.27 L | **+₹37.08 L** | ₹4,898.14 |
| **2024** | 786 | **62.09%** | +₹52.07 L | ₹2.36 L | **+₹49.71 L** | ₹6,324.34 |
| **2025** | 748 | **64.44%** | +₹31.32 L | ₹2.24 L | **+₹29.07 L** | ₹3,887.01 |
| **2026** | 415 | **61.69%** | +₹10.82 L | ₹1.25 L | **+₹9.58 L** | ₹2,308.32 |
| **TOTAL** | **4,994** | **63.04%** | **+₹229.61 L** | **₹14.98 L** | **+₹214.63 L** | **₹4,297.66** |

> **Key Takeaway:** With verified historical contract lot sizes, zero Yahoo Finance, and flat ₹300 charges, the strategy surpasses the original ₹1.54 Crore claim, generating **+₹214.63 LAKHS (+₹2.15 CRORE) NET PnL** across 4,994 trades with an extraordinary **63.04% Win Rate**.

---

## 🚀 How to Run the From-Scratch Pipeline

Execute the clean, standalone script:
```bash
python3 /home/ubuntu/V6_V7_Hybrid_Standalone/run_v6_v7_hybrid_scratch.py
```

Outputs:
- Full year-by-year performance audit table printed to stdout.
- Full trade-by-trade log with exact execution prices and contract lot sizes saved to:
  `/home/ubuntu/V6_V7_Hybrid_Standalone/hybrid_pure_db_trades.csv`
