import os
import time
import pymysql
import pandas as pd
from concurrent.futures import ThreadPoolExecutor

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TRADES_FILE = os.path.join(BASE_DIR, 'data', 'model2_predictions.csv')
OUTPUT_FILE = os.path.join(BASE_DIR, 'output', 'model2_cash_audited_pnl.csv')

def get_kotak_mis_charges(qty, sell_price, buy_price):
    sell_value = qty * sell_price
    buy_value = qty * buy_price
    turnover = sell_value + buy_value
    
    brokerage = 0.0
    stt = round(sell_value * 0.00025)
    txn_charge = turnover * 0.0000322
    sebi_charge = turnover * 0.000001
    stamp_duty = round(buy_value * 0.00003)
    gst = (brokerage + txn_charge + sebi_charge) * 0.18
    
    return round(brokerage + stt + txn_charge + sebi_charge + stamp_duty + gst, 2)

def get_db_connection():
    return pymysql.connect(host='localhost', user='root', password='root', database='markets', autocommit=True)

def process_prediction(row):
    d = row['date']
    s = row['stockname']
    base_capital = 100000.0
    leveraged_capital = base_capital * 5.0
    
    conn = get_db_connection()
    cur = conn.cursor(pymysql.cursors.DictCursor)
    
    cur.execute(f"SELECT time, price, high, low, close FROM scrapdata WHERE date = '{d}' AND stockname IN ('{s}', '\"{s}\"', '{s} ') AND time >= '{d} 09:42:00' AND time <= '{d} 09:43:59' ORDER BY time ASC LIMIT 1")
    entry_tick = cur.fetchone()
    
    if not entry_tick or not float(entry_tick['price'] or entry_tick['close'] or 0) > 0:
        conn.close()
        return {'date': d, 'stockname': s, 'exit_reason': 'SKIPPED_NO_ENTRY', 'net_pnl': 0.0}
        
    en = float(entry_tick['price'] or entry_tick['close'])
    en_time = entry_tick['time']
    qty = int(leveraged_capital // en)
    
    cur.execute(f"SELECT time, price, high, low, close FROM scrapdata WHERE date = '{d}' AND stockname IN ('{s}', '\"{s}\"', '{s} ') AND time >= '{en_time}' AND time <= '{d} 14:45:59' ORDER BY time ASC")
    ticks = cur.fetchall()
    
    sl = round(en * 1.03, 2)
    hit, ex, ex_time, reason = False, None, None, None
    
    for t in ticks:
        if float(t['high'] or t['price'] or 0) >= sl:
            hit, ex, ex_time, reason = True, sl, t['time'], 'STOP_LOSS_3PCT'
            break
            
    if not hit:
        cur.execute(f"SELECT time, price, high, low, close FROM scrapdata WHERE date = '{d}' AND stockname IN ('{s}', '\"{s}\"', '{s} ') AND time >= '{d} 14:44:00' AND time <= '{d} 14:45:59' ORDER BY time DESC LIMIT 1")
        exit_tick = cur.fetchone()
        if not exit_tick:
            conn.close()
            return {'date': d, 'stockname': s, 'exit_reason': 'SKIPPED_NO_EXIT', 'net_pnl': 0.0}
        ex = float(exit_tick['close'] or exit_tick['price'])
        ex_time = exit_tick['time']
        reason = 'TIME_EXIT_1445'
        
    gross_pnl = (en - ex) * qty
    taxes = get_kotak_mis_charges(qty, en, ex)
    net_pnl = round(gross_pnl - taxes, 2)
    
    conn.close()
    return {
        'date': d, 'stockname': s, 'qty': qty, 'entry': en, 'exit': ex, 
        'gross_pnl': gross_pnl, 'taxes': taxes, 'net_pnl': net_pnl, 
        'exit_time': str(ex_time), 'exit_reason': reason
    }

print("--- REBUILDING MODEL 2 (09:42 -> 14:45) IN CASH (EQ) ---")
df = pd.read_csv(TRADES_FILE)
results = []
count = 0
start_time = time.time()
with ThreadPoolExecutor(max_workers=20) as executor:
    futures = [executor.submit(process_prediction, r) for _, r in df.iterrows()]
    for f in futures:
        results.append(f.result())
        count += 1
        if count % 500 == 0:
            print(f"Processed {count} / {len(df)}")
            
res_df = pd.DataFrame(results)
res_df.to_csv(OUTPUT_FILE, index=False)

valid = res_df[res_df['exit_reason'].str.startswith('SKIPPED') == False]
wins = valid[valid['net_pnl'] > 0]
win_rate = len(wins) / len(valid) * 100 if len(valid) > 0 else 0
total_pnl = valid['net_pnl'].sum()

print(f"\nCompleted! Valid Trades: {len(valid)}")
print(f"Win Rate: {win_rate:.2f}%")
print(f"Net PnL: Rs {total_pnl:,.2f}")
