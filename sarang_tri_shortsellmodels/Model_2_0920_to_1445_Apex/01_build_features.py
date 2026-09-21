import pymysql, pd, numpy as np, os, time
csv_path = 'model2_features.csv'
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
    
    m_feat = df[(df['time'] >= f'{d} 09:15:00') & (df['time'] <= f'{d} 09:19:59')]
    m_ent = df[(df['time'] >= f'{d} 09:22:00') & (df['time'] <= f'{d} 09:24:59')]
    m_ext = df[(df['time'] >= f'{d} 14:45:00') & (df['time'] <= f'{d} 14:47:59')]
    if m_feat.empty or m_ent.empty or m_ext.empty: continue
    
    res = pd.DataFrame({'stockname': df['stockname'].unique()})
    res = res.merge(m_feat.groupby('stockname').first().reset_index()[['stockname', 'price']].rename(columns={'price': 'open_price'}), on='stockname', how='left')
    res = res.merge(m_feat.groupby('stockname').last().reset_index()[['stockname', 'price']].rename(columns={'price': 'morning_close'}), on='stockname', how='left')
    res = res.merge(m_feat.groupby('stockname')['volume'].sum().reset_index().rename(columns={'volume': 'morning_volume'}), on='stockname', how='left')
    res = res.merge(m_ent.groupby('stockname').first().reset_index()[['stockname', 'price']].rename(columns={'price': 'entry_price'}), on='stockname', how='left')
    res = res.merge(m_ext.groupby('stockname').first().reset_index()[['stockname', 'price']].rename(columns={'price': 'exit_price'}), on='stockname', how='left')
    
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
