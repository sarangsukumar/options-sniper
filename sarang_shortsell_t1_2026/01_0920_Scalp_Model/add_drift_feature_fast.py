import os
import pymysql
import pandas as pd
from concurrent.futures import ThreadPoolExecutor
import time
import threading

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
df = pd.read_csv(os.path.join(BASE_DIR, 'data/scalp_0920_ml_dataset.csv.gz'))

thread_local = threading.local()

def get_db_connection():
    if not hasattr(thread_local, "conn"):
        thread_local.conn = pymysql.connect(
            host='localhost', user='root', password='root', 
            database='markets', cursorclass=pymysql.cursors.DictCursor
        )
    return thread_local.conn

def get_drift(row):
    d = row['short_date']
    s = row['clean_stock']
    conn = get_db_connection()
    with conn.cursor() as cur:
        # Get prices between 09:19:00 and 09:24:00
        cur.execute(f"SELECT time, price FROM scrapdata WHERE date='{d}' AND stockname = '{s}' AND time>='{d} 09:18:00' AND time<='{d} 09:25:00' ORDER BY time ASC")
        ticks = cur.fetchall()
    
    if not ticks: return (row.name, 0.0)
    
    p_19 = None
    p_23 = None
    
    for t in ticks:
        t_time = str(t['time'])
        if t_time >= f"{d} 09:19:00" and p_19 is None:
            p_19 = float(t['price'] or 0)
        if t_time >= f"{d} 09:23:00" and p_23 is None:
            p_23 = float(t['price'] or 0)
            
    if not p_19 or not p_23 or p_19 <= 0:
        return (row.name, 0.0)
        
    drift = ((p_23 - p_19) / p_19) * 100.0
    return (row.name, drift)

print(f"Adding 09:19 -> 09:23 Drift Feature to {len(df)} rows using Thread-Local DB Connections...")
start = time.time()
drifts = {}
with ThreadPoolExecutor(max_workers=50) as ex:
    for idx, (r_idx, drift) in enumerate(ex.map(get_drift, [row for _, row in df.iterrows()])):
        drifts[r_idx] = drift
        if idx % 10000 == 0:
            print(f"Processed {idx}/{len(df)} rows... ({(time.time()-start):.1f}s)")

df['drift_0919_to_0923_pct'] = df.index.map(drifts)
out_path = os.path.join(BASE_DIR, 'data/scalp_0920_ml_dataset_with_drift.csv.gz')
df.to_csv(out_path, index=False, compression='gzip')
print(f"Saved new dataset to {out_path}!")
