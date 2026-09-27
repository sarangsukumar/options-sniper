import os
import pymysql
import pandas as pd
from concurrent.futures import ThreadPoolExecutor

BASE_DIR = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_shortsell_t1_2026/01_0920_Scalp_Model'
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
    
    check_time_start = f"{d} 09:36:00"
    final_exit_time = f"{d} 09:40:00"
    
    for t in ticks:
        t_time = str(t['time'])
        if t_time <= sell_time: continue
        
        # 1. Check Stop Loss always
        h = float(t['high'] or t['price'] or 0)
        if h >= sl_price:
            buy_price = sl_price
            buy_time = t_time
            break
            
        # 2. If we are in the trailing window (09:36 to 09:39), check for profit target
        if t_time >= check_time_start and t_time < final_exit_time:
            current_price = float(t['price'] or 0)
            current_profit_pct = ((sell_price - current_price) / sell_price) * 100.0
            if current_profit_pct >= target_pct:
                buy_price = current_price
                buy_time = t_time
                break
                
        # 3. Final Hard Exit at 09:40
        if t_time >= final_exit_time:
            buy_price = float(t['price'] or 0)
            buy_time = t_time
            break
            
    if not buy_price:
        buy_price = float(ticks[-1]['price'] or 0)
        buy_time = str(ticks[-1]['time'])
        
    net_pnl = ((sell_price - buy_price) * qty) - get_taxes(qty, sell_price, buy_price)
    
    return {
        'Date': d, 'Stock': s, 'Net_PnL': net_pnl, 'Exit_Time': buy_time
    }

target_pcts = [0.00, 0.05, 0.10, 0.15, 0.20, 0.25]

print("\n--- CONTINUOUS EXIT STRATEGY (Trailing from 09:36 to 09:40) ---")
for pct in target_pcts:
    args_list = [(row, pct) for _, row in preds.iterrows()]
    results = []
    with ThreadPoolExecutor(max_workers=30) as ex:
        for res in ex.map(audit_trade, args_list):
            if res is not None:
                results.append(res)
                
    df_res = pd.DataFrame(results)
    total_pnl = df_res['Net_PnL'].sum() / 100000.0
    win_rate = (df_res['Net_PnL'] > 0).mean() * 100
    print(f"Exit IMMEDIATELY if profit >= {pct:.2f}% during 09:36-09:39, ELSE hold to 09:40 => Total PnL: Rs {total_pnl:6.2f} Lakhs | Win Rate: {win_rate:.1f}%")
