# 🚀 DAILY APPENDING PROTOCOL (STRICTLY NO NOISE FILTER)

This document contains the exact rules for updating the primary model tracker daily.

### 🛑 THE GOLDEN RULE
**NEVER rebuild the entire history!**
The historical baseline (2019 to July 7, 2026) is permanently locked in `output/trades_dynamic_threshold_CLEAN_REFERENCE_20260812.csv`. Because the underlying PnL database lost ~58,000 rows on Aug 5, running a full rebuild will permanently skew historical features.

### 📝 HOW TO APPEND DAILY TRADES
When you run the model today or any day in the future, you must follow these exact steps to bolt the new trades onto the safe historical file:

#### 1. Turn OFF the Noise Filter
Ensure your daily prediction script (`predict_today.py` or `dynamic_threshold.py`) is configured with the **No-Noise** settings:
* `REMOVE_EXTREME_TRAINING_LOSSES = False`
* `NOISE_CLEANING_METHOD = 'none'`

*Why? We proved that running without the Noise Filter most closely replicates the authentic historical structure of the old, un-purged dataset.*

#### 2. Generate Today's Predictions
Run your daily script. It will generate today's predictions (e.g., Aug 12, Aug 13).

#### 3. Append (Do Not Overwrite)
Take **only** the new rows generated for today, and append them directly to the bottom of:
`output/trades_dynamic_threshold.csv`
(And keep `output/trades_dynamic_threshold_CLEAN_REFERENCE_20260812.csv` fully synced so it acts as your ultimate backup).

#### 4. The Recommended Trade Sizing (R1 + R3)
Based on massive historical walk-forward analysis, the absolute safest and most mathematically robust configuration is:
* **Max Trades per Day:** `2`
* **Target Ranks:** Rank 1 and Rank 3 (`R1 + R3`)
* **Trade Sizing:** `1x + 1x` (Strictly 1-lot each, NO Dual Confirmation)

**Why R1 + R3?**
If you cap trades at 2 per day, taking Rank 1 and Rank 3 is the ONLY combination that generated a positive return in *every single year* since 2019. It avoids picking two highly correlated stocks on a bad day. 

*Note: The `predict_today.py` script has already been hard-coded to automatically extract exactly Rank 1 and Rank 3 at 1x size, and the -10% Outlier Filter has been disabled to perfectly match the No-Noise baseline.*

### 🛠️ SCRIPT FOR AUTOMATED APPENDING
If you want to automate this, run a script that does:
1. Load `CLEAN_REFERENCE`
2. Load Today's Output
3. Append Today's rows where `date > max(CLEAN_REFERENCE['date'])`
4. Save over `CLEAN_REFERENCE` and `trades_dynamic_threshold.csv`

---

### ⚠️ HOW TO REBUILD HISTORICAL RESULTS FROM SCRATCH
If a researcher or team member explicitly needs to re-run the entire 7.5-year historical simulation from scratch (for R&D or to regenerate the cache files), follow these steps:

**Warning:** Due to the database purge on Aug 5, 2026, a fresh rebuild will look slightly different than the `CLEAN_REFERENCE` baseline. It is recommended for R&D purposes only, NOT for overwriting production tracking.

**Step 1: Regenerate Base ML Caches & Walk-Forward**
```bash
cd historical_models/
chmod +x rebuild_historical_caches.sh
./rebuild_historical_caches.sh
```
*(This rebuilds the raw `.pkl` prediction scores for all frequencies and processes them through the walk-forward logic. The script has been hard-coded to `REMOVE_EXTREME_TRAINING_LOSSES=False` to perfectly match your baseline).*
