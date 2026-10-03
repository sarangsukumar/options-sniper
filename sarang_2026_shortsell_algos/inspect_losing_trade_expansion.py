#!/usr/bin/env python3
import os, sys, pymysql
import pandas as pd
import numpy as np
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, '/home/ubuntu/sarang_2026_shortsell_algos')
from kotak_mis_calculator import calculate_kotak_charges

M2_CSV = '/home/ubuntu/sarang_2026_shortsell_algos/model2_equity_kotak_vs_f1_flat600.csv'

def get_db():
    return pymysql.connect(host='localhost', user='root', password='root', database='markets', autocommit=True)

def check_trade(trade):
    d = trade['date']
    s = trade['stockname']
    qty = int(trade['total_quantity'])
    yr = int(d[:4])
    
    conn = get_db()
    cur = conn.cursor(pymysql.cursors.DictCursor)
    cur.execute(f"""
    SELECT time, price, high, low, close 
    FROM scrapdata 
    WHERE date = '{d}' AND stockname IN ('{s}', '\"{s}\"', '{s} ') 
      AND time >= '{d} 09:42:00' AND time <= '{d} 14:45:59' 
    ORDER BY time ASC
    """)
    ticks = cur.fetchall()
    conn.close()
    
    if not ticks or len(ticks) < 10:
        return None
        
    en = float(ticks[0]['price'] or ticks[0]['close'] or ticks[0]['open'])
    sl3 = round(en * 1.03, 2)
    final_p = float(ticks[-1]['close'] or ticks[-1]['price'])
    
    # Track checkpoints
    def get_cp_price(hhmm):
        sub = [t for t in ticks if str(t['time']) <= f"{d} {hhmm}:59"]
        return float(sub[-1]['close'] or sub[-1]['price']) if sub else en
        
    p_1000 = get_cp_price('10:00')
    p_1030 = get_cp_price('10:30')
    p_1100 = get_cp_price('11:00')
    p_1130 = get_cp_price('11:30')
    
    # Baseline 3% SL
    ex_base = final_p
    hit_sl = False
    hit_sl_time = None
    for t in ticks:
        h = float(t['high'] or t['price'] or 0)
        if h >= sl3:
            ex_base = sl3
            hit_sl = True
            hit_sl_time = str(t['time'])
            break
            
    loss_1000 = ((p_1000 - en) / en) * 100.0
    loss_1030 = ((p_1030 - en) / en) * 100.0
    loss_1100 = ((p_1100 - en) / en) * 100.0
    loss_1130 = ((p_1130 - en) / en) * 100.0
    final_loss = ((ex_base - en) / en) * 100.0
    
    return {
        'date': d, 'stockname': s, 'year': yr, 'qty': qty, 'en': en,
        'p_1000': p_1000, 'loss_1000': loss_1000,
        'p_1030': p_1030, 'loss_1030': loss_1030,
        'p_1100': p_1100, 'loss_1100': loss_1100,
        'p_1130': p_1130, 'loss_1130': loss_1130,
        'ex_base': ex_base, 'final_loss': final_loss,
        'hit_sl': hit_sl, 'hit_sl_time': hit_sl_time,
        'net_base': (en - ex_base) * qty - calculate_kotak_charges(en, ex_base, qty)['total_charges']
    }

def main():
    df_m2 = pd.read_csv(M2_CSV)
    trades = df_m2.to_dict('records')
    with ThreadPoolExecutor(max_workers=24) as ex:
        results = [r for r in ex.map(check_trade, trades) if r is not None]
    df = pd.DataFrame(results)
    
    # Split
    ins = df[df['year'] <= 2025].copy()
    oos = df[df['year'] == 2026].copy()
    
    print("=" * 115)
    print("DO INITIAL LOSSES GET HUGE? EMPIRICAL TRACKING OF LOSS PROGRESSION (2020-2025 IN-SAMPLE)")
    print("=" * 115)
    
    # Look at trades that were in loss at 10:30 AM
    in_loss_1030 = ins[ins['loss_1030'] > 0].copy()
    print(f"Trades in Loss at 10:30 AM: {len(in_loss_1030):,} / {len(ins):,} ({len(in_loss_1030)/len(ins)*100:.1f}%)")
    
    # How did their loss change from 10:30 to Final?
    in_loss_1030['loss_diff'] = in_loss_1030['final_loss'] - in_loss_1030['loss_1030']
    
    expanded = (in_loss_1030['loss_diff'] > 0.5).mean() * 100
    stayed_same = ((in_loss_1030['loss_diff'] >= -0.5) & (in_loss_1030['loss_diff'] <= 0.5)).mean() * 100
    shrank = (in_loss_1030['loss_diff'] < -0.5).mean() * 100
    recovered_to_win = (in_loss_1030['final_loss'] < 0).mean() * 100
    hit_sl_pct = in_loss_1030['hit_sl'].mean() * 100
    
    print(f"Of the trades in loss at 10:30 AM:")
    print(f"  • Hit 3.0% Stop Loss:            {hit_sl_pct:>5.1f}%")
    print(f"  • Loss Expanded (> +0.5% worse): {expanded:>5.1f}%")
    print(f"  • Loss Remained Similar (±0.5%):  {stayed_same:>5.1f}%")
    print(f"  • Loss Shrank / Improved:        {shrank:>5.1f}%")
    print(f"  • Recovered to Net Win:          {recovered_to_win:>5.1f}%")
    
    # Breakdown by severity of loss at 10:30
    print("\n" + "-" * 115)
    print(f"{'Loss @ 10:30 Bucket':<20} | {'Count':<8} | {'Hit 3% SL %':<12} | {'Expanded %':<12} | {'Recovered %':<12} | {'Avg Final Loss %':<16} | {'Avg 10:30 Loss %'}")
    print("-" * 115)
    
    bins = [0.0, 0.5, 1.0, 1.5, 2.0, 3.0, 999.0]
    labels = ['0.0% to 0.5%', '0.5% to 1.0%', '1.0% to 1.5%', '1.5% to 2.0%', '2.0% to 3.0%', '> 3.0%']
    in_loss_1030['bucket'] = pd.cut(in_loss_1030['loss_1030'], bins=bins, labels=labels)
    
    for lbl in labels:
        sub = in_loss_1030[in_loss_1030['bucket'] == lbl]
        if len(sub) == 0: continue
        sl_p = sub['hit_sl'].mean() * 100
        exp_p = ((sub['final_loss'] - sub['loss_1030']) > 0.5).mean() * 100
        rec_p = (sub['final_loss'] < 0).mean() * 100
        avg_f = sub['final_loss'].mean()
        avg_cp = sub['loss_1030'].mean()
        print(f"{lbl:<20} | {len(sub):>8} | {sl_p:>10.1f}% | {exp_p:>10.1f}% | {rec_p:>10.1f}% | {avg_f:>+14.2f}% | {avg_cp:>+14.2f}%")
    print("=" * 115)
    
    # 2026 OUT OF SAMPLE
    print("\n" + "=" * 115)
    print("2026 OUT-OF-SAMPLE BLIND VERIFICATION:")
    print("=" * 115)
    oos_loss_1030 = oos[oos['loss_1030'] > 0].copy()
    oos_loss_1030['bucket'] = pd.cut(oos_loss_1030['loss_1030'], bins=bins, labels=labels)
    for lbl in labels:
        sub = oos_loss_1030[oos_loss_1030['bucket'] == lbl]
        if len(sub) == 0: continue
        sl_p = sub['hit_sl'].mean() * 100
        exp_p = ((sub['final_loss'] - sub['loss_1030']) > 0.5).mean() * 100
        rec_p = (sub['final_loss'] < 0).mean() * 100
        avg_f = sub['final_loss'].mean()
        avg_cp = sub['loss_1030'].mean()
        print(f"{lbl:<20} | {len(sub):>8} | {sl_p:>10.1f}% | {exp_p:>10.1f}% | {rec_p:>10.1f}% | {avg_f:>+14.2f}% | {avg_cp:>+14.2f}%")
    print("=" * 115)

if __name__ == '__main__':
    main()
