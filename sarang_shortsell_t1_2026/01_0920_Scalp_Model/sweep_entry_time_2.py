import os
import pymysql
import pandas as pd
from concurrent.futures import ThreadPoolExecutor

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
preds = pd.read_csv(os.path.join(BASE_DIR, '0920_monthly_predictions.csv'))

def get_taxes(qty, sell_price, buy_price):
    turnover = (qty * sell_price) + (qty * buy_price)
    stt = round(qty * sell_price * 0.00025)
    txn = turnover * 0.0000322
    sebi = turnover * 0.000001
    stamp = round(qty * buy_price * 0.00003)
    gst = (40.0 + txn + sebi) * 0.18
    return round(40.0 + stt + txn + sebi + stamp + gst, 2)

def audit_trade(args):
    row, entry_min = args
    d = row['short_date']
    s = row['clean_stock']
    
    conn = pymysql.connect(host='localhost', user='root', password='root', database='markets', cursorclass=pymysql.cursors.DictCursor)
    with conn.cursor() as cur:
        cur.execute(f"SELECT time, price, high FROM scrapdata WHERE date='{d}' AND stockname = '{s}' AND time>='{d} 09:{entry_min}:00' AND time<='{d} 09:45:00' ORDER BY time ASC")
        ticks = cur.fetchall()
    conn.close()
    
    if not ticks: return None
    
    sell_price = float(ticks[0]['price'] or 0)
    sell_time = str(ticks[0]['time'])
    if sell_price <= 0: return None
    if sell_time > f"{d} 09:{int(entry_min)+4:02d}:59": return None
    
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
        
    if buy_time > f"{d} 09:43:59":
        return None
        
    net_pnl = ((sell_price - buy_price) * qty) - get_taxes(qty, sell_price, buy_price)
    return net_pnl

for entry_min in ['25', '26', '27', '28']:
    print(f"\nEvaluating exactly 09:{entry_min}:00 Entry...")
    args_list = [(row, entry_min) for _, row in preds.iterrows()]
    results = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        for res in ex.map(audit_trade, args_list):
            if res is not None:
                results.append(res)
    
    total_pnl = sum(results)
    win_rate = sum([1 for r in results if r > 0]) / len(results) * 100
    print(f"➔ 09:{entry_min} Entry PnL: Rs {total_pnl/100000:.2f} Lakhs | Win Rate: {win_rate:.2f}% ({len(results)} trades)")

