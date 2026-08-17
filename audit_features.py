import pandas as pd
import numpy as np

def audit_file(filepath, date_col, skip_cols):
    print(f"\n========================================")
    print(f"Auditing: {filepath.split('/')[-1]}")
    
    df = pd.read_csv(filepath)
    print(f"Loaded {len(df)} rows and {len(df.columns)} columns.")

    # Filter to 2026 data if possible
    if date_col in df.columns:
        df_train = df[df[date_col].astype(str).str.startswith('2026-08-17')].copy()
        if len(df_train) == 0:
            df_train = df
    else:
        df_train = df
        
    print(f"Data to audit: {len(df_train)} rows.")

    constant_cols = []
    all_nan_cols = []
    near_constant_cols = []

    for col in df_train.columns:
        if col.lower() in skip_cols: continue
        col_data = df_train[col]
        
        if col_data.isna().all():
            all_nan_cols.append(col)
            continue
            
        unique_vals = col_data.dropna().unique()
        if len(unique_vals) <= 1:
            val = unique_vals[0] if len(unique_vals) == 1 else np.nan
            constant_cols.append((col, val))
            continue
            
        if pd.api.types.is_numeric_dtype(col_data):
            var_val = col_data.var(ddof=1)
            if var_val < 1e-6:
                near_constant_cols.append((col, var_val))

    print(f"\nFound {len(all_nan_cols)} 100% NaN columns.")
    if len(all_nan_cols) > 0: print(f"  -> {all_nan_cols}")
    
    print(f"Found {len(constant_cols)} completely constant columns.")
    if len(constant_cols) > 0: print(f"  -> {constant_cols}")
        
    print(f"Found {len(near_constant_cols)} near-constant columns (variance < 1e-6).")
    if len(near_constant_cols) > 0: print(f"  -> {near_constant_cols}")

    print("\n--- CASING MISMATCH AUDIT ---")
    lowered_cols = [str(c).lower() for c in df.columns]
    duplicates = set([c for c in lowered_cols if lowered_cols.count(c) > 1])

    if duplicates:
        print(f"⚠️ Found {len(duplicates)} case-duplicate columns!")
        print(list(duplicates)[:10])
    else:
        print("✅ No casing duplicates found.")

skip = ['date', 'stock', 'simulationdate', 'pnl', 'y', 'dt_parsed', 'stockname']
audit_file("/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/data/f11_intraday_features_all.csv", "Date", skip)
audit_file("/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/data/yahoo_finance_all_stocks_2015_2026_gap_features.csv", "Date", skip)
