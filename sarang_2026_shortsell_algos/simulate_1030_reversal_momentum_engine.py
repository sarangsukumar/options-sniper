#!/usr/bin/env python3
"""
simulate_1030_reversal_momentum_engine.py
=========================================
Tests User's Novel Hypothesis:
"What if at 10:30 AM we trade 1 lot based on the detected patterns:
 1. BUY (Go Long) on Loss Pattern 1 (Bull Breakout: New HOD + Gain >= 1.0%)
 2. SELL (Go Short) on Profit Pattern 2 (Bear Breakdown: New LOD + Gain >= 1.0%)
 With correct commissions:
 - Futures F1: Flat Rs 600
 - Equity Cash: Kotak MIS Calculator (+Rs 50 buffer)
"""

import os, sys, pymysql
import pandas as pd
import numpy as np
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, '/home/ubuntu/sarang_2026_shortsell_algos')
from kotak_mis_calculator import calculate_kotak_charges

M2_CSV = '/home/ubuntu/sarang_2026_shortsell_algos/model2_equity_kotak_vs_f1_flat600.csv'
HIST_DATASET = '/home/ubuntu/v5_from_scratch/data/short_sell_ml_dataset_v5_scratch.csv'

def get_db():
    return pymysql.connect(host='localhost', user='root', password='root', database='markets', autocommit=True)

def sim_1030_trade(trade):
    d = trade['date']
    s = trade['stockname']
    lotsize = int(trade['lotsize']) # Exactly 1 lot
    yr = int(d[:4])
    clean_en_eq = float(trade.get('eq_entry_price', 0) or trade.get('entry_price', 0))
    
    conn = get_db()
    cur = conn.cursor(pymysql.cursors.DictCursor)
    
    # 1. Morning Pre-Entry (09:15 to 09:41:59)
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
    final_p = float(ticks[-1]['close'] or ticks[-1]['price'])
    
    # Check 10:30 state
    m_ticks_1030 = [t for t in ticks if str(t['time']) <= f"{d} 10:30:59"]
    a_ticks_1030 = [t for t in ticks if str(t['time']) > f"{d} 10:30:59"]
    
    if not m_ticks_1030 or not a_ticks_1030:
        return None
        
    p_1030 = float(m_ticks_1030[-1]['close'] or m_ticks_1030[-1]['price'])
    max_h_1030 = max([float(t.get('high') or t['price'] or 0) for t in m_ticks_1030])
    min_l_1030 = min([float(t.get('low') or t['price'] or 999999) for t in m_ticks_1030])
    
    # Check Triggers at 10:30 AM
    # Trigger 1: BUY (Long) on Pattern 1
    # Condition: Break above morning high AND price is up >= 1.0% from 09:42 entry
    chg_from_0942_pct = ((p_1030 - en_0942) / en_0942) * 100.0
    
    is_buy_trigger  = (pre_high > 0) and (max_h_1030 > pre_high) and (chg_from_0942_pct >= 1.0)
    
    # Trigger 2: SELL (Short) on Pattern 2
    # Condition: Break below morning low AND price is down >= 1.0% from 09:42 entry
    is_sell_trigger = (pre_low < 999999) and (min_l_1030 < pre_low) and (chg_from_0942_pct <= -1.0)
    
    if not is_buy_trigger and not is_sell_trigger:
        return None # No pattern triggered
        
    trade_type = 'BUY_LONG' if is_buy_trigger else 'SELL_SHORT'
    
    # Simulate trade from 10:30 AM to 14:45 PM
    # Let's test with a 2.5% Stop Loss from 10:30 entry
    sl_pct = 2.5
    exit_p = final_p
    sl_hit = False
    
    if trade_type == 'BUY_LONG':
        sl_val = round(p_1030 * (1.0 - sl_pct / 100.0), 2)
        for t in a_ticks_1030:
            l = float(t.get('low') or t['price'] or 999999)
            if l <= sl_val:
                exit_p = sl_val
                sl_hit = True
                break
        gross_pnl = (exit_p - p_1030) * lotsize
        ret_pct = ((exit_p - p_1030) / p_1030) * 100.0
        
    else: # SELL_SHORT
        sl_val = round(p_1030 * (1.0 + sl_pct / 100.0), 2)
        for t in a_ticks_1030:
            h = float(t.get('high') or t['price'] or 0)
            if h >= sl_val:
                exit_p = sl_val
                sl_hit = True
                break
        gross_pnl = (p_1030 - exit_p) * lotsize
        ret_pct = ((p_1030 - exit_p) / p_1030) * 100.0
        
    # Charges
    chg_kotak = calculate_kotak_charges(p_1030, exit_p, lotsize)['total_charges']
    net_kotak = gross_pnl - chg_kotak
    net_f1    = gross_pnl - 600.0 # Flat Rs 600 per lot
    
    return {
        'date': d, 'stockname': s, 'year': yr, 'lotsize': lotsize,
        'trade_type': trade_type, 'p_1030': p_1030, 'exit_p': exit_p,
        'gross_pnl': gross_pnl, 'net_kotak': net_kotak, 'net_f1': net_f1,
        'ret_pct': ret_pct, 'sl_hit': sl_hit
    }

def main():
    df_m2 = pd.read_csv(M2_CSV)
    trades = df_m2.to_dict('records')
    print(f"Simulating 10:30 AM Momentum Strategy across {len(trades):,} opportunities...")
    with ThreadPoolExecutor(max_workers=24) as ex:
        results = [r for r in ex.map(sim_1030_trade, trades) if r is not None]
    rdf = pd.DataFrame(results)
    
    print(f"\n✔ Total 10:30 AM Strategy Trades Triggered: {len(rdf):,} (1 Lot Each)")
    
    # Breakdown by Trade Type
    buys = rdf[rdf['trade_type'] == 'BUY_LONG']
    sells = rdf[rdf['trade_type'] == 'SELL_SHORT']
    
    print("=" * 115)
    print("⚡ 10:30 AM REVERSAL MOMENTUM STRATEGY BENCHMARK (1 LOT TRADES, 2020-2026)")
    print("=" * 115)
    print(f"{'Strategy Arm':<25} | {'Trades':<8} | {'Win Rate %':<12} | {'Gross PnL (L)':<15} | {'Net Kotak (L)':<15} | {'Net F1 (L)':<15} | {'Avg Net/Trd'}")
    print("-" * 115)
    
    for name, sub in [("1. BUY LONG (Pattern 1)", buys), ("2. SELL SHORT (Pattern 2)", sells), ("TOTAL COMBINED STRATEGY", rdf)]:
        cnt = len(sub)
        wr = (sub['net_kotak'] > 0).mean() * 100
        gross = sub['gross_pnl'].sum() / 1e5
        k_net = sub['net_kotak'].sum() / 1e5
        f1_net = sub['net_f1'].sum() / 1e5
        avg_k = sub['net_kotak'].mean()
        print(f"{name:<25} | {cnt:>8} | {wr:>10.2f}% | Rs {gross:>11.2f} L | Rs {k_net:>11.2f} L | Rs {f1_net:>11.2f} L | Rs {avg_k:>8.2f}")
    print("=" * 115)
    
    # Year by Year Breakdown
    print("\n📅 YEAR-BY-YEAR PERFORMANCE (Net Kotak MIS Charges in ₹ Lakhs):")
    print("-" * 115)
    print(f"{'Year':<6} | {'Trades':<8} | {'BUY Trades':<12} | {'SELL Trades':<12} | {'Win Rate %':<12} | {'Net Kotak (L)':<15} | {'Net F1 (L)':<15}")
    print("-" * 115)
    for y, g in rdf.groupby('year'):
        cnt = len(g)
        b_cnt = (g['trade_type'] == 'BUY_LONG').sum()
        s_cnt = (g['trade_type'] == 'SELL_SHORT').sum()
        wr = (g['net_kotak'] > 0).mean() * 100
        k_net = g['net_kotak'].sum() / 1e5
        f1_net = g['net_f1'].sum() / 1e5
        print(f"{y:<6} | {cnt:>8} | {b_cnt:>12} | {s_cnt:>12} | {wr:>10.2f}% | +Rs {k_net:>11.2f} L | +Rs {f1_net:>11.2f} L")
    print("-" * 115)
    tot_cnt = len(rdf)
    tot_wr = (rdf['net_kotak'] > 0).mean() * 100
    tot_k = rdf['net_kotak'].sum() / 1e5
    tot_f1 = rdf['net_f1'].sum() / 1e5
    print(f"{'TOTAL':<6} | {tot_cnt:>8} | {(rdf['trade_type']=='BUY_LONG').sum():>12} | {(rdf['trade_type']=='SELL_SHORT').sum():>12} | {tot_wr:>10.2f}% | +Rs {tot_k:>11.2f} L | +Rs {tot_f1:>11.2f} L")
    print("=" * 115)

if __name__ == '__main__':
    main()
