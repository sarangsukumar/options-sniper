import os
import subprocess
import pandas as pd
from datetime import datetime, timedelta

BASE_DIR = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold'
PREDICT_SCRIPT = os.path.join(BASE_DIR, 'predict_today.py')
TRACKER_CSV = os.path.join(BASE_DIR, 'output', 'trades_dynamic_threshold.csv')
PNL_CSV = os.path.join(BASE_DIR, 'data', 'markets_pnl0325.csv')

dates_to_run = [
    '2026-08-13', '2026-08-14', '2026-08-17', '2026-08-18', '2026-08-19', 
    '2026-08-20', '2026-08-21', '2026-08-24', '2026-08-25', '2026-08-26', '2026-08-27'
]

# 1. Disable Telegram in predict_today.py
with open(PREDICT_SCRIPT, 'r') as f:
    code = f.read()
code = code.replace('subprocess.run(["node", bot_path, tg_msg], check=True, timeout=15)', 'pass # Telegram disabled for backfill')
code = code.replace('subprocess.run(["node", bot_path, tg_msg], check=True, stdout=subprocess.DEVNULL, timeout=15)', 'pass # Telegram disabled for backfill')
with open(PREDICT_SCRIPT, 'w') as f:
    f.write(code)

print("Telegram alerts disabled.")

# 2. Clear tracker from Aug 13 onwards
df_tracker = pd.read_csv(TRACKER_CSV)
df_tracker = df_tracker[df_tracker['date'] <= '2026-08-12']
df_tracker.to_csv(TRACKER_CSV, index=False)
print("Tracker cleared from 2026-08-13 onwards.")

# 3. Load PnL database once
df_pnl = pd.read_csv(PNL_CSV)
df_pnl['parsed_date'] = pd.to_datetime(df_pnl['simulationdate'], format='mixed', dayfirst=True)

# 4. Loop and run
for d in dates_to_run:
    print(f"\n--- Processing {d} ---")
    
    # Run predict_today.py
    subprocess.run(['python3', PREDICT_SCRIPT, '--date', d])
    
    # After it runs, it appends ghost trades (if any passed threshold) with actual_pnl=0.0
    # Let's read tracker, find rows for this date, and update actual_pnl from df_pnl
    df_t = pd.read_csv(TRACKER_CSV)
    mask_today = df_t['date'] == d
    
    if df_t[mask_today].empty:
        print(f"No trades appended on {d} (Threshold filter likely blocked them all).")
    else:
        # Update actual_pnl
        for idx, row in df_t[mask_today].iterrows():
            stock = row['stock']
            # Find in PnL db
            match = df_pnl[(df_pnl['parsed_date'] == d) & (df_pnl['stockname'] == stock)]
            if not match.empty:
                real_pnl = match.iloc[0]['pnl']
                df_t.at[idx, 'actual_pnl'] = real_pnl
                print(f"Updated {stock} on {d} to Real PnL: {real_pnl}")
            else:
                print(f"Warning: {stock} on {d} not found in PnL database!")
                
        df_t.to_csv(TRACKER_CSV, index=False)

# 5. Restore Telegram in predict_today.py
with open(PREDICT_SCRIPT, 'r') as f:
    code = f.read()
code = code.replace('pass # Telegram disabled for backfill', 'subprocess.run(["node", bot_path, tg_msg], check=True, timeout=15)')
with open(PREDICT_SCRIPT, 'w') as f:
    f.write(code)

print("\nTelegram alerts restored. Backfill completed.")
