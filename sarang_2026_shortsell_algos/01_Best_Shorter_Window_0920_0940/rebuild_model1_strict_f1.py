import os
import time
import pymysql
import pandas as pd
from concurrent.futures import ThreadPoolExecutor

BASE_DIR = '/home/ubuntu/sarang_2026_shortsell_algos/01_Best_Shorter_Window_0920_0940'
TRADES_FILE = os.path.join(BASE_DIR, 'm1_dual_table_all_trades.csv')
LOTS_FILE = os.path.join(BASE_DIR, 'data', 'historical_lotsize_new.csv')
OUTPUT_FILE = os.path.join(BASE_DIR, 'rebuilt_model1_strict_f1_pnl.csv')

def get_db_connection():
    return pymysql.connect(host='localhost', user='root', password='root', database='markets', autocommit=True)

print("Loading lotsize database...")
df_lots = pd.read_csv(LOTS_FILE)
df_lots['exp_dt'] = pd.to_datetime(df_lots['expdate'], format='%d/%m/%Y', errors='coerce')

def get_kotak_f1_charges(qty, sell_price, buy_price, flat_commission=600):
    sell_value = qty * sell_price
    buy_value = qty * buy_price
    turnover = sell_value + buy_value
    
    stt = round(sell_value * 0.0002) # Budget 2024 Futures STT
    txn_charge = turnover * 0.000019
    sebi_charge = turnover * 0.000001
    stamp_duty = round(buy_value * 0.00002)
    
    gst = (flat_commission + txn_charge + sebi_charge) * 0.18
    total_charges = flat_commission + stt + txn_charge + sebi_charge + stamp_duty + gst
    return round(total_charges, 2)

def process_prediction(row):
    d = row['short_date']
    s = row['clean_stock']
    base_capital = 100000.0
    leveraged_capital = base_capital * 5.0
    
    date_dt = pd.to_datetime(d)
    valid_lots = df_lots[(df_lots['stockname'] == s) & (df_lots['exp_dt'] >= date_dt)].sort_values('exp_dt')
    
    if valid_lots.empty:
        return {'date': d, 'stockname': s, 'exit_reason': 'SKIPPED_NO_LOTSIZE', 'net_pnl': 0.0}
    
    true_lotsize = int(valid_lots.iloc[0]['lotsize'])
    
    conn = get_db_connection()
    cur = conn.cursor(pymysql.cursors.DictCursor)
    
    # Strict F1 Entry: 09:20 to 09:21
    q_entry = f"""
    SELECT time, price, high, low, close 
    FROM scrapdata_F1 
    WHERE date = '{d}' AND stockname IN ('{s}', '\"{s}\"', '{s} ') AND is_future='F1' 
      AND time >= '{d} 09:20:00' AND time <= '{d} 09:21:59' 
    ORDER BY time ASC LIMIT 1
    """
    cur.execute(q_entry)
    entry_tick = cur.fetchone()
    
    if not entry_tick:
        conn.close()
        return {'date': d, 'stockname': s, 'exit_reason': 'SKIPPED_NO_F1_ENTRY_TICK', 'net_pnl': 0.0}
        
    en = float(entry_tick['price'] or entry_tick['close'] or entry_tick['open'] or 0)
    if en <= 0:
        conn.close()
        return {'date': d, 'stockname': s, 'exit_reason': 'SKIPPED_ZERO_F1_ENTRY_PRICE', 'net_pnl': 0.0}

    en_time = entry_tick['time']
    
    max_shares = int(leveraged_capital // en)
    num_lots = max_shares // true_lotsize
    
    if num_lots < 1:
        conn.close()
        return {'date': d, 'stockname': s, 'exit_reason': 'SKIPPED_CAPITAL_TOO_LOW_FOR_LOT', 'net_pnl': 0.0}
        
    qty = num_lots * true_lotsize
    
    q_window = f"""
    SELECT time, price, high, low, close 
    FROM scrapdata_F1 
    WHERE date = '{d}' AND stockname IN ('{s}', '\"{s}\"', '{s} ') AND is_future='F1' 
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
        if h >= sl:
            hit = True
            ex = sl
            ex_time = t['time']
            reason = 'STOP_LOSS_3PCT'
            break
            
    if not hit:
        q_exit = f"""
        SELECT time, price, high, low, close 
        FROM scrapdata_F1 
        WHERE date = '{d}' AND stockname IN ('{s}', '\"{s}\"', '{s} ') AND is_future='F1' 
          AND time >= '{d} 09:40:00' AND time <= '{d} 09:41:59' 
        ORDER BY time DESC LIMIT 1
        """
        cur.execute(q_exit)
        exit_tick = cur.fetchone()
        
        if not exit_tick:
            conn.close()
            return {'date': d, 'stockname': s, 'exit_reason': 'SKIPPED_NO_F1_EXIT_TICK', 'net_pnl': 0.0}
            
        ex = float(exit_tick['close'] or exit_tick['price'] or exit_tick['open'] or 0)
        ex_time = exit_tick['time']
        reason = 'TIME_EXIT'

    conn.close()
    
    gross_pnl = (en - ex) * qty
    # Using 600 flat per LOT as verified by user previously
    charges = get_kotak_f1_charges(qty, sell_price=en, buy_price=ex, flat_commission=600 * num_lots)
    net_pnl = gross_pnl - charges
    
    return {
        'date': d, 'stockname': s, 'capital_used': 100000.0, 'qty': qty, 'lots': num_lots,
        'entry_time': str(en_time), 'entry_price': en,
        'exit_time': str(ex_time), 'exit_price': ex,
        'exit_reason': reason,
        'gross_pnl': round(gross_pnl, 2), 'charges': charges, 'net_pnl': round(net_pnl, 2)
    }

def main():
    df = pd.read_csv(TRADES_FILE)
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
    
    valid_df = res_df[~res_df['exit_reason'].str.startswith('SKIPPED_')]
    
    wins = len(valid_df[valid_df['net_pnl'] > 0])
    win_rate = (wins / len(valid_df)) * 100 if len(valid_df) > 0 else 0
    
    gross = valid_df['gross_pnl'].sum()
    charges = valid_df['charges'].sum()
    net = valid_df['net_pnl'].sum()
    
    print("\n--- MODEL 1 STRICT REBUILD RESULTS (FUTURES F1) ---")
    print(f"Valid Executed Trades: {len(valid_df)}")
    print(f"Skipped Trades: {len(res_df) - len(valid_df)}")
    print(f"Win Rate: {win_rate:.2f}%")
    print(f"Total Gross: ₹ {gross:,.2f}")
    print(f"Total Kotak Charges (w/ ₹600/lot): ₹ {charges:,.2f}")
    print(f"Total NET PnL: ₹ {net:,.2f}")
    print("\nYearly Breakdown:")
    
    valid_df['year'] = pd.to_datetime(valid_df['date']).dt.year
    print(valid_df.groupby('year')[['gross_pnl', 'charges', 'net_pnl']].sum().applymap(lambda x: f"₹ {x/100000:,.2f}L"))

if __name__ == '__main__':
    main()
