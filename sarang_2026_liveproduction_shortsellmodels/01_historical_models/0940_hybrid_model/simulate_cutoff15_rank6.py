#!/usr/bin/env python3
"""
simulate_cutoff15_rank6.py
Simulates:
1. System with Cutoff -1.5% WITHOUT replacements (dropping stocks < -1.5%).
2. The specific Replacements taken (Rank 5 & Rank 6 only, model_rank < 7).
3. System with Cutoff -1.5% WITH Replacements (Rank 5 & 6 only).
4. Compared to Original Production (Cutoff -1.0%, no replacements).
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
df_feat = df_feat[df_feat['date_dt'].dt.dayofweek != 0].copy()
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

conn = pymysql.connect(host='localhost', user='root', password='root', database='markets', cursorclass=pymysql.cursors.DictCursor)

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

print("2. Running walkforward simulation...")
years = [2020, 2021, 2022, 2023, 2024, 2025, 2026]

# Data structures to collect trades
trades_base_no_rep = []       # Cutoff -1.5%, No replacements
trades_rep_only = []          # The replacement trades only (Rank 5 & 6)
trades_with_rep = []          # Base + Replacements (Rank 5 & 6)

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
        
        # Check initial top 4 with cutoff -1.5%
        orig_top4 = day_cands.iloc[:4]
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
            
        # Simulate base picks
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
                    'exit_reason': res['exit_reason']
                }
                trades_base_no_rep.append(trade_info)
                trades_with_rep.append(trade_info)
                
        # Now search replacements ONLY if dropped_count > 0 and model_rank < 7 (i.e. Rank 5 and Rank 6 only)
        if dropped_count > 0:
            reps_needed = dropped_count
            reps_found = 0
            # Only examine rank 5 and rank 6 (indices 4 and 5)
            for r_idx in range(4, min(6, len(day_cands))):
                r_cand = day_cands.iloc[r_idx]
                spct = r_cand['stock_pct_940']
                # Must pass Rule 1 with -1.5% cutoff
                if spct < -1.5: continue
                # Must pass Rule 2
                if nifty_ret < -0.5 and spct < -0.5: continue
                
                clean = r_cand['clean_stock']
                ep_db = float(r_cand['short_entry_price'])
                qty = max(1, int(1000000.0 / ep_db)) if ep_db > 0 else 0
                tks = get_ticks_for_stock(d_str, clean)
                res = simulate_s1(tks, qty)
                if res:
                    rep_info = {
                        'year': test_year, 'date': d_str, 'stock': clean, 'model_rank': r_idx + 1,
                        'is_replacement': True, 'net_pnl': res['net_pnl'], 'ret_pct': res['ret_pct'],
                        'exit_reason': res['exit_reason']
                    }
                    trades_rep_only.append(rep_info)
                    trades_with_rep.append(rep_info)
                    reps_found += 1
                    if reps_found == reps_needed:
                        break

conn.close()

df_base = pd.DataFrame(trades_base_no_rep)
df_rep = pd.DataFrame(trades_rep_only)
df_all = pd.DataFrame(trades_with_rep)

# Load original production trades (cutoff -1.0%, no replacements)
df_orig = pd.read_csv('/home/ubuntu/live_production0942_model/walkforward_0942_trades_10L_2020_2026.csv')

# Yearly summaries
print("\n" + "="*110)
print("📊 1. PERFORMANCE OF MODIFIED REPLACEMENTS ONLY (Rank 5 & 6, Cutoff -1.5%)")
print("="*110)
for y in years:
    sub = df_rep[df_rep['year'] == y]
    cnt = len(sub)
    pnl = sub['net_pnl'].sum() / 100000.0 if cnt > 0 else 0.0
    wr = (sub['net_pnl'] > 0).mean() * 100.0 if cnt > 0 else 0.0
    cnt_r5 = len(sub[sub['model_rank'] == 5])
    cnt_r6 = len(sub[sub['model_rank'] == 6])
    print(f"Year {y}: {cnt:3d} trades (R5: {cnt_r5:2d}, R6: {cnt_r6:2d}) | Net PnL: ₹{pnl:+6.2f}L | Win Rate: {wr:4.1f}%")

tot_rep_cnt = len(df_rep)
tot_rep_pnl = df_rep['net_pnl'].sum() / 100000.0
tot_rep_wr = (df_rep['net_pnl'] > 0).mean() * 100.0
print("-" * 110)
print(f"TOTAL: {tot_rep_cnt} trades | Net PnL: ₹{tot_rep_pnl:+6.2f}L | Win Rate: {tot_rep_wr:4.1f}%")
print("="*110)

print("\n" + "="*110)
print("📊 2. YEAR-BY-YEAR COMPARISON ACROSS ALL 3 CONFIGURATIONS")
print("="*110)
print(f"{'Year':<6} | {'Original Prod (-1.0% No Rep)':<28} | {'New Base (-1.5% No Rep)':<28} | {'New System (-1.5% + Rank 5&6 Rep)':<32}")
print(f"{'':<6} | {'Trades':<7} {'PnL (L)':<10} {'WR%':<8} | {'Trades':<7} {'PnL (L)':<10} {'WR%':<8} | {'Trades':<7} {'PnL (L)':<10} {'WR%':<8} {'vs Orig Diff':<8}")
print("-" * 110)

for y in years:
    o = df_orig[df_orig['year'] == y]
    b = df_base[df_base['year'] == y]
    a = df_all[df_all['year'] == y]
    
    o_cnt, o_pnl, o_wr = len(o), o['s1_net_pnl'].sum()/100000.0, (o['s1_net_pnl']>0).mean()*100.0
    b_cnt, b_pnl, b_wr = len(b), b['net_pnl'].sum()/100000.0, (b['net_pnl']>0).mean()*100.0
    a_cnt, a_pnl, a_wr = len(a), a['net_pnl'].sum()/100000.0, (a['net_pnl']>0).mean()*100.0
    diff = a_pnl - o_pnl
    
    print(f"{y:<6} | {o_cnt:<7} ₹{o_pnl:+6.2f}L   {o_wr:4.1f}%  | {b_cnt:<7} ₹{b_pnl:+6.2f}L   {b_wr:4.1f}%  | {a_cnt:<7} ₹{a_pnl:+6.2f}L   {a_wr:4.1f}%  {diff:+6.2f}L")

print("-" * 110)
tot_o_cnt, tot_o_pnl, tot_o_wr = len(df_orig), df_orig['s1_net_pnl'].sum()/100000.0, (df_orig['s1_net_pnl']>0).mean()*100.0
tot_b_cnt, tot_b_pnl, tot_b_wr = len(df_base), df_base['net_pnl'].sum()/100000.0, (df_base['net_pnl']>0).mean()*100.0
tot_a_cnt, tot_a_pnl, tot_a_wr = len(df_all), df_all['net_pnl'].sum()/100000.0, (df_all['net_pnl']>0).mean()*100.0
tot_diff = tot_a_pnl - tot_o_pnl

print(f"{'TOTAL':<6} | {tot_o_cnt:<7} ₹{tot_o_pnl:+6.2f}L   {tot_o_wr:4.1f}%  | {tot_b_cnt:<7} ₹{tot_b_pnl:+6.2f}L   {tot_b_wr:4.1f}%  | {tot_a_cnt:<7} ₹{tot_a_pnl:+6.2f}L   {tot_a_wr:4.1f}%  {tot_diff:+6.2f}L")
print("="*110)
