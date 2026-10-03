import pymysql
import pandas as pd
import numpy as np

def get_db():
    return pymysql.connect(host='localhost', user='root', password='root', database='markets', autocommit=True)

conn = get_db()
cur = conn.cursor(pymysql.cursors.DictCursor)

df_rep = pd.read_csv('/home/ubuntu/sarang_2026_shortsell_algos/df_with_rep.csv', nrows=10)

print("Testing Dual Tick Separation for 10 Trades:")
print("=" * 85)

for idx, r in df_rep.iterrows():
    d = r['date_str'][:10]
    s = r['clean_stock']
    en = float(r['entry_price'])
    mult = min(2, int(r['lots_multiplier']))
    qty = int(r['lotsize']) * mult
    
    # F1 ticks
    cur.execute(f"""
    SELECT time, price, high, low, close 
    FROM scrapdata_F1 
    WHERE date = '{d}' AND stockname IN ('{s}', '\"{s}\"', '{s} ')
      AND time >= '{d} 09:42:00' AND time <= '{d} 14:45:59'
    ORDER BY time ASC
    """)
    ticks_f1 = cur.fetchall()
    
    # EQ ticks
    cur.execute(f"""
    SELECT time, price, high, low, close 
    FROM scrapdata 
    WHERE date = '{d}' AND stockname IN ('{s}', '\"{s}\"', '{s} ')
      AND time >= '{d} 09:42:00' AND time <= '{d} 14:45:59'
    ORDER BY time ASC
    """)
    ticks_eq = cur.fetchall()
    
    en_f1 = float(ticks_f1[0]['price']) if ticks_f1 else en
    ex_f1 = float(ticks_f1[-1]['close']) if ticks_f1 else en
    gross_f1 = (en_f1 - ex_f1) * qty
    
    en_eq = float(ticks_eq[0]['price']) if ticks_eq else en
    ex_eq = float(ticks_eq[-1]['close']) if ticks_eq else en
    gross_eq = (en_eq - ex_eq) * qty
    
    print(f"{d} {s:<10} | F1: en={en_f1:>7.2f}, ex={ex_f1:>7.2f}, gross=Rs {gross_f1:>8.1f} | EQ: en={en_eq:>7.2f}, ex={ex_eq:>7.2f}, gross=Rs {gross_eq:>8.1f} | Diff: Rs {gross_f1 - gross_eq:>+7.1f}")

conn.close()
