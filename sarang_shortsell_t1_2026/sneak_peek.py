import pandas as pd
import pymysql
import os

BASE_DIR = '/home/ubuntu/sarang_shortsell_t1_2026/01_0920_Scalp_Model'

def get_taxes(qty, sell_price, buy_price):
    turnover = (qty * sell_price) + (qty * buy_price)
    stt = round(qty * sell_price * 0.00025)
    txn = turnover * 0.0000322
    sebi = turnover * 0.000001
    stamp = round(qty * buy_price * 0.00003)
    gst = (40.0 + txn + sebi) * 0.18
    return round(40.0 + stt + txn + sebi + stamp + gst, 2)

preds = pd.read_csv(os.path.join(BASE_DIR, '0920_predictions.csv'))
sample = preds.sample(50, random_state=42)

conn = pymysql.connect(host='localhost', user='root', password='root', database='markets', cursorclass=pymysql.cursors.DictCursor)

results = []
with conn.cursor() as cur:
    for _, row in sample.iterrows():
        d = row['short_date']
        s = row['clean_stock']
        
        cur.execute(f"SELECT time, price, high FROM scrapdata WHERE date='{d}' AND stockname LIKE '%{s}%' AND time>='{d} 09:22:00' AND time<='{d} 09:45:00' ORDER BY time ASC")
        ticks = cur.fetchall()
        
        if not ticks: continue
        
        sell_price = float(ticks[0]['price'] or 0)
        sell_time = str(ticks[0]['time'])
        if sell_price <= 0 or sell_time > f"{d} 09:25:59": continue
        
        qty = int(1000000.0 / sell_price)
        sl_price = round(sell_price * 1.03, 2)
        
        buy_price = None
        buy_time = None
        for t in ticks:
            t_time = str(t['time'])
            h = float(t['high'] or t['price'] or 0)
            if h >= sl_price:
                buy_price = sl_price
                buy_time = t_time
                break
            if t_time >= f"{d} 09:40:00":
                buy_price = float(t['price'] or 0)
                buy_time = t_time
                break
                
        if not buy_price:
            buy_price = float(ticks[-1]['price'] or 0)
            buy_time = str(ticks[-1]['time'])
            
        if buy_time > f"{d} 09:43:59": continue
            
        net_pnl = ((sell_price - buy_price) * qty) - get_taxes(qty, sell_price, buy_price)
        results.append(net_pnl)

conn.close()

if results:
    wins = sum(1 for p in results if p > 0)
    win_rate = (wins / len(results)) * 100
    total_pnl = sum(results)
    print(f"--- SNEAK PEEK (50 Random Trades) ---")
    print(f"Total Trades Executed: {len(results)}")
    print(f"Wins: {wins}")
    print(f"Win Rate: {win_rate:.2f}%")
    print(f"Net PnL (Sample): Rs {total_pnl:,.2f}")
else:
    print("No trades executed in sample.")
