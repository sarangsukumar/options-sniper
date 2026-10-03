import pandas as pd
import pymysql
from concurrent.futures import ThreadPoolExecutor, as_completed
import warnings
warnings.filterwarnings('ignore')

print("Loading Model 1 and Model 2 Trades...")
m1 = pd.read_csv('/home/ubuntu/sarang_2026_shortsell_algos/01_Best_Shorter_Window_0920_0940/audited_0920_0940_trades.csv')
m2 = pd.read_csv('/home/ubuntu/sarang_2026_shortsell_algos/02_Best_Longer_Window_0942_1445/audited_0940_hybrid_trades.csv')

def get_connection():
    return pymysql.connect(host='localhost', user='root', password='root', database='markets')

def simulate_m1(batch):
    conn = get_connection()
    cursor = conn.cursor(pymysql.cursors.DictCursor)
    results = []
    for _, row in batch.iterrows():
        d = row['short_date']
        s = row['clean_stock']
        ls = float(row['dynamic_lotsize'])
        
        # Eq
        cursor.execute(f"SELECT price FROM scrapdata WHERE date='{d}' AND stockname='{s}' AND time >= '{d} 09:21:00' AND price IS NOT NULL ORDER BY time ASC LIMIT 1")
        res_e = cursor.fetchone()
        eq_e = float(res_e['price']) if res_e and res_e['price'] is not None else None
        
        cursor.execute(f"SELECT price FROM scrapdata WHERE date='{d}' AND stockname='{s}' AND time >= '{d} 09:41:00' AND price IS NOT NULL ORDER BY time ASC LIMIT 1")
        res_x = cursor.fetchone()
        eq_x = float(res_x['price']) if res_x and res_x['price'] is not None else None
        
        eq_pnl = (eq_e - eq_x) * ls if eq_e and eq_x else 0
        
        # Fut
        cursor.execute(f"SELECT price FROM scrapdata_F1 WHERE date='{d}' AND stockname='{s}' AND is_future='F1' AND time >= '{d} 09:21:00' AND price IS NOT NULL ORDER BY time ASC LIMIT 1")
        res_fe = cursor.fetchone()
        fut_e = float(res_fe['price']) if res_fe and res_fe['price'] is not None else None
        
        cursor.execute(f"SELECT price FROM scrapdata_F1 WHERE date='{d}' AND stockname='{s}' AND is_future='F1' AND time >= '{d} 09:41:00' AND price IS NOT NULL ORDER BY time ASC LIMIT 1")
        res_fx = cursor.fetchone()
        fut_x = float(res_fx['price']) if res_fx and res_fx['price'] is not None else None
        
        fut_pnl = (fut_e - fut_x) * ls if fut_e and fut_x else 0
        
        results.append({'date': d, 'stock': s, 'eq_pnl': eq_pnl, 'fut_pnl': fut_pnl, 'has_f1': 1 if fut_e and fut_x else 0})
    conn.close()
    return results

def simulate_m2(batch):
    conn = get_connection()
    cursor = conn.cursor(pymysql.cursors.DictCursor)
    results = []
    for _, row in batch.iterrows():
        d = row['date']
        s = row['stockname']
        ls = float(row['total_quantity'])
        
        # EQ
        cursor.execute(f"SELECT price FROM scrapdata WHERE date='{d}' AND stockname='{s}' AND time >= '{d} 09:42:00' AND time <= '{d} 14:45:59' AND price IS NOT NULL ORDER BY time ASC")
        eq_ticks = cursor.fetchall()
        eq_pnl = 0
        if eq_ticks and len(eq_ticks) > 0:
            prices = [float(t['price']) for t in eq_ticks if t['price'] is not None]
            if prices:
                entry = prices[0]
                sl = entry * 1.03
                exit_p = prices[-1]
                for p in prices:
                    if p >= sl:
                        exit_p = sl
                        break
                eq_pnl = (entry - exit_p) * ls
                
        # FUT
        cursor.execute(f"SELECT price FROM scrapdata_F1 WHERE date='{d}' AND stockname='{s}' AND is_future='F1' AND time >= '{d} 09:42:00' AND time <= '{d} 14:45:59' AND price IS NOT NULL ORDER BY time ASC")
        fut_ticks = cursor.fetchall()
        fut_pnl = 0
        has_f1 = 0
        if fut_ticks and len(fut_ticks) > 0:
            prices = [float(t['price']) for t in fut_ticks if t['price'] is not None]
            if prices:
                has_f1 = 1
                entry = prices[0]
                sl = entry * 1.03
                exit_p = prices[-1]
                for p in prices:
                    if p >= sl:
                        exit_p = sl
                        break
                fut_pnl = (entry - exit_p) * ls
                
        results.append({'date': d, 'stock': s, 'eq_pnl': eq_pnl, 'fut_pnl': fut_pnl, 'has_f1': has_f1})
    conn.close()
    return results

print("Simulating Model 1 (09:20 Scalp)...")
m1_chunks = [m1.iloc[i:i+500] for i in range(0, len(m1), 500)]
m1_res = []
with ThreadPoolExecutor(max_workers=50) as executor:
    for f in as_completed([executor.submit(simulate_m1, c) for c in m1_chunks]):
        m1_res.extend(f.result())

m1_df = pd.DataFrame(m1_res)

print("Simulating Model 2 (09:42 Extended)...")
m2_chunks = [m2.iloc[i:i+500] for i in range(0, len(m2), 500)]
m2_res = []
with ThreadPoolExecutor(max_workers=50) as executor:
    for f in as_completed([executor.submit(simulate_m2, c) for c in m2_chunks]):
        m2_res.extend(f.result())

m2_df = pd.DataFrame(m2_res)

print("\n=======================================================")
print("MODEL 1 (09:20 -> 09:40 SCALP)")
print(f"Trades with F1 Data: {m1_df['has_f1'].sum()}")
m1_f1_only = m1_df[m1_df['has_f1'] == 1]
print(f"Equity (scrapdata) Gross PnL  : Rs {m1_f1_only['eq_pnl'].sum():,.2f}")
print(f"Futures (scrapdata_F1) Gross PnL: Rs {m1_f1_only['fut_pnl'].sum():,.2f}")
print("=======================================================")
print("MODEL 2 (09:42 -> 14:45 EXTENDED + 3% SL)")
print(f"Trades with F1 Data: {m2_df['has_f1'].sum()}")
m2_f1_only = m2_df[m2_df['has_f1'] == 1]
print(f"Equity (scrapdata) Gross PnL  : Rs {m2_f1_only['eq_pnl'].sum():,.2f}")
print(f"Futures (scrapdata_F1) Gross PnL: Rs {m2_f1_only['fut_pnl'].sum():,.2f}")
print("=======================================================")
