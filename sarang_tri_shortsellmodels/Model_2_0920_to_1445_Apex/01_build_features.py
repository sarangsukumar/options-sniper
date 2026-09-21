import pymysql, pd, numpy as np, os, time
csv_path = 'model2_features.csv'
processed = set(pd.read_csv(csv_path)['date'].unique()) if os.path.exists(csv_path) else set()
dates = pd.to_datetime(pd.read_csv('/home/ubuntu/github_repo/shortsellmodel940v3/short_sell_ml_dataset_v3.csv.gz')['short_sell_date']).dt.strftime('%Y-%m-%d').unique()
dates = [d for d in sorted(dates) if d >= '2015-01-01' and d not in processed]

db = pymysql.connect(host='localhost', user='root', password='root', database='markets', cursorclass=pymysql.cursors.DictCursor)
cur = db.cursor()
for i, d in enumerate(dates):
    q = f"""SELECT stockname, MIN(CASE WHEN time >= '{d} 09:15:00' THEN price END) as open_price,
               MAX(CASE WHEN time >= '{d} 09:19:00' AND time <= '{d} 09:19:59' THEN price END) as morning_close,
               SUM(CASE WHEN time >= '{d} 09:15:00' AND time <= '{d} 09:19:59' THEN volume END) as morning_volume,
               MAX(CASE WHEN time >= '{d} 09:22:00' AND time <= '{d} 09:24:59' THEN price END) as entry_price,
               MAX(CASE WHEN time >= '{d} 14:45:00' AND time <= '{d} 14:47:59' THEN price END) as exit_price
        FROM scrapdata WHERE date = '{d}' GROUP BY stockname"""
    cur.execute(q)
    rows = cur.fetchall()
    if not rows: continue
    df = pd.DataFrame(rows).dropna(subset=['open_price', 'morning_close', 'morning_volume', 'entry_price', 'exit_price'])
    df = df[df['open_price'] > 50.0].copy()
    if df.empty: continue
    df['Gap_Pct'] = ((df['open_price'] - df['morning_close']) / df['open_price']) * 100.0 
    df['morning_return'] = ((df['morning_close'] - df['open_price']) / df['open_price']) * 100.0
    df['Daily_Volume_Rank'] = df['morning_volume'].rank(ascending=False, method='min')
    df['Daily_Momentum_Rank'] = df['morning_return'].rank(ascending=False, method='min')
    df['target'] = (((df['entry_price'] - df['exit_price']) / df['entry_price']) > 0).astype(int)
    df['date'] = d
    df.to_csv(csv_path, mode='a', header=not os.path.exists(csv_path), index=False)
db.close()
