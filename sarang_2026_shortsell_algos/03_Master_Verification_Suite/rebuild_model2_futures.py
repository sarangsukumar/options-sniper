import os
import time
import pymysql
import pandas as pd
from concurrent.futures import ThreadPoolExecutor

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TRADES_FILE = os.path.join(BASE_DIR, 'data', 'model2_predictions.csv')
LOTS_FILE = os.path.join(BASE_DIR, 'data', 'historical_lotsize_new.csv')
OUTPUT_FILE = os.path.join(BASE_DIR, 'output', 'model2_futures_audited_pnl.csv')

def get_kotak_f1_charges(qty, sell_price, buy_price, num_lots):
    sell_value = qty * sell_price
    buy_value = qty * buy_price
    turnover = sell_value + buy_value
    
    flat_commission = 600 * num_lots
    stt = round(sell_value * 0.0002) # Revised Budget 2024 STT for Futures
    txn_charge = turnover * 0.000019
    sebi_charge = turnover * 0.000001
    stamp_duty = round(buy_value * 0.00002)
    gst = (flat_commission + txn_charge + sebi_charge) * 0.18
    
    return round(flat_commission + stt + txn_charge + sebi_charge + stamp_duty + gst, 2)

print("Loading lotsize database...")
df_lots = pd.read_csv(LOTS_FILE)
df_lots['exp_dt'] = pd.to_datetime(df_lots['expdate'], format='%d/%m/%Y', errors='coerce')

def get_db_connection():
    return pymysql.connect(host='localhost', user='root', password='root', database='markets', autocommit=True)

def process_prediction(row):
    d = row['date']
    s = row['stockname']
    
    base_capital = 200000.0 if row.get('lots_to_trade', 1) >= 2 else 100000.0
    leveraged_capital = base_capital * 5.0
    
    valid_lots = df_lots[(df_lots['stockname'] == s) & (df_lots['exp_dt'] >= pd.to_datetime(d))].sort_values('exp_dt')
    if valid_lots.empty:
        return {'date': d, 'stockname': s, 'exit_reason': 'SKIPPED_NO_LOTSIZE', 'net_pnl': 0.0}
    true_lotsize = int(valid_lots.iloc[0]['lotsize'])
    
    conn = get_db_connection()
    cur = conn.cursor(pymysql.cursors.DictCursor)
    
    # Strict Model 2 Entry: 09:42 to 09:44 (Futures F1)
    cur.execute(f"SELECT time, price, high, low, close FROM scrapdata_F1 WHERE date = '{d}' AND stockname IN ('{s}', '\"{s}\"', '{s} ') AND is_future='F1' AND time >= '{d} 09:42:00' AND time <= '{d} 09:44:59' ORDER BY time ASC LIMIT 1")
    entry_tick = cur.fetchone()
    
    if not entry_tick or not float(entry_tick['price'] or entry_tick['close'] or 0) > 0:
        conn.close()
        return {'date': d, 'stockname': s, 'exit_reason': 'SKIPPED_NO_F1_ENTRY', 'net_pnl': 0.0}
        
    en = float(entry_tick['price'] or entry_tick['close'])
    en_time = entry_tick['time']
    
    max_shares = int(leveraged_capital // en)
    num_lots = max_shares // true_lotsize
    if num_lots < 1:
        conn.close()
        return {'date': d, 'stockname': s, 'exit_reason': 'SKIPPED_CAPITAL_TOO_LOW', 'net_pnl': 0.0}
        
    qty = num_lots * true_lotsize
    
    # Fetch window for SL check
    cur.execute(f"SELECT time, price, high, low, close FROM scrapdata_F1 WHERE date = '{d}' AND stockname IN ('{s}', '\"{s}\"', '{s} ') AND is_future='F1' AND time >= '{en_time}' AND time <= '{d} 14:47:59' ORDER BY time ASC")
    ticks = cur.fetchall()
    
    sl = round(en * 1.03, 2)
    hit, ex, ex_time, reason = False, None, None, None
    
    for t in ticks:
        if float(t['high'] or t['price'] or 0) >= sl:
            hit, ex, ex_time, reason = True, sl, t['time'], 'STOP_LOSS_3PCT'
            break
            
    if not hit:
        # Strict Model 2 Exit: 14:45 to 14:47 (Futures F1)
        cur.execute(f"SELECT time, price, high, low, close FROM scrapdata_F1 WHERE date = '{d}' AND stockname IN ('{s}', '\"{s}\"', '{s} ') AND is_future='F1' AND time >= '{d} 14:45:00' AND time <= '{d} 14:47:59' ORDER BY time DESC LIMIT 1")
        exit_tick = cur.fetchone()
        if not exit_tick:
            conn.close()
            return {'date': d, 'stockname': s, 'exit_reason': 'SKIPPED_NO_F1_EXIT', 'net_pnl': 0.0}
        ex = float(exit_tick['close'] or exit_tick['price'])
        ex_time = exit_tick['time']
        reason = 'TIME_EXIT'

    conn.close()
    
    gross = (en - ex) * qty
    charges = get_kotak_f1_charges(qty, en, ex, num_lots)
    return {
        'date': d, 'stockname': s, 'segment': 'FUTURES', 'capital': base_capital, 'qty': qty, 'lots': num_lots,
        'entry_time': str(en_time), 'entry_price': en,
        'exit_time': str(ex_time), 'exit_price': ex,
        'exit_reason': reason,
        'gross_pnl': round(gross, 2), 'charges': charges, 'net_pnl': round(gross - charges, 2)
    }

def main():
    print("--- REBUILDING MODEL 2 (09:42 -> 14:45) IN FUTURES (F1) ---")
    trades = pd.read_csv(TRADES_FILE).to_dict('records')
    results = []
    with ThreadPoolExecutor(max_workers=50) as executor:
        for i, res in enumerate(executor.map(process_prediction, trades)):
            results.append(res)
            if (i+1) % 500 == 0: print(f"Processed {i+1} / {len(trades)}")
            
    res_df = pd.DataFrame(results)
    res_df.to_csv(OUTPUT_FILE, index=False)
    
    valid_df = res_df[~res_df['exit_reason'].str.startswith('SKIPPED')]
    wins = len(valid_df[valid_df['net_pnl'] > 0])
    print(f"\nCompleted! Valid Trades: {len(valid_df)}")
    print(f"Win Rate: {(wins/len(valid_df))*100:.2f}%")
    print(f"Net PnL: Rs {valid_df['net_pnl'].sum():,.2f}\n")

if __name__ == '__main__':
    main()
