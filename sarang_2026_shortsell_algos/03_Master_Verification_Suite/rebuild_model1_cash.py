import os
import time
import pymysql
import pandas as pd
from concurrent.futures import ThreadPoolExecutor

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TRADES_FILE = os.path.join(BASE_DIR, 'data', 'model1_predictions.csv')
OUTPUT_FILE = os.path.join(BASE_DIR, 'output', 'model1_cash_audited_pnl.csv')

def get_kotak_mis_charges(qty, sell_price, buy_price):
    sell_value = qty * sell_price
    buy_value = qty * buy_price
    turnover = sell_value + buy_value
    
    brokerage = 0.0
    stt = round(sell_value * 0.00025) # Revised Budget 2024 STT for Cash MIS
    txn_charge = turnover * 0.0000322
    sebi_charge = turnover * 0.000001
    stamp_duty = round(buy_value * 0.00003)
    gst = (brokerage + txn_charge + sebi_charge) * 0.18
    
    return round(brokerage + stt + txn_charge + sebi_charge + stamp_duty + gst, 2)

def get_db_connection():
    return pymysql.connect(host='localhost', user='root', password='root', database='markets', autocommit=True)

def process_prediction(row):
    d = row['short_date']
    s = row['clean_stock']
    base_capital = 100000.0 # 1 Lakh per stock
    leveraged_capital = base_capital * 5.0 # 5x Margin
    
    conn = get_db_connection()
    cur = conn.cursor(pymysql.cursors.DictCursor)
    
    # Strict Model 1 Entry: 09:20:00 to 09:21:59 (Cash)
    cur.execute(f"SELECT time, price, high, low, close FROM scrapdata WHERE date = '{d}' AND stockname IN ('{s}', '\"{s}\"', '{s} ') AND time >= '{d} 09:20:00' AND time <= '{d} 09:21:59' ORDER BY time ASC LIMIT 1")
    entry_tick = cur.fetchone()
    
    if not entry_tick or not float(entry_tick['price'] or entry_tick['close'] or 0) > 0:
        conn.close()
        return {'date': d, 'stockname': s, 'exit_reason': 'SKIPPED_NO_ENTRY', 'net_pnl': 0.0}
        
    en = float(entry_tick['price'] or entry_tick['close'])
    en_time = entry_tick['time']
    qty = int(leveraged_capital // en)
    
    # Fetch window for SL check
    cur.execute(f"SELECT time, price, high, low, close FROM scrapdata WHERE date = '{d}' AND stockname IN ('{s}', '\"{s}\"', '{s} ') AND time >= '{en_time}' AND time <= '{d} 09:41:59' ORDER BY time ASC")
    ticks = cur.fetchall()
    
    sl = round(en * 1.03, 2)
    hit, ex, ex_time, reason = False, None, None, None
    
    for t in ticks:
        if float(t['high'] or t['price'] or 0) >= sl:
            hit, ex, ex_time, reason = True, sl, t['time'], 'STOP_LOSS_3PCT'
            break
            
    if not hit:
        # Strict Model 1 Exit: 09:40:00 to 09:41:59 (Cash)
        cur.execute(f"SELECT time, price, high, low, close FROM scrapdata WHERE date = '{d}' AND stockname IN ('{s}', '\"{s}\"', '{s} ') AND time >= '{d} 09:40:00' AND time <= '{d} 09:41:59' ORDER BY time DESC LIMIT 1")
        exit_tick = cur.fetchone()
        if not exit_tick:
            conn.close()
            return {'date': d, 'stockname': s, 'exit_reason': 'SKIPPED_NO_EXIT', 'net_pnl': 0.0}
        ex = float(exit_tick['close'] or exit_tick['price'])
        ex_time = exit_tick['time']
        reason = 'TIME_EXIT'

    conn.close()
    
    gross = (en - ex) * qty
    charges = get_kotak_mis_charges(qty, en, ex)
    return {
        'date': d, 'stockname': s, 'segment': 'CASH', 'capital': base_capital, 'qty': qty,
        'entry_time': str(en_time), 'entry_price': en,
        'exit_time': str(ex_time), 'exit_price': ex,
        'exit_reason': reason,
        'gross_pnl': round(gross, 2), 'charges': charges, 'net_pnl': round(gross - charges, 2)
    }

def main():
    print("--- REBUILDING MODEL 1 (09:20 -> 09:40) IN CASH (EQ) ---")
    trades = pd.read_csv(TRADES_FILE).to_dict('records')
    results = []
    with ThreadPoolExecutor(max_workers=50) as executor:
        for i, res in enumerate(executor.map(process_prediction, trades)):
            results.append(res)
            if (i+1) % 1000 == 0: print(f"Processed {i+1} / {len(trades)}")
            
    res_df = pd.DataFrame(results)
    res_df.to_csv(OUTPUT_FILE, index=False)
    
    valid_df = res_df[~res_df['exit_reason'].str.startswith('SKIPPED')]
    wins = len(valid_df[valid_df['net_pnl'] > 0])
    print(f"\nCompleted! Valid Trades: {len(valid_df)}")
    print(f"Win Rate: {(wins/len(valid_df))*100:.2f}%")
    print(f"Net PnL: Rs {valid_df['net_pnl'].sum():,.2f}\n")

if __name__ == '__main__':
    main()
