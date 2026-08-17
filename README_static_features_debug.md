# Guide to Detecting Static, Constant, and Empty Features

This guide explains how to programmatically detect "static feature smells" (features that are constant, entirely NaN, or case-duplicated) in machine learning pipelines during both **Training** (on historical master datasets) and **Inference** (on daily candidate matrices).

---

## 🚨 Why Static Features Happen (The Pipeline "Smells")

1. **Casing Discrepancies (Case-Sensitivity Mismatches):**
   * **The Smell:** A pipeline stage outputs lowercase features (e.g., `eod_markup_index`), but the model metadata expects mixed-casing (e.g., `EOD_Markup_Index`).
   * **The Bug:** Doing `pd.concat([master_df, df_daily], ignore_index=True)` causes Pandas to append them as two separate columns. The target date rows will have values in the lowercase column but `NaN` in the mixed-casing column. During training or inference, `fillna(0.0)` silently turns these NaNs into static `0.0` values.
2. **Missing Derived Feature Stages:**
   * **The Smell:** Base features are present, but complex derived or relative features are completely missing (`NaN`) for new dates because the post-processing scripts (e.g., sector ratio or rolling calculations) were skipped.
3. **Over-Clipping:**
   * **The Smell:** A feature that should have variance is constant (e.g., `10.0` or `0.0`). 
   * **The Bug:** Clipping bounds (e.g., `np.clip(val, -10.0, 10.0)`) are set too narrow for the ratio, forcing all values to hit the ceiling/floor.

---

## 📊 1. Detection During Training (Historical Dataset Audit)

To find static features in your historical training matrix, check for columns that are entirely NaN, have zero variance, or have only one unique value.

### Python Code for Training Audit
```python
import pandas as pd
import numpy as np

# Load your historical matrix
df = pd.read_csv("stage6_strategy_matrix.csv")

# Filter to the active training year or segment
df_train = df[df['dt_parsed'].str.startswith('2026')].copy()

print(f"Rows: {len(df_train)} | Columns: {len(df_train.columns)}")

constant_cols = []
all_nan_cols = []
near_constant_cols = []

ignore_cols = ['dt_parsed', 'stockname', 'simulationdate', 'pnl', 'y']

for col in df_train.columns:
    if col in ignore_cols:
        continue
        
    col_data = df_train[col]
    
    # 1. Check for 100% NaNs
    if col_data.isna().all():
        all_nan_cols.append(col)
        continue
        
    # 2. Check for unique values (ignoring NaNs)
    unique_vals = col_data.dropna().unique()
    if len(unique_vals) <= 1:
        val = unique_vals[0] if len(unique_vals) == 1 else np.nan
        constant_cols.append((col, val))
        continue
        
    # 3. Check for extremely low variance (near constant)
    var_val = col_data.var(ddof=1)
    if var_val < 1e-6:
        near_constant_cols.append((col, var_val))

print(f"\nFound {len(all_nan_cols)} 100% NaN columns.")
print(f"Found {len(constant_cols)} completely constant columns.")
print(f"Found {len(near_constant_cols)} near-constant columns (variance < 1e-6).")
```

---

## 📆 2. Detection During Inference (Daily Candidate Snapshot Audit)

During daily inference, candidate stocks are scored on a single date.
* **Important Distinction:** Market/Index-level features (e.g., `nifty_rsi_14`, `BSESN_lag1`) will naturally be constant across all stocks for that day. However, **stock-level features** (e.g., `EOD_Markup_Index`, `Tick_Trend_Strength`) must have variance across the candidates. If they are constant or NaN, the model is scoring stocks blindly.

### Python Code for Inference Audit
```python
import pandas as pd
import numpy as np

# Load the daily candidates file used for inference (e.g. features_today.csv)
df_today = pd.read_csv("features_today.csv")

# List of stock-level features that MUST have variance
STOCK_FEATURES = [
    'EOD_Markup_Index', 'Opening_Drive_Ratio', 'Tick_Trend_Strength', 
    'Intraday_Momentum_Score', 'Intraday_Volatility_Ratio', 'Gap_Fade_Probability',
    'Rolling_Win_Loss_Ratio_20d', 'Rolling_Sharpe_20d', 'Historical_Volatility_Regime',
    'afternoon_return_alpha', 'morning_return_alpha', 'stock_vs_sector_momentum_divergence', 
    'eod_to_lod_range_position', 'gap_pct_to_intraday_range_ratio'
]

print("--- DAILY INFERENCE FEATURE SMELL AUDIT ---")
for feat in STOCK_FEATURES:
    if feat not in df_today.columns:
        print(f"❌ {feat:<35} | MISSING from daily inference file!")
        continue
        
    col_data = df_today[feat]
    nan_pct = col_data.isna().mean() * 100.0
    unique_cnt = col_data.nunique(dropna=True)
    var_val = col_data.var() if unique_cnt > 1 else 0.0
    
    if nan_pct == 100.0:
        print(f"❌ {feat:<35} | 100% NaN! (Silently filled with 0.0)")
    elif unique_cnt <= 1:
        print(f"⚠️ {feat:<35} | STATIC (Unique values: {unique_cnt}, Value: {col_data.iloc[0]})")
    else:
        print(f"✅ {feat:<35} | OK (Unique values: {unique_cnt}, Var: {var_val:.6f})")
```

---

## 🔍 3. How to Audit and Fix Case-Sensitivity Mismatches

To verify if your master matrix contains duplicate columns due to casing issues:

```python
import pandas as pd

df = pd.read_csv("stage6_strategy_matrix.csv", nrows=5)
lowered_cols = [c.lower() for c in df.columns]
duplicates = set([c for c in lowered_cols if lowered_cols.count(c) > 1])

if duplicates:
    print(f"⚠️ Found {len(duplicates)} case-duplicate columns!")
    print(list(duplicates)[:10]) # Print first 10 duplicates
else:
    print("✅ No casing duplicates found.")
```

### The Fix
To prevent this when merging daily inference features into the master matrix, **case-align the daily DataFrame** with the master DataFrame's column mapping before doing `pd.concat`:

```python
# Align column casing of df_daily with master_df
col_map = {c.lower(): c for c in master_df.columns}
df_daily = df_daily.rename(columns=lambda c: col_map.get(c.lower(), c))

# Safely concatenate
master_df = pd.concat([master_df, df_daily], ignore_index=True)
```
