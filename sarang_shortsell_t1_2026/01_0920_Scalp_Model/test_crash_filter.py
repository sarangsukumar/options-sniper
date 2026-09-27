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

def audit_trade(row):
    d = row['short_date']
    s = row['clean_stock']
    
    conn = pymysql.connect(host='localhost', user='root', password='root', database='markets', cursorclass=pymysql.cursors.DictCursor)
    with conn.cursor() as cur:
        cur.execute(f"SELECT time, price, high FROM scrapdata WHERE date='{d}' AND stockname = '{s}' AND time>='{d} 09:19:00' AND time<='{d} 09:45:00' ORDER BY time ASC")
        ticks = cur.fetchall()
    conn.close()
    
    if not ticks: return None
    
    # 1. Measure the 09:19 to 09:24 crash!
    p_19 = None
    p_24 = None
    
    for t in ticks:
        t_time = str(t['time'])
        if t_time >= f"{d} 09:19:00" and p_19 is None:
            p_19 = float(t['price'] or 0)
        if t_time >= f"{d} 09:24:00" and p_24 is None:
            p_24 = float(t['price'] or 0)
            break
            
    if not p_19 or not p_24 or p_19 <= 0: return None
    crash_pct = ((p_24 - p_19) / p_19) * 100.0
    
    # 2. Proceed with 09:25 Entry Execution
    sell_price = None
    sell_time = None
    for t in ticks:
        t_time = str(t['time'])
        if t_time >= f"{d} 09:25:00":
            sell_price = float(t['price'] or 0)
            sell_time = t_time
            break
            
    if not sell_price or sell_price <= 0: return None
    if sell_time > f"{d} 09:29:59": return None # Missed entry
    
    qty = int(1000000.0 / sell_price)
    sl_price = round(sell_price * 1.03, 2)
    
    buy_price = None
    buy_time = None
    for t in ticks:
        t_time = str(t['time'])
        if t_time <= sell_time: continue # Ignore ticks before entry
        
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
        
    net_pnl = ((sell_price - buy_price) * qty) - get_taxes(qty, sell_price, buy_price)
    
    return {
        'Date': d, 'Stock': s, 'crash_pct': crash_pct, 'Net_PnL': net_pnl
    }

print("\nScanning 09:19-09:24 Exhaustion Filters...")
args_list = [row for _, row in preds.iterrows()]
results = []
with ThreadPoolExecutor(max_workers=20) as ex:
    for res in ex.map(audit_trade, args_list):
        if res is not None:
            results.append(res)

df_res = pd.DataFrame(results)

print("\n--- PNL IMPACT OF SKIPPING EXHAUSTED STOCKS ---")
for threshold in [0, -0.5, -1.0, -1.5, -2.0, -2.5, -3.0]:
    # We skip trades where the crash is WORSE (more negative) than the threshold
    filtered = df_res[df_res['crash_pct'] >= threshold]
    total_pnl = filtered['Net_PnL'].sum() / 100000.0
    win_rate = (filtered['Net_PnL'] > 0).mean() * 100
    skipped = len(df_res) - len(filtered)
    print(f"Skip if crashed > {abs(threshold):.1f}%: Rs {total_pnl:6.2f} L | {win_rate:.1f}% Win | Skipped {skipped} trades")

