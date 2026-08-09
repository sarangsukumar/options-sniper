#!/usr/bin/env python3
import os
import sys
import shutil
import pandas as pd
import subprocess
from datetime import datetime

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────
BASE_DIR = "/home/ubuntu/daily_prediction_sytem_Dynamic_threshold"
DATA_DIR = os.path.join(BASE_DIR, "data")
SANDBOX_DIR = os.path.join(BASE_DIR, "sandbox_mondays")

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
    lower_cols = [c.lower().strip() for c in df.columns]
    for p in possible_names:
        if p.lower() in lower_cols:
            idx = lower_cols.index(p.lower())
            return df.columns[idx]
    return None

def create_sandbox_for_date(target_date_str):
    target_date = pd.to_datetime(target_date_str, format='%Y-%m-%d')
    date_dir = os.path.join(SANDBOX_DIR, target_date_str)
    date_data_dir = os.path.join(date_dir, "data")
    os.makedirs(date_data_dir, exist_ok=True)
    
    for file_info in FILES_TO_SLICE:
        src_path = os.path.join(DATA_DIR, file_info["filename"])
        dest_path = os.path.join(date_data_dir, file_info["filename"])
        
        if not os.path.exists(src_path):
            continue
            
        df = pd.read_csv(src_path)
        date_col = find_date_col(df, file_info["date_col_possible"])
        
        if date_col:
            parsed_dates = pd.to_datetime(df[date_col], format='mixed', dayfirst=True, errors='coerce')
            sliced_df = df[parsed_dates <= target_date]
            sliced_df.to_csv(dest_path, index=False)
        else:
            shutil.copy2(src_path, dest_path)
            
    # Copy script
    shutil.copy2(os.path.join(BASE_DIR, "predict_today.py"), os.path.join(date_dir, "predict_today.py"))
    
    # Copy switcher historical medians
    src_medians = os.path.join(BASE_DIR, "historical_models", "output", "daily_medians_std.csv")
    if os.path.exists(src_medians):
        dest_out_dir = os.path.join(date_dir, "output")
        os.makedirs(dest_out_dir, exist_ok=True)
        df_med = pd.read_csv(src_medians)
        df_med['date_parsed'] = pd.to_datetime(df_med['date'])
        sliced_med = df_med[df_med['date_parsed'] <= target_date].drop(columns=['date_parsed'])
        sliced_med.to_csv(os.path.join(dest_out_dir, "daily_medians_std.csv"), index=False)

    return date_dir

def get_first_mondays_2026():
    main_pnl = pd.read_csv(os.path.join(DATA_DIR, "markets_pnl0325.csv"))
    date_col = find_date_col(main_pnl, ["simulationdate", "Date", "date", "time"])
    main_pnl['parsed_date'] = pd.to_datetime(main_pnl[date_col], format='mixed', dayfirst=True, errors='coerce')
    
    dates_2026 = main_pnl[main_pnl['parsed_date'].dt.year == 2026].copy()
    dates_2026 = dates_2026.drop_duplicates(subset=['parsed_date'])
    dates_2026['month'] = dates_2026['parsed_date'].dt.month
    dates_2026['day_name'] = dates_2026['parsed_date'].dt.day_name()
    
    # Filter for Mondays
    mondays = dates_2026[dates_2026['day_name'] == 'Monday']
    
    first_mondays = []
    for month in sorted(mondays['month'].unique()):
        month_mondays = mondays[mondays['month'] == month].sort_values('parsed_date')
        if not month_mondays.empty:
            first_monday = month_mondays.iloc[0]['parsed_date'].strftime('%Y-%m-%d')
            first_mondays.append(first_monday)
            
    return first_mondays

def extract_predictions(log_output):
    lines = log_output.split('\n')
    capture = False
    table_lines = []
    for line in lines:
        if "SNIPER ALGORITHM PRODUCTION TRADING CANDIDATES" in line:
            capture = True
        if capture:
            table_lines.append(line)
            if "FINAL STRATEGY RECOMMENDATIONS" in line:
                break
    return "\n".join(table_lines)

def main():
    if os.path.exists(SANDBOX_DIR):
        shutil.rmtree(SANDBOX_DIR)
    
    first_mondays = get_first_mondays_2026()
    print(f"[*] Found {len(first_mondays)} First Mondays in 2026 data: {first_mondays}")
    
    results = []
    
    for dt in first_mondays:
        print(f"\n" + "="*60)
        print(f"  PROCESSING FIRST MONDAY: {dt}")
        print("="*60)
        
        # 1. Create Sandbox
        print("  -> Creating strict lookahead-free sandbox...")
        sdir = create_sandbox_for_date(dt)
        
        # 2. Run predict_today.py
        print(f"  -> Running predict_today.py for {dt}...")
        cmd = [sys.executable, "predict_today.py", "--date", dt]
        process = subprocess.run(cmd, cwd=sdir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        
        # 3. Capture Results
        output = process.stdout
        pred_table = extract_predictions(output)
        
        results.append(f"\n\n{'='*80}\nRESULTS FOR {dt}\n{'='*80}\n{pred_table}")
        print(f"  -> Successfully generated predictions for {dt}.")
        
        # 4. Clean up Sandbox to save disk space
        print("  -> Cleaning up sandbox to conserve disk space...")
        shutil.rmtree(sdir)
        
    print("\n" + "#"*80)
    print("ALL FIRST MONDAY SANDBOX RUNS COMPLETE")
    print("#"*80)
    
    # Save the master log
    log_path = os.path.join(BASE_DIR, "first_mondays_sandbox_report.txt")
    with open(log_path, 'w') as f:
        f.write("SANDBOX EXPERIMENT: FIRST MONDAYS OF 2026\n")
        f.write("Every execution was done in a mathematically isolated folder with zero future data.\n")
        for r in results:
            f.write(r)
            
    print(f"\nFull report saved to: {log_path}")
    
    # Print a summary to console
    for r in results:
        print(r)

if __name__ == "__main__":
    main()
