#!/usr/bin/env python3
"""
audit_filter_breakdown.py
Detailed breakdown of Rule 1, Rule 2, and Replacement performance year-by-year
for the live production 0942 model (2020-2026).
"""
import os, sys, math, warnings
from datetime import datetime
import pandas as pd
import numpy as np
import lightgbm as lgb
import pyarrow.parquet as pq

warnings.filterwarnings('ignore')

BASE_DIR = '/home/ubuntu/live_production0942_model'
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
    return brokerage + stt + txn + sebi + stamp + gst

def sim_trade_s1(ticks, ep_db, qty):
    if not ticks or ep_db <= 0 or qty <= 0:
        return None
    sell_price = ep_db
    sl_price = round(sell_price * 1.0225, 2)
    exit_price = None
    exit_reason = None
    
    highs = ticks['high']
    closes = ticks['close']
    times = ticks['time']
    
    for i in range(len(highs)):
        h = highs[i]
        p = closes[i]
        tm = times[i]
        if h >= sl_price:
            exit_price = sl_price
            exit_reason = 'STOP_LOSS_2.25%'
            break
        if tm >= '14:45:00':
            exit_price = p
            exit_reason = 'TIME_EXIT_1445'
            break
    if exit_price is None:
        exit_price = closes[-1] if len(closes) > 0 else sell_price
        exit_reason = 'TIME_EXIT_1445'
    
    gross = (sell_price - exit_price) * qty
    taxes = get_taxes(qty, sell_price, exit_price)
    net = gross - taxes
    return {'sell_price': sell_price, 'exit_price': exit_price, 'net_pnl': net, 'exit_reason': exit_reason}

print("1. Loading Datasets and Parquet Caches...")
df_feat = pd.read_csv(HIST_DATASET, low_memory=False)
df_feat['clean_stock'] = df_feat['clean_stock'].astype(str).str.strip().str.upper()
df_feat['date_dt'] = pd.to_datetime(df_feat['date_str'])
df_feat['year'] = df_feat['date_dt'].dt.year

# Exclude Mondays
df_feat = df_feat[df_feat['date_dt'].dt.dayofweek != 0].copy()

# Universal Penny Stock Liquidity Filter (Price >= Rs 30)
df_feat['short_entry_price'] = pd.to_numeric(df_feat['short_entry_price'], errors='coerce').fillna(0.0)
df_feat = df_feat[df_feat['short_entry_price'] >= 30.0].copy()

# Engineer Rebound Propensity Features & Bear Momentum Acceleration
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
        nifty_ret = ((p940 - open_p) / open_p) * 100.0
        nifty_day_map[d_str] = nifty_ret
    else:
        nifty_day_map[d_str] = 0.0

ticks_table = pq.read_table(PARQUET_TICKS, columns=['date_str', 'stock', 'time_str', 'high', 'close'])
df_ticks = ticks_table.to_pandas()
df_ticks['stock'] = df_ticks['stock'].astype(str).str.strip().str.upper()
df_ticks['date_str'] = df_ticks['date_str'].astype(str)
df_ticks = df_ticks.sort_values(['date_str', 'stock', 'time_str'])

print("   • Fast indexing tick candles...")
# Group by (date_str, stock) and extract high, close, time_str as numpy arrays
ticks_dict = {}
for (d_str, stk), g in df_ticks.groupby(['date_str', 'stock']):
    ticks_dict[(d_str, stk)] = {
        'high': g['high'].values,
        'close': g['close'].values,
        'time': g['time_str'].values
    }

print("2. Running Walkforward and Logging Filter/Replacement Performance...")
years = [2020, 2021, 2022, 2023, 2024, 2025, 2026]

all_records = []

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
        nifty_ret = nifty_day_map.get(d_str, 0.0)
        
        orig_top4_indices = set(range(min(4, len(day_cands))))
        
        passed_indices = []
        rule1_blocked_indices = []
        rule2_blocked_indices = []
        
        for idx, r in day_cands.iterrows():
            spct = r['stock_pct_940']
            if spct < -1.0:
                if idx in orig_top4_indices:
                    rule1_blocked_indices.append(idx)
                continue
            if nifty_ret < -0.5 and spct < -0.5:
                if idx in orig_top4_indices:
                    rule2_blocked_indices.append(idx)
                continue
            
            passed_indices.append(idx)
            if len(passed_indices) == 4:
                break
        
        # Now simulate passed trades
        for p_rank, idx in enumerate(passed_indices, start=1):
            r = day_cands.iloc[idx]
            clean = r['clean_stock']
            ep = float(r['short_entry_price'])
            if ep <= 0: continue
            qty = max(1, int(1000000.0 / ep))
            ticks = ticks_dict.get((d_str, clean), [])
            res = sim_trade_s1(ticks, ep, qty)
            if res:
                trade_type = 'ORIG_TOP4' if idx in orig_top4_indices else 'REPLACEMENT'
                all_records.append({
                    'year': test_year, 'date': d_str, 'stock': clean, 'idx': idx, 'rank': p_rank,
                    'type': trade_type, 'filter_blocked': 'NONE',
                    'net_pnl': res['net_pnl'], 'exit_reason': res['exit_reason']
                })
        
        # Now simulate blocked trades (to see what would have happened if we traded them)
        for idx in rule1_blocked_indices:
            r = day_cands.iloc[idx]
            clean = r['clean_stock']
            ep = float(r['short_entry_price'])
            if ep <= 0: continue
            qty = max(1, int(1000000.0 / ep))
            ticks = ticks_dict.get((d_str, clean), [])
            res = sim_trade_s1(ticks, ep, qty)
            if res:
                all_records.append({
                    'year': test_year, 'date': d_str, 'stock': clean, 'idx': idx, 'rank': idx+1,
                    'type': 'BLOCKED_BY_FILTER', 'filter_blocked': 'RULE_1',
                    'net_pnl': res['net_pnl'], 'exit_reason': res['exit_reason']
                })
                
        for idx in rule2_blocked_indices:
            r = day_cands.iloc[idx]
            clean = r['clean_stock']
            ep = float(r['short_entry_price'])
            if ep <= 0: continue
            qty = max(1, int(1000000.0 / ep))
            ticks = ticks_dict.get((d_str, clean), [])
            res = sim_trade_s1(ticks, ep, qty)
            if res:
                all_records.append({
                    'year': test_year, 'date': d_str, 'stock': clean, 'idx': idx, 'rank': idx+1,
                    'type': 'BLOCKED_BY_FILTER', 'filter_blocked': 'RULE_2',
                    'net_pnl': res['net_pnl'], 'exit_reason': res['exit_reason']
                })

df_res = pd.DataFrame(all_records)
df_res.to_csv(os.path.join(BASE_DIR, 'filter_and_replacement_audit.csv'), index=False)
print("✔ Audit complete! Saved to filter_and_replacement_audit.csv")
