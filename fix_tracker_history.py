import pandas as pd
import numpy as np

tracker_path = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/output/trades_dynamic_threshold.csv'
df = pd.read_csv(tracker_path)

# Ensure no duplicate backfills exist
df = df[df['date'] <= '2026-08-12']

# 1. Backfill the EXACT trades that would have passed the >1800 threshold barrier.
# This accurately replicates the Ghost Baseline that drives the state machine.
# Format: date, day, stock, pred_pnl, actual_pnl, threshold_used
missing_trades = [
    # Aug 17 (Passed the ~1820 threshold)
    {'date': '2026-08-17', 'day': 'Monday', 'stock': 'ALKEM', 'pred_pnl': 2001.0, 'actual_pnl': 487.5, 'threshold_used': 1800.0},
    {'date': '2026-08-17', 'day': 'Monday', 'stock': 'ABCAPITAL', 'pred_pnl': 2106.0, 'actual_pnl': 1195.0, 'threshold_used': 1800.0},
    
    # Aug 18
    {'date': '2026-08-18', 'day': 'Tuesday', 'stock': 'IDEA', 'pred_pnl': 3141.0, 'actual_pnl': 1229.5, 'threshold_used': 1800.0},
    {'date': '2026-08-18', 'day': 'Tuesday', 'stock': 'INDIGO', 'pred_pnl': 2239.0, 'actual_pnl': -3425.0, 'threshold_used': 1800.0},
    
    # Aug 19
    {'date': '2026-08-19', 'day': 'Wednesday', 'stock': 'NATIONALUM', 'pred_pnl': 2401.0, 'actual_pnl': 16581.25, 'threshold_used': 1800.0},
    
    # Aug 25
    # IDEA was predicted at 2182. Real PnL in markets_pnl0325 is missing/0.0
    {'date': '2026-08-25', 'day': 'Tuesday', 'stock': 'IDEA', 'pred_pnl': 2182.0, 'actual_pnl': 0.0, 'threshold_used': 1800.0},
]

# For days with NO passing trades (Aug 13, 14, 20, 21, 24, 26, 27) the historical model logs "NO_TRADES" internally
# and does not append rows to trades_dynamic_threshold.csv, which means daily_pnl = 0.0.
# The state machine code in predict_today handles missing dates correctly by advancing state when it sees rows.

new_df = pd.DataFrame(missing_trades)
df = pd.concat([df, new_df], ignore_index=True)

df.to_csv(tracker_path, index=False)
print(f"✅ Successfully appended {len(missing_trades)} valid ghost trades to the Master Tracker.")
