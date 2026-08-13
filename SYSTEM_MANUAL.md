# 🎯 SNIPER ALGORITHM (v3.0) - MASTER LIVE SERVER MANUAL

This document is the **single source of truth** for anyone deploying, tracking, or updating the live production server. The system has been mathematically locked to trade exactly **Rank 1 and Rank 3** at a strict **1x size** based on the pristine, unfiltered historical baseline.

---

## 📂 1. THE DATA ARCHITECTURE
Both the live prediction engine (`predict_today.py`) and the historical backtest engine (`run_master_backtest.py`) share and rely on the exact same `data/` folder.

### The Golden Rule of Data
Due to a database purge on Aug 5, 2026, recreating historical files from scratch will permanently break the model's accuracy. **You must use the provided data archives.**

### Initial Setup (For Server Admins)
When cloning the repository for the first time, you must unpack the historical data:
```bash
cd data/
tar -xzvf data_input_files_v3.tar.gz
```
This extracts the flawless historical baseline up to August 2026 for `f11_intraday_features_all.csv`, `yahoo_finance_all_stocks_2015_2026_gap_features.csv`, and `markets_pnl0325.csv`.

### Daily Data Updates
As the live server operates, your data pipelines will fetch new daily intraday, gap, and PnL data. 
**CRITICAL:** When your pipelines download new data, you must **APPEND** the new rows to the bottom of the files in the `data/` folder. Do NOT overwrite the files with fresh API pulls, or you will lose the 2015-2026 history!

---

## ⚡ 2. DAILY PREDICTIONS (`predict_today.py`)
This script uses the `data/` folder to generate today's live trades.

```bash
python3 predict_today.py
```
**Automated Logic built into the script:**
* **Bypasses Noise Filters:** Automatically runs on the pure, unaltered baseline.
* **Normal Market (3+ candidates):** Spits out exactly **Rank 1 and Rank 3** at 1x size.
* **Weak Market (1 or 2 candidates):** Automatically defaults to **Rank 1 Only** to protect capital.
* **Dead Market (0 candidates):** Prints `[NO TRADES]`.

---

## 📝 3. UPDATING THE MASTER TRACKER
After `predict_today.py` gives you the daily trades, you must log them.
Take the new output rows generated for today and copy/append them to the very bottom of:
`output/trades_dynamic_threshold.csv`

*(Note: If your file ever corrupts, you can always instantly restore the historical baseline by running `git checkout -- output/trades_dynamic_threshold_CLEAN_REFERENCE_20260812.csv`)*

---

## 📈 4. THE MASTER BACKTESTER (`run_master_backtest.py`)
Because you append live trades daily to `output/trades_dynamic_threshold.csv`, that file acts as the ultimate, growing database of our exact live performance.

To see the up-to-the-minute historical simulation combined with your new live trades, run:
```bash
python3 run_master_backtest.py
```

**How it works:**
1. It reads `output/trades_dynamic_threshold.csv`.
2. It splits the data at `August 12, 2026`.
3. For the old 7.5-year history, it applies the mathematical R1+R3 filter.
4. For the new live data (which is already R1+R3), it seamlessly stacks it on top.
5. It prints the perfectly accurate Year-Over-Year Win Rate and Average PnL table.

---

## ⚠️ 5. (R&D ONLY) REBUILDING HISTORICAL ML CACHES
If a researcher explicitly needs to completely regenerate the raw `.pkl` prediction scores from 2019 to 2026, they must use the dedicated rebuild script:

```bash
cd historical_models/
chmod +x rebuild_historical_caches.sh
./rebuild_historical_caches.sh
```
*(This script has already been hard-coded to `REMOVE_EXTREME_TRAINING_LOSSES=False` so it perfectly mirrors the live engine's "No-Noise" logic).*
