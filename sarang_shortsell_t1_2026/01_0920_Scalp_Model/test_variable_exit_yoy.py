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
    row, target_pct = args
    d = row['short_date']
    s = row['clean_stock']
    
    conn = pymysql.connect(host='localhost', user='root', password='root', database='markets', cursorclass=pymysql.cursors.DictCursor)
    with conn.cursor() as cur:
        cur.execute(f"SELECT time, price, high FROM scrapdata WHERE date='{d}' AND stockname = '{s}' AND time>='{d} 09:25:00' AND time<='{d} 09:42:00' ORDER BY time ASC")
        ticks = cur.fetchall()
    conn.close()
    
    if not ticks: return None
    
    sell_price = float(ticks[0]['price'] or 0)
    sell_time = str(ticks[0]['time'])
    if sell_price <= 0: return None
    
    qty = int(1000000.0 / sell_price)
    sl_price = round(sell_price * 1.03, 2)
    
    buy_price = None
    buy_time = None
    
    check_time_0936 = f"{d} 09:36:00"
    final_exit_time = f"{d} 09:40:00"
    
    price_at_0936 = None
    
    for t in ticks:
        t_time = str(t['time'])
        if t_time <= sell_time: continue
        
        h = float(t['high'] or t['price'] or 0)
        if h >= sl_price:
            buy_price = sl_price
            buy_time = t_time
            break
            
        if t_time >= check_time_0936 and price_at_0936 is None:
            price_at_0936 = float(t['price'] or 0)
            
        if t_time >= final_exit_time:
            break
            
    if buy_price is None:
        if price_at_0936 is not None:
            current_profit_pct = ((sell_price - price_at_0936) / sell_price) * 100.0
            
            if current_profit_pct >= target_pct:
                buy_price = price_at_0936
                buy_time = check_time_0936
            else:
                for t in ticks:
                    t_time = str(t['time'])
                    if t_time < check_time_0936: continue
                    h = float(t['high'] or t['price'] or 0)
                    if h >= sl_price:
                        buy_price = sl_price
                        buy_time = t_time
                        break
                    if t_time >= final_exit_time:
                        buy_price = float(t['price'] or 0)
                        buy_time = t_time
                        break
                        
    if not buy_price:
        buy_price = float(ticks[-1]['price'] or 0)
        buy_time = str(ticks[-1]['time'])
        
    net_pnl = ((sell_price - buy_price) * qty) - get_taxes(qty, sell_price, buy_price)
    
    return {
        'Date': d, 'Stock': s, 'Net_PnL': net_pnl
    }

print("\n--- 0.05% VARIABLE EXIT (YOY BREAKDOWN) ---")
args_list = [(row, 0.05) for _, row in preds.iterrows()]
results = []
with ThreadPoolExecutor(max_workers=30) as ex:
    for res in ex.map(audit_trade, args_list):
        if res is not None:
            results.append(res)
            
df_res = pd.DataFrame(results)
df_res['Year'] = pd.to_datetime(df_res['Date']).dt.year

print("==========================================================")
for y in sorted(df_res['Year'].unique()):
    sub = df_res[df_res['Year'] == y]
    pnl = sub['Net_PnL'].sum() / 100000.0
    win = (sub['Net_PnL'] > 0).mean() * 100.0
    print(f"  {y}: Rs {pnl:6.2f} L | {win:.1f}% Win | {len(sub)} trades")
print("----------------------------------------------------------")
print(f"  TOTAL: Rs {df_res['Net_PnL'].sum() / 100000.0:.2f} Lakhs")
print("==========================================================")

