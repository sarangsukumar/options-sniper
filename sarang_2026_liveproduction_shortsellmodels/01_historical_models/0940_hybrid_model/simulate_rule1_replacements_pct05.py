#!/usr/bin/env python3
"""
simulate_rule1_replacements_pct05.py
Simulates:
1. System with Rule 1 Cutoff -1.5% WITHOUT replacements.
2. The specific Replacements: Rank 5 & 6 ONLY where stock_pct_940 >= -0.5%.
3. System with Cutoff -1.5% + Replacements (Rank 5 & 6 where stock_pct_940 >= -0.5%).
4. Original Production (Cutoff -1.0%, no replacements) updated through Oct 23, 2026.
"""
import os, sys, math, time, warnings
import pandas as pd
import numpy as np
import lightgbm as lgb
import pyarrow.parquet as pq
import pymysql

warnings.filterwarnings('ignore')

HIST_DATASET = '/home/ubuntu/sarang_verified_shorsellalgo_0940/data/0940_hybrid_dataset_from_scrapdata.csv'
PARQUET_TICKS = '/home/ubuntu/trading2026/sarang_verified_shorsellalgo_0940/data/ticks_0940_cache.parquet'
PARQUET_NIFTY = '/home/ubuntu/trading2026/sarang_verified_shorsellalgo_0940/data/nifty50_ticks_cache.parquet'

PURE_DB_FEATURES = [
    'gap_0907_pct', 'gap_fade_0907_to_940_pct',
    'prev_intraday_vwap_gap', 'prev_intraday_return', 'prev_intraday_roc_last_hour',
    'morn_range_pct', 'rejection_wick',
    'ret_0940_vs_prev_close', 'crash_dip_bounce_risk', 'dip_zone_flag', 'rebound_interaction',
    'bear_mom_acceleration'
]

def get_taxes(qty, sell_price, buy_price):
    if qty <= 0 or sell_price <= 0 or buy_price <= 0:
        return 0.0
    sell_value = qty * sell_price
    buy_value = qty * buy_price
    turnover = sell_value + buy_value
    brokerage = 40.0
    stt = math.ceil(sell_value * 0.00025)
    txn = turnover * 0.0000322
    sebi = turnover * 0.000001
    stamp = round(buy_value * 0.00003)
    gst = (brokerage + txn + sebi) * 0.18
    return round(brokerage + stt + txn + sebi + stamp + gst, 2)

def simulate_s1(ticks, total_qty):
    valid_ticks = [t for t in ticks if t.get('price') is not None and float(t.get('price') or 0) > 0]
    if not valid_ticks or total_qty <= 0:
        return None
    ep = float(valid_ticks[0]['price'])
    sl_price = round(ep * 1.0225, 2)
    exit_p = None
    exit_reason = None
    
    for t in valid_ticks:
        tm = str(t['time']).split()[-1]
        p = float(t['price'])
        h = float(t.get('high') if t.get('high') is not None and float(t.get('high') or 0) > 0 else p)
        if h >= sl_price:
            exit_p = sl_price
            exit_reason = 'STOP_LOSS'
            break
        if tm >= '14:45:00':
            exit_p = p
            exit_reason = 'TIME_EXIT'
            break
            
    if exit_p is None:
        exit_p = float(valid_ticks[-1]['price'])
        exit_reason = 'EOD_FALLBACK'
        
    gross = round((ep - exit_p) * total_qty, 2)
    taxes = get_taxes(total_qty, ep, exit_p)
    net = round(gross - taxes, 2)
    ret_pct = round(((ep - exit_p) / ep) * 100.0, 2)
    return {
        'entry_price': ep,
        'exit_price': exit_p,
        'exit_reason': exit_reason,
        'gross_pnl': gross,
        'charges': taxes,
        'net_pnl': net,
        'ret_pct': ret_pct
    }

print("1. Loading datasets and caches...")
df_feat = pd.read_csv(HIST_DATASET, low_memory=False)
df_feat['clean_stock'] = df_feat['clean_stock'].astype(str).str.strip().str.upper()
df_feat['date_dt'] = pd.to_datetime(df_feat['date_str'])
df_feat['year'] = df_feat['date_dt'].dt.year
df_feat = df_feat[df_feat['date_dt'].dt.dayofweek != 0].copy()  # Exclude Mondays
df_feat['short_entry_price'] = pd.to_numeric(df_feat['short_entry_price'], errors='coerce').fillna(0.0)
df_feat = df_feat[df_feat['short_entry_price'] >= 30.0].copy()

df_feat['gap_0907_pct'] = pd.to_numeric(df_feat['gap_0907_pct'], errors='coerce').fillna(0.0)
df_feat['gap_fade_0907_to_940_pct'] = pd.to_numeric(df_feat['gap_fade_0907_to_940_pct'], errors='coerce').fillna(0.0)
df_feat['prev_intraday_return'] = pd.to_numeric(df_feat['prev_intraday_return'], errors='coerce').fillna(0.0)

df_feat['ret_0940_vs_prev_close'] = ((1.0 + df_feat['gap_0907_pct']/100.0) * (1.0 + df_feat['gap_fade_0907_to_940_pct']/100.0) - 1.0) * 100.0
df_feat['crash_dip_bounce_risk'] = np.where((df_feat['prev_intraday_return'] < -2.5) & (df_feat['ret_0940_vs_prev_close'] < 0.0), 1.0, 0.0)
df_feat['dip_zone_flag'] = np.where((df_feat['ret_0940_vs_prev_close'] >= -2.0) & (df_feat['ret_0940_vs_prev_close'] <= -1.0), 1.0, 0.0)
df_feat['rebound_interaction'] = df_feat['prev_intraday_return'] * df_feat['ret_0940_vs_prev_close']
df_feat['bear_mom_acceleration'] = df_feat['prev_intraday_return'] * df_feat['gap_fade_0907_to_940_pct']

for f in PURE_DB_FEATURES:
    if f not in df_feat.columns: df_feat[f] = 0.0
    df_feat[f] = pd.to_numeric(df_feat[f], errors='coerce').fillna(0.0)

df_feat['short_target'] = pd.to_numeric(df_feat.get('short_pct_return', 0.0), errors='coerce').fillna(0.0)
df_feat['stock_pct_940'] = df_feat['gap_0907_pct'] + df_feat['gap_fade_0907_to_940_pct']

# Load Nifty from parquet and DB
df_nifty = pq.read_table(PARQUET_NIFTY).to_pandas()
nifty_day_map = {}
for d_str, g in df_nifty.groupby('date_str'):
    g_sorted = g.sort_values('time_str')
    open_p = g_sorted.iloc[0]['open']
    t940 = g_sorted[g_sorted['time_str'] >= '09:40:00']
    if len(t940) > 0 and open_p > 0:
        p940 = t940.iloc[0]['close']
        nifty_day_map[d_str] = ((p940 - open_p) / open_p) * 100.0
    else:
        nifty_day_map[d_str] = 0.0

conn = pymysql.connect(host='localhost', user='root', password='root', database='markets', cursorclass=pymysql.cursors.DictCursor)

# Add missing Nifty dates directly from scrapdata
with conn.cursor() as cur:
    cur.execute("SELECT date, time, open, close FROM scrapdata WHERE stockname = 'NIFTY 50' AND date >= '2026-10-12' ORDER BY date ASC, time ASC")
    db_nifty_rows = cur.fetchall()
if db_nifty_rows:
    df_db_nifty = pd.DataFrame(db_nifty_rows)
    df_db_nifty['date_str'] = df_db_nifty['date'].astype(str)
    df_db_nifty['time_str'] = pd.to_datetime(df_db_nifty['time']).dt.strftime('%H:%M:%S')
    for d_str, g in df_db_nifty.groupby('date_str'):
        g_sorted = g.sort_values('time_str')
        open_p = float(g_sorted.iloc[0]['open'])
        t940 = g_sorted[g_sorted['time_str'] >= '09:40:00']
        if len(t940) > 0 and open_p > 0:
            p940 = float(t940.iloc[0]['close'])
            nifty_day_map[d_str] = ((p940 - open_p) / open_p) * 100.0

ticks_table = pq.read_table(PARQUET_TICKS, columns=['date_str', 'stock', 'time_str', 'high', 'low', 'close'])
df_ticks = ticks_table.to_pandas()
df_ticks['stock'] = df_ticks['stock'].astype(str).str.strip().str.upper()
df_ticks['date_str'] = df_ticks['date_str'].astype(str)
ticks_dict = {}
for (d_str, stk), g in df_ticks.groupby(['date_str', 'stock']):
    g_sorted = g.sort_values('time_str')
    ticks_dict[(d_str, stk)] = [
        {'time': f"{d_str} {r['time_str']}", 'price': r['close'], 'high': r['high'], 'low': r['low'], 'close': r['close']}
        for _, r in g_sorted.iterrows()
    ]

def get_ticks_for_stock(d_str, stk):
    if (d_str, stk) in ticks_dict:
        return ticks_dict[(d_str, stk)]
    try:
        with conn.cursor() as cur:
            sql = "SELECT time, close as price, high, low, close FROM scrapdata WHERE date = %s AND stockname = %s AND TIME(time) >= '09:42:00' AND TIME(time) <= '14:45:00' ORDER BY time ASC"
            cur.execute(sql, (d_str, stk))
            rows = cur.fetchall()
            if rows:
                return rows
            sql_fuzzy = "SELECT time, close as price, high, low, close FROM scrapdata WHERE date = %s AND stockname LIKE %s AND TIME(time) >= '09:42:00' AND TIME(time) <= '14:45:00' ORDER BY time ASC"
            cur.execute(sql_fuzzy, (d_str, f"%{stk}%"))
            rows = cur.fetchall()
            return rows
    except Exception as e:
        return []

print("2. Running walkforward simulation across all years (2020-2026)...")
years = [2020, 2021, 2022, 2023, 2024, 2025, 2026]

# Data structures to collect trades
trades_orig_prod = []         # Cutoff -1.0%, No replacements (updated through Oct 23)
trades_base_no_rep = []       # Cutoff -1.5%, No replacements
trades_rep_only = []          # The replacement trades only (Rank 5 & 6, pct >= -0.5%)
trades_with_rep = []          # Base (-1.5%) + Replacements (Rank 5 & 6, pct >= -0.5%)

for test_year in years:
    t0 = time.time()
    df_train = df_feat[df_feat['year'] < test_year].copy()
    df_test = df_feat[df_feat['year'] == test_year].copy()
    if len(df_train) == 0 or len(df_test) == 0: continue
    
    mod = lgb.LGBMRegressor(n_estimators=100, learning_rate=0.05, max_depth=5, random_state=42, n_jobs=-1, verbose=-1)
    mod.fit(df_train[PURE_DB_FEATURES], df_train['short_target'])
    df_test['pred_return'] = mod.predict(df_test[PURE_DB_FEATURES])
    
    test_dates = sorted(df_test['date_str'].unique())
    for d_str in test_dates:
        day_cands = df_test[df_test['date_str'] == d_str].sort_values('pred_return', ascending=False).reset_index(drop=True)
        nifty_ret = nifty_day_map.get(d_str, 0.0)
        
        orig_top4 = day_cands.iloc[:4]
        
        # --- A. Original Production (-1.0% Cutoff, No Replacements) ---
        for idx, r in orig_top4.iterrows():
            spct = r['stock_pct_940']
            if spct < -1.0: continue
            if nifty_ret < -0.5 and spct < -0.5: continue
            clean = r['clean_stock']
            ep_db = float(r['short_entry_price'])
            qty = max(1, int(1000000.0 / ep_db)) if ep_db > 0 else 0
            tks = get_ticks_for_stock(d_str, clean)
            res = simulate_s1(tks, qty)
            if res:
                trades_orig_prod.append({
                    'year': test_year, 'date': d_str, 'stock': clean, 'model_rank': idx + 1,
                    'is_replacement': False, 'net_pnl': res['net_pnl'], 'ret_pct': res['ret_pct'],
                    'exit_reason': res['exit_reason'], 'stock_pct_940': spct
                })
        
        # --- B. Base System with Cutoff -1.5% ---
        day_base_picks = []
        dropped_count = 0
        for idx, r in orig_top4.iterrows():
            spct = r['stock_pct_940']
            # RULE 1: Cutoff -1.5%
            if spct < -1.5:
                dropped_count += 1
                continue
            # RULE 2: Crash Day Protector
            if nifty_ret < -0.5 and spct < -0.5:
                dropped_count += 1
                continue
            day_base_picks.append((idx + 1, r))
            
        for rank_pos, r in day_base_picks:
            clean = r['clean_stock']
            ep_db = float(r['short_entry_price'])
            qty = max(1, int(1000000.0 / ep_db)) if ep_db > 0 else 0
            tks = get_ticks_for_stock(d_str, clean)
            res = simulate_s1(tks, qty)
            if res:
                trade_info = {
                    'year': test_year, 'date': d_str, 'stock': clean, 'model_rank': rank_pos,
                    'is_replacement': False, 'net_pnl': res['net_pnl'], 'ret_pct': res['ret_pct'],
                    'exit_reason': res['exit_reason'], 'stock_pct_940': r['stock_pct_940']
                }
                trades_base_no_rep.append(trade_info)
                trades_with_rep.append(trade_info)
                
        # --- C. Search Replacements: Rank 5 & 6 ONLY where stock_pct_940 >= -0.5% ---
        if dropped_count > 0:
            reps_needed = dropped_count
            reps_found = 0
            for r_idx in range(4, min(6, len(day_cands))):
                r_cand = day_cands.iloc[r_idx]
                spct = r_cand['stock_pct_940']
                
                # CRITICAL USER RULE: Only if 09:40 pct >= -0.5%
                if spct < -0.5:
                    continue
                
                # Must also pass Rule 2 (crash day drop)
                if nifty_ret < -0.5 and spct < -0.5:
                    continue
                
                clean = r_cand['clean_stock']
                ep_db = float(r_cand['short_entry_price'])
                qty = max(1, int(1000000.0 / ep_db)) if ep_db > 0 else 0
                tks = get_ticks_for_stock(d_str, clean)
                res = simulate_s1(tks, qty)
                if res:
                    rep_info = {
                        'year': test_year, 'date': d_str, 'stock': clean, 'model_rank': r_idx + 1,
                        'is_replacement': True, 'net_pnl': res['net_pnl'], 'ret_pct': res['ret_pct'],
                        'exit_reason': res['exit_reason'], 'stock_pct_940': spct
                    }
                    trades_rep_only.append(rep_info)
                    trades_with_rep.append(rep_info)
                    reps_found += 1
                    if reps_found == reps_needed:
                        break

conn.close()

df_orig = pd.DataFrame(trades_orig_prod)
df_base = pd.DataFrame(trades_base_no_rep)
df_rep = pd.DataFrame(trades_rep_only)
df_all = pd.DataFrame(trades_with_rep)

df_orig.to_csv('/home/ubuntu/live_production0942_model/trades_orig_prod_updated_oct23.csv', index=False)
df_base.to_csv('/home/ubuntu/live_production0942_model/trades_base_cutoff15_oct23.csv', index=False)
df_rep.to_csv('/home/ubuntu/live_production0942_model/trades_replacements_rank5_6_pct05_oct23.csv', index=False)
df_all.to_csv('/home/ubuntu/live_production0942_model/trades_system_with_rep_pct05_oct23.csv', index=False)

print("\n" + "="*115)
print("📊 1. PERFORMANCE OF REPLACEMENTS ONLY (Rank 5 & 6, stock_pct_940 >= -0.5%)")
print("="*115)
print(f"{'Year':<6} | {'Trades':<8} | {'Win Rate':<10} | {'Net PnL (₹)':<14} | {'Avg PnL/Tr':<12} | {'Rank 5 Tr (PnL)':<20} | {'Rank 6 Tr (PnL)':<20}")
print("-" * 115)

for y in years:
    sub = df_rep[df_rep['year'] == y]
    cnt = len(sub)
    pnl = sub['net_pnl'].sum() / 100000.0 if cnt > 0 else 0.0
    wr = (sub['net_pnl'] > 0).mean() * 100.0 if cnt > 0 else 0.0
    avg_pnl = sub['net_pnl'].mean() if cnt > 0 else 0.0
    
    sub_r5 = sub[sub['model_rank'] == 5]
    sub_r6 = sub[sub['model_rank'] == 6]
    r5_str = f"{len(sub_r5)} (₹{sub_r5['net_pnl'].sum()/100000.0:+5.2f}L)" if len(sub_r5) > 0 else "0 (₹ 0.00L)"
    r6_str = f"{len(sub_r6)} (₹{sub_r6['net_pnl'].sum()/100000.0:+5.2f}L)" if len(sub_r6) > 0 else "0 (₹ 0.00L)"
    
    print(f"{y:<6} | {cnt:<8} | {wr:6.1f}%    | ₹{pnl:+7.2f} Lakhs | ₹{avg_pnl:+7.0f}    | {r5_str:<20} | {r6_str:<20}")

tot_cnt = len(df_rep)
tot_pnl = df_rep['net_pnl'].sum() / 100000.0
tot_wr = (df_rep['net_pnl'] > 0).mean() * 100.0
tot_avg = df_rep['net_pnl'].mean()
sub_r5_all = df_rep[df_rep['model_rank'] == 5]
sub_r6_all = df_rep[df_rep['model_rank'] == 6]
tot_r5_str = f"{len(sub_r5_all)} (₹{sub_r5_all['net_pnl'].sum()/100000.0:+5.2f}L)"
tot_r6_str = f"{len(sub_r6_all)} (₹{sub_r6_all['net_pnl'].sum()/100000.0:+5.2f}L)"

print("-" * 115)
print(f"{'TOTAL':<6} | {tot_cnt:<8} | {tot_wr:6.1f}%    | ₹{tot_pnl:+7.2f} Lakhs | ₹{tot_avg:+7.0f}    | {tot_r5_str:<20} | {tot_r6_str:<20}")
print("="*115)

print("\n" + "="*125)
print("📊 2. YEAR-BY-YEAR COMPARISON: ORIGINAL PRODUCTION vs NEW BASE (-1.5%) vs NEW SYSTEM WITH REPLACEMENTS")
print("="*125)
print(f"{'Year':<6} | {'Original Prod (-1.0% No Rep)':<30} | {'Base System (-1.5% No Rep)':<30} | {'New System (-1.5% + Rank 5&6 >= -0.5%)':<35} | {'Diff vs Orig':<12}")
print(f"{'':<6} | {'Trades':<7} {'PnL (L)':<11} {'WR%':<8} | {'Trades':<7} {'PnL (L)':<11} {'WR%':<8} | {'Trades':<7} {'PnL (L)':<11} {'WR%':<8}       | {'Net Benefit':<12}")
print("-" * 125)

for y in years:
    o = df_orig[df_orig['year'] == y]
    b = df_base[df_base['year'] == y]
    a = df_all[df_all['year'] == y]
    
    o_cnt, o_pnl, o_wr = len(o), o['net_pnl'].sum()/100000.0, (o['net_pnl']>0).mean()*100.0 if len(o)>0 else 0.0
    b_cnt, b_pnl, b_wr = len(b), b['net_pnl'].sum()/100000.0, (b['net_pnl']>0).mean()*100.0 if len(b)>0 else 0.0
    a_cnt, a_pnl, a_wr = len(a), a['net_pnl'].sum()/100000.0, (a['net_pnl']>0).mean()*100.0 if len(a)>0 else 0.0
    diff = a_pnl - o_pnl
    
    print(f"{y:<6} | {o_cnt:<7} ₹{o_pnl:+7.2f}L   {o_wr:5.1f}%  | {b_cnt:<7} ₹{b_pnl:+7.2f}L   {b_wr:5.1f}%  | {a_cnt:<7} ₹{a_pnl:+7.2f}L   {a_wr:5.1f}%        | {diff:+7.2f}L")

print("-" * 125)
tot_o_cnt, tot_o_pnl, tot_o_wr = len(df_orig), df_orig['net_pnl'].sum()/100000.0, (df_orig['net_pnl']>0).mean()*100.0
tot_b_cnt, tot_b_pnl, tot_b_wr = len(df_base), df_base['net_pnl'].sum()/100000.0, (df_base['net_pnl']>0).mean()*100.0
tot_a_cnt, tot_a_pnl, tot_a_wr = len(df_all), df_all['net_pnl'].sum()/100000.0, (df_all['net_pnl']>0).mean()*100.0
tot_diff = tot_a_pnl - tot_o_pnl

print(f"{'TOTAL':<6} | {tot_o_cnt:<7} ₹{tot_o_pnl:+7.2f}L   {tot_o_wr:5.1f}%  | {tot_b_cnt:<7} ₹{tot_b_pnl:+7.2f}L   {tot_b_wr:5.1f}%  | {tot_a_cnt:<7} ₹{tot_a_pnl:+7.2f}L   {tot_a_wr:5.1f}%        | {tot_diff:+7.2f}L")
print("="*125)
