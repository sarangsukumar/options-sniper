import pandas as pd
import pickle
import os

BASE_DIR = "/home/ubuntu/daily_prediction_sytem_Dynamic_threshold"
CACHE_FILE = os.path.join(BASE_DIR, "historical_models", "output", "wf_predictions_cache_ensemble_da_standard_dl_3.0_nf.pkl")
SANDBOX_REPORT = os.path.join(BASE_DIR, "random_sandbox_report.txt")

# Read sandbox report to extract top picks for each date
sandbox_picks = {}
current_date = None

with open(SANDBOX_REPORT, 'r') as f:
    for line in f:
        if "RESULTS FOR" in line:
            current_date = line.strip().split()[-1]
            sandbox_picks[current_date] = []
        elif current_date and "|" in line and "Stock Name" not in line and "---" not in line:
            parts = line.split("|")
            if len(parts) > 3:
                stock = parts[0].strip()
                pred_pnl_str = parts[3].strip().replace("Rs", "").replace(",", "").strip()
                try:
                    pred_pnl = float(pred_pnl_str)
                    sandbox_picks[current_date].append((stock, pred_pnl))
                except:
                    pass

print("Loading historical predictions cache...")
with open(CACHE_FILE, 'rb') as f:
    cache = pickle.load(f)
    
print("="*80)
print("MATCHING SANDBOX PREDICTIONS TO BACKTEST CACHE (Lookahead Bias Check)")
print("="*80)

for dt in sorted(sandbox_picks.keys()):
    print(f"\n[Date: {dt}]")
    dt_ts = pd.Timestamp(dt)
    if dt_ts not in cache:
        print("  -> Date not found in historical cache.")
        continue
        
    day_obj = cache[dt_ts]
    s_picks = sandbox_picks[dt][:5]  # Compare top 5 for brevity
    
    if isinstance(day_obj, dict) and day_obj.get('status') == 'SKIPPED':
        print(f"  -> Backtester SKIPPED this entire day. Reason: {day_obj.get('reason')}")
        print("  -> Sandbox also should have generated NO final trades.")
        continue
        
    day_df = day_obj
    
    for stock, sandbox_pnl in s_picks:
        stock_row = day_df[day_df['stockname'] == stock]
        if not stock_row.empty:
            hist_pnl = stock_row['pred_pnl'].values[0]
            diff = abs(sandbox_pnl - hist_pnl)
            status = "✅ EXACT MATCH" if diff < 5.0 else f"❌ MISMATCH (Diff: {diff:.2f})"
            print(f"  {stock:12} | Sandbox: {sandbox_pnl:8.2f} | Backtest: {hist_pnl:8.2f} | {status}")
        else:
            print(f"  {stock:12} | Sandbox: {sandbox_pnl:8.2f} | Backtest: MISSING")
