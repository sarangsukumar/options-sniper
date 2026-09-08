import pickle
import os
import pandas as pd
import numpy as np
from datetime import time as dtime

DEST_DIR = '/home/ubuntu/shortsellmodel940v3'
SRC_DIR = '/home/ubuntu/short_sell_simulation_algo/output'

print("1. Loading predictions v3 and ticks cache...")
preds = pd.read_csv(f'{DEST_DIR}/predictions_top10_v3.csv')
top5 = preds[preds['rank'].isin([1, 2, 3, 4, 5])].drop_duplicates(subset=['date', 'stock']).copy()

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

top5['gap_pct'] = top5.apply(lambda r: gap_map.get((r['date'], r['stock']), np.nan), axis=1)

ent_t = dtime(9, 42) # Strictly 09:42 AM Entry Price
ext_t = dtime(14, 45)

def sim_scalp_0942(time_arr, h_arr, l_arr, c_arr, sl_pct=4.0, tp_pct=1.0):
    m = time_arr >= ent_t
    if not m.any(): return None, None
    e_idx = np.argmax(m); ep = c_arr[e_idx] # Entry at 09:42:00
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

def sim_trailing_0942(time_arr, h_arr, l_arr, c_arr, sl_pct=4.0, act_pct=1.4, floor_pct=1.0, gb_pct=0.4):
    m = time_arr >= ent_t
    if not m.any(): return None, None
    e_idx = np.argmax(m); ep = c_arr[e_idx] # Entry at 09:42:00
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

def size_alpha_conviction(rank, is_bleed, is_crash, gap):
    mult = 1.0
    if is_crash: mult += 0.6
    elif is_bleed: mult += 0.3
    if rank in [1, 4]: mult += 0.2
    if pd.notna(gap) and 0.5 <= gap <= 2.5: mult += 0.2
    return mult

pnls = []
dates = []
trades_detail = []

for _, tr in top5.iterrows():
    d = tr['date']
    s = tr['stock']
    k = (d, s)
    if k not in ticks: continue
    t = ticks[k]
    gap = tr['gap_pct']
    
    if d in nifty_map and pd.notna(nifty_map[d]):
        n_ret = nifty_map[d]
    elif d in nifty_941:
        n_ret = nifty_941[d]['nifty_ret_941']
    else:
        n_ret = 0.0
        
    is_bleed = (n_ret <= -0.10)
    is_crash = (n_ret <= -0.25)
    
    mult = size_alpha_conviction(tr['rank'], is_bleed, is_crash, gap)
    qty = tr['qty'] * mult
    time_arr, h_arr, l_arr, c_arr = t['time'], t['high'], t['low'], t['close']
    
    if tr['rank'] == 1:
        ep, xp = sim_trailing_0942(time_arr, h_arr, l_arr, c_arr, sl_pct=5.0, act_pct=2.0, floor_pct=1.5, gb_pct=0.5)
    else:
        if not is_bleed:
            ep, xp = sim_scalp_0942(time_arr, h_arr, l_arr, c_arr, sl_pct=4.0, tp_pct=1.0)
        else:
            ep, xp = sim_trailing_0942(time_arr, h_arr, l_arr, c_arr, sl_pct=4.0, act_pct=1.4, floor_pct=1.0, gb_pct=0.4)
            
    if ep is not None:
        pnl = (ep - xp) * qty - 300.0 * mult
        pnls.append(pnl)
        dates.append(d)
        trades_detail.append({
            'date': d, 'stock': s, 'rank': tr['rank'], 'ep': ep, 'xp': xp, 'qty': qty, 'pnl': pnl
        })

df_res = pd.DataFrame(trades_detail)
df_res.to_csv(f'{DEST_DIR}/simulated_trades_v3.csv', index=False)

s_pnl = pd.Series(pnls)
s_dates = pd.Series(dates)
total = s_pnl.sum()
wins = (s_pnl > 0).sum()
wr = (wins / len(s_pnl)) * 100
df_d = pd.DataFrame({'date': s_dates, 'pnl': s_pnl}).groupby('date').sum()
daily_m = df_d['pnl'].mean()
daily_s = df_d['pnl'].std()
sharpe = (daily_m / daily_s * np.sqrt(252)) if daily_s > 0 else 0
cum = df_d['pnl'].cumsum()
peak = cum.cummax()
max_dd = (cum - peak).min()

print("\n" + "="*115)
print("     CLEAN SCRATCH RE-SIMULATION RESULTS (folder: shortsellmodel940v3)")
print("="*115)
print(f"Total Net PnL:     ₹{total:,.2f} ({total/1e7:.3f} Crore)")
print(f"Total Trades:      {len(pnls):,}")
print(f"Win Rate:          {wr:.2f}%")
print(f"Sharpe Ratio:      {sharpe:.2f}")
print(f"Max Drawdown:      ₹{max_dd:,.2f}")

print("\n" + "="*115)
print("     YEAR-BY-YEAR WALK-FORWARD BREAKDOWN")
print("="*115)

df_yoy = pd.DataFrame({'date': dates, 'pnl': pnls})
df_yoy['year'] = pd.to_datetime(df_yoy['date']).dt.year
y_grp = df_yoy.groupby('year').agg(
    trades=('pnl', 'count'),
    wins=('pnl', lambda x: (x > 0).sum()),
    total_pnl=('pnl', 'sum'),
    avg_pnl=('pnl', 'mean')
).reset_index()
y_grp['win_rate'] = (y_grp['wins'] / y_grp['trades']) * 100

for _, r in y_grp.iterrows():
    print(f"| {int(r['year'])} | {int(r['trades']):<5} trades | Win: {r['win_rate']:.1f}% | Avg: ₹{r['avg_pnl']:>6,.0f} | Total: ₹{r['total_pnl']:>11,.0f} |")

