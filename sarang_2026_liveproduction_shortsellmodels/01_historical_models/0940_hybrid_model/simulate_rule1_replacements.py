#!/usr/bin/env python3
"""
simulate_rule1_replacements.py
Detailed simulation and year-by-year performance audit of the 437 Rule 1 replacement trades
in the 09:42 Simple Rebound-Aware Model (2020-2026).
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
OUTPUT_CSV = '/home/ubuntu/live_production0942_model/rule1_replacements_audit.csv'

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

print("1. Loading datasets...")
df_feat = pd.read_csv(HIST_DATASET, low_memory=False)
df_feat['clean_stock'] = df_feat['clean_stock'].astype(str).str.strip().str.upper()
df_feat['date_dt'] = pd.to_datetime(df_feat['date_str'])
df_feat['year'] = df_feat['date_dt'].dt.year

# Exclude Mondays
df_feat = df_feat[df_feat['date_dt'].dt.dayofweek != 0].copy()

# Filter price >= 30
df_feat['short_entry_price'] = pd.to_numeric(df_feat['short_entry_price'], errors='coerce').fillna(0.0)
df_feat = df_feat[df_feat['short_entry_price'] >= 30.0].copy()

# Features
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

print("2. Loading Nifty 50 and Parquet Cache...")
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
print(f"   Indexed {len(ticks_dict):,} cached candle series.")

# Setup MySQL connection pool / cursor
conn = pymysql.connect(host='localhost', user='root', password='root', database='markets', cursorclass=pymysql.cursors.DictCursor)

def get_ticks_for_stock(d_str, stk):
    if (d_str, stk) in ticks_dict:
        return ticks_dict[(d_str, stk)]
    # Query MySQL
    try:
        with conn.cursor() as cur:
            sql = "SELECT time, close as price, high, low, close FROM scrapdata WHERE date = %s AND stockname = %s AND TIME(time) >= '09:42:00' AND TIME(time) <= '14:45:00' ORDER BY time ASC"
            cur.execute(sql, (d_str, stk))
            rows = cur.fetchall()
            if rows:
                return rows
            # Try fuzzy match if exact failed
            sql_fuzzy = "SELECT time, close as price, high, low, close FROM scrapdata WHERE date = %s AND stockname LIKE %s AND TIME(time) >= '09:42:00' AND TIME(time) <= '14:45:00' ORDER BY time ASC"
            cur.execute(sql_fuzzy, (d_str, f"%{stk}%"))
            rows = cur.fetchall()
            return rows
    except Exception as e:
        print(f"DB Error for {d_str} {stk}: {e}")
        return []

print("3. Executing Walkforward Model & Identifying 437 Replacements...")
years = [2020, 2021, 2022, 2023, 2024, 2025, 2026]

replacement_records = []
blocked_records = []

for test_year in years:
    t0 = time.time()
    df_train = df_feat[df_feat['year'] < test_year].copy()
    df_test = df_feat[df_feat['year'] == test_year].copy()
    if len(df_train) == 0 or len(df_test) == 0: continue
    
    mod = lgb.LGBMRegressor(n_estimators=100, learning_rate=0.05, max_depth=5, random_state=42, n_jobs=-1, verbose=-1)
    mod.fit(df_train[PURE_DB_FEATURES], df_train['short_target'])
    df_test['pred_return'] = mod.predict(df_test[PURE_DB_FEATURES])
    
    test_dates = sorted(df_test['date_str'].unique())
    year_replacements = 0
    
    for d_str in test_dates:
        day_cands = df_test[df_test['date_str'] == d_str].sort_values('pred_return', ascending=False).reset_index(drop=True)
        nifty_ret = nifty_day_map.get(d_str, 0.0)
        
        orig_top4 = day_cands.iloc[:4]
        rule1_blocked_indices = []
        for idx, r in orig_top4.iterrows():
            spct = r['stock_pct_940']
            if spct < -1.0:
                rule1_blocked_indices.append(idx)
                
        if not rule1_blocked_indices:
            continue
            
        # Record blocked trades
        for b_idx in rule1_blocked_indices:
            b_row = day_cands.iloc[b_idx]
            clean = b_row['clean_stock']
            ep_db = float(b_row['short_entry_price'])
            qty = max(1, int(1000000.0 / ep_db)) if ep_db > 0 else 0
            tks = get_ticks_for_stock(d_str, clean)
            res = simulate_s1(tks, qty)
            blocked_records.append({
                'year': test_year,
                'date': d_str,
                'stock': clean,
                'orig_rank': b_idx + 1,
                'stock_pct_940': b_row['stock_pct_940'],
                'entry_price': res['entry_price'] if res else ep_db,
                'exit_price': res['exit_price'] if res else None,
                'exit_reason': res['exit_reason'] if res else 'NO_DATA',
                'net_pnl': res['net_pnl'] if res else 0.0,
                'ret_pct': res['ret_pct'] if res else 0.0
            })
            
        # Find exactly len(rule1_blocked_indices) replacements from rank 5 onwards
        needed = len(rule1_blocked_indices)
        found = 0
        for r_idx in range(4, len(day_cands)):
            r_cand = day_cands.iloc[r_idx]
            spct = r_cand['stock_pct_940']
            if spct < -1.0: continue
            if nifty_ret < -0.5 and spct < -0.5: continue
            
            clean = r_cand['clean_stock']
            ep_db = float(r_cand['short_entry_price'])
            qty = max(1, int(1000000.0 / ep_db)) if ep_db > 0 else 0
            tks = get_ticks_for_stock(d_str, clean)
            res = simulate_s1(tks, qty)
            
            replacement_records.append({
                'year': test_year,
                'date': d_str,
                'stock': clean,
                'model_rank': r_idx + 1,
                'stock_pct_940': spct,
                'pred_return': r_cand['pred_return'],
                'entry_price': res['entry_price'] if res else ep_db,
                'exit_price': res['exit_price'] if res else None,
                'exit_reason': res['exit_reason'] if res else 'NO_DATA',
                'net_pnl': res['net_pnl'] if res else 0.0,
                'ret_pct': res['ret_pct'] if res else 0.0,
                'has_tick_data': res is not None
            })
            found += 1
            year_replacements += 1
            if found == needed:
                break
                
    print(f"   Year {test_year}: Simulated {year_replacements} replacements in {time.time()-t0:.1f}s")

conn.close()

df_rep = pd.DataFrame(replacement_records)
df_blk = pd.DataFrame(blocked_records)

df_rep.to_csv(OUTPUT_CSV, index=False)
print(f"\n✔ Done! Total replacements simulated: {len(df_rep)}")
print(f"✔ Replacements with tick data: {df_rep['has_tick_data'].sum()} / {len(df_rep)}")

# Yearly summary
print("\n" + "="*85)
print("📊 PERFORMANCE SUMMARY: 437 RULE 1 REPLACEMENTS vs 437 BLOCKED TRADES")
print("="*85)

rep_summary = df_rep.groupby('year').agg(
    rep_count=('net_pnl', 'count'),
    rep_net_pnl=('net_pnl', 'sum'),
    rep_wins=('net_pnl', lambda x: (x > 0).sum())
).reset_index()
rep_summary['rep_win_rate'] = (rep_summary['rep_wins'] / rep_summary['rep_count']) * 100.0

blk_summary = df_blk.groupby('year').agg(
    blk_count=('net_pnl', 'count'),
    blk_net_pnl=('net_pnl', 'sum'),
    blk_wins=('net_pnl', lambda x: (x > 0).sum())
).reset_index()
blk_summary['blk_win_rate'] = (blk_summary['blk_wins'] / blk_summary['blk_count']) * 100.0

merged = pd.merge(rep_summary, blk_summary, on='year')
merged['rep_net_lakhs'] = merged['rep_net_pnl'] / 100000.0
merged['blk_net_lakhs'] = merged['blk_net_pnl'] / 100000.0
merged['diff_lakhs'] = merged['rep_net_lakhs'] - merged['blk_net_lakhs']

for _, r in merged.iterrows():
    print(f"Year {int(r['year'])}: {int(r['rep_count'])} trades | Rep PnL: ₹{r['rep_net_lakhs']:+6.2f}L ({r['rep_win_rate']:.1f}% WR) vs Blocked PnL: ₹{r['blk_net_lakhs']:+6.2f}L ({r['blk_win_rate']:.1f}% WR) | Diff: ₹{r['diff_lakhs']:+6.2f}L")

total_rep_lakhs = df_rep['net_pnl'].sum() / 100000.0
total_blk_lakhs = df_blk['net_pnl'].sum() / 100000.0
rep_wr = (df_rep['net_pnl'] > 0).mean() * 100.0
blk_wr = (df_blk['net_pnl'] > 0).mean() * 100.0

print("-" * 85)
print(f"TOTAL: {len(df_rep)} trades | Rep PnL: ₹{total_rep_lakhs:+6.2f}L ({rep_wr:.1f}% WR) vs Blocked PnL: ₹{total_blk_lakhs:+6.2f}L ({blk_wr:.1f}% WR) | Diff: ₹{total_rep_lakhs - total_blk_lakhs:+6.2f}L")
print("="*85)
