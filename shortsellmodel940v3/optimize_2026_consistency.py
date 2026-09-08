import pickle
import os
import pandas as pd
import numpy as np
from datetime import time as dtime

DEST_DIR = '/home/ubuntu/shortsellmodel940v3'
SRC_DIR = '/home/ubuntu/short_sell_simulation_algo/output'

preds = pd.read_csv(f'{DEST_DIR}/predictions_top10_v3.csv')
top5 = preds[preds['rank'].isin([1, 2, 3, 4, 5])].drop_duplicates(subset=['date', 'stock']).copy()

with open(f'{SRC_DIR}/ticks_cache_ranks_1_to_5.pkl', 'rb') as f:
    ticks = pickle.load(f)

# Nifty 940 return
nifty_file = f'{SRC_DIR}/nifty_ret_940.csv'
if os.path.exists(nifty_file):
    nifty_df = pd.read_csv(nifty_file).set_index('date')
    nifty_map = nifty_df['nifty_ret_940'].to_dict()
else:
    nifty_map = {}

nifty_941 = pd.read_csv(f'{SRC_DIR}/nifty_morning_metrics.csv').set_index('date').to_dict('index')

# Gap features
gap_df = pd.read_csv('/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/data/yahoo_finance_all_stocks_2015_2026_gap_features.csv')
gap_df.columns = gap_df.columns.str.strip().str.lower()
gap_map = gap_df.set_index(['date', 'stock'])['gap_pct'].to_dict()

top5['gap_pct'] = top5.apply(lambda r: gap_map.get((r['date'], r['stock']), np.nan), axis=1)

ent_t = dtime(9, 42) # 09:42 AM Entry
ext_t = dtime(14, 45)

def sim_trade(time_arr, h_arr, l_arr, c_arr, sl_pct, act_pct, floor_pct, gb_pct, is_trailing=True):
    m = time_arr >= ent_t
    if not m.any(): return None, None
    e_idx = np.argmax(m); ep = c_arr[e_idx]
    xm = time_arr >= ext_t
    x_idx = np.argmax(xm) if xm.any() else len(time_arr) - 1
    sl_p = ep * (1.0 + sl_pct / 100.0)
    
    if not is_trailing: # Fixed TP
        tp_p = ep * (1.0 - act_pct / 100.0)
        sl_h = np.where(h_arr[e_idx+1:x_idx+1] >= sl_p)[0]
        tp_h = np.where(l_arr[e_idx+1:x_idx+1] <= tp_p)[0]
        f_sl = sl_h[0] if len(sl_h) > 0 else 9999
        f_tp = tp_h[0] if len(tp_h) > 0 else 9999
        if f_sl == 9999 and f_tp == 9999: xp = c_arr[x_idx]
        elif f_sl < f_tp: xp = sl_p
        else: xp = tp_p
        return ep, xp
        
    is_act = False; peak_p = 0.0; trail_p = 0.0; xp = None
    for i in range(e_idx+1, x_idx+1):
        h, l, c = h_arr[i], l_arr[i], c_arr[i]
        cand_p = ((ep - l) / ep) * 100.0
            
        if not is_act:
            if h >= sl_p: xp = sl_p; break
            if cand_p >= act_pct:
                is_act = True; peak_p = cand_p; trail_p = max(floor_pct, peak_p - gb_pct)
        else:
            if cand_p > peak_p:
                peak_p = cand_p; trail_p = max(trail_p, max(floor_pct, peak_p - gb_pct))
            sp = ep * (1.0 - trail_p / 100.0)
            if c >= sp: xp = sp; break
    if xp is None: xp = c_arr[x_idx]
    return ep, xp

def eval_config(r1_act, r1_floor, r1_gb, r25_tp, r25_act, r25_floor, r25_gb, star_ranks):
    pnls = []; dates = []
    for _, tr in top5.iterrows():
        d = tr['date']; s = tr['stock']; k = (d, s)
        if k not in ticks: continue
        t = ticks[k]; gap = tr['gap_pct']
        
        n_ret = nifty_map.get(d, nifty_941.get(d, {}).get('nifty_ret_941', 0.0))
        is_bleed = (n_ret <= -0.10)
        is_crash = (n_ret <= -0.25)
        
        # Sizing
        mult = 1.0
        if is_crash: mult += 0.6
        elif is_bleed: mult += 0.3
        if tr['rank'] in star_ranks: mult += 0.2
        if pd.notna(gap) and 0.5 <= gap <= 2.5: mult += 0.2
        
        qty = tr['qty'] * mult
        time_arr, h_arr, l_arr, c_arr = t['time'], t['high'], t['low'], t['close']
        
        if tr['rank'] == 1:
            ep, xp = sim_trade(time_arr, h_arr, l_arr, c_arr, sl_pct=5.0, act_pct=r1_act, floor_pct=r1_floor, gb_pct=r1_gb, is_trailing=True)
        else:
            if not is_bleed:
                ep, xp = sim_trade(time_arr, h_arr, l_arr, c_arr, sl_pct=4.0, act_pct=r25_tp, floor_pct=0, gb_pct=0, is_trailing=False)
            else:
                ep, xp = sim_trade(time_arr, h_arr, l_arr, c_arr, sl_pct=4.0, act_pct=r25_act, floor_pct=r25_floor, gb_pct=r25_gb, is_trailing=True)
                
        if ep is not None:
            pnl = (ep - xp) * qty - 300.0 * mult
            pnls.append(pnl); dates.append(d)
            
    df_eval = pd.DataFrame({'date': dates, 'pnl': pnls})
    df_eval['year'] = pd.to_datetime(df_eval['date']).dt.year
    
    total_pnl = df_eval['pnl'].sum()
    pnl_2026 = df_eval[df_eval['year'] == 2026]['pnl'].sum()
    pnl_2025 = df_eval[df_eval['year'] == 2025]['pnl'].sum()
    
    # Calculate yearly std dev for consistency
    y_sums = df_eval.groupby('year')['pnl'].sum()
    min_year = y_sums.min()
    
    return total_pnl, pnl_2026, pnl_2025, min_year

print("Running parameter optimization to maximize 2026 PnL & Yearly Consistency...")

results = []
# Grid search over key parameters
for r1_act, r1_floor, r1_gb in [(1.8, 1.2, 0.4), (2.0, 1.5, 0.5), (1.5, 1.0, 0.3)]:
    for r25_tp in [1.0, 1.2, 1.5]:
        for r25_act, r25_floor, r25_gb in [(1.2, 0.8, 0.3), (1.4, 1.0, 0.4), (1.5, 1.0, 0.4)]:
            for star_ranks in [[1, 4], [1, 2], [1, 2, 3]]:
                tot, p26, p25, min_y = eval_config(r1_act, r1_floor, r1_gb, r25_tp, r25_act, r25_floor, r25_gb, star_ranks)
                results.append({
                    'R1_Params': f"Act:{r1_act}/Flr:{r1_floor}",
                    'Normal_TP': f"{r25_tp}%",
                    'Bleed_Params': f"Act:{r25_act}/Flr:{r25_floor}",
                    'Star_Ranks': str(star_ranks),
                    'Total_PnL': tot,
                    'PnL_2026': p26,
                    'PnL_2025': p25,
                    'Min_Year_PnL': min_y
                })

df_res = pd.DataFrame(results).sort_values('PnL_2026', ascending=False)
print("\n" + "="*115)
print("     TOP 10 PARAMETER COMBINATIONS RANKED BY 2026 PnL BOOST")
print("="*115)
print(df_res.head(10).to_string(index=False))

