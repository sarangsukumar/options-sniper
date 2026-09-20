import pandas as pd
import pymysql
import time
import os

TRADES_FILE = '/home/ubuntu/942_regime_shift_model/longer_window_trades_futures_and_eq.csv'
OUT_FILE = '/home/ubuntu/942_regime_shift_model/verified_ledger_with_margin.csv'

def get_kotak_neo_charges(qty, sell_price, buy_price):
    turnover = (qty * sell_price) + (qty * buy_price)
    brokerage = 40.0
    stt = round(qty * sell_price * 0.00025)
    txn = turnover * 0.0000322
    sebi = turnover * 0.000001
    stamp = round(qty * buy_price * 0.00003)
    gst = (brokerage + txn + sebi) * 0.18
    return round(brokerage + stt + txn + sebi + stamp + gst, 2)

def audit_trade(trade):
    d = trade['date'].strip()
    s = trade['stockname'].strip()
    # Dynamic Qty based on 2L Capital & 5x Margin (10L Exposure)
    # We will calculate exact qty AFTER we fetch the entry_price (sell_price)
    
    for attempt in range(3):
        try:
            conn = pymysql.connect(host='localhost', user='root', password='root', database='markets', cursorclass=pymysql.cursors.DictCursor)
            cur = conn.cursor()
            q = f"""
            SELECT time, price, high, low, close 
            FROM scrapdata 
            WHERE date = '{d}' AND stockname IN ('{s}', '"{s}"', '{s} ') 
              AND time >= '{d} 09:39:00' AND time <= '{d} 15:30:00' 
            ORDER BY time ASC
            """
            cur.execute(q)
            ticks = cur.fetchall()
            conn.close()
            break
        except Exception:
            time.sleep(1)
            if attempt == 2: return None
            
    if not ticks:
        return None

    # 1. Strict Entry (09:42:00 to 09:44:59)
    entry_ticks = [t for t in ticks if f"{d} 09:42:00" <= str(t['time']) <= f"{d} 09:44:59"]
    if not entry_ticks:
        # Fallback: 3 minutes backward (09:39:00 to 09:41:59)
        fallback_ticks = [t for t in ticks if f"{d} 09:39:00" <= str(t['time']) <= f"{d} 09:41:59"]
        if not fallback_ticks:
            return None
        sell_time = str(fallback_ticks[-1]['time'])
        sell_price = float(fallback_ticks[-1]['price'] or fallback_ticks[-1]['close'] or fallback_ticks[-1]['open'])
    else:
        sell_time = str(entry_ticks[0]['time'])
        sell_price = float(entry_ticks[0]['price'] or entry_ticks[0]['close'] or entry_ticks[0]['open'])

    if sell_price <= 0: return None
    
    # Capital Allocation: 2 Lakhs Capital * 5x Margin = 10,00,000 Exposure Limit
    max_exposure = 1000000.0
    qty = int(max_exposure / sell_price)
    
    sl_price = round(sell_price * 1.03, 2)
    
    # 2. Tick-by-tick Stop Loss check
    hit_sl = False
    buy_time = None
    buy_price = None
    exit_reason = ''
    
    for t in ticks:
        t_time = str(t['time'])
        if t_time <= sell_time: continue
        if t_time >= f"{d} 14:45:00": break
        
        h = float(t['high'] or t['price'] or 0)
        if h >= sl_price:
            hit_sl = True
            buy_time = t_time
            buy_price = sl_price
            exit_reason = 'STOP_LOSS_3PCT'
            break
            
    # 3. Strict Exit (14:45:00 to 14:47:59)
    if not hit_sl:
        exit_ticks = [t for t in ticks if f"{d} 14:45:00" <= str(t['time']) <= f"{d} 14:47:59"]
        if not exit_ticks:
            # Fallback: 3 minutes backward (14:42:00 to 14:44:59)
            fallback_exit = [t for t in ticks if f"{d} 14:42:00" <= str(t['time']) <= f"{d} 14:44:59"]
            if not fallback_exit:
                return None
            buy_time = str(fallback_exit[-1]['time'])
            buy_price = float(fallback_exit[-1]['price'] or fallback_exit[-1]['close'] or fallback_exit[-1]['open'])
        else:
            buy_time = str(exit_ticks[0]['time'])
            buy_price = float(exit_ticks[0]['price'] or exit_ticks[0]['close'] or exit_ticks[0]['open'])
        exit_reason = 'TIME_EXIT'
        
    gross = (sell_price - buy_price) * qty
    comm = get_kotak_neo_charges(qty, sell_price, buy_price)
    net = gross - comm
    
    margin_amount = round((qty * sell_price) / 5.0, 2)
    
    return {
        'date': d,
        'stockname': s,
        'qty': qty,
        'margin_amount': margin_amount,
        'sell_time': sell_time,
        'sell_price': sell_price,
        'buy_time': buy_time,
        'buy_price': buy_price,
        'gross_pnl': round(gross, 2),
        'commission': comm,
        'net_pnl': round(net, 2),
        'exit_reason': exit_reason
    }

print("1. Loading Model 2 Trades...")
df = pd.read_csv(TRADES_FILE)
trades = df.to_dict('records')

print(f"2. Auditing {len(trades)} trades strictly against scrapdata ticks...")
t0 = time.time()
res = []

for i, t in enumerate(trades):
    if i > 0 and i % 500 == 0:
        print(f"Processed {i} trades... ({time.time()-t0:.1f}s)")
    out = audit_trade(t)
    if out:
        res.append(out)

res_df = pd.DataFrame(res)
res_df = res_df.sort_values(['date', 'sell_time']).reset_index(drop=True)
res_df.to_csv(OUT_FILE, index=False)

wins = (res_df['net_pnl'] > 0).sum()
win_rate = (wins / len(res_df)) * 100

print("\n========================================================")
print("BULLETPROOF TICK-BY-TICK AUDIT COMPLETE")
print("========================================================")
print(f"Original Trades: {len(trades)}")
print(f"Strictly Valid Trades (Survived missing ticks): {len(res_df)}")
print(f"Total Net PnL (After all charges): Rs {res_df['net_pnl'].sum():,.2f}")
print(f"Win Rate: {win_rate:.2f}%")
print(f"Saved exact ledger to: {OUT_FILE}")
