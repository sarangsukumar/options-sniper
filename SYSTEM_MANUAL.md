# 🎯 SNIPER ALGORITHM (v3.0) — MASTER LIVE SERVER & BACKTEST MANUAL

> **This is the single source of truth for the team.**
> The system has been mathematically locked to the **R1 + R3 (1x Sizing)** architecture.
> This perfectly eliminates the dual-correlated drawdown risk seen in Rank 2, producing positive returns in every single year including 2025.

---

## 📊 GOLDEN TARGET RESULTS

Before running any live predictions, ensure your server is **perfectly synced** with our data.
Once synced, your local master backtester **must produce these exact numbers**:

| Year | Trades | Win Rate | Avg PnL (₹) |
| :--- | :---: | :---: | ---: |
| **2019** | 103 | 76.7% | ₹ 1,363 |
| **2020** | 210 | 67.6% | ₹ 2,514 |
| **2021** | 282 | 75.9% | ₹ 4,547 |
| **2022** | 286 | 71.0% | ₹ 1,835 |
| **2023** | 222 | 77.0% | ₹ 1,375 |
| **2024** | 285 | 76.1% | ₹ 2,109 |
| **2025** | 172 | 70.9% | ₹ 1,283 |
| **2026** | 95 | 64.2% | ₹ 1,552 |
| **OVERALL** | **1,655** | **73.1%** | **₹ 2,266** |

> ⚠️ If **any** number differs, your data is de-synced. Do **not** go live. Follow the verification steps below.

---

## 🔧 HOW TO VERIFY YOUR SETUP (New Server / After Re-clone)

### Step 1 — Pull Code & Unpack Data
```bash
git pull origin main
cd data/
tar -xzvf data_input_files_v3.tar.gz
cd ..
```

> **Critical:** You MUST extract the archive to get the un-corrupted pre-August history.
> Do NOT overwrite the historical data with fresh API pulls — only **append** new daily data.

### Step 2 — Lock the Historical Baseline
```bash
git checkout -- output/trades_dynamic_threshold_CLEAN_REFERENCE_20260812.csv
```

This restores the pristine, immutable 7.5-year reference file protected from the Aug 5 DB purge.

### Step 3 — Run the Master Backtest to Verify
```bash
python3 run_master_backtest.py
```

If your output **perfectly matches** the golden table above — your system is fully synced and ready for live production. ✅

---

## 📂 DATA ARCHITECTURE — THE GOLDEN RULE

Both the live prediction engine (`predict_today.py`) and the historical backtest engine (`run_master_backtest.py`) share the **exact same `data/` folder**.

| File | Purpose |
| :--- | :--- |
| `data/markets_pnl0325.csv` | Master F&O PnL history (2015–present) |
| `data/f11_intraday_features_all.csv` | Intraday tick features (3:19 PM session) |
| `data/yahoo_finance_all_stocks_2015_2026_gap_features.csv` | Daily gap, open, volume change features |
| `data/masterfile.csv` | Active F&O universe filter |

> **NEVER overwrite these files.** When your daily pipelines download new data, always **APPEND** new rows to the bottom. Overwriting destroys 11+ years of clean history that cannot be re-fetched correctly.

---

## ⚡ DAILY LIVE OPERATIONS

### Step 1 — Download Today's Data
Run the pipeline to fetch intraday ticks and gap features after 3:19 PM:
```bash
./pipeline/run_todays_prediction_pipeline.sh
```

### Step 2 — Run Today's Predictions
```bash
python3 predict_today.py
```

**Automated R1+R3 Logic (built into the script):**

| Condition | Action |
| :--- | :--- |
| Normal Day (3+ candidates) | Outputs exactly **Rank 1 and Rank 3** at **1x size** |
| Scarce Day (1 or 2 candidates) | Defaults to **Rank 1 Only** at 1x (capital protection) |
| Dead Market (0 candidates) | Prints `[NO TRADES]` |
| Friday | `[NO TRADES]` — Friday Lock active |
| Toxic Expiry DTE | `[NO TRADES]` — Expiry Lock active |

> The script automatically bypasses all noise filters and ML dual-confirmation. Zero extra steps needed.

### Step 3 — Append to the Master Tracker
After `predict_today.py` prints today's picks, append the new rows to:

```
output/trades_dynamic_threshold.csv
```

> **Do NOT overwrite.** Only append to the bottom.
> This keeps the file as a continuously growing live trade log — blending 7.5 years of history with your newly executed live trades.

---

## 📈 MASTER BACKTESTER — LIVE PERFORMANCE VIEW

Run at any time to see your real, up-to-the-minute performance:
```bash
python3 run_master_backtest.py
```

**How it works:**
1. Reads `output/trades_dynamic_threshold.csv`
2. Applies the mathematical R1+R3 filter to historical data (pre-Aug 12, 2026)
3. Seamlessly stacks new live trades (already R1+R3) on top
4. Prints the Year-Over-Year Win Rate and Average PnL table

Because you append live trades daily, this command continuously updates and blends your 7.5-year history with fresh live production data — giving a constantly live strategy view.

---

## 🛡️ EMERGENCY RECOVERY

If `output/trades_dynamic_threshold.csv` ever becomes corrupted, instantly restore the locked baseline:
```bash
git checkout -- output/trades_dynamic_threshold_CLEAN_REFERENCE_20260812.csv
```

Then copy it over and re-append your live trades from where they left off.

---

## ⚠️ (R&D ONLY) — REBUILDING HISTORICAL ML CACHES

> **Do not run this in production.** This is a full 7.5-year walk-forward rebuild for research only.

If a researcher needs to completely regenerate the walk-forward ML prediction scores from 2019–2026:
```bash
cd historical_models/
chmod +x rebuild_historical_caches.sh
./rebuild_historical_caches.sh
```

The script is hard-coded to `REMOVE_EXTREME_TRAINING_LOSSES=False` so it **perfectly mirrors** the live engine's No-Noise architecture.

---

## 🏛️ ARCHITECTURE SUMMARY

```
predict_today.py          ← Live daily predictions (R1+R3 No-Noise)
run_master_backtest.py    ← Backtest verification against golden targets
historical_models/
  dynamic_threshold.py    ← Base walk-forward model (default: r1_r3 strategy)
  rebuild_historical_caches.sh  ← R&D only full rebuild
data/
  markets_pnl0325.csv                                ← APPEND ONLY. Never overwrite.
  f11_intraday_features_all.csv                      ← APPEND ONLY. Never overwrite.
  yahoo_finance_all_stocks_2015_2026_gap_features.csv ← APPEND ONLY. Never overwrite.
output/
  trades_dynamic_threshold.csv                        ← Live trade log. APPEND ONLY.
  trades_dynamic_threshold_CLEAN_REFERENCE_20260812.csv ← LOCKED. Never edit.
```

---

*Last updated: 2026-08-13 | Architecture: Sniper v3.0 R1+R3 (1x Size) No-Noise*
