import pandas as pd
import numpy as np
import lightgbm as lgb
import pymysql
from concurrent.futures import ThreadPoolExecutor
import warnings
warnings.filterwarnings('ignore')

df = pd.read_csv('/home/ubuntu/v5_from_scratch/data/short_sell_ml_dataset_v5_scratch.csv', low_memory=False)

df['morning_short_pnl'] = df['morning_open'] - df['morning_close']
df['target'] = (df['morning_short_pnl'] > 0).astype(int)

df['drift_0915_pct'] = (df['morning_open'] - df['price_0907_unified']) / df['price_0907_unified'] * 100

features = [c for c in df.columns if c.startswith('prev_intraday_')]
if 'gap_0907_pct' in df.columns:
    features.append('gap_0907_pct')
elif 'Gap_Pct' in df.columns:
    features.append('Gap_Pct')
features.append('drift_0915_pct')

df = df.dropna(subset=features + ['target'])
df['date_dt'] = pd.to_datetime(df['short_sell_date'])
df = df.sort_values('date_dt').reset_index(drop=True)

picks = []
for year in range(2020, 2027):
    train = df[df['date_dt'].dt.year < year]
    test = df[df['date_dt'].dt.year == year]
    if test.empty or train.empty: continue
    
    X_train, y_train = train[features], train['target']
    X_test = test[features]
    
    model = lgb.LGBMClassifier(n_estimators=100, learning_rate=0.05, max_depth=5, random_state=42)
    model.fit(X_train, y_train)
    
    test = test.copy()
    test['prob'] = model.predict_proba(X_test)[:, 1]
    
    daily_picks = test.sort_values(['short_sell_date', 'prob'], ascending=[True, False]).groupby('short_sell_date').head(4)
    for _, row in daily_picks.iterrows():
        picks.append({'date': row['short_sell_date'], 'stock': row['stockname']})

def get_db_connection():
    return pymysql.connect(host='localhost', user='root', password='root', database='markets', autocommit=True)

def process_trade(trade):
    d = trade['date']
    s = trade['stock']
    conn = get_db_connection()
    cur = conn.cursor(pymysql.cursors.DictCursor)
    
    q_en = f"SELECT price FROM scrapdata WHERE date='{d}' AND stockname IN ('{s}', '\"{s}\"') AND time >= '{d} 09:16:00' AND time <= '{d} 09:16:59' ORDER BY time ASC LIMIT 1"
    cur.execute(q_en)
    r_en = cur.fetchone()
    
    q_ex = f"SELECT price FROM scrapdata WHERE date='{d}' AND stockname IN ('{s}', '\"{s}\"') AND time >= '{d} 09:39:00' AND time <= '{d} 09:40:59' ORDER BY time DESC LIMIT 1"
    cur.execute(q_ex)
    r_ex = cur.fetchone()
    
    conn.close()
    
    if not r_en or not r_ex: return None
        
    en = float(r_en['price'])
    ex = float(r_ex['price'])
    if en <= 0: return None
    
    qty = int(500000.0 // en)
    gross = (en - ex) * qty
    net = gross - ((en + ex) * qty * 0.00035)
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
    print(f"| {y} | {trd} | {(wins/trd)*100:.1f}% | ₹{grp['gross'].sum()/100000:.2f}L | ₹{grp['net'].sum()/100000:.2f}L |")

wins = len(res_df[res_df['net'] > 0])
trd = len(res_df)
print(f"| TOTAL | {trd} | {(wins/trd)*100:.1f}% | ₹{res_df['gross'].sum()/100000:.2f}L | ₹{res_df['net'].sum()/100000:.2f}L |")
