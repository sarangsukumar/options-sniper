import os
import pickle
import pandas as pd
import numpy as np

DEST_DIR = '/home/ubuntu/shortsellmodel940v3'
SRC_DIR = '/home/ubuntu/short_sell_simulation_algo/output'

print("1. Loading base dataset from short_sell_ml_dataset_v2.csv...")
df = pd.read_csv(f'{SRC_DIR}/short_sell_ml_dataset_v2.csv', low_memory=False)

# Clean dates
df['short_sell_date'] = pd.to_datetime(df['short_sell_date'], format='mixed')
df['date_str'] = df['short_sell_date'].dt.strftime('%Y-%m-%d')
df['year'] = df['short_sell_date'].dt.year
df['month'] = df['short_sell_date'].dt.month
df['year_month'] = df['year'] * 100 + df['month']
df['day_of_week'] = df['short_sell_date'].dt.day_name()

# Exclude Mondays (BTST Friday -> Monday proxy exclusion)
df = df[df['day_of_week'] != 'Monday'].copy()

# Fill missing gap
df['Gap_Pct'] = df['Gap_Pct'].fillna(0.0)

# Merge Nifty 09:40 return from database
nifty_file = f'{SRC_DIR}/nifty_ret_940.csv'
if os.path.exists(nifty_file):
    nifty_df = pd.read_csv(nifty_file)
    nifty_df['date_str'] = nifty_df['date']
    df = df.merge(nifty_df[['date_str', 'nifty_ret_940']], on='date_str', how='left')
else:
    df['nifty_ret_940'] = 0.0

df['nifty_ret_940'] = df['nifty_ret_940'].fillna(0.0)

# Load ticks cache for morning features
print("2. Recalculating morning intraday features (09:15 to 09:40 AM strictly)...")
with open(f'{SRC_DIR}/ticks_cache_ranks_1_to_5.pkl', 'rb') as f:
    ticks = pickle.load(f)

# Merge morning features for cached trades
records = []
for k, t in ticks.items():
    date_str, stock = k
    time_arr = t['time']
    c_arr = t['close']
    h_arr = t['high']
    l_arr = t['low']
    
    # Strictly 09:15 open
    m_915 = time_arr >= pd.to_datetime('09:15:00').time()
    if not m_915.any(): continue
    open_p = c_arr[np.argmax(m_915)]
    
    # Strictly 09:40 close
    m_940 = time_arr >= pd.to_datetime('09:40:00').time()
    if not m_940.any(): continue
    idx_940 = np.argmax(m_940)
    close_940 = c_arr[idx_940]
    
    # 09:42 entry price
    m_942 = time_arr >= pd.to_datetime('09:42:00').time()
    if not m_942.any(): continue
    close_942 = c_arr[np.argmax(m_942)]
    
    # Morning high and low up to 09:40
    morn_h = np.max(h_arr[:idx_940+1])
    morn_l = np.min(l_arr[:idx_940+1])
    
    stock_ret_940 = ((close_940 - open_p) / open_p) * 100.0
    morn_range_pct = ((morn_h - morn_l) / open_p) * 100.0
    rejection_wick = ((morn_h - close_940) / (morn_h - morn_l + 1e-5))
    
    records.append({
        'date_str': date_str,
        'clean_stock': stock,
        'stock_ret_940': stock_ret_940,
        'morn_range_pct': morn_range_pct,
        'rejection_wick': rejection_wick,
        'entry_price_0942': close_942
    })

m_df = pd.DataFrame(records)
print(f"Calculated 09:40 morning features for {len(m_df):,} trades.")

# Save dataset v3
out_csv = f'{DEST_DIR}/short_sell_ml_dataset_v3.csv'
df.to_csv(out_csv, index=False)
m_df.to_csv(f'{DEST_DIR}/morning_features_v3.csv', index=False)

print(f"3. Saved v3 dataset cleanly to {out_csv} ({len(df):,} rows).")

