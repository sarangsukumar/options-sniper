import pandas as pd
import numpy as np
import lightgbm as lgb
import pymysql
import time
from concurrent.futures import ThreadPoolExecutor
import warnings
warnings.filterwarnings('ignore')

print("1. Loading base dataset...")
df_a = pd.read_csv('/home/ubuntu/v5_from_scratch/data/short_sell_ml_dataset_v5_scratch.csv', low_memory=False)
df_a = df_a[df_a['Gap_Pct'] >= 0.5]
df_a['date_dt'] = pd.to_datetime(df_a['short_sell_date'])
df_a['stock'] = df_a['stockname'].str.strip().str.upper()

# Keep top 1500 gappers per year for a robust sample
df_a = df_a.sort_values(['date_dt', 'Gap_Pct'], ascending=[True, False]).groupby(df_a['date_dt'].dt.year).head(1500)
trades_to_fetch = df_a[['date_dt', 'stock', 'short_sell_date', 'Gap_Pct', 'prev_intraday_return']].to_dict('records')

print(f"2. Fetching 09:15 to 09:34 features for {len(trades_to_fetch)} candidates...")

def get_db_connection():
    return pymysql.connect(host='localhost', user='root', password='root', database='markets', autocommit=True)

def fetch_data(trade):
    d, s = trade['short_sell_date'], trade['stock']
    conn = get_db_connection()
    cur = conn.cursor(pymysql.cursors.DictCursor)
    
    res = {'date': d, 'stock': s, 'gap': trade['Gap_Pct'], 'pre_vol': trade['prev_intraday_return'], 
           'eq_0915': np.nan, 'eq_0934': np.nan, 'eq_0936': np.nan, 'eq_1445': np.nan}
    
    # 09:15
    cur.execute(f"SELECT price, close FROM scrapdata WHERE date='{d}' AND stockname='{s}' AND time >= '{d} 09:15:00' AND time <= '{d} 09:16:59' ORDER BY time ASC LIMIT 1")
    r = cur.fetchone(); 
    if r: res['eq_0915'] = float(r['price'] or r['close'] or 0)
        
    # 09:34 (Feature Extraction End)
    cur.execute(f"SELECT price, close FROM scrapdata WHERE date='{d}' AND stockname='{s}' AND time >= '{d} 09:34:00' AND time <= '{d} 09:34:59' ORDER BY time ASC LIMIT 1")
    r = cur.fetchone(); 
    if r: res['eq_0934'] = float(r['price'] or r['close'] or 0)
        
    # 09:36 (Execution)
    cur.execute(f"SELECT price, close FROM scrapdata WHERE date='{d}' AND stockname='{s}' AND time >= '{d} 09:36:00' AND time <= '{d} 09:37:59' ORDER BY time ASC LIMIT 1")
    r = cur.fetchone(); 
    if r: res['eq_0936'] = float(r['price'] or r['close'] or 0)
        
    # 14:45 (Time Exit Target)
    cur.execute(f"SELECT price, close FROM scrapdata WHERE date='{d}' AND stockname='{s}' AND time >= '{d} 14:45:00' AND time <= '{d} 14:47:59' ORDER BY time DESC LIMIT 1")
    r = cur.fetchone(); 
    if r: res['eq_1445'] = float(r['price'] or r['close'] or 0)

    conn.close()
    return res

t0 = time.time()
results = []
with ThreadPoolExecutor(max_workers=75) as executor:
    for i, res in enumerate(executor.map(fetch_data, trades_to_fetch)):
        results.append(res)
        if (i+1) % 1500 == 0: print(f"Fetched {i+1} in {time.time()-t0:.1f}s")
        
df = pd.DataFrame(results).dropna()
df['morning_ret'] = (df['eq_0934'] - df['eq_0915']) / df['eq_0915']
df['fwd_ret'] = (df['eq_0936'] - df['eq_1445']) / df['eq_0936']
df['target'] = (df['fwd_ret'] > 0.005).astype(int) # Target: Drops more than 0.5% by 14:45
df['date_dt'] = pd.to_datetime(df['date'])
df = df.sort_values('date_dt')

print(f"3. Training Walk-Forward LightGBM Model on {len(df)} samples...")
features = ['gap', 'pre_vol', 'morning_ret']

preds = []
years = sorted(df['date_dt'].dt.year.unique())
for i in range(1, len(years)):
    train_years = years[:i]
    test_year = years[i]
    
    train = df[df['date_dt'].dt.year.isin(train_years)]
    test = df[df['date_dt'].dt.year == test_year]
    
    if len(train) < 500: continue
    
    model = lgb.LGBMClassifier(n_estimators=100, max_depth=4, learning_rate=0.05, random_state=42)
    model.fit(train[features], train['target'])
    
    test_copy = test.copy()
    test_copy['prob'] = model.predict_proba(test[features])[:, 1]
    preds.append(test_copy)

pred_df = pd.concat(preds)

# Select Top 4 per day
top_picks = pred_df.sort_values(['date', 'prob'], ascending=[True, False]).groupby('date').head(4)

print(f"4. Selected {len(top_picks)} Top Trades. Simulating PnL (3% SL, 5% TP)...")

def get_kotak_mis_charges(qty, sell_price, buy_price):
    turnover = (qty * sell_price) + (qty * buy_price)
    stt = round(qty * sell_price * 0.00025)
    txn = turnover * 0.0000322
    sebi = turnover * 0.000001
    stamp = round(qty * buy_price * 0.00003)
    gst = (txn + sebi) * 0.18
    return round(stt + txn + sebi + stamp + gst, 2)

def sim_trade(row):
    d, s, en = row['date'], row['stock'], row['eq_0936']
    qty = int(500000.0 // en)
    
    conn = pymysql.connect(host='localhost', user='root', password='root', database='markets', autocommit=True)
    cur = conn.cursor(pymysql.cursors.DictCursor)
    
    cur.execute(f"SELECT time, price, high, low, close FROM scrapdata WHERE date = '{d}' AND stockname IN ('{s}', '\"{s}\"', '{s} ') AND time >= '{d} 09:36:00' AND time <= '{d} 14:47:59' ORDER BY time ASC")
    ticks = cur.fetchall()
    
    sl = round(en * 1.03, 2); tp = round(en * 0.95, 2)
    hit, ex = False, en
    
    for t in ticks:
        h = float(t['high'] or t['price'] or 0)
        l = float(t['low'] or t['price'] or 0)
        if h >= sl: hit, ex = True, sl; break
        if l <= tp: hit, ex = True, tp; break
            
    if not hit:
        cur.execute(f"SELECT price, close FROM scrapdata WHERE date = '{d}' AND stockname IN ('{s}', '\"{s}\"', '{s} ') AND time >= '{d} 14:45:00' AND time <= '{d} 14:47:59' ORDER BY time DESC LIMIT 1")
        xt = cur.fetchone()
        ex = float(xt['close'] or xt['price'] or 0) if xt else en
        
    conn.close()
    return {'date': d, 'net': (en - ex) * qty - get_kotak_mis_charges(qty, en, ex)}

final_results = []
with ThreadPoolExecutor(max_workers=75) as executor:
    for i, res in enumerate(executor.map(sim_trade, top_picks.to_dict('records'))):
        final_results.append(res)
        
final_df = pd.DataFrame(final_results)
final_df['year'] = pd.to_datetime(final_df['date']).dt.year

print("\n=== ZERO-BIAS 09:34 MODEL (EXEC 09:36) ===")
print(f"Total Valid Trades: {len(final_df)}")
wins = len(final_df[final_df['net'] > 0])
total_net = final_df['net'].sum()
print(f"Overall Net PnL: Rs {total_net/100000:,.2f} Lakhs")
print(f"Overall Win Rate: {(wins/len(final_df))*100:.2f}%\n")

for y in sorted(final_df['year'].unique()):
    ydf = final_df[final_df['year'] == y]
    ywins = len(ydf[ydf['net'] > 0])
    print(f"{y} | Trades: {len(ydf):3d} | Win Rate: {(ywins/len(ydf))*100:5.1f}% | Net PnL: Rs {ydf['net'].sum()/100000:7.2f} Lakhs")
