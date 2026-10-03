import os, time, pymysql
import pandas as pd
from concurrent.futures import ThreadPoolExecutor

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TRADES_FILE = os.path.join(BASE_DIR, 'data', 'model1_predictions.csv')

def get_kotak_mis_charges(qty, sell_price, buy_price):
    sell_value = qty * sell_price
    buy_value = qty * buy_price
    turnover = sell_value + buy_value
    stt = round(sell_value * 0.00025)
    txn = turnover * 0.0000322
    sebi = turnover * 0.000001
    stamp = round(buy_value * 0.00003)
    gst = (txn + sebi) * 0.18
    return round(stt + txn + sebi + stamp + gst, 2)

def get_db_connection():
    return pymysql.connect(host='localhost', user='root', password='root', database='markets', autocommit=True)

def process_prediction(row):
    d = row['short_date']
    s = row['clean_stock']
    leveraged_capital = 500000.0
    
    conn = get_db_connection()
    cur = conn.cursor(pymysql.cursors.DictCursor)
    
    cur.execute(f"SELECT time, price, high, low, close FROM scrapdata WHERE date = '{d}' AND stockname IN ('{s}', '\"{s}\"', '{s} ') AND time >= '{d} 09:20:00' AND time <= '{d} 09:21:59' ORDER BY time ASC LIMIT 1")
    entry_tick = cur.fetchone()
    if not entry_tick or not float(entry_tick['price'] or entry_tick['close'] or 0) > 0:
        conn.close()
        return {'net_pnl': 0.0, 'valid': False}
        
    en = float(entry_tick['price'] or entry_tick['close'])
    en_time = entry_tick['time']
    qty = int(leveraged_capital // en)
    
    cur.execute(f"SELECT time, price, high, low, close FROM scrapdata WHERE date = '{d}' AND stockname IN ('{s}', '\"{s}\"', '{s} ') AND time >= '{en_time}' AND time <= '{d} 09:41:59' ORDER BY time ASC")
    ticks = cur.fetchall()
    
    sl = round(en * 1.03, 2)
    tp = round(en * 0.95, 2) # 5% Take Profit
    hit, ex = False, None
    
    for t in ticks:
        if float(t['high'] or t['price'] or 0) >= sl:
            hit, ex = True, sl
            break
        if float(t['low'] or t['price'] or 0) <= tp:
            hit, ex = True, tp
            break
            
    if not hit:
        cur.execute(f"SELECT time, price, high, low, close FROM scrapdata WHERE date = '{d}' AND stockname IN ('{s}', '\"{s}\"', '{s} ') AND time >= '{d} 09:40:00' AND time <= '{d} 09:41:59' ORDER BY time DESC LIMIT 1")
        exit_tick = cur.fetchone()
        if not exit_tick:
            conn.close()
            return {'net_pnl': 0.0, 'valid': False}
        ex = float(exit_tick['close'] or exit_tick['price'])
        
    gross = (en - ex) * qty
    taxes = get_kotak_mis_charges(qty, en, ex)
    net = round(gross - taxes, 2)
    conn.close()
    return {'net_pnl': net, 'valid': True}

df = pd.read_csv(TRADES_FILE)
results = []
with ThreadPoolExecutor(max_workers=20) as executor:
    futures = [executor.submit(process_prediction, r) for _, r in df.iterrows()]
    for f in futures:
        res = f.result()
        if res['valid']: results.append(res)
            
valid = pd.DataFrame(results)
wins = len(valid[valid['net_pnl'] > 0])
win_rate = wins / len(valid) * 100
total_pnl = valid['net_pnl'].sum()

print(f"Model 1 (3% SL, 5% TP) | WinRate: {win_rate:.2f}% | PnL: {total_pnl:,.2f}")
