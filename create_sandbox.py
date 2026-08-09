#!/usr/bin/env python3
import os
import sys
import shutil
import pandas as pd
import random
from datetime import datetime

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────
BASE_DIR = "/home/ubuntu/daily_prediction_sytem_Dynamic_threshold"
DATA_DIR = os.path.join(BASE_DIR, "data")
SANDBOX_DIR = os.path.join(BASE_DIR, "sandbox")

FILES_TO_SLICE = [
    {
        "filename": "markets_pnl0325.csv",
        "date_col_possible": ["simulationdate", "Date", "date", "time"]
    },
    {
        "filename": "f11_intraday_features_all.csv",
        "date_col_possible": ["Date", "date", "simulationdate"]
    },
    {
        "filename": "yahoo_finance_all_stocks_2015_2026_gap_features.csv",
        "date_col_possible": ["Date", "date", "simulationdate"]
    }
]

def find_date_col(df, possible_names):
    # Standardize column names to lower case for checking
    lower_cols = [c.lower().strip() for c in df.columns]
    for p in possible_names:
        if p.lower() in lower_cols:
            idx = lower_cols.index(p.lower())
            return df.columns[idx]
    return None

def create_sandbox_for_date(target_date_str):
    print(f"\n[+] Building sandbox for {target_date_str}...")
    target_date = pd.to_datetime(target_date_str, format='%Y-%m-%d')
    
    # Create directories
    date_dir = os.path.join(SANDBOX_DIR, target_date_str)
    date_data_dir = os.path.join(date_dir, "data")
    os.makedirs(date_data_dir, exist_ok=True)
    
    # 1. Slice and copy data files
    for file_info in FILES_TO_SLICE:
        src_path = os.path.join(DATA_DIR, file_info["filename"])
        dest_path = os.path.join(date_data_dir, file_info["filename"])
        
        if not os.path.exists(src_path):
            print(f"  [!] Missing {file_info['filename']}, skipping.")
            continue
            
        print(f"  -> Slicing {file_info['filename']}...")
        df = pd.read_csv(src_path)
        date_col = find_date_col(df, file_info["date_col_possible"])
        
        if date_col:
            # Parse dates safely
            parsed_dates = pd.to_datetime(df[date_col], format='mixed', dayfirst=True, errors='coerce')
            
            # Slice rule: Keep ALL rows where Date <= target_date
            # This completely removes any future data mathematically.
            sliced_df = df[parsed_dates <= target_date]
            sliced_df.to_csv(dest_path, index=False)
            print(f"     Kept {len(sliced_df)} rows out of {len(df)}.")
        else:
            print(f"  [!] Could not find date column in {file_info['filename']}. Copying as is (might not be time-series).")
            shutil.copy2(src_path, dest_path)
            
    # 2. Copy the predict_today.py script
    src_script = os.path.join(BASE_DIR, "predict_today.py")
    dest_script = os.path.join(date_dir, "predict_today.py")
    shutil.copy2(src_script, dest_script)
    
    # Copy output/daily_medians_std.csv if it exists (for the switcher logic)
    src_medians = os.path.join(BASE_DIR, "historical_models", "output", "daily_medians_std.csv")
    if os.path.exists(src_medians):
        dest_out_dir = os.path.join(date_dir, "output")
        os.makedirs(dest_out_dir, exist_ok=True)
        # also slice this one
        df_med = pd.read_csv(src_medians)
        df_med['date_parsed'] = pd.to_datetime(df_med['date'])
        sliced_med = df_med[df_med['date_parsed'] <= target_date].drop(columns=['date_parsed'])
        sliced_med.to_csv(os.path.join(dest_out_dir, "daily_medians_std.csv"), index=False)
        print("  -> Sliced daily_medians_std.csv")

    print(f"✔ Sandbox created at: {date_dir}")
    return date_dir

def main():
    if os.path.exists(SANDBOX_DIR):
        shutil.rmtree(SANDBOX_DIR)
    os.makedirs(SANDBOX_DIR, exist_ok=True)
    
    # Read the main PnL sheet to find valid 2026 trading dates
    main_pnl = pd.read_csv(os.path.join(DATA_DIR, "markets_pnl0325.csv"))
    date_col = find_date_col(main_pnl, ["simulationdate", "Date", "date", "time"])
    parsed_dates = pd.to_datetime(main_pnl[date_col], format='mixed', dayfirst=True, errors='coerce').dropna()
    dates_2026 = parsed_dates[parsed_dates.dt.year == 2026].dt.strftime('%Y-%m-%d').unique().tolist()
    
    if len(dates_2026) < 2:
        print("[!] Not enough 2026 dates found!")
        return
        
    random.seed(42) # For reproducible random dates
    selected_dates = random.sample(dates_2026, 2)
    
    sandbox_dirs = []
    for dt in selected_dates:
        sdir = create_sandbox_for_date(dt)
        sandbox_dirs.append((dt, sdir))
        
    print("\n" + "="*80)
    print("SANDBOX TEST INSTRUCTIONS:")
    print("="*80)
    for dt, sdir in sandbox_dirs:
        print(f"\nTo test {dt} with absolutely NO access to future data:")
        print(f"  cd {sdir} && python3 predict_today.py --date {dt}")

if __name__ == "__main__":
    main()
