import pandas as pd
import numpy as np
import lightgbm as lgb
import pymysql
from concurrent.futures import ThreadPoolExecutor, as_completed
import warnings
import os

warnings.filterwarnings('ignore')

print("=" * 85)
print("🔍 AUDIT & RECREATION: 09:20 - 09:40 ENGINE (PURE DATABASE | EXACT LOT SIZES)")
print("=" * 85)

# 1. Load exact historical lot size mapping
print("\n1. Loading Dynamic Expiry-Matched Lot Sizes from historical_lotsize_new.csv...")
lot_path = '/home/ubuntu/KotakCodes1/historical_lotsize_new.csv'
lot_df = pd.read_csv(lot_path)
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

# 2. Load Features (Derived 100% from MySQL database, zero Yahoo Finance)
print("2. Loading Pure Database Features (Zero Yahoo Finance)...")
v6_df = pd.read_csv('/home/ubuntu/V8_Hybrid_Engine/v6_master_features.csv')
v6_df['clean_stock'] = v6_df['stockname'].astype(str).str.strip().str.upper()
v6_df = v6_df[['short_date', 'clean_stock', 'prev_intraday_vwap_gap', 'prev_intraday_roc_last_hour', 
               'prev_intraday_return', 'positive_arc_ratio', 'Gap_Pct', 'gap_0907_pct', 'rejection_wick']]

v8_df = pd.read_csv('/home/ubuntu/V8_Hybrid_Engine/features_250k_0919_final_v2.csv')
v8_df['clean_stock'] = v8_df['stockname'].astype(str).str.strip().str.upper()
v8_df = v8_df[['short_date', 'clean_stock', 'morn_range_pct', 'pnl_net', 'lotsize']]

df = pd.merge(v8_df, v6_df, on=['short_date', 'clean_stock'], how='inner')
df = df.dropna().reset_index(drop=True)
df['date_obj'] = pd.to_datetime(df['short_date'])
df['year'] = df['date_obj'].dt.year
df['target'] = (df['pnl_net'] > 0).astype(int)

# Map exact historical lot size
df['dynamic_lotsize'] = [get_exact_lot(r['clean_stock'], r['date_obj'], r['lotsize']) for _, r in df.iterrows()]

features = ['prev_intraday_vwap_gap', 'prev_intraday_roc_last_hour', 'prev_intraday_return', 
            'positive_arc_ratio', 'Gap_Pct', 'gap_0907_pct', 'morn_range_pct', 'rejection_wick']
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
for test_year in range(2021, 2027):
    train_df = df[df['year'] < test_year]
    test_df = df[df['year'] == test_year]
    if len(train_df) == 0 or len(test_df) == 0:
        continue
    model = lgb.train(params, lgb.Dataset(train_df[features], label=train_df['target']), num_boost_round=300)
    test_df_copy = test_df.copy()
    test_df_copy['prob'] = model.predict(test_df[features])
    all_oos.append(test_df_copy)

oos_df = pd.concat(all_oos).sort_values(['short_date', 'prob'], ascending=[True, False])
top4_ml = oos_df.groupby('short_date').head(4).reset_index(drop=True)
print(f"   • Filtered to Top 4 daily candidates: {len(top4_ml):,} total trades")

# 3. Query MySQL tick data directly for 09:21:00 entry and 09:41:00 exit (also 09:20 and 09:40)
print("\n4. Fetching Live MySQL Execution Ticks (09:20, 09:21, 09:40, 09:41)...")

def fetch_prices_batch(batch_rows):
    conn = pymysql.connect(host='localhost', user='root', password='root', database='markets')
    cursor = conn.cursor(pymysql.cursors.DictCursor)
    results = []
    
    for _, row in batch_rows.iterrows():
        d = row['short_date']
        s = row['clean_stock']
        
        # 09:21 Entry (1-min execution buffer)
        cursor.execute(f"SELECT price FROM scrapdata WHERE date='{d}' AND stockname='{s}' AND time >= '{d} 09:21:00' ORDER BY time ASC LIMIT 1")
        res_e21 = cursor.fetchone()
        p_0921 = float(res_e21['price']) if res_e21 else None
        
        # 09:20 Entry (0 buffer)
        cursor.execute(f"SELECT price FROM scrapdata WHERE date='{d}' AND stockname='{s}' AND time >= '{d} 09:20:00' ORDER BY time ASC LIMIT 1")
        res_e20 = cursor.fetchone()
        p_0920 = float(res_e20['price']) if res_e20 else None
        
        # 09:41 Exit (20-min hold from 09:21)
        cursor.execute(f"SELECT price FROM scrapdata WHERE date='{d}' AND stockname='{s}' AND time >= '{d} 09:41:00' ORDER BY time ASC LIMIT 1")
        res_x41 = cursor.fetchone()
        p_0941 = float(res_x41['price']) if res_x41 else None
        
        # 09:40 Exit (20-min hold from 09:20)
        cursor.execute(f"SELECT price FROM scrapdata WHERE date='{d}' AND stockname='{s}' AND time >= '{d} 09:40:00' ORDER BY time ASC LIMIT 1")
        res_x40 = cursor.fetchone()
        p_0940 = float(res_x40['price']) if res_x40 else None
        
        results.append({
            'short_date': d,
            'clean_stock': s,
            'p_0920': p_0920,
            'p_0921': p_0921,
            'p_0940': p_0940,
            'p_0941': p_0941
        })
    conn.close()
    return results

chunks = [top4_ml.iloc[i:i+400] for i in range(0, len(top4_ml), 400)]
res_list = []
with ThreadPoolExecutor(max_workers=50) as executor:
    for f in as_completed([executor.submit(fetch_prices_batch, c) for c in chunks]):
        res_list.extend(f.result())

price_df = pd.DataFrame(res_list)
merged_ml = pd.merge(top4_ml, price_df, on=['short_date', 'clean_stock'], how='inner')

# Calculate PnLs:
# A. Old Method (Static Lot, No Charges):
merged_ml['gross_static_0921_0941'] = (merged_ml['p_0921'] - merged_ml['p_0941']) * merged_ml['lotsize']

# B. True Audited Method (Exact Dynamic Historical Lot, with and without charges):
merged_ml['gross_dyn_0921_0941'] = (merged_ml['p_0921'] - merged_ml['p_0941']) * merged_ml['dynamic_lotsize']
merged_ml['net_dyn_0921_0941'] = merged_ml['gross_dyn_0921_0941'] - 300.0

# C. 09:20 -> 09:40 timing (Exact Dynamic Historical Lot):
merged_ml['gross_dyn_0920_0940'] = (merged_ml['p_0920'] - merged_ml['p_0940']) * merged_ml['dynamic_lotsize']
merged_ml['net_dyn_0920_0940'] = merged_ml['gross_dyn_0920_0940'] - 300.0

# Save full trade audit sheet
out_trades = '/home/ubuntu/920-940_model/audited_0920_0940_trades.csv'
merged_ml.to_csv(out_trades, index=False)
print(f"✅ Audited trades saved to: {out_trades}")

# Display comparative results
print("\n" + "=" * 105)
print("📊 FORENSIC PnL AUDIT: STATIC LOT vs DYNAMIC HISTORICAL LOT (09:21 -> 09:41 with 1-min buffer)")
print("=" * 105)
header = f"{'Year':<6} | {'Trades':<7} | {'Win Rate':<9} | {'Old Static Gross':<18} | {'Exact Dyn Gross':<18} | {'Exact Dyn NET (₹300)':<22}"
print(header)
print("-" * 105)

for y in range(2021, 2027):
    ydf = merged_ml[(merged_ml['year'] == y) & (merged_ml['p_0921'].notnull()) & (merged_ml['p_0941'].notnull())]
    if len(ydf) == 0: continue
    t_cnt = len(ydf)
    wr = (ydf['gross_dyn_0921_0941'] > 0).mean() * 100
    pnl_old = ydf['gross_static_0921_0941'].sum()
    pnl_dyn_gross = ydf['gross_dyn_0921_0941'].sum()
    pnl_dyn_net = ydf['net_dyn_0921_0941'].sum()
    print(f"{y:<6} | {t_cnt:<7} | {wr:>6.2f}%  | ₹{pnl_old:>14,.2f} | ₹{pnl_dyn_gross:>14,.2f} | ₹{pnl_dyn_net:>18,.2f}")

valid_all = merged_ml[(merged_ml['p_0921'].notnull()) & (merged_ml['p_0941'].notnull())]
tot_t = len(valid_all)
tot_wr = (valid_all['gross_dyn_0921_0941'] > 0).mean() * 100
tot_old = valid_all['gross_static_0921_0941'].sum()
tot_dyn_gross = valid_all['gross_dyn_0921_0941'].sum()
tot_dyn_net = valid_all['net_dyn_0921_0941'].sum()

print("-" * 105)
print(f"{'TOTAL':<6} | {tot_t:<7} | {tot_wr:>6.2f}%  | ₹{tot_old:>14,.2f} | ₹{tot_dyn_gross:>14,.2f} | ₹{tot_dyn_net:>18,.2f}")
print("=" * 105)

print("\n" + "=" * 105)
print("📊 ALTERNATIVE TIMING: 09:20:00 ENTRY -> 09:40:00 EXIT (EXACT DYNAMIC HISTORICAL LOT)")
print("=" * 105)
header2 = f"{'Year':<6} | {'Trades':<7} | {'Win Rate':<9} | {'Exact Dyn Gross':<18} | {'Exact Dyn NET (₹300)':<22}"
print(header2)
print("-" * 105)

for y in range(2021, 2027):
    ydf2 = merged_ml[(merged_ml['year'] == y) & (merged_ml['p_0920'].notnull()) & (merged_ml['p_0940'].notnull())]
    if len(ydf2) == 0: continue
    t_cnt2 = len(ydf2)
    wr2 = (ydf2['gross_dyn_0920_0940'] > 0).mean() * 100
    pnl_dyn_gross2 = ydf2['gross_dyn_0920_0940'].sum()
    pnl_dyn_net2 = ydf2['net_dyn_0920_0940'].sum()
    print(f"{y:<6} | {t_cnt2:<7} | {wr2:>6.2f}%  | ₹{pnl_dyn_gross2:>14,.2f} | ₹{pnl_dyn_net2:>18,.2f}")

valid_all2 = merged_ml[(merged_ml['p_0920'].notnull()) & (merged_ml['p_0940'].notnull())]
tot_t2 = len(valid_all2)
tot_wr2 = (valid_all2['gross_dyn_0920_0940'] > 0).mean() * 100
tot_dyn_gross2 = valid_all2['gross_dyn_0920_0940'].sum()
tot_dyn_net2 = valid_all2['net_dyn_0920_0940'].sum()
print("-" * 105)
print(f"{'TOTAL':<6} | {tot_t2:<7} | {tot_wr2:>6.2f}%  | ₹{tot_dyn_gross2:>14,.2f} | ₹{tot_dyn_net2:>18,.2f}")
print("=" * 105)

