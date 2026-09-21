import re

with open('/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/predict_today.py', 'r') as f:
    code = f.read()

# 1. Add the state machine function near the top (after imports)
state_machine_func = """
# ── Dynamic Threshold State Machine ──────────────────────────────────────────
def get_current_dynamic_threshold():
    import pandas as pd
    tracker_path = os.path.join(_THIS_DIR, 'output', 'trades_dynamic_threshold.csv')
    if not os.path.exists(tracker_path):
        return 1800.0
        
    try:
        tracker_df = pd.read_csv(tracker_path)
        daily_pnl = tracker_df.groupby('date')['actual_pnl'].sum().reset_index()
        daily_pnl = daily_pnl.sort_values('date')
        
        current_thr = 1800.0
        consec_win = 0
        consec_loss = 0
        
        for _, row in daily_pnl.iterrows():
            thr_pnl = row['actual_pnl']
            if thr_pnl < 0:
                consec_loss += 1
                consec_win = 0
            elif thr_pnl > 0:
                consec_win += 1
                consec_loss = 0
                
            if consec_loss >= 3:
                current_thr = min(current_thr + 1800.0 * 0.30, 1800.0 * 2.00)
                consec_loss = 0
            elif consec_win >= 5:
                current_thr = max(current_thr - 1800.0 * 0.10, 1800.0 * 0.60)
                consec_win = 0
                
            current_thr = current_thr * (1 - 0.08) + 1800.0 * 0.08
            
        return current_thr
    except Exception as e:
        print(f"Warning: Failed to compute dynamic threshold: {e}")
        return 1800.0
"""

# Insert the function
code = code.replace("def get_stock_sector(symbol):", state_machine_func + "\ndef get_stock_sector(symbol):")

# 2. Modify step 7C to apply the threshold filter
old_7c = """        # ── 7C. Build ranked candidate list (sorted by pred_pnl, ban-filtered) ──
        test_candidates = test_scored.drop_duplicates(subset=['stockname']).sort_values('pred_pnl', ascending=False)
        if banned_today and not test_candidates.empty:
            test_candidates = test_candidates[~test_candidates['stockname'].str.strip().str.upper().isin(banned_today)].copy()
        test_candidates = test_candidates.reset_index(drop=True)"""

new_7c = """        # ── 7C. Build ranked candidate list (sorted by pred_pnl, ban-filtered) ──
        current_thr = get_current_dynamic_threshold()
        log(f"Dynamic Threshold Applied: Rs {current_thr:,.2f}")
        
        # Apply the Dynamic Threshold filter BEFORE ranking
        test_scored_filtered = test_scored[test_scored['pred_pnl'] > current_thr]
        
        test_candidates = test_scored_filtered.drop_duplicates(subset=['stockname']).sort_values('pred_pnl', ascending=False)
        if banned_today and not test_candidates.empty:
            test_candidates = test_candidates[~test_candidates['stockname'].str.strip().str.upper().isin(banned_today)].copy()
        test_candidates = test_candidates.reset_index(drop=True)"""

code = code.replace(old_7c, new_7c)

# 3. Replace the static 1800.0 I added earlier with the real current_thr
code = code.replace("'threshold_used': 1800.0", "'threshold_used': current_thr")

with open('/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/predict_today.py', 'w') as f:
    f.write(code)

print("predict_today.py patched successfully!")
