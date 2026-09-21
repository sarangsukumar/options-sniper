import pymysql, pandas as pd, numpy as np, os, time
csv_path = 'model1_features.csv'
processed = set(pd.read_csv(csv_path)['date'].unique()) if os.path.exists(csv_path) else set()
dates = pd.to_datetime(pd.read_csv('/home/ubuntu/github_repo/shortsellmodel940v3/short_sell_ml_dataset_v3.csv.gz')['short_sell_date']).dt.strftime('%Y-%m-%d').unique()
dates = [d for d in sorted(dates) if d >= '2015-01-01' and d not in processed]

db = pymysql.connect(host='localhost', user='root', password='root', database='markets', cursorclass=pymysql.cursors.DictCursor)
cur = db.cursor()
for i, d in enumerate(dates):
    cur.execute(f"SELECT stockname, time, price, volume FROM scrapdata WHERE date = '{d}' AND time <= '{d} 14:47:59'")
    rows = cur.fetchall()
    if not rows: continue
    df = pd.DataFrame(rows)
    df = df.sort_values('time')
    
    # Isolate timeframes
    m_feat = df[(df['time'] >= f'{d} 09:15:00') & (df['time'] <= f'{d} 09:40:59')]
    m_ent = df[(df['time'] >= f'{d} 09:42:00') & (df['time'] <= f'{d} 09:44:59')]
    m_ext = df[(df['time'] >= f'{d} 14:45:00') & (df['time'] <= f'{d} 14:47:59')]
    
    if m_feat.empty or m_ent.empty or m_ext.empty: continue
    
    res = pd.DataFrame({
        'stockname': df['stockname'].unique()
    })
    
    # 1. True Open Price (First tick >= 09:15)
    first_ticks = m_feat.groupby('stockname').first().reset_index()
    res = res.merge(first_ticks[['stockname', 'price']].rename(columns={'price': 'open_price'}), on='stockname', how='left')
    
    # 2. Morning Close (Last tick <= 09:40:59)
    last_ticks = m_feat.groupby('stockname').last().reset_index()
    res = res.merge(last_ticks[['stockname', 'price']].rename(columns={'price': 'morning_close'}), on='stockname', how='left')
    
    # 3. Morning Volume Sum
    vols = m_feat.groupby('stockname')['volume'].sum().reset_index().rename(columns={'volume': 'morning_volume'})
    res = res.merge(vols, on='stockname', how='left')
    
    # 4. Entry Price (FIRST tick in 09:42 window)
    first_ent = m_ent.groupby('stockname').first().reset_index()
    res = res.merge(first_ent[['stockname', 'price']].rename(columns={'price': 'entry_price'}), on='stockname', how='left')
    
    # 5. Exit Price (FIRST tick in 14:45 window)
    first_ext = m_ext.groupby('stockname').first().reset_index()
    res = res.merge(first_ext[['stockname', 'price']].rename(columns={'price': 'exit_price'}), on='stockname', how='left')
    
    res = res.dropna()
    res = res[res['open_price'] > 50.0].copy()
    if res.empty: continue
    
    res['Gap_Pct'] = ((res['open_price'] - res['morning_close']) / res['open_price']) * 100.0 
    res['morning_return'] = ((res['morning_close'] - res['open_price']) / res['open_price']) * 100.0
    res['Daily_Volume_Rank'] = res['morning_volume'].rank(ascending=False, method='min')
    res['Daily_Momentum_Rank'] = res['morning_return'].rank(ascending=False, method='min')
    res['target'] = (((res['entry_price'] - res['exit_price']) / res['entry_price']) > 0).astype(int)
    res['date'] = d
    
    res.to_csv(csv_path, mode='a', header=not os.path.exists(csv_path), index=False)
db.close()
