import os
import time
import pymysql
import pandas as pd
from concurrent.futures import ThreadPoolExecutor

BASE_DIR = '/home/ubuntu/sarang_2026_shortsell_algos/01_Best_Shorter_Window_0920_0940'
TRADES_FILE = os.path.join(BASE_DIR, 'm1_dual_table_all_trades.csv')
OUTPUT_FILE = os.path.join(BASE_DIR, 'rebuilt_model1_strict_pnl.csv')

def get_kotak_mis_charges(qty, sell_price, buy_price):
    sell_value = qty * sell_price
    buy_value = qty * buy_price
    turnover = sell_value + buy_value
    
    brokerage = 0.0
    stt = round(sell_value * 0.00025) # Budget 2024 revised STT for MIS
    txn_charge = turnover * 0.0000322
    sebi_charge = turnover * 0.000001
    stamp_duty = round(buy_value * 0.00003)
    
    gst = (brokerage + txn_charge + sebi_charge) * 0.18
    
    total_charges = brokerage + stt + txn_charge + sebi_charge + stamp_duty + gst
    return round(total_charges, 2)

def get_db_connection():
    return pymysql.connect(host='localhost', user='root', password='root', database='markets', autocommit=True)

def process_prediction(row):
    d = row['short_date']
    s = row['clean_stock']
    
    # Capital allocation: 1 Lakh base (flat for all picks in Model 1)
    base_capital = 100000.0
    
    # Kotak Neo MIS Margin Multiplier (using 5x for F&O stocks)
    margin_multiplier = 5.0
    leveraged_capital = base_capital * margin_multiplier
    
    conn = get_db_connection()
    cur = conn.cursor(pymysql.cursors.DictCursor)
    
    # Strict Entry: 09:20 to 09:21
    q_entry = f"""
    SELECT time, price, high, low, close 
    FROM scrapdata 
    WHERE date = '{d}' AND stockname IN ('{s}', '\"{s}\"', '{s} ') 
      AND time >= '{d} 09:20:00' AND time <= '{d} 09:21:59' 
    ORDER BY time ASC LIMIT 1
    """
    cur.execute(q_entry)
    entry_tick = cur.fetchone()
    
    if not entry_tick:
        conn.close()
        return {
            'date': d, 'stockname': s, 'capital_used': base_capital, 'qty': 0,
            'entry_time': None, 'entry_price': None,
            'exit_time': None, 'exit_price': None,
            'exit_reason': 'SKIPPED_NO_ENTRY_TICK',
            'gross_pnl': 0.0, 'charges': 0.0, 'net_pnl': 0.0
        }
        
    en = float(entry_tick['price'] or entry_tick['close'] or entry_tick['open'] or 0)
    if en <= 0:
        conn.close()
        return {
            'date': d, 'stockname': s, 'capital_used': base_capital, 'qty': 0,
            'entry_time': None, 'entry_price': None,
            'exit_time': None, 'exit_price': None,
            'exit_reason': 'SKIPPED_ZERO_ENTRY_PRICE',
            'gross_pnl': 0.0, 'charges': 0.0, 'net_pnl': 0.0
        }

    en_time = entry_tick['time']
    
    # Calculate exact quantity based on margin
    qty = int(leveraged_capital // en)
    
    # Now get the ticks for the whole window to check 3% SL
    q_window = f"""
    SELECT time, price, high, low, close 
    FROM scrapdata 
    WHERE date = '{d}' AND stockname IN ('{s}', '\"{s}\"', '{s} ') 
      AND time >= '{en_time}' AND time <= '{d} 09:41:59' 
    ORDER BY time ASC
    """
    cur.execute(q_window)
    ticks = cur.fetchall()
    
    sl = round(en * 1.03, 2)
    hit = False
    ex = None
    ex_time = None
    reason = None
    
    for t in ticks:
        h = float(t['high'] or t['price'] or 0)
        # Check SL breach
        if h >= sl:
            hit = True
            ex = sl
            ex_time = t['time']
            reason = 'STOP_LOSS_3PCT'
            break
            
    if not hit:
        # Strict Exit: Must be in 09:40 to 09:41
        q_exit = f"""
        SELECT time, price, high, low, close 
        FROM scrapdata 
        WHERE date = '{d}' AND stockname IN ('{s}', '\"{s}\"', '{s} ') 
          AND time >= '{d} 09:40:00' AND time <= '{d} 09:41:59' 
        ORDER BY time DESC LIMIT 1
        """
        cur.execute(q_exit)
        exit_tick = cur.fetchone()
        
        if not exit_tick:
            conn.close()
            return {
                'date': d, 'stockname': s, 'capital_used': base_capital, 'qty': qty,
                'entry_time': str(en_time), 'entry_price': en,
                'exit_time': None, 'exit_price': None,
                'exit_reason': 'SKIPPED_NO_EXIT_TICK',
                'gross_pnl': 0.0, 'charges': 0.0, 'net_pnl': 0.0
            }
            
        ex = float(exit_tick['close'] or exit_tick['price'] or exit_tick['open'] or 0)
        ex_time = exit_tick['time']
        reason = 'TIME_EXIT'

    conn.close()
    
    gross_pnl = (en - ex) * qty
    charges = get_kotak_mis_charges(qty, sell_price=en, buy_price=ex)
    net_pnl = gross_pnl - charges
    
    return {
        'date': d, 'stockname': s, 'capital_used': base_capital, 'qty': qty,
        'entry_time': str(en_time), 'entry_price': en,
        'exit_time': str(ex_time), 'exit_price': ex,
        'exit_reason': reason,
        'gross_pnl': round(gross_pnl, 2), 'charges': charges, 'net_pnl': round(net_pnl, 2)
    }

def main():
    if not os.path.exists(TRADES_FILE):
        print(f"Error: Trades file {TRADES_FILE} not found.")
        return
        
    df = pd.read_csv(TRADES_FILE)
    
    # We only take actual predictions (prob or something) or just the whole file.
    # The file m1_dual_table_all_trades.csv contains daily picks.
    trades = df.to_dict('records')
    
    results = []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=50) as executor:
        for idx, res in enumerate(executor.map(process_prediction, trades)):
            results.append(res)
            if (idx + 1) % 500 == 0:
                print(f"Processed {idx + 1} / {len(trades)} in {time.time()-t0:.1f}s")
                
    res_df = pd.DataFrame(results)
    res_df.to_csv(OUTPUT_FILE, index=False)
    
    total_trades = len(res_df)
    valid_df = res_df[~res_df['exit_reason'].str.startswith('SKIPPED_')]
    skipped_entry = len(res_df[res_df['exit_reason'] == 'SKIPPED_NO_ENTRY_TICK'])
    skipped_exit = len(res_df[res_df['exit_reason'] == 'SKIPPED_NO_EXIT_TICK'])
    
    wins = len(valid_df[valid_df['net_pnl'] > 0])
    win_rate = (wins / len(valid_df)) * 100 if len(valid_df) > 0 else 0
    
    gross = valid_df['gross_pnl'].sum()
    charges = valid_df['charges'].sum()
    net = valid_df['net_pnl'].sum()
    
    print("\n--- MODEL 1 STRICT REBUILD RESULTS (CASH EQ) ---")
    print(f"Total Predictions: {total_trades}")
    print(f"Valid Executed Trades: {len(valid_df)}")
    print(f"Skipped (No Entry Tick 09:20-09:21): {skipped_entry}")
    print(f"Skipped (No Exit Tick 09:40-09:41): {skipped_exit}")
    print(f"Win Rate: {win_rate:.2f}%")
    print(f"Total Gross: ₹ {gross:,.2f}")
    print(f"Total Kotak Charges: ₹ {charges:,.2f}")
    print(f"Total NET PnL: ₹ {net:,.2f}")
    print("\nYearly Breakdown:")
    
    valid_df['year'] = pd.to_datetime(valid_df['date']).dt.year
    print(valid_df.groupby('year')[['gross_pnl', 'charges', 'net_pnl']].sum().applymap(lambda x: f"₹ {x/100000:,.2f}L"))

if __name__ == '__main__':
    main()
