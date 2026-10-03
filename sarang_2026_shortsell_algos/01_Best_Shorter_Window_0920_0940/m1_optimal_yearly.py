import os, pymysql
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
    
    sl_base = round(en * 1.03, 2)
    tp_2p5 = round(en * 0.975, 2)
    
    hit, ex, reason = False, None, None
    for t in ticks:
        h = float(t['high'] or t['price'] or 0)
        l = float(t['low'] or t['price'] or 0)
        
        if h >= sl_base:
            hit, ex, reason = True, sl_base, 'SL_3%'
            break
        elif l <= tp_2p5:
            hit, ex, reason = True, tp_2p5, 'TP_2.5%'
            break
            
    if not hit:
        cur.execute(f"SELECT time, price, high, low, close FROM scrapdata WHERE date = '{d}' AND stockname IN ('{s}', '\"{s}\"', '{s} ') AND time >= '{d} 09:40:00' AND time <= '{d} 09:41:59' ORDER BY time DESC LIMIT 1")
        ex_tick = cur.fetchone()
        conn.close()
        ex = float(ex_tick['close'] or ex_tick['price'] or 0) if ex_tick else en
        reason = 'TIME_EXIT'
    else:
        conn.close()
        
    gross = (en - ex) * qty
    net = gross - get_kotak_mis_charges(qty, en, ex)
    
    return {'date': d, 'net_pnl': net, 'reason': reason}

def main():
    trades = pd.read_csv(TRADES_FILE).to_dict('records')
    results = []
    with ThreadPoolExecutor(max_workers=60) as executor:
        for res in executor.map(process_prediction, trades):
            if res: results.append(res)
            
    df = pd.DataFrame(results)
    df['year'] = pd.to_datetime(df['date']).dt.year
    
    print("M1_YEARLY_DATA")
    for y in sorted(df['year'].unique()):
        ydf = df[df['year'] == y]
        print(f"{y},{ydf['net_pnl'].sum()}")

if __name__ == '__main__':
    main()
