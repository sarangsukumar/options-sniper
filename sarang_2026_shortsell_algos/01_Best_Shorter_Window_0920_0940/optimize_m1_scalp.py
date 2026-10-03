import os, pymysql, time
import pandas as pd
from concurrent.futures import ThreadPoolExecutor

TRADES_FILE = '/home/ubuntu/sarang_2026_shortsell_algos/01_Best_Shorter_Window_0920_0940/m1_dual_table_all_trades.csv'

def get_kotak_mis_charges(qty, sell_price, buy_price):
    turnover = (qty * sell_price) + (qty * buy_price)
    stt = round(qty * sell_price * 0.00025)
    txn = turnover * 0.0000322
    sebi = turnover * 0.000001
    stamp = round(qty * buy_price * 0.00003)
    gst = (txn + sebi) * 0.18
    return round(stt + txn + sebi + stamp + gst, 2)

def process_prediction(row):
    d, s = row['short_date'], row['clean_stock']
    base_cap = 100000.0
    lev_cap = base_cap * 5.0
    
    conn = pymysql.connect(host='localhost', user='root', password='root', database='markets', autocommit=True)
    cur = conn.cursor(pymysql.cursors.DictCursor)
    
    cur.execute(f"SELECT time, price, high, low, close FROM scrapdata WHERE date = '{d}' AND stockname IN ('{s}', '\"{s}\"', '{s} ') AND time >= '{d} 09:20:00' AND time <= '{d} 09:21:59' ORDER BY time ASC LIMIT 1")
    en_tick = cur.fetchone()
    if not en_tick: conn.close(); return None
    en = float(en_tick['price'] or en_tick['close'] or en_tick['open'] or 0)
    if en <= 0: conn.close(); return None
    
    qty = int(lev_cap // en)
    
    cur.execute(f"SELECT time, price, high, low, close FROM scrapdata WHERE date = '{d}' AND stockname IN ('{s}', '\"{s}\"', '{s} ') AND time >= '{en_tick['time']}' AND time <= '{d} 09:41:59' ORDER BY time ASC")
    ticks = cur.fetchall()
    
    rules = {
        'base_3pct': {'ex': None, 'hit': False},
        'tight_2pct': {'ex': None, 'hit': False},
        'tp_1p5pct': {'ex': None, 'hit': False},
        'tp_2pct': {'ex': None, 'hit': False},
        'tp_2p5pct': {'ex': None, 'hit': False},
        'tp_3pct': {'ex': None, 'hit': False},
        'trail_1pct': {'ex': None, 'hit': False}
    }
    
    sl_base = round(en * 1.03, 2); sl_tight = round(en * 1.02, 2)
    tp_1p5 = round(en * 0.985, 2); tp_2 = round(en * 0.98, 2); tp_2p5 = round(en * 0.975, 2); tp_3 = round(en * 0.97, 2)
    lowest_seen = en
    
    for t in ticks:
        h = float(t['high'] or t['price'] or 0)
        l = float(t['low'] or t['price'] or 0)
        lowest_seen = min(lowest_seen, l)
        trail_sl = min(sl_base, round(lowest_seen * 1.01, 2))
        
        if not rules['base_3pct']['hit'] and h >= sl_base:
            rules['base_3pct'].update({'hit': True, 'ex': sl_base})
        if not rules['tight_2pct']['hit'] and h >= sl_tight:
            rules['tight_2pct'].update({'hit': True, 'ex': sl_tight})
            
        for tp_rule, tp_val in [('tp_1p5pct', tp_1p5), ('tp_2pct', tp_2), ('tp_2p5pct', tp_2p5), ('tp_3pct', tp_3)]:
            if not rules[tp_rule]['hit']:
                if h >= sl_base: rules[tp_rule].update({'hit': True, 'ex': sl_base})
                elif l <= tp_val: rules[tp_rule].update({'hit': True, 'ex': tp_val})
                
        if not rules['trail_1pct']['hit'] and h >= trail_sl:
            rules['trail_1pct'].update({'hit': True, 'ex': trail_sl})
            
    cur.execute(f"SELECT time, price, high, low, close FROM scrapdata WHERE date = '{d}' AND stockname IN ('{s}', '\"{s}\"', '{s} ') AND time >= '{d} 09:40:00' AND time <= '{d} 09:41:59' ORDER BY time DESC LIMIT 1")
    ex_tick = cur.fetchone()
    conn.close()
    
    time_ex = float(ex_tick['close'] or ex_tick['price'] or 0) if ex_tick else en
    
    res = {'date': d, 'stockname': s}
    for r, state in rules.items():
        ex = state['ex'] if state['hit'] else time_ex
        res[r] = (en - ex) * qty - get_kotak_mis_charges(qty, en, ex)
        
    return res

def main():
    trades = pd.read_csv(TRADES_FILE).to_dict('records')
    results = []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=50) as executor:
        for i, res in enumerate(executor.map(process_prediction, trades)):
            if res: results.append(res)
            if (i+1) % 1000 == 0: print(f"Processed {i+1}")
            
    df = pd.DataFrame(results)
    print("\n--- MODEL 1 (CASH EQ) SCALP OPTIMIZATION RESULTS ---")
    print(f"Total Valid Executed Trades: {len(df)}")
    
    for col in ['base_3pct', 'tight_2pct', 'tp_1p5pct', 'tp_2pct', 'tp_2p5pct', 'tp_3pct', 'trail_1pct']:
        pnl = df[col].sum()
        win_rate = (len(df[df[col] > 0]) / len(df)) * 100
        print(f"{col}: Net PnL: Rs {pnl/100000:,.2f} Lakhs | Win Rate: {win_rate:.2f}%")

if __name__ == '__main__':
    main()
