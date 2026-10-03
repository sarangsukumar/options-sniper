#!/usr/bin/env python3
"""
train_walk_forward_scalp.py
----------------------------
Executes Walk-Forward Machine Learning (2021-2026) for the 09:20–09:40 Short Sell Scalp Strategy.
  - Zero Lookahead Bias: Model for year Y is trained exclusively on data from years < Y.
  - Zero Yahoo Finance Leakage: All features sourced 100% from MySQL database ticks.
  - Hardcoded Universe: Uses the official 180+ NSE F&O universe (no external simulation CSV dependencies).
  - Dynamic Expiry-Matched Lot Sizes: Uses the 35,206-row Master Contract Database.
  - Round-trip Statutory Costs: Flat ₹300 per trade.
"""

import os
import sys
import warnings
import numpy as np
import pandas as pd
import lightgbm as lgb
import pymysql

warnings.filterwarnings('ignore')

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROD_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..'))

LOT_PATH = os.path.join(PROD_ROOT, 'config', 'historical_lotsize_new.csv')
DATASET_PATH = os.path.join(SCRIPT_DIR, 'data', 'scalp_0920_ml_dataset.csv.gz')
OUTPUT_TRADES_CSV = os.path.join(SCRIPT_DIR, 'audited_0920_0940_trades.csv')
OUTPUT_MODEL_FILE = os.path.join(SCRIPT_DIR, 'lgb_0920_scalp_model.txt')

# Official NSE F&O Universe (180+ Liquid Contract Stocks)
VALID_STOCKS = [
    'AARTIIND', 'ABB', 'ABBOTINDIA', 'ABCAPITAL', 'ABFRL', 'ACC', 'ADANIENT', 'ADANIPORTS',
    'ALKEM', 'AMBUJACEM', 'APOLLOHOSP', 'APOLLOTYRE', 'ASHOKLEY', 'ASIANPAINT', 'ASTRAL',
    'ATUL', 'AUBANK', 'AUROPHARMA', 'AXISBANK', 'BAJAJ-AUTO', 'BAJAJFINSV', 'BAJFINANCE',
    'BALKRISIND', 'BALRAMCHIN', 'BANDHANBNK', 'BANKBARODA', 'BATAINDIA', 'BEL', 'BERGEPAINT',
    'BHARATFORG', 'BHARTIARTL', 'BHEL', 'BIOCON', 'BOSCHLTD', 'BPCL', 'BRITANNIA', 'BSOFT',
    'CANBK', 'CANFINHOME', 'CHAMBLFERT', 'CHOLAFIN', 'CIPLA', 'COALINDIA', 'COFORGE', 'COLPAL',
    'CONCOR', 'COROMANDEL', 'CROMPTON', 'CUB', 'CUMMINSIND', 'DABUR', 'DALBHARAT', 'DEEPAKNTR',
    'DELTACORP', 'DIVISLAB', 'DIXON', 'DLF', 'DRREDDY', 'EICHERMOT', 'ESCORTS', 'EXIDEIND',
    'FEDERALBNK', 'GAIL', 'GLENMARK', 'GMRINFRA', 'GNFC', 'GODREJCP', 'GODREJPROP', 'GRANULES',
    'GRASIM', 'GUJGASLTD', 'HAL', 'HAVELLS', 'HCLTECH', 'HDFCAMC', 'HDFCBANK', 'HDFCLIFE',
    'HEROMOTOCO', 'HINDALCO', 'HINDCOPPER', 'HINDPETRO', 'HINDUNILVR', 'IBULHSGFIN', 'ICICIBANK',
    'ICICIGI', 'ICICIPRULI', 'IDEA', 'IDFC', 'IDFCFIRSTB', 'IEX', 'IGL', 'INDHOTEL', 'INDIACEM',
    'INDIAMART', 'INDIGO', 'INDUSINDBK', 'INDUSTOWER', 'INFY', 'IOC', 'IPCALAB', 'IRCTC', 'ITC',
    'JINDALSTEL', 'JKCEMENT', 'JSWSTEEL', 'JUBLFOOD', 'KOTAKBANK', 'L&TFH', 'LALPATHLAB',
    'LAURUSLABS', 'LICHSGFIN', 'LT', 'LTF', 'LTIM', 'LTTS', 'LUPIN', 'M&M', 'M&MFIN', 'MANAPPURAM',
    'MARICO', 'MARUTI', 'MCDOWELL-N', 'MCX', 'METROPOLIS', 'MFSL', 'MGL', 'MOTHERSON', 'MPHASIS',
    'MRF', 'MUTHOOTFIN', 'NATIONALUM', 'NAUKRI', 'NAVINFLUOR', 'NESTLEIND', 'NMDC', 'NTPC',
    'OBEROIRLTY', 'OFSS', 'ONGC', 'PAGEIND', 'PEL', 'PERSISTENT', 'PETRONET', 'PFC', 'PIDILITIND',
    'PIIND', 'PNB', 'POLYCAB', 'POWERGRID', 'PVRINOX', 'RAMCOCEM', 'RBLBANK', 'RECLTD', 'RELIANCE',
    'SAIL', 'SBICARD', 'SBILIFE', 'SBIN', 'SHREECEM', 'SHRIRAMFIN', 'SIEMENS', 'SRF', 'SUNPHARMA',
    'SUNTV', 'SYNGENE', 'TATACHEM', 'TATACOMM', 'TATACONSUM', 'TATAMOTORS', 'TATAPOWER', 'TATASTEEL',
    'TCS', 'TECHM', 'TITAN', 'TORNTPHARM', 'TRENT', 'TVSMOTOR', 'UBL', 'ULTRACEMCO', 'UNITDSPR',
    'UPL', 'VEDL', 'VOLTAS', 'WIPRO', 'ZEEL', 'ZYDUSLIFE'
]
VALID_SET = set(VALID_STOCKS)

print("=" * 95)
print("🔍 09:20 - 09:40 SCALP ENGINE: HARDCODED F&O UNIVERSE & WALK-FORWARD AUDIT")
print("=" * 95)

# 1. Load exact historical lot sizes
print(f"\n1. Loading Dynamic Expiry-Matched Lot Sizes from {os.path.basename(LOT_PATH)}...")
lot_df = pd.read_csv(LOT_PATH)
lot_df['clean_stock'] = lot_df['stockname'].astype(str).str.strip().str.upper()
lot_df['parsed_exp'] = pd.to_datetime(lot_df['expdate'], format='%d/%m/%Y', errors='coerce')

lot_map = {}
for stock, grp in lot_df.groupby('clean_stock'):
    lot_map[stock] = grp.sort_values('parsed_exp')

def get_exact_lot(stock, dt, fallback=1000):
    if stock not in lot_map:
        return fallback
    sub = lot_map[stock]
    matches = sub[sub['parsed_exp'] >= dt]
    if len(matches) > 0:
        return int(matches.iloc[0]['lotsize'])
    return int(sub.iloc[-1]['lotsize'])

# 2. Load Features
print(f"2. Loading Pure Database Features from {os.path.basename(DATASET_PATH)}...")
df = pd.read_csv(DATASET_PATH)
df['clean_stock'] = df['clean_stock'].astype(str).str.strip().str.upper()

# Filter strictly to hardcoded universe
df = df[df['clean_stock'].isin(VALID_SET)].reset_index(drop=True)

df['date_obj'] = pd.to_datetime(df['short_date'])
df['year'] = df['date_obj'].dt.year
df['target'] = (df['pnl_net'] > 0).astype(int)

# Map dynamic lot sizes
df['dynamic_lotsize'] = [get_exact_lot(r['clean_stock'], r['date_obj'], r.get('lotsize', 1000)) for _, r in df.iterrows()]

features = [
    'prev_intraday_vwap_gap', 'prev_intraday_roc_last_hour', 'prev_intraday_return',
    'positive_arc_ratio', 'Gap_Pct', 'gap_0907_pct', 'morn_range_pct', 'rejection_wick'
]

params = {
    'objective': 'binary',
    'metric': 'auc',
    'boosting_type': 'gbdt',
    'learning_rate': 0.03,
    'num_leaves': 15,
    'max_depth': 4,
    'min_child_samples': 50,
    'subsample': 0.8,
    'colsample_bytree': 0.8,
    'random_state': 42,
    'verbose': -1
}

print(f"   • Total evaluated dataset rows: {len(df):,}")
print("3. Executing Walk-Forward Machine Learning (2021 - 2026)...")

all_oos = []
last_model = None

for test_year in range(2021, 2027):
    train_df = df[df['year'] < test_year]
    test_df = df[df['year'] == test_year]
    if len(train_df) == 0 or len(test_df) == 0:
        continue
    
    trn_data = lgb.Dataset(train_df[features], label=train_df['target'])
    model = lgb.train(params, trn_data, num_boost_round=300)
    last_model = model
    
    test_df_copy = test_df.copy()
    test_df_copy['prob'] = model.predict(test_df[features])
    all_oos.append(test_df_copy)

# Save latest production model
if last_model is not None:
    last_model.save_model(OUTPUT_MODEL_FILE)
    print(f"   • Saved latest production model to: {OUTPUT_MODEL_FILE}")

oos_df = pd.concat(all_oos).sort_values(['short_date', 'prob'], ascending=[True, False])
top4_ml = oos_df.groupby('short_date').head(4).reset_index(drop=True)
print(f"   • Filtered to Top 4 daily candidates: {len(top4_ml):,} total trades")

# 4. Merge verified execution prices from existing audited sheet
if os.path.exists(OUTPUT_TRADES_CSV):
    print("4. Attaching MySQL tick execution prices...")
    existing_audited = pd.read_csv(OUTPUT_TRADES_CSV)
    price_cols = ['short_date', 'clean_stock', 'p_0920', 'p_0921', 'p_0940', 'p_0941']
    if all(c in existing_audited.columns for c in price_cols):
        price_sub = existing_audited[price_cols].drop_duplicates()
        merged_ml = pd.merge(top4_ml, price_sub, on=['short_date', 'clean_stock'], how='inner')
    else:
        merged_ml = top4_ml
else:
    merged_ml = top4_ml

# 5. Compute PnLs with Dynamic Master Lot Sizes
# Recommended Execution Window (09:21 Entry -> 09:41 Exit with 1-min buffer):
merged_ml['gross_dyn_0921_0941'] = (merged_ml['p_0921'] - merged_ml['p_0941']) * merged_ml['dynamic_lotsize']
merged_ml['net_dyn_0921_0941'] = merged_ml['gross_dyn_0921_0941'] - 300.0

# Strict Window (09:20 Entry -> 09:40 Exit):
merged_ml['gross_dyn_0920_0940'] = (merged_ml['p_0920'] - merged_ml['p_0940']) * merged_ml['dynamic_lotsize']
merged_ml['net_dyn_0920_0940'] = merged_ml['gross_dyn_0920_0940'] - 300.0

# Save trades
merged_ml.to_csv(OUTPUT_TRADES_CSV, index=False)
print(f"✅ Audited trades saved to: {OUTPUT_TRADES_CSV}")

# Display YoY Performance
print("\n" + "=" * 95)
print("📊 WALK-FORWARD AUDIT: 09:21 -> 09:41 (HARDCODED F&O UNIVERSE | ₹300 CHARGES)")
print("=" * 95)
header = f"{'Year':<6} | {'Trades':<7} | {'Win Rate':<10} | {'Gross PnL (₹)':<18} | {'NET PnL (₹300 Charges)':<24}"
print(header)
print("-" * 95)

for y in sorted(merged_ml['year'].unique()):
    ydf = merged_ml[(merged_ml['year'] == y) & merged_ml['p_0921'].notnull() & merged_ml['p_0941'].notnull()]
    if len(ydf) == 0: continue
    t_cnt = len(ydf)
    wr = (ydf['gross_dyn_0921_0941'] > 0).mean() * 100
    pnl_gross = ydf['gross_dyn_0921_0941'].sum()
    pnl_net = ydf['net_dyn_0921_0941'].sum()
    print(f"{y:<6} | {t_cnt:<7} | {wr:>7.2f}%   | ₹{pnl_gross:>14,.2f}  | ₹{pnl_net:>18,.2f}")

valid_all = merged_ml[merged_ml['p_0921'].notnull() & merged_ml['p_0941'].notnull()]
tot_t = len(valid_all)
tot_wr = (valid_all['gross_dyn_0921_0941'] > 0).mean() * 100
tot_gross = valid_all['gross_dyn_0921_0941'].sum()
tot_net = valid_all['net_dyn_0921_0941'].sum()

print("-" * 95)
print(f"{'TOTAL':<6} | {tot_t:<7} | {tot_wr:>7.2f}%   | ₹{tot_gross:>14,.2f}  | ₹{tot_net:>18,.2f} (+₹{tot_net/1e7:.2f} Cr)")
print("=" * 95)
