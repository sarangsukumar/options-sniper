import pickle
import os
import pandas as pd
import numpy as np
from datetime import time as dtime

DEST_DIR = '/home/ubuntu/shortsellmodel940v3'
SRC_DIR = '/home/ubuntu/short_sell_simulation_algo/output'

print("1. Loading predictions v3 and ticks cache...")
preds = pd.read_csv(f'{DEST_DIR}/predictions_top10_v3.csv')

with open(f'{SRC_DIR}/ticks_cache_ranks_1_to_5.pkl', 'rb') as f:
    ticks = pickle.load(f)

# Load Nifty return 940
nifty_file = f'{SRC_DIR}/nifty_ret_940.csv'
if os.path.exists(nifty_file):
    nifty_df = pd.read_csv(nifty_file).set_index('date')
    nifty_map = nifty_df['nifty_ret_940'].to_dict()
else:
    nifty_map = {}

nifty_941 = pd.read_csv(f'{SRC_DIR}/nifty_morning_metrics.csv').set_index('date').to_dict('index')

# Load Gap features
gap_df = pd.read_csv('/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/data/yahoo_finance_all_stocks_2015_2026_gap_features.csv')
gap_df.columns = gap_df.columns.str.strip().str.lower()
gap_map = gap_df.set_index(['date', 'stock'])['gap_pct'].to_dict()

preds['gap_pct'] = preds.apply(lambda r: gap_map.get((r['date'], r['stock']), np.nan), axis=1)

ent_t = dtime(9, 42) # 09:42 AM Entry
ext_t = dtime(14, 45)

def sim_scalp(time_arr, h_arr, l_arr, c_arr, sl_pct=4.0, tp_pct=1.5):
    m = time_arr >= ent_t
    if not m.any(): return None, None
    e_idx = np.argmax(m); ep = c_arr[e_idx]
    xm = time_arr >= ext_t
    x_idx = np.argmax(xm) if xm.any() else len(time_arr) - 1
    
    sl_p = ep * (1.0 + sl_pct / 100.0)
    tp_p = ep * (1.0 - tp_pct / 100.0)
    
    sl_h = np.where(h_arr[e_idx+1:x_idx+1] >= sl_p)[0]
    tp_h = np.where(l_arr[e_idx+1:x_idx+1] <= tp_p)[0]
    f_sl = sl_h[0] if len(sl_h) > 0 else 9999
    f_tp = tp_h[0] if len(tp_h) > 0 else 9999
    
    if f_sl == 9999 and f_tp == 9999: xp = c_arr[x_idx]
    elif f_sl < f_tp: xp = sl_p
    else: xp = tp_p
    return ep, xp

def sim_trailing(time_arr, h_arr, l_arr, c_arr, sl_pct=5.0, act_pct=1.5, floor_pct=1.0, gb_pct=0.3):
    m = time_arr >= ent_t
    if not m.any(): return None, None
    e_idx = np.argmax(m); ep = c_arr[e_idx]
    xm = time_arr >= ext_t
    x_idx = np.argmax(xm) if xm.any() else len(time_arr) - 1
    sl_p = ep * (1.0 + sl_pct / 100.0)
    
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

def run_combo_simulation(allowed_ranks, star_ranks, name):
    subset = preds[preds['rank'].isin(allowed_ranks)].drop_duplicates(subset=['date', 'stock']).copy()
    pnls = []; dates = []; ranks = []
    
    for _, tr in subset.iterrows():
        d = tr['date']; s = tr['stock']; r = tr['rank']; k = (d, s)
        if k not in ticks: continue
        t = ticks[k]; gap = tr['gap_pct']
        
        n_ret = nifty_map.get(d, nifty_941.get(d, {}).get('nifty_ret_941', 0.0))
        is_bleed = (n_ret <= -0.10)
        is_crash = (n_ret <= -0.25)
        
        mult = 1.0
        if is_crash: mult += 0.6
        elif is_bleed: mult += 0.3
        if r in star_ranks: mult += 0.2
        if pd.notna(gap) and 0.5 <= gap <= 2.5: mult += 0.2
        
        qty = tr['qty'] * mult
        time_arr, h_arr, l_arr, c_arr = t['time'], t['high'], t['low'], t['close']
        
        if r == 1:
            ep, xp = sim_trailing(time_arr, h_arr, l_arr, c_arr, sl_pct=5.0, act_pct=1.5, floor_pct=1.0, gb_pct=0.3)
        else:
            if not is_bleed:
                ep, xp = sim_scalp(time_arr, h_arr, l_arr, c_arr, sl_pct=4.0, tp_pct=1.5)
            else:
                ep, xp = sim_trailing(time_arr, h_arr, l_arr, c_arr, sl_pct=4.0, act_pct=1.2, floor_pct=0.8, gb_pct=0.3)
                
        if ep is not None:
            pnl = (ep - xp) * qty - 300.0 * mult
            pnls.append(pnl); dates.append(d); ranks.append(r)
            
    df_eval = pd.DataFrame({'date': dates, 'pnl': pnls, 'rank': ranks})
    df_eval['year'] = pd.to_datetime(df_eval['date']).dt.year
    return df_eval

combos = {
    'Combo 1: Top 1 & Top 4 Only (R1 & R4)': ([1, 4], [1, 4]),
    'Combo 2: Top 2, Top 3 & Top 4 Only (R2 to R4)': ([2, 3, 4], [2, 4]),
    'Combo 3: All Top 5 (R1 to R5)': ([1, 2, 3, 4, 5], [1, 2, 3])
}

all_yoy = {}
summary = []

for c_name, (allowed, star) in combos.items():
    df_c = run_combo_simulation(allowed, star, c_name)
    total_pnl = df_c['pnl'].sum()
    total_trades = len(df_c)
    win_rate = (df_c['pnl'] > 0).mean() * 100
    avg_pnl = df_c['pnl'].mean()
    
    # Yearly breakdown
    yoy = df_c.groupby('year').agg(
        trades=('pnl', 'count'),
        wins=('pnl', lambda x: (x > 0).sum()),
        total_pnl=('pnl', 'sum'),
        avg_pnl=('pnl', 'mean')
    ).reset_index()
    yoy['win_rate'] = (yoy['wins'] / yoy['trades']) * 100
    all_yoy[c_name] = yoy
    
    p26 = yoy[yoy['year'] == 2026]['total_pnl'].values[0] if 2026 in yoy['year'].values else 0
    p26_avg = yoy[yoy['year'] == 2026]['avg_pnl'].values[0] if 2026 in yoy['year'].values else 0
    p26_wr = yoy[yoy['year'] == 2026]['win_rate'].values[0] if 2026 in yoy['year'].values else 0
    
    summary.append({
        'Combo': c_name,
        'Total PnL': total_pnl,
        'Trades': total_trades,
        'Win Rate (%)': win_rate,
        'Overall Avg PnL': avg_pnl,
        '2026 Net PnL': p26,
        '2026 Avg PnL/Trade': p26_avg,
        '2026 Win Rate (%)': p26_wr
    })

print("\n" + "="*115)
print("     OVERALL COMPARISON OF STRATEGY COMBINATIONS (2018–2026)")
print("="*115)
df_sum = pd.DataFrame(summary)
print(df_sum.to_string(index=False))

print("\n" + "="*115)
print("     YEAR-BY-YEAR COMPARISON FOR EACH COMBO")
print("="*115)

years = sorted(all_yoy['Combo 3: All Top 5 (R1 to R5)']['year'].unique())
for y in years:
    print(f"\n--- YEAR {y} ---")
    for c_name, y_df in all_yoy.items():
        row = y_df[y_df['year'] == y]
        if len(row) > 0:
            r = row.iloc[0]
            print(f"  • {c_name:<45} | Trades: {int(r['trades']):<4} | Win: {r['win_rate']:.1f}% | Avg PnL: ₹{r['avg_pnl']:>5,.0f} | Total PnL: ₹{r['total_pnl']:>10,.0f}")

