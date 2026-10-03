#!/usr/bin/env python3
"""
sweep_1030_exit_times.py
========================
Sweeps exit times for the 10:30 AM Strategy:
- Entry at 10:30:00 AM
  - Arm 1: BUY LONG on Pattern 1 (New HOD + Gain >= 1.0%)
  - Arm 2: SELL SHORT on Pattern 2 (New LOD + Gain >= 1.0%)
- Exit times evaluated:
  10:45, 11:00, 11:15, 11:30, 11:45, 12:00, 12:30, 13:00, 13:30, 14:00, 14:30, 14:45
- Evaluated on:
  1. Futures F1 (Flat Rs 600 per lot)
  2. Equity Cash (Kotak MIS charges)
"""

import os, sys, pymysql
import pandas as pd
import numpy as np
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, '/home/ubuntu/sarang_2026_shortsell_algos')
from kotak_mis_calculator import calculate_kotak_charges

M2_CSV = '/home/ubuntu/sarang_2026_shortsell_algos/model2_equity_kotak_vs_f1_flat600.csv'

def get_db():
    return pymysql.connect(host='localhost', user='root', password='root', database='markets', autocommit=True)

def sim_trade_sweep(trade):
    d = trade['date']
    s = trade['stockname']
    lotsize = int(trade['lotsize']) # 1 lot
    yr = int(d[:4])
    clean_en_eq = float(trade.get('eq_entry_price', 0) or trade.get('entry_price', 0))
    
    conn = get_db()
    cur = conn.cursor(pymysql.cursors.DictCursor)
    
    # 1. Pre-entry high/low (09:15 to 09:41:59)
    price_cond = f"AND price BETWEEN {clean_en_eq * 0.75} AND {clean_en_eq * 1.25}" if clean_en_eq > 0 else ""
    cur.execute(f"""
    SELECT MAX(high) as morn_high, MIN(low) as morn_low
    FROM scrapdata 
    WHERE date = '{d}' AND stockname IN ('{s}', '\"{s}\"', '{s} ')
      AND time >= '{d} 09:15:00' AND time < '{d} 09:42:00' {price_cond}
    """)
    m_row = cur.fetchone()
    pre_high = float(m_row['morn_high'] or 0)
    pre_low  = float(m_row['morn_low'] or 999999)
    
    # 2. Ticks from 09:42 to 14:45
    cur.execute(f"""
    SELECT time, price, high, low, close 
    FROM scrapdata 
    WHERE date = '{d}' AND stockname IN ('{s}', '\"{s}\"', '{s} ') 
      AND time >= '{d} 09:42:00' AND time <= '{d} 14:45:59' {price_cond}
    ORDER BY time ASC
    """)
    ticks = cur.fetchall()
    conn.close()
    
    if not ticks or len(ticks) < 10 or clean_en_eq <= 0:
        return None
        
    en_0942 = float(ticks[0]['price'] or ticks[0]['close'] or ticks[0]['open'])
    
    # 10:30 checkpoint
    m_ticks_1030 = [t for t in ticks if str(t['time']) <= f"{d} 10:30:59"]
    if not m_ticks_1030:
        return None
        
    p_1030 = float(m_ticks_1030[-1]['close'] or m_ticks_1030[-1]['price'])
    max_h_1030 = max([float(t.get('high') or t['price'] or 0) for t in m_ticks_1030])
    min_l_1030 = min([float(t.get('low') or t['price'] or 999999) for t in m_ticks_1030])
    
    chg_0942_pct = ((p_1030 - en_0942) / en_0942) * 100.0
    
    is_buy  = (pre_high > 0) and (max_h_1030 > pre_high) and (chg_0942_pct >= 1.0)
    is_sell = (pre_low < 999999) and (min_l_1030 < pre_low) and (chg_0942_pct <= -1.0)
    
    if not is_buy and not is_sell:
        return None
        
    trade_type = 'BUY_LONG' if is_buy else 'SELL_SHORT'
    
    # Check prices at different exit horizons
    exit_times = [
        '10:45', '11:00', '11:15', '11:30', '11:45',
        '12:00', '12:30', '13:00', '13:30', '14:00', '14:30', '14:45'
    ]
    
    res = {
        'date': d, 'stockname': s, 'year': yr, 'lotsize': lotsize,
        'trade_type': trade_type, 'p_1030': p_1030
    }
    
    for et in exit_times:
        sub_et = [t for t in ticks if str(t['time']) <= f"{d} {et}:59"]
        p_et = float(sub_et[-1]['close'] or sub_et[-1]['price']) if sub_et else p_1030
        
        # Calculate PnL for this exit time
        if trade_type == 'BUY_LONG':
            gross = (p_et - p_1030) * lotsize
            ret = ((p_et - p_1030) / p_1030) * 100.0
        else:
            gross = (p_1030 - p_et) * lotsize
            ret = ((p_1030 - p_et) / p_1030) * 100.0
            
        chg_k = calculate_kotak_charges(p_1030, p_et, lotsize)['total_charges']
        net_k = gross - chg_k
        net_f1 = gross - 600.0
        
        col = et.replace(':', '')
        res[f'p_{col}'] = p_et
        res[f'gross_{col}'] = gross
        res[f'net_k_{col}'] = net_k
        res[f'net_f1_{col}'] = net_f1
        res[f'ret_{col}'] = ret
        
    return res

def main():
    df_m2 = pd.read_csv(M2_CSV)
    trades = df_m2.to_dict('records')
    print(f"Sweeping exit times for {len(trades):,} trade opportunities...")
    with ThreadPoolExecutor(max_workers=24) as ex:
        results = [r for r in ex.map(sim_trade_sweep, trades) if r is not None]
        
    rdf = pd.DataFrame(results)
    print(f"✔ Total Trades Triggered: {len(rdf):,} (BUY: {(rdf['trade_type']=='BUY_LONG').sum()}, SELL: {(rdf['trade_type']=='SELL_SHORT').sum()})")
    
    exit_times = [
        ('10:45 (15m)', '1045'),
        ('11:00 (30m)', '1100'),
        ('11:15 (45m)', '1115'),
        ('11:30 (60m)', '1130'),
        ('11:45 (75m)', '1145'),
        ('12:00 (90m)', '1200'),
        ('12:30 (2h)',  '1230'),
        ('13:00 (2.5h)','1300'),
        ('13:30 (3h)',  '1330'),
        ('14:00 (3.5h)','1400'),
        ('14:30 (4h)',  '1430'),
        ('14:45 (EOD)', '1445'),
    ]
    
    buys = rdf[rdf['trade_type'] == 'BUY_LONG'].copy()
    sells = rdf[rdf['trade_type'] == 'SELL_SHORT'].copy()
    
    # -------------------------------------------------------------
    # 1. BUY LONG (Pattern 1) EXIT SWEEP
    # -------------------------------------------------------------
    print("\n" + "=" * 115)
    print("📈 1. BUY LONG (Pattern 1 Breakout) EXIT TIME SWEEP (186 Trades, 1 Lot Each)")
    print("=" * 115)
    print(f"{'Exit Time Horizon':<20} | {'Win Rate %':<12} | {'Gross PnL':<14} | {'Net Kotak (L)':<15} | {'Net F1 (L)':<15} | {'Avg Return %'}")
    print("-" * 115)
    for lbl, col in exit_times:
        wr = (buys[f'net_k_{col}'] > 0).mean() * 100
        g = buys[f'gross_{col}'].sum() / 1e5
        nk = buys[f'net_k_{col}'].sum() / 1e5
        nf1 = buys[f'net_f1_{col}'].sum() / 1e5
        avg_ret = buys[f'ret_{col}'].mean()
        status = "🟢 Positive" if nk > 0 else "🔴 Negative"
        print(f"{lbl:<20} | {wr:>10.2f}% | Rs {g:>8.2f} L | Rs {nk:>9.2f} L   | Rs {nf1:>9.2f} L   | {avg_ret:>+8.2f}% ({status})")
    print("=" * 115)
    
    # -------------------------------------------------------------
    # 2. SELL SHORT (Pattern 2) EXIT SWEEP
    # -------------------------------------------------------------
    print("\n" + "=" * 115)
    print("📉 2. SELL SHORT (Pattern 2 Breakdown) EXIT TIME SWEEP (241 Trades, 1 Lot Each)")
    print("=" * 115)
    print(f"{'Exit Time Horizon':<20} | {'Win Rate %':<12} | {'Gross PnL':<14} | {'Net Kotak (L)':<15} | {'Net F1 (L)':<15} | {'Avg Return %'}")
    print("-" * 115)
    for lbl, col in exit_times:
        wr = (sells[f'net_k_{col}'] > 0).mean() * 100
        g = sells[f'gross_{col}'].sum() / 1e5
        nk = sells[f'net_k_{col}'].sum() / 1e5
        nf1 = sells[f'net_f1_{col}'].sum() / 1e5
        avg_ret = sells[f'ret_{col}'].mean()
        status = "🟢 Positive" if nk > 0 else "🔴 Negative"
        print(f"{lbl:<20} | {wr:>10.2f}% | Rs {g:>8.2f} L | Rs {nk:>9.2f} L   | Rs {nf1:>9.2f} L   | {avg_ret:>+8.2f}% ({status})")
    print("=" * 115)
    
    # -------------------------------------------------------------
    # 3. TOTAL COMBINED STRATEGY EXIT SWEEP
    # -------------------------------------------------------------
    print("\n" + "=" * 115)
    print("⚡ 3. TOTAL COMBINED 10:30 STRATEGY (BUY Pattern 1 + SELL Pattern 2) EXIT SWEEP (427 Trades)")
    print("=" * 115)
    print(f"{'Exit Time Horizon':<20} | {'Win Rate %':<12} | {'Gross PnL':<14} | {'Net Kotak (L)':<15} | {'Net F1 (L)':<15} | {'Verdict'}")
    print("-" * 115)
    for lbl, col in exit_times:
        wr = (rdf[f'net_k_{col}'] > 0).mean() * 100
        g = rdf[f'gross_{col}'].sum() / 1e5
        nk = rdf[f'net_k_{col}'].sum() / 1e5
        nf1 = rdf[f'net_f1_{col}'].sum() / 1e5
        status = "🟢 WINNING WINDOW" if nk > 0 else "🔴 Losing"
        print(f"{lbl:<20} | {wr:>10.2f}% | Rs {g:>8.2f} L | Rs {nk:>9.2f} L   | Rs {nf1:>9.2f} L   | {status}")
    print("=" * 115)

if __name__ == '__main__':
    main()
