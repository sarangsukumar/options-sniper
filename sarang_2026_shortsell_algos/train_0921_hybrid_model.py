import pandas as pd
import numpy as np
import lightgbm as lgb
import pymysql
from concurrent.futures import ThreadPoolExecutor
import warnings
warnings.filterwarnings('ignore')

print("1. Loading and merging datasets...")
df_a = pd.read_csv('/home/ubuntu/v5_from_scratch/data/short_sell_ml_dataset_v5_scratch.csv', low_memory=False)
df_b = pd.read_csv('/home/ubuntu/sarang_2026_shortsell_algos/01_Best_Shorter_Window_0920_0940/data/scalp_0920_ml_dataset.csv.gz')

df_a['date_dt'] = pd.to_datetime(df_a['short_sell_date'])
df_b['date_dt'] = pd.to_datetime(df_b['short_date'])
df_a['stock'] = df_a['stockname'].str.strip().str.upper()
df_b['stock'] = df_b['clean_stock'].str.strip().str.upper()

df = pd.merge(df_a, df_b, on=['date_dt', 'stock'], how='inner')

# Target: 14:45 Exit vs 09:15 Open (since this represents a huge intraday fade)
df['full_day_fade'] = df['morning_open'] - df['short_exit_price']
df['target'] = (df['full_day_fade'] > 0).astype(int)

# Select Look-Ahead Free Features up to 09:20!
features = [c for c in df.columns if c.startswith('prev_intraday_') and not c.endswith('_y')]
if 'gap_0907_pct_x' in df.columns:
    features.append('gap_0907_pct_x')
elif 'gap_0907_pct' in df.columns:
    features.append('gap_0907_pct')
elif 'Gap_Pct_x' in df.columns:
    features.append('Gap_Pct_x')

# Add the 5-min dynamics from dataset B
features.extend(['morn_range_pct_y', 'rejection_wick_y'])

df = df.dropna(subset=features + ['target'])
df = df.sort_values('date_dt').reset_index(drop=True)

start_year = 2020
print(f"2. Training Walk-Forward Model (Entry 09:21, Exit 14:45) with {len(features)} Features...")

picks = []
for year in range(start_year, 2027):
    train = df[df['date_dt'].dt.year < year]
    test = df[df['date_dt'].dt.year == year]
    if test.empty: continue
    
    X_train, y_train = train[features], train['target']
    X_test = test[features]
    
    model = lgb.LGBMClassifier(n_estimators=100, learning_rate=0.05, max_depth=5, random_state=42)
    model.fit(X_train, y_train)
    
    test = test.copy()
    test['prob'] = model.predict_proba(X_test)[:, 1]
    
    daily_picks = test.sort_values(['date_dt', 'prob'], ascending=[True, False]).groupby('date_dt').head(4)
    for _, row in daily_picks.iterrows():
        picks.append({'date': row['short_date'], 'stock': row['stock']})

print(f"3. Fetching exact 09:21 and 14:45 execution for {len(picks)} trades from MySQL...")

def get_db_connection():
    return pymysql.connect(host='localhost', user='root', password='root', database='markets', autocommit=True)

def process_trade(trade):
    d = trade['date']
    s = trade['stock']
    conn = get_db_connection()
    cur = conn.cursor(pymysql.cursors.DictCursor)
    
    # 09:21 entry
    q_en = f"SELECT price FROM scrapdata WHERE date='{d}' AND stockname IN ('{s}', '\"{s}\"') AND time >= '{d} 09:21:00' AND time <= '{d} 09:21:59' ORDER BY time ASC LIMIT 1"
    cur.execute(q_en)
    r_en = cur.fetchone()
    
    # 14:45 exit
    q_ex = f"SELECT price FROM scrapdata WHERE date='{d}' AND stockname IN ('{s}', '\"{s}\"') AND time >= '{d} 14:44:00' AND time <= '{d} 14:45:59' ORDER BY time DESC LIMIT 1"
    cur.execute(q_ex)
    r_ex = cur.fetchone()
    
    conn.close()
    
    if not r_en or not r_ex: return None
        
    en = float(r_en['price'])
    ex = float(r_ex['price'])
    if en <= 0: return None
    
    cap = 500000.0 # 1L * 5x
    qty = int(cap // en)
    gross = (en - ex) * qty
    charges = (en + ex) * qty * 0.00035 # Strict Kotak MIS charges
    net = gross - charges
    
    return {'date': d, 'gross': gross, 'net': net}

results = []
with ThreadPoolExecutor(max_workers=32) as executor:
    for res in executor.map(process_trade, picks):
        if res: results.append(res)
        
res_df = pd.DataFrame(results)
res_df['year'] = pd.to_datetime(res_df['date']).dt.year

print("\n| Year | Trades | Win Rate | Gross PnL | NET PnL |")
print("|------|--------|----------|-----------|---------|")
for y, grp in res_df.groupby('year'):
    wins = len(grp[grp['net'] > 0])
    trd = len(grp)
    wr = (wins/trd)*100
    gr = grp['gross'].sum() / 100000
    nt = grp['net'].sum() / 100000
    print(f"| {y} | {trd} | {wr:.1f}% | ₹{gr:.2f}L | ₹{nt:.2f}L |")

wins = len(res_df[res_df['net'] > 0])
trd = len(res_df)
wr = (wins/trd)*100
gr = res_df['gross'].sum() / 100000
nt = res_df['net'].sum() / 100000
print(f"| TOTAL | {trd} | {wr:.1f}% | ₹{gr:.2f}L | ₹{nt:.2f}L |")

