#!/usr/bin/env python3
"""
audit_percentage_buckets.py
Analyzes the performance of blocked trades across granular buckets between -1.0% and -5.0%+:
- [-1.0% to -1.5%)
- [-1.5% to -2.0%)
- [-2.0% to -2.5%)
- [-2.5% to -3.0%)
- [-3.0% to -4.0%)
- [-4.0% to -5.0%)
- [<-5.0%]

Also tests alternative filter thresholds (-1.0%, -1.5%, -2.0%, -2.5%, -3.0%).
"""
import os, sys, math, time, warnings
import pandas as pd
import numpy as np
import lightgbm as lgb
import pyarrow.parquet as pq

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
df_feat['gap_fade_0907_to_940_pct'] = pd.to_numeric(df_fade := df_feat['gap_fade_0907_to_940_pct'], errors='coerce').fillna(0.0)
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

print("2. Running walkforward to collect all 437 Rule 1 blocked trades...")
years = [2020, 2021, 2022, 2023, 2024, 2025, 2026]
blocked_trades = []

for test_year in years:
    df_train = df_feat[df_feat['year'] < test_year].copy()
    df_test = df_feat[df_feat['year'] == test_year].copy()
    if len(df_train) == 0 or len(df_test) == 0: continue
    
    mod = lgb.LGBMRegressor(n_estimators=100, learning_rate=0.05, max_depth=5, random_state=42, n_jobs=-1, verbose=-1)
    mod.fit(df_train[PURE_DB_FEATURES], df_train['short_target'])
    df_test['pred_return'] = mod.predict(df_test[PURE_DB_FEATURES])
    
    test_dates = sorted(df_test['date_str'].unique())
    for d_str in test_dates:
        day_cands = df_test[df_test['date_str'] == d_str].sort_values('pred_return', ascending=False).reset_index(drop=True)
        orig_top4 = day_cands.iloc[:4]
        
        for idx, r in orig_top4.iterrows():
            spct = r['stock_pct_940']
            if spct < -1.0:
                clean = r['clean_stock']
                ep_db = float(r['short_entry_price'])
                qty = max(1, int(1000000.0 / ep_db)) if ep_db > 0 else 0
                tks = ticks_dict.get((d_str, clean), [])
                res = simulate_s1(tks, qty)
                blocked_trades.append({
                    'year': test_year,
                    'date': d_str,
                    'stock': clean,
                    'orig_rank': idx + 1,
                    'stock_pct_940': spct,
                    'net_pnl': res['net_pnl'] if res else 0.0,
                    'exit_reason': res['exit_reason'] if res else 'NO_DATA',
                    'ret_pct': res['ret_pct'] if res else 0.0
                })

df_b = pd.DataFrame(blocked_trades)
df_b.to_csv('/home/ubuntu/live_production0942_model/rule1_blocked_trades_audited.csv', index=False)

print(f"✔ Audited {len(df_b)} blocked trades.")

# Assign buckets
def assign_bucket(pct):
    if pct >= -1.5:
        return "-1.0% to -1.5%"
    elif pct >= -2.0:
        return "-1.5% to -2.0%"
    elif pct >= -2.5:
        return "-2.0% to -2.5%"
    elif pct >= -3.0:
        return "-2.5% to -3.0%"
    elif pct >= -4.0:
        return "-3.0% to -4.0%"
    elif pct >= -5.0:
        return "-4.0% to -5.0%"
    else:
        return "Fell > -5.0%"

df_b['bucket'] = df_b['stock_pct_940'].apply(assign_bucket)

bucket_order = [
    "-1.0% to -1.5%",
    "-1.5% to -2.0%",
    "-2.0% to -2.5%",
    "-2.5% to -3.0%",
    "-3.0% to -4.0%",
    "-4.0% to -5.0%",
    "Fell > -5.0%"
]

print("\n" + "="*95)
print("📊 PERFORMANCE OF BLOCKED TRADES BY PERCENTAGE DROP BUCKET (2020-2026)")
print("="*95)

summary_rows = []
for bkt in bucket_order:
    sub = df_b[df_b['bucket'] == bkt]
    cnt = len(sub)
    if cnt == 0: continue
    pnl = sub['net_pnl'].sum() / 100000.0
    wr = (sub['net_pnl'] > 0).mean() * 100.0
    sl_rate = (sub['exit_reason'] == 'STOP_LOSS').mean() * 100.0
    avg_trade = sub['net_pnl'].mean()
    pnl_2020 = sub[sub['year'] == 2020]['net_pnl'].sum() / 100000.0
    pnl_post2020 = sub[sub['year'] > 2020]['net_pnl'].sum() / 100000.0
    
    print(f"Bucket: {bkt:16s} | Trades: {cnt:3d} | Net PnL: ₹{pnl:+6.2f}L | WR: {wr:4.1f}% | SL Hit: {sl_rate:4.1f}% | Avg/Trd: ₹{avg_trade:+6.0f} | 2020: ₹{pnl_2020:+5.2f}L | 2021-26: ₹{pnl_post2020:+5.2f}L")

print("="*95)

# Also check cumulative threshold impact:
# What if threshold was -1.0%, -1.5%, -2.0%, -2.5%, -3.0%?
print("\n" + "="*95)
print("🔍 SENSITIVITY TEST: WHAT IF RULE 1 THRESHOLD WAS CHANGED?")
print("="*95)
for thresh in [-1.0, -1.5, -2.0, -2.5, -3.0]:
    # Trades that would be blocked with this threshold:
    sub_blk = df_b[df_b['stock_pct_940'] < thresh]
    # Trades that would NOT be blocked (allowed into portfolio) between -1.0% and thresh:
    sub_allowed = df_b[(df_b['stock_pct_940'] >= thresh) & (df_b['stock_pct_940'] < -1.0)]
    
    pnl_blk = sub_blk['net_pnl'].sum() / 100000.0
    wr_blk = (sub_blk['net_pnl'] > 0).mean() * 100.0 if len(sub_blk) > 0 else 0.0
    
    pnl_all = sub_allowed['net_pnl'].sum() / 100000.0
    wr_all = (sub_allowed['net_pnl'] > 0).mean() * 100.0 if len(sub_allowed) > 0 else 0.0
    
    print(f"Filter at < {thresh:4.1f}% | Blocked: {len(sub_blk):3d} (PnL: ₹{pnl_blk:+6.2f}L, WR: {wr_blk:4.1f}%) | Allowed in (vs -1.0%): {len(sub_allowed):3d} (PnL: ₹{pnl_all:+6.2f}L, WR: {wr_all:4.1f}%)")
print("="*95)
