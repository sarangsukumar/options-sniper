import pandas as pd
import numpy as np
import pymysql
import time
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor, as_completed

DB_CONFIG = {'host':'localhost', 'user':'root', 'password':'root', 'database':'markets'}

def get_db():
    return pymysql.connect(**DB_CONFIG, cursorclass=pymysql.cursors.DictCursor, connect_timeout=10)

def sim_trade_for_all_sls(trade, sl_grid):
    d = trade['date']
    s = trade['stockname']
    qty = trade['qty']
    
    conn = get_db()
    cur = conn.cursor()
    
    # Get 09:42 entry price
    cur.execute(f"SELECT price FROM scrapdata WHERE date='{d}' AND stockname='{s}' AND time>='{d} 09:39:00' AND time<='{d} 09:45:00' ORDER BY ABS(TIMESTAMPDIFF(SECOND, time, '{d} 09:42:00')) LIMIT 1")
    r = cur.fetchone()
    if not r:
        conn.close()
        return None
    en_cash = r['price']
    
    # Get ticks
    cur.execute(f"SELECT time, price, high, low, close FROM scrapdata WHERE date='{d}' AND stockname='{s}' AND time>='{d} 09:42:00' AND time<='{d} 14:45:59' AND price BETWEEN {en_cash*0.85} AND {en_cash*1.15} ORDER BY time ASC")
    ticks = cur.fetchall()
    conn.close()
    
    if not ticks: return None

    # Results dictionary for this trade
    results = {}
    
    for sl_pct in sl_grid:
        sl = en_cash * (1 + (sl_pct / 100.0)) if sl_pct is not None else float('inf')
        
        ex_price = ticks[-1]['close'] if ticks[-1]['close'] else ticks[-1]['price']
        ex_reason = '1445_TIME_EXIT'
        
        max_hi_since = -9999
        min_low_since = 99999
        trail_active = False
        trail_sl = -1
        
        for t in ticks:
            tm = t['time']
            ph = t['high']
            pl = t['low']
            
            if ph > max_hi_since: max_hi_since = ph
            if pl < min_low_since: min_low_since = pl
            
            # Rule 5: Trailing stop
            if min_low_since <= en_cash * 0.98:
                trail_active = True
                prop_sl = min_low_since * 1.02
                if prop_sl < trail_sl or trail_sl == -1:
                    trail_sl = prop_sl
                    
            if trail_active and ph >= trail_sl:
                ex_price = trail_sl
                ex_reason = 'TRAIL_STOP'
                break
                
            # Rule 2: Hard SL
            if ph >= sl:
                ex_price = sl
                ex_reason = 'STOP_LOSS'
                break
                
            # Rule 3: OFF
            # Rule 4B: OFF
            
            # Rule 4A: 11:00 Cut (2% loss)
            if tm >= datetime(tm.year, tm.month, tm.day, 11, 0):
                loss_pct = (ph - en_cash) / en_cash * 100
                if loss_pct >= 2.0:
                    ex_price = max(en_cash * 1.02, t['price'])
                    ex_reason = 'RULE4A_CUT_1100'
                    break
                    
            if tm.hour == 14 and tm.minute >= 45:
                ex_price = t['close'] if t['close'] else t['price']
                ex_reason = '1445_TIME_EXIT'
                break
                
        gross = (en_cash - ex_price) * qty
        # Scaled charges logic equivalent
        # For kotack MIS: turnover * 0.0003 + 50 is a rough scaled approximation
        # We will use exactly Kotak MIS logic for perfect matching:
        # sell: stt=0.025%, ex=0.00325%, sebi=0.0001%
        sell_val = en_cash * qty
        buy_val = ex_price * qty
        stt = sell_val * 0.00025
        ex_tx = (sell_val + buy_val) * 0.0000325
        sebi = (sell_val + buy_val) * 0.000001
        stamp = sell_val * 0.00003
        gst = (ex_tx + sebi) * 0.18
        tot_chg = stt + ex_tx + sebi + stamp + gst
        
        net = gross - tot_chg
        results[sl_pct] = {'net': net, 'reason': ex_reason}
        
    return results

def process_chunk(chunk, sl_grid):
    results = {sl: {'net': 0.0, 'win': 0, 'total': 0, 'sl_hits': 0} for sl in sl_grid}
    for _, tr in chunk.iterrows():
        trade_res = sim_trade_for_all_sls(tr, sl_grid)
        if trade_res is not None:
            for sl in sl_grid:
                net = trade_res[sl]['net']
                results[sl]['net'] += net
                results[sl]['total'] += 1
                if net > 0: results[sl]['win'] += 1
                if trade_res[sl]['reason'] == 'STOP_LOSS':
                    results[sl]['sl_hits'] += 1
    return results

if __name__ == '__main__':
    df = pd.read_csv('/home/ubuntu/sarang_2026_shortsell_algos/rebuild_model2_strict_db_ledger.csv')
    print(f"Loaded {len(df)} base trades for SL Optimization...")
    
    sl_grid = [2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 6.0, None] # None = No SL
    
    chunks = np.array_split(df, 20)
    final_results = {sl: {'net': 0.0, 'win': 0, 'total': 0, 'sl_hits': 0} for sl in sl_grid}
    
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=20) as exe:
        futs = [exe.submit(process_chunk, c, sl_grid) for c in chunks]
        for fut in as_completed(futs):
            chunk_res = fut.result()
            for sl in sl_grid:
                final_results[sl]['net'] += chunk_res[sl]['net']
                final_results[sl]['win'] += chunk_res[sl]['win']
                final_results[sl]['total'] += chunk_res[sl]['total']
                final_results[sl]['sl_hits'] += chunk_res[sl]['sl_hits']
                
    print(f"\nCompleted in {time.time()-t0:.1f} seconds")
    
    print("\n" + "="*80)
    print(" TICK-BY-TICK STOP LOSS OPTIMIZATION RESULTS (Scaled Equity Cash)")
    print(" (Active: R1 Entry, R4A 11:00 Cut, R5 Trailing Stop | OFF: R3, R4B)")
    print("="*80)
    print(f"{'Stop Loss %':<15} | {'Net Profit':<15} | {'Win Rate':<10} | {'SL Triggers':<15}")
    print("-" * 80)
    
    # Sort for display
    best_net = -9999999
    best_sl = None
    
    for sl in sl_grid:
        stats = final_results[sl]
        net_lakhs = stats['net'] / 100000
        wr = (stats['win'] / stats['total']) * 100 if stats['total'] > 0 else 0
        sl_name = f"{sl:.1f}%" if sl is not None else "NO SL (Inf)"
        
        if net_lakhs > best_net:
            best_net = net_lakhs
            best_sl = sl_name
            
        print(f"{sl_name:<15} | Rs {net_lakhs:>7.2f} L   | {wr:>5.1f}%     | {stats['sl_hits']:>5}")
        
    print("="*80)
    print(f"👑 OPTIMAL STOP LOSS: {best_sl} (Peak Profit: Rs {best_net:.2f} L)")
    print("="*80)

