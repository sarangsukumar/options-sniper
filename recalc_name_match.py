import pandas as pd
import pickle
import os

BASE_DIR = "/home/ubuntu/daily_prediction_sytem_Dynamic_threshold"
CACHE_FILE = os.path.join(BASE_DIR, "historical_models", "output", "wf_predictions_cache_ensemble_da_standard_dl_3.0_nf.pkl")

# The 10 random dates we tested
test_dates = ['2019-04-09', '2020-03-18', '2020-04-28', '2020-08-13', '2021-07-15', '2021-10-11', '2022-02-07', '2025-02-04', '2026-02-23', '2026-07-22']

import subprocess
import shutil
from run_decade_sandbox_pdf import create_sandbox_for_date, extract_sandbox_picks

with open(CACHE_FILE, 'rb') as f:
    cache = pickle.load(f)

total_sandbox_stocks = 0
stocks_found_in_backtest = 0

print("Recalculating Stock NAME Match Rate with Suspensions...")

for dt_str in test_dates:
    ts = pd.Timestamp(dt_str)
    day_obj = cache[ts]
    
    if isinstance(day_obj, dict) and day_obj.get('status') == 'SKIPPED':
        continue
        
    sdir = create_sandbox_for_date(dt_str)
    cmd = ["python3", "predict_today.py", "--date", dt_str]
    process = subprocess.run(cmd, cwd=sdir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    s_picks = extract_sandbox_picks(process.stdout)[:5] # Top 5
    shutil.rmtree(sdir)
    
    day_df = day_obj
    
    for stock, _ in s_picks:
        total_sandbox_stocks += 1
        stock_row = day_df[day_df['stockname'] == stock]
        if not stock_row.empty:
            stocks_found_in_backtest += 1
        else:
            print(f"[{dt_str}] MISSING in backtest: {stock}")
            
name_match_rate = (stocks_found_in_backtest / total_sandbox_stocks) * 100 if total_sandbox_stocks > 0 else 100
print(f"\nTotal Top 5 Stocks Predicted by Sandbox: {total_sandbox_stocks}")
print(f"Total found in Historical Backtest: {stocks_found_in_backtest}")
print(f"STOCK NAME EXACT MATCH RATE: {name_match_rate:.2f}%")
