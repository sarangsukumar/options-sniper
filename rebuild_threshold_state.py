import pandas as pd
import numpy as np

DYN_LOSS_DAYS_TRIGGER  = 3
DYN_WIN_DAYS_TRIGGER   = 5
DYN_RAISE_STEP         = 0.30
DYN_LOWER_STEP         = 0.10
DYN_MIN_FACTOR         = 0.60
DYN_MAX_FACTOR         = 2.00
DYN_REVERT_RATE        = 0.08
BASE_THRESHOLD         = 1800.0

def rebuild_threshold():
    # 1. Get Ghost Baseline Daily PnL
    tracker_df = pd.read_csv('/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/output/trades_dynamic_threshold.csv')
    daily_pnl = tracker_df.groupby('date')['actual_pnl'].sum().reset_index()
    daily_pnl = daily_pnl.sort_values('date')
    
    current_thr = BASE_THRESHOLD
    consec_win = 0
    consec_loss = 0
    
    # Simulate state machine over history
    for _, row in daily_pnl.iterrows():
        thr_pnl = row['actual_pnl']
        
        if thr_pnl < 0:
            consec_loss += 1
            consec_win = 0
        elif thr_pnl > 0:
            consec_win += 1
            consec_loss = 0
            
        if consec_loss >= DYN_LOSS_DAYS_TRIGGER:
            current_thr = min(current_thr + BASE_THRESHOLD * DYN_RAISE_STEP, BASE_THRESHOLD * DYN_MAX_FACTOR)
            consec_loss = 0
        elif consec_win >= DYN_WIN_DAYS_TRIGGER:
            current_thr = max(current_thr - BASE_THRESHOLD * DYN_LOWER_STEP, BASE_THRESHOLD * DYN_MIN_FACTOR)
            consec_win = 0
            
        # Simplification: Use static revert rate since we don't have historical volatility_ratio loaded easily here
        # But wait, Option 2 is True historically. Let's see if we can approximate or if static is close enough.
        # For an exact replica, we should use it. Let's just use static for now to see the value.
        current_thr = current_thr * (1 - DYN_REVERT_RATE) + BASE_THRESHOLD * DYN_REVERT_RATE
        
    return current_thr, consec_win, consec_loss

thr, wins, losses = rebuild_threshold()
print(f"Computed Today's Threshold: {thr}")
print(f"Consec Wins: {wins}, Consec Losses: {losses}")
