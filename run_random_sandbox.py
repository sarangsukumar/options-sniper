#!/usr/bin/env python3
import os
import sys
import shutil
import pandas as pd
import subprocess
import random

BASE_DIR = "/home/ubuntu/daily_prediction_sytem_Dynamic_threshold"
DATA_DIR = os.path.join(BASE_DIR, "data")
SANDBOX_DIR = os.path.join(BASE_DIR, "sandbox_random")

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
    },
    {
        "filename": "masterfile.csv",
        "date_col_possible": [] # Will just copy it over
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
            
        if len(file_info["date_col_possible"]) > 0:
            df = pd.read_csv(src_path)
            date_col = find_date_col(df, file_info["date_col_possible"])
            if date_col:
                parsed_dates = pd.to_datetime(df[date_col], format='mixed', dayfirst=True, errors='coerce')
                sliced_df = df[parsed_dates <= target_date]
                sliced_df.to_csv(dest_path, index=False)
            else:
                shutil.copy2(src_path, dest_path)
        else:
            # Just copy the file directly (e.g. masterfile.csv)
            shutil.copy2(src_path, dest_path)
            
    # Copy scripts
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

def get_random_dates_2026(n=4):
    main_pnl = pd.read_csv(os.path.join(DATA_DIR, "markets_pnl0325.csv"))
    date_col = find_date_col(main_pnl, ["simulationdate", "Date", "date", "time"])
    main_pnl['parsed_date'] = pd.to_datetime(main_pnl[date_col], format='mixed', dayfirst=True, errors='coerce')
    
    dates_2026 = main_pnl[main_pnl['parsed_date'].dt.year == 2026].copy()
    
    # Let's pick dates that are actually in the cache to ensure we can match them
    import pickle
    cache_path = os.path.join(BASE_DIR, "historical_models", "output", "wf_predictions_cache_ensemble_da_standard_dl_3.0_nf.pkl")
    with open(cache_path, 'rb') as f:
        cache = pickle.load(f)
        
    valid_dates = [ts for ts in cache.keys() if ts.year == 2026]
    valid_dates_str = [ts.strftime('%Y-%m-%d') for ts in valid_dates]
    
    random.seed(42) # Reproducible
    selected_dates = random.sample(valid_dates_str, n)
    return selected_dates

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
        
    random_dates = get_random_dates_2026(4)
    print(f"[*] Selected 4 random dates from 2026 for testing with masterfile: {random_dates}")
    
    results = []
    for dt in random_dates:
        print(f"\n============================================================\n  PROCESSING DATE: {dt}\n============================================================")
        sdir = create_sandbox_for_date(dt)
        cmd = [sys.executable, "predict_today.py", "--date", dt]
        process = subprocess.run(cmd, cwd=sdir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        pred_table = extract_predictions(process.stdout)
        results.append(f"\n\n{'='*80}\nRESULTS FOR {dt}\n{'='*80}\n{pred_table}")
        shutil.rmtree(sdir)
        
    log_path = os.path.join(BASE_DIR, "random_sandbox_report.txt")
    with open(log_path, 'w') as f:
        f.write("SANDBOX EXPERIMENT: 4 RANDOM DATES WITH MASTERFILE\n")
        for r in results:
            f.write(r)
            
    print(f"\nFull report saved to: {log_path}")

if __name__ == "__main__":
    main()
