#!/usr/bin/env python3
"""
test_multitime_loss_controls.py
Testing loss control rules across multiple time horizons:
11:30, 12:00, 12:30, 13:00, 13:30
Across all 4,424 trades in Model 2.
"""
import os, sys, pymysql
import pandas as pd
import numpy as np
from concurrent.futures import ThreadPoolExecutor

BASE_DIR = '/home/ubuntu/sarang_2026_shortsell_algos'
M2_FILE = os.path.join(BASE_DIR, '02_Best_Longer_Window_0942_1445', 'audited_0940_hybrid_trades.csv')

def get_db():
    return pymysql.connect(host='localhost', user='root', password='root', database='markets', autocommit=True)

def sim_trade(trade):
    d = trade['date']
    s = trade['stockname']
    qty = int(trade['total_quantity'])
    lots = int(trade['lots_to_trade'])
    yr = int(d[:4])
    
    conn = get_db()
    cur = conn.cursor(pymysql.cursors.DictCursor)
    cur.execute(f"""
    SELECT time, price 
    FROM scrapdata_F1 
    WHERE date = '{d}' AND stockname IN ('{s}', '\"{s}\"', '{s} ') 
      AND time >= '{d} 09:42:00' AND time <= '{d} 14:45:59' 
    ORDER BY time ASC
    """)
    ticks = cur.fetchall()
    conn.close()
    
    if not ticks or len(ticks) < 10:
        return None
        
    prices = [float(t['price']) for t in ticks if t['price'] is not None]
    times = [str(t['time']) for t in ticks if t['price'] is not None]
    
    if len(prices) < 10:
        return None
        
    en = prices[0]
    sl3 = round(en * 1.03, 2)
    final_p = prices[-1]
    
    # Base 3% SL
    ex_base = final_p
    sl_hit_time = None
    for t, p in zip(times, prices):
        if p >= sl3:
            ex_base = sl3
            sl_hit_time = t
            break
            
    # Checkpoints
    checkpoints = ['11:00', '11:30', '12:00', '12:30', '13:00', '13:30']
    cp_prices = {}
    for cp in checkpoints:
        p_cp = en
        for t, p in zip(times, prices):
            if t <= f"{d} {cp}:59":
                p_cp = p
        cp_prices[cp] = p_cp
        
    res = {
        'date': d, 'stockname': s, 'year': yr, 'qty': qty, 'lots': lots,
        'en': en, 'sl3': sl3, 'ex_base': ex_base, 'sl_hit_time': sl_hit_time,
        'final_p': final_p
    }
    for cp in checkpoints:
        res[f'p_{cp.replace(":", "")}'] = cp_prices[cp]
        res[f'loss_pct_{cp.replace(":", "")}'] = ((cp_prices[cp] - en) / en) * 100.0
        
    # High up to each checkpoint
    for cp in checkpoints:
        sub_p = [p for t, p in zip(times, prices) if t <= f"{d} {cp}:59"]
        res[f'max_p_{cp.replace(":", "")}'] = max(sub_p) if sub_p else en
        
    return res

def main():
    df = pd.read_csv(M2_FILE)
    df = df[df['status'] == 'COMPLETED'].copy()
    trades = df.to_dict('records')
    print(f"Loading ticks for {len(trades):,} trades...")
    with ThreadPoolExecutor(max_workers=24) as ex:
        results = [r for r in ex.map(sim_trade, trades) if r is not None]
        
    rdf = pd.DataFrame(results)
    print(f"Valid trades: {len(rdf):,}")
    
    # Baseline Gross & Net
    rdf['gross_base'] = (rdf['en'] - rdf['ex_base']) * rdf['qty']
    base_gross_total = rdf['gross_base'].sum()
    print(f"Baseline Gross PnL: Rs {base_gross_total/1e5:.2f} Lakhs")
    
    checkpoints = [
        ('11:30', '1130'),
        ('12:00', '1200'),
        ('12:30', '1230'),
        ('13:00', '1300'),
        ('13:30', '1330')
    ]
    
    print("\n" + "=" * 115)
    print("ANALYSIS ACROSS TIME HORIZONS: WHAT HAPPENS IF WE CUT AT TIME T IF IN LOSS?")
    print("=" * 115)
    print(f"{'Time':<8} | {'Loss Filter':<25} | {'Trades Cut':<12} | {'Recov %':<8} | {'Base Gross':<12} | {'Cut Gross':<12} | {'Delta Saved (L)'}")
    print("-" * 115)
    
    loss_thresholds = [0.0, 0.5, 1.0, 1.5, 1.8, 2.0, 2.2, 2.5]
    
    for label, cp in checkpoints:
        # trades not stopped out before this time
        # sl_hit_time > time or None
        cp_time_str = f" {label}:59"
        not_stopped = rdf[(rdf['sl_hit_time'].isna()) | (rdf['sl_hit_time'] > (rdf['date'] + cp_time_str))].copy()
        
        for th in loss_thresholds:
            col_loss = f'loss_pct_{cp}'
            col_p = f'p_{cp}'
            
            if th == 0.0:
                mask = not_stopped[col_loss] > 0
                filter_name = f"Loss > 0.0% (Any Loss)"
            else:
                mask = not_stopped[col_loss] >= th
                filter_name = f"Loss >= {th:.1f}%"
                
            sub = not_stopped[mask]
            if len(sub) == 0:
                continue
                
            rec_pct = (sub['ex_base'] < sub['en']).mean() * 100
            bg = sub['gross_base'].sum()
            cg = ((sub['en'] - sub[col_p]) * sub['qty']).sum()
            delta = cg - bg
            
            print(f"{label:<8} | {filter_name:<25} | {len(sub):>5} ({len(sub)/len(not_stopped)*100:>4.1f}%) | {rec_pct:>6.1f}% | Rs {bg/1e5:>7.2f} L | Rs {cg/1e5:>7.2f} L | {delta/1e5:>+10.2f} L")
        print("-" * 115)

if __name__ == '__main__':
    main()
