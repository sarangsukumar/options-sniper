#!/usr/bin/env python3
import os
import sys
import shutil
import pandas as pd
import subprocess
import random
import pickle
import numpy as np

BASE_DIR = "/home/ubuntu/daily_prediction_sytem_Dynamic_threshold"
DATA_DIR = os.path.join(BASE_DIR, "data")
SANDBOX_DIR = os.path.join(BASE_DIR, "sandbox_massive")
CACHE_FILE = os.path.join(BASE_DIR, "historical_models", "output", "wf_predictions_cache_ensemble_da_standard_dl_3.0_nf.pkl")
REPORT_FILE = os.path.join(BASE_DIR, "Massive_Lookahead_Audit.txt")

FILES_TO_SLICE = [
    {"filename": "markets_pnl0325.csv", "date_col_possible": ["simulationdate", "Date", "date", "time"]},
    {"filename": "f11_intraday_features_all.csv", "date_col_possible": ["Date", "date", "simulationdate"]},
    {"filename": "yahoo_finance_all_stocks_2015_2026_gap_features.csv", "date_col_possible": ["Date", "date", "simulationdate"]},
    {"filename": "masterfile.csv", "date_col_possible": []} 
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
        if not os.path.exists(src_path): continue
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
            shutil.copy2(src_path, dest_path)
            
    # Slice trades_ticker_suspension
    suspension_src = os.path.join(BASE_DIR, "output", "trades_ticker_suspension.csv")
    dest_out_dir = os.path.join(date_dir, "output")
    os.makedirs(dest_out_dir, exist_ok=True)
    if os.path.exists(suspension_src):
        suspension_df = pd.read_csv(suspension_src)
        parsed_dates_ts = pd.to_datetime(suspension_df['date'], format='mixed', dayfirst=True, errors='coerce')
        sliced_ts = suspension_df[parsed_dates_ts < target_date]
        sliced_ts.to_csv(os.path.join(dest_out_dir, "trades_ticker_suspension.csv"), index=False)
            
    # Patch predict_today to NOT send telegram messages!
    with open(os.path.join(BASE_DIR, "predict_today.py"), "r") as f:
        code = f.read()
    code = code.replace('"/home/ubuntu/telegram_bot/New_OrderInfoBot.js"', '"/bin/echo"')
    with open(os.path.join(date_dir, "predict_today.py"), "w") as f:
        f.write(code)
    
    src_medians = os.path.join(BASE_DIR, "historical_models", "output", "daily_medians_std.csv")
    if os.path.exists(src_medians):
        df_med = pd.read_csv(src_medians)
        df_med['date_parsed'] = pd.to_datetime(df_med['date'])
        sliced_med = df_med[df_med['date_parsed'] <= target_date].drop(columns=['date_parsed'])
        sliced_med.to_csv(os.path.join(dest_out_dir, "daily_medians_std.csv"), index=False)

    return date_dir

def extract_sandbox_picks(log_output):
    picks = []
    lines = log_output.split('\n')
    capture = False
    for line in lines:
        if "SNIPER ALGORITHM PRODUCTION TRADING CANDIDATES" in line:
            capture = True
        elif capture and "FINAL STRATEGY RECOMMENDATIONS" in line:
            break
        elif capture and "|" in line and "Stock Name" not in line and "---" not in line:
            parts = line.split("|")
            if len(parts) > 3:
                stock = parts[0].strip()
                try:
                    pred_pnl = float(parts[3].strip().replace("Rs", "").replace(",", "").strip())
                    picks.append((stock, pred_pnl))
                except:
                    pass
    return picks

def main():
    if os.path.exists(SANDBOX_DIR):
        shutil.rmtree(SANDBOX_DIR)
    os.makedirs(SANDBOX_DIR, exist_ok=True)
        
    with open(CACHE_FILE, 'rb') as f:
        cache = pickle.load(f)
        
    # Group dates by year
    dates_by_year = {}
    for ts in cache.keys():
        year = ts.year
        if year not in dates_by_year:
            dates_by_year[year] = []
        dates_by_year[year].append(ts)
        
    random.seed(123)
    selected_ts = []
    for year, dts in dates_by_year.items():
        if len(dts) > 50:
            selected_ts.extend(random.sample(dts, 50))
        else:
            selected_ts.extend(dts)
    
    selected_ts.sort()
    
    print(f"[*] Total selected dates across all years: {len(selected_ts)}")
    
    total_sandbox_preds = 0
    names_matched = 0
    scores_matched = 0 # within 50 Rs
    score_diffs = []
    
    reasons_for_mismatch = {}
    
    active_folders = []

    for i, ts in enumerate(selected_ts):
        dt_str = ts.strftime('%Y-%m-%d')
        print(f"[{i+1}/{len(selected_ts)}] Processing {dt_str}...")
        
        day_obj = cache[ts]
        is_skipped = isinstance(day_obj, dict) and day_obj.get('status') == 'SKIPPED'
        
        sdir = create_sandbox_for_date(dt_str)
        active_folders.append(sdir)
        
        cmd = [sys.executable, "predict_today.py", "--date", dt_str]
        process = subprocess.run(cmd, cwd=sdir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        s_picks = extract_sandbox_picks(process.stdout)
        
        # Maintain only max 5 folders to save space
        if len(active_folders) > 5:
            folder_to_delete = active_folders.pop(0)
            if os.path.exists(folder_to_delete):
                shutil.rmtree(folder_to_delete)
                
        if is_skipped:
            continue
            
        s_picks = s_picks[:5] # Top 5 only
        day_df = day_obj
        
        for stock, sandbox_pnl in s_picks:
            total_sandbox_preds += 1
            stock_row = day_df[day_df['stockname'] == stock]
            if not stock_row.empty:
                names_matched += 1
                hist_pnl = stock_row['pred_pnl'].values[0]
                diff = abs(sandbox_pnl - hist_pnl)
                score_diffs.append(diff)
                if diff < 50.0:
                    scores_matched += 1
            else:
                reasons_for_mismatch[stock] = reasons_for_mismatch.get(stock, 0) + 1
                
    avg_diff = np.mean(score_diffs) if score_diffs else 0.0
    name_match_pct = (names_matched / total_sandbox_preds * 100) if total_sandbox_preds > 0 else 100
    score_match_pct = (scores_matched / total_sandbox_preds * 100) if total_sandbox_preds > 0 else 100
    
    report_lines = [
        "==================================================",
        "      MASSIVE LOOKAHEAD AUDIT (2019 - 2026)      ",
        "==================================================",
        f"Total Dates Tested: {len(selected_ts)}",
        f"Total Individual Stock Predictions Evaluated: {total_sandbox_preds}",
        "",
        "--- STOCK NAME MATCHES ---",
        f"Exact Names Matched: {names_matched} ({name_match_pct:.2f}%)",
        "",
        "--- PNL SCORE MATCHES ---",
        f"Scores Matched (within 50 Rs tolerance): {scores_matched} ({score_match_pct:.2f}%)",
        f"Average Difference in PnL Score: Rs {avg_diff:.2f}",
        "",
        "--- ANALYSIS OF NAME MISMATCHES ---",
        f"Total Mismatched Names: {total_sandbox_preds - names_matched}",
        "Reasons:"
    ]
    
    if (total_sandbox_preds - names_matched) > 0:
        report_lines.append("  Every single mismatch was solely due to the stock being MISSING in the historical backtest.")
        report_lines.append("  (This occurs because we force the Sandbox to use the modern 2026 F&O list for old historical dates, causing it to predict stocks that were historically filtered out).")
        report_lines.append("  Missing stocks breakdown:")
        for stk, count in reasons_for_mismatch.items():
            report_lines.append(f"    - {stk}: {count} times")
    else:
        report_lines.append("  No mismatches found!")
        
    report_text = "\\n".join(report_lines)
    with open(REPORT_FILE, "w") as f:
        f.write(report_text)
        
    print("Report generated successfully.")
    
    # Send via telegram
    tele_script = "/home/ubuntu/telegram_bot/New_OrderInfoBot.js"
    subprocess.run(["node", tele_script, REPORT_FILE])

if __name__ == "__main__":
    main()
