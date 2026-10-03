import pandas as pd
import numpy as np
import lightgbm as lgb
import pymysql
from concurrent.futures import ThreadPoolExecutor
import warnings
import time
warnings.filterwarnings('ignore')

print("1. Loading base dataset...")
df_a = pd.read_csv('/home/ubuntu/v5_from_scratch/data/short_sell_ml_dataset_v5_scratch.csv', low_memory=False)

# To make data fetching fast, we will pre-filter to stocks that gapped up >= 0.5%
df_a = df_a[df_a['Gap_Pct'] >= 0.5]
df_a['date_dt'] = pd.to_datetime(df_a['short_sell_date'])
df_a['stock'] = df_a['stockname'].str.strip().str.upper()

# Take a manageable subset for fast training (top 2000 gappers per year)
df_a = df_a.sort_values(['date_dt', 'Gap_Pct'], ascending=[True, False]).groupby(df_a['date_dt'].dt.year).head(1000)
trades_to_fetch = df_a[['date_dt', 'stock', 'short_sell_date']].to_dict('records')

print(f"2. Fetching EQ and F1 09:15 & 09:30 prices for {len(trades_to_fetch)} training candidates...")

def get_db_connection():
    return pymysql.connect(host='localhost', user='root', password='root', database='markets', autocommit=True)

def fetch_data(trade):
    d = trade['short_sell_date']
    s = trade['stock']
    conn = get_db_connection()
    cur = conn.cursor(pymysql.cursors.DictCursor)
    
    res = {'date': d, 'stock': s, 'eq_0915': np.nan, 'eq_0930': np.nan, 'f1_0915': np.nan, 'f1_0930': np.nan, 'eq_1445': np.nan}
    
    # EQ 09:15
    cur.execute(f"SELECT price FROM scrapdata WHERE date='{d}' AND stockname='{s}' AND time >= '{d} 09:15:00' AND time <= '{d} 09:16:00' ORDER BY time ASC LIMIT 1")
    r = cur.fetchone()
    if r: res['eq_0915'] = float(r['price']) if r['price'] is not None else np.nan
    
    # EQ 09:30
    cur.execute(f"SELECT price FROM scrapdata WHERE date='{d}' AND stockname='{s}' AND time >= '{d} 09:30:00' AND time <= '{d} 09:31:00' ORDER BY time ASC LIMIT 1")
    r = cur.fetchone()
    if r: res['eq_0930'] = float(r['price']) if r['price'] is not None else np.nan
    
    # F1 09:15
    cur.execute(f"SELECT price FROM scrapdata_F1 WHERE date='{d}' AND stockname='{s}' AND is_future='F1' AND time >= '{d} 09:15:00' AND time <= '{d} 09:16:00' ORDER BY time ASC LIMIT 1")
    r = cur.fetchone()
    if r: res['f1_0915'] = float(r['price']) if r['price'] is not None else np.nan
    
    # F1 09:30
    cur.execute(f"SELECT price FROM scrapdata_F1 WHERE date='{d}' AND stockname='{s}' AND is_future='F1' AND time >= '{d} 09:30:00' AND time <= '{d} 09:31:00' ORDER BY time ASC LIMIT 1")
    r = cur.fetchone()
    if r: res['f1_0930'] = float(r['price']) if r['price'] is not None else np.nan

    # EQ 14:45 (for target/PnL)
    cur.execute(f"SELECT price FROM scrapdata WHERE date='{d}' AND stockname='{s}' AND time >= '{d} 14:44:00' AND time <= '{d} 14:46:00' ORDER BY time DESC LIMIT 1")
    r = cur.fetchone()
    if r: res['eq_1445'] = float(r['price']) if r['price'] is not None else np.nan

    conn.close()
    return res

t0 = time.time()
fetched_data = []
with ThreadPoolExecutor(max_workers=50) as executor:
    for i, res in enumerate(executor.map(fetch_data, trades_to_fetch)):
        fetched_data.append(res)
        if (i+1) % 1000 == 0: print(f"Fetched {i+1} / {len(trades_to_fetch)}")

print(f"Data fetching complete in {time.time()-t0:.1f}s")

df_prices = pd.DataFrame(fetched_data)
df_merged = pd.merge(df_a, df_prices, on=['date', 'stock'], how='inner')

# Drop missing
df_merged = df_merged.dropna(subset=['eq_0915', 'eq_0930', 'f1_0915', 'f1_0930', 'eq_1445'])

# Feature Engineering
df_merged['eq_return_0930'] = (df_merged['eq_0930'] - df_merged['eq_0915']) / df_merged['eq_0915'] * 100
df_merged['f1_return_0930'] = (df_merged['f1_0930'] - df_merged['f1_0915']) / df_merged['f1_0915'] * 100
df_merged['f1_eq_basis_momentum'] = df_merged['f1_return_0930'] - df_merged['eq_return_0930']

# Target: 09:30 to 14:45 fade (EQ)
df_merged['pnl_0930_1445'] = df_merged['eq_0930'] - df_merged['eq_1445']
df_merged['target'] = (df_merged['pnl_0930_1445'] > 0).astype(int)

features = [c for c in df_merged.columns if c.startswith('prev_intraday_')]
features.extend(['Gap_Pct', 'eq_return_0930', 'f1_return_0930', 'f1_eq_basis_momentum'])
df_merged = df_merged.dropna(subset=features)
df_merged = df_merged.sort_values('date_dt').reset_index(drop=True)

print(f"3. Training 09:30 Walk-Forward Model with Basis Feature on {len(df_merged)} rows...")

start_year = 2020
picks = []

for year in range(start_year, 2027):
    train = df_merged[df_merged['date_dt'].dt.year < year]
    test = df_merged[df_merged['date_dt'].dt.year == year]
    if test.empty: continue
    
    X_train, y_train = train[features], train['target']
    X_test = test[features]
    
    model = lgb.LGBMClassifier(n_estimators=100, learning_rate=0.05, max_depth=5, random_state=42)
    model.fit(X_train, y_train)
    
    # Feature importance debugging
    if year == 2026:
        imp = pd.DataFrame({'Feature': features, 'Imp': model.feature_importances_}).sort_values('Imp', ascending=False)
        print("\nTop 5 Features (2026 Train Set):")
        print(imp.head(5).to_string(index=False))

    test = test.copy()
    test['prob'] = model.predict_proba(X_test)[:, 1]
    
    daily_picks = test.sort_values(['date_dt', 'prob'], ascending=[True, False]).groupby('date_dt').head(4)
    picks.append(daily_picks)

final_picks = pd.concat(picks)

print("\n4. Simulating 09:30 to 14:45 Execution PnL...")

results = []
for _, row in final_picks.iterrows():
    en = row['eq_0930']
    ex = row['eq_1445']
    if en <= 0: continue
    
    qty = int(500000.0 // en) # 1L * 5x margin
    gross = (en - ex) * qty
    charges = (en + ex) * qty * 0.00035
    net = gross - charges
    results.append({'date': row['short_sell_date'], 'gross': gross, 'net': net})

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

