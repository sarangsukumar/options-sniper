#!/usr/bin/env python3
"""
evaluate_m2_1pct_sl.py
======================
Simulates Model 2 (09:42 -> 14:45) with 1.0% Stop Loss vs 3.0% Stop Loss.
Evaluates tick-by-tick continuous Stop Loss from MySQL `scrapdata_F1` (Futures)
and `scrapdata` (Equity Cash).
Computes Net PnL under:
1. Flat Rs 600 per lot traded
2. Kotak MIS Calculator charges
"""

import os, sys, time, pymysql
import pandas as pd
import numpy as np
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, '/home/ubuntu/sarang_2026_shortsell_algos')
from kotak_mis_calculator import calculate_kotak_charges

BASE_DIR = '/home/ubuntu/sarang_2026_shortsell_algos'
M2_FILE = os.path.join(BASE_DIR, '02_Best_Longer_Window_0942_1445', 'audited_0940_hybrid_trades.csv')
OUT_CSV = os.path.join(BASE_DIR, 'model2_1pct_vs_3pct_sl_comparison.csv')

def get_db_connection():
    return pymysql.connect(host='localhost', user='root', password='root', database='markets', autocommit=True)

def eval_sl_trade(trade):
    d = trade['date']
    s = trade['stockname']
    qty = int(trade['total_quantity'])
    mult = int(trade['lots_to_trade'])
    yr = int(d[:4])
    
    conn = get_db_connection()
    cur = conn.cursor(pymysql.cursors.DictCursor)
    
    # 1. Query Futures scrapdata_F1
    q_f1 = f"""
    SELECT time, price 
    FROM scrapdata_F1 
    WHERE date = '{d}' AND (stockname = '{s}' OR stockname = '\"{s}\"' OR stockname = '{s} ') 
      AND time >= '{d} 09:42:00' AND time <= '{d} 14:45:59' 
    ORDER BY time ASC
    """
    cur.execute(q_f1)
    ticks_f1 = cur.fetchall()
    
    # 2. Query Equity scrapdata
    q_eq = f"""
    SELECT time, price, high, low, close 
    FROM scrapdata 
    WHERE date = '{d}' AND (stockname = '{s}' OR stockname = '\"{s}\"' OR stockname = '{s} ') 
      AND time >= '{d} 09:42:00' AND time <= '{d} 14:45:59' 
    ORDER BY time ASC
    """
    cur.execute(q_eq)
    ticks_eq = cur.fetchall()
    conn.close()
    
    res = {
        'date': d, 'stockname': s, 'year': yr, 'total_quantity': qty, 'lots_to_trade': mult
    }
    
    # Process Futures F1
    if ticks_f1:
        prices_f1 = [float(t['price']) for t in ticks_f1 if t['price'] is not None]
        if prices_f1:
            en_f1 = prices_f1[0]
            final_f1 = prices_f1[-1]
            
            # 3% SL
            sl3 = round(en_f1 * 1.03, 2)
            ex_f1_3 = final_f1
            hit_f1_3 = False
            for p in prices_f1:
                if p >= sl3:
                    ex_f1_3 = sl3
                    hit_f1_3 = True
                    break
                    
            # 1% SL
            sl1 = round(en_f1 * 1.01, 2)
            ex_f1_1 = final_f1
            hit_f1_1 = False
            for p in prices_f1:
                if p >= sl1:
                    ex_f1_1 = sl1
                    hit_f1_1 = True
                    break
                    
            res['f1_en'] = en_f1
            res['f1_ex_3sl'] = ex_f1_3
            res['f1_hit_3sl'] = hit_f1_3
            res['f1_ex_1sl'] = ex_f1_1
            res['f1_hit_1sl'] = hit_f1_1
            res['f1_gross_3sl'] = (en_f1 - ex_f1_3) * qty
            res['f1_gross_1sl'] = (en_f1 - ex_f1_1) * qty
        else:
            res['f1_en'] = None
    else:
        res['f1_en'] = None
        
    # Process Equity Cash
    if ticks_eq:
        en_eq = float(ticks_eq[0]['price'] or ticks_eq[0]['close'] or ticks_eq[0]['open'])
        final_eq = float(ticks_eq[-1]['close'] or ticks_eq[-1]['price'])
        
        # 3% SL
        sl3_eq = round(en_eq * 1.03, 2)
        ex_eq_3 = final_eq
        hit_eq_3 = False
        for t in ticks_eq:
            h = float(t['high'] or t['price'] or 0)
            if h >= sl3_eq:
                ex_eq_3 = sl3_eq
                hit_eq_3 = True
                break
                
        # 1% SL
        sl1_eq = round(en_eq * 1.01, 2)
        ex_eq_1 = final_eq
        hit_eq_1 = False
        for t in ticks_eq:
            h = float(t['high'] or t['price'] or 0)
            if h >= sl1_eq:
                ex_eq_1 = sl1_eq
                hit_eq_1 = True
                break
                
        res['eq_en'] = en_eq
        res['eq_ex_3sl'] = ex_eq_3
        res['eq_hit_3sl'] = hit_eq_3
        res['eq_ex_1sl'] = ex_eq_1
        res['eq_hit_1sl'] = hit_eq_1
        res['eq_gross_3sl'] = (en_eq - ex_eq_3) * qty
        res['eq_gross_1sl'] = (en_eq - ex_eq_1) * qty
    else:
        res['eq_en'] = None
        
    return res

def main():
    print("=" * 95)
    print("🔬 MODEL 2 STOP LOSS EXPERIMENT: 1.0% SL vs 3.0% SL (TICK-BY-TICK CONTINUOUS)")
    print("=" * 95)
    
    df = pd.read_csv(M2_FILE)
    df = df[df['status'] == 'COMPLETED'].copy()
    print(f"Loaded {len(df):,} completed Model 2 trades.")
    
    trades = df.to_dict('records')
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=24) as executor:
        results = list(executor.map(eval_sl_trade, trades))
    t1 = time.time()
    print(f"✔ Queried all {len(results):,} trades in {t1-t0:.2f} seconds.")
    
    res_df = pd.DataFrame(results)
    
    # Calculate Charges and Net PnL
    # Futures Flat 600
    chg_f1 = 600.0 * res_df['lots_to_trade']
    res_df['f1_net_3sl'] = res_df['f1_gross_3sl'] - chg_f1
    res_df['f1_net_1sl'] = res_df['f1_gross_1sl'] - chg_f1
    
    # Equity Kotak Charges
    eq_chg_3 = [calculate_kotak_charges(float(en), float(ex), int(q))['total_charges'] if pd.notna(en) and pd.notna(ex) else 0.0 
                for en, ex, q in zip(res_df['eq_en'], res_df['eq_ex_3sl'], res_df['total_quantity'])]
    eq_chg_1 = [calculate_kotak_charges(float(en), float(ex), int(q))['total_charges'] if pd.notna(en) and pd.notna(ex) else 0.0 
                for en, ex, q in zip(res_df['eq_en'], res_df['eq_ex_1sl'], res_df['total_quantity'])]
    res_df['eq_net_3sl'] = res_df['eq_gross_3sl'] - pd.Series(eq_chg_3)
    res_df['eq_net_1sl'] = res_df['eq_gross_1sl'] - pd.Series(eq_chg_1)
    
    # Equity Flat 600
    res_df['eq_net_3sl_flat600'] = res_df['eq_gross_3sl'] - chg_f1
    res_df['eq_net_1sl_flat600'] = res_df['eq_gross_1sl'] - chg_f1
    
    res_df.to_csv(OUT_CSV, index=False)
    print(f"✔ Saved trade comparison ledger to:\n  {OUT_CSV}")
    
    # -------------------------------------------------------------
    # COMPARISON REPORT
    # -------------------------------------------------------------
    print("\n" + "#" * 95)
    print("📊 1. FUTURES F1 (`scrapdata_F1`): 3.0% SL vs 1.0% SL (FLAT ₹600/lot)")
    print("#" * 95)
    f1_valid = res_df[res_df['f1_en'].notna()].copy()
    
    print(f"{'Metric':<35} | {'Baseline (3.0% Stop Loss)':<28} | {'Experimental (1.0% Stop Loss)':<28}")
    print("-" * 95)
    print(f"{'SL Hit Frequency':<35} | {f1_valid['f1_hit_3sl'].sum():>6} / {len(f1_valid)} ({f1_valid['f1_hit_3sl'].mean()*100:>5.1f}%) | {f1_valid['f1_hit_1sl'].sum():>6} / {len(f1_valid)} ({f1_valid['f1_hit_1sl'].mean()*100:>5.1f}%) ⚠️")
    print(f"{'Gross Profit':<35} | +Rs {f1_valid['f1_gross_3sl'].sum()/1e5:>8.2f} L (+Rs {f1_valid['f1_gross_3sl'].sum()/1e7:.3f} Cr) | +Rs {f1_valid['f1_gross_1sl'].sum()/1e5:>8.2f} L (+Rs {f1_valid['f1_gross_1sl'].sum()/1e7:.3f} Cr)")
    print(f"{'Total Charges (@ Flat 600)':<35} | -Rs {chg_f1.sum()/1e5:>8.2f} Lakhs            | -Rs {chg_f1.sum()/1e5:>8.2f} Lakhs")
    print(f"{'Net Profit':<35} | 👑 +Rs {f1_valid['f1_net_3sl'].sum()/1e5:>6.2f} L (+Rs {f1_valid['f1_net_3sl'].sum()/1e7:.3f} Cr) | +Rs {f1_valid['f1_net_1sl'].sum()/1e5:>8.2f} L (+Rs {f1_valid['f1_net_1sl'].sum()/1e7:.3f} Cr)")
    print(f"{'Trade Win Rate':<35} | { (f1_valid['f1_net_3sl']>0).mean()*100:>26.2f}% | { (f1_valid['f1_net_1sl']>0).mean()*100:>26.2f}%")
    
    # Yearly breakdown Futures
    print("\n📅 FUTURES F1: YEAR-BY-YEAR NET PnL (₹ Lakhs) [@ Flat 600]")
    print("-" * 95)
    print(f"{'Year':<6} | {'Trades':<8} | {'3.0% SL Hit %':<14} | {'3.0% SL Net PnL':<17} | {'1.0% SL Hit %':<14} | {'1.0% SL Net PnL':<17} | {'Difference':<12}")
    print("-" * 95)
    for y, g in f1_valid.groupby('year'):
        hit3_p = g['f1_hit_3sl'].mean() * 100
        net3 = g['f1_net_3sl'].sum() / 1e5
        hit1_p = g['f1_hit_1sl'].mean() * 100
        net1 = g['f1_net_1sl'].sum() / 1e5
        diff = net1 - net3
        print(f"{y:<6} | {len(g):<8} | {hit3_p:>12.1f}% | +Rs {net3:>9.2f} L     | {hit1_p:>12.1f}% | +Rs {net1:>9.2f} L     | {diff:>+8.2f} L")
    print("-" * 95)
    
    # -------------------------------------------------------------
    # EQUITY CASH BREAKDOWN
    # -------------------------------------------------------------
    print("\n" + "#" * 95)
    print("📊 2. EQUITY CASH (`scrapdata`): 3.0% SL vs 1.0% SL")
    print("#" * 95)
    eq_valid = res_df[res_df['eq_en'].notna()].copy()
    
    print(f"{'Metric':<35} | {'Baseline (3.0% Stop Loss)':<28} | {'Experimental (1.0% Stop Loss)':<28}")
    print("-" * 95)
    print(f"{'SL Hit Frequency':<35} | {eq_valid['eq_hit_3sl'].sum():>6} / {len(eq_valid)} ({eq_valid['eq_hit_3sl'].mean()*100:>5.1f}%) | {eq_valid['eq_hit_1sl'].sum():>6} / {len(eq_valid)} ({eq_valid['eq_hit_1sl'].mean()*100:>5.1f}%) ⚠️")
    print(f"{'Gross Profit':<35} | +Rs {eq_valid['eq_gross_3sl'].sum()/1e5:>8.2f} L (+Rs {eq_valid['eq_gross_3sl'].sum()/1e7:.3f} Cr) | +Rs {eq_valid['eq_gross_1sl'].sum()/1e5:>8.2f} L (+Rs {eq_valid['eq_gross_1sl'].sum()/1e7:.3f} Cr)")
    print(f"{'Net PnL (Kotak MIS Charges)':<35} | 👑 +Rs {eq_valid['eq_net_3sl'].sum()/1e5:>6.2f} L (+Rs {eq_valid['eq_net_3sl'].sum()/1e7:.3f} Cr) | +Rs {eq_valid['eq_net_1sl'].sum()/1e5:>8.2f} L (+Rs {eq_valid['eq_net_1sl'].sum()/1e7:.3f} Cr)")
    print(f"{'Net PnL (Flat 600 Charges)':<35} | 👑 +Rs {eq_valid['eq_net_3sl_flat600'].sum()/1e5:>6.2f} L (+Rs {eq_valid['eq_net_3sl_flat600'].sum()/1e7:.3f} Cr) | +Rs {eq_valid['eq_net_1sl_flat600'].sum()/1e5:>8.2f} L (+Rs {eq_valid['eq_net_1sl_flat600'].sum()/1e7:.3f} Cr)")
    print(f"{'Trade Win Rate':<35} | { (eq_valid['eq_net_3sl']>0).mean()*100:>26.2f}% | { (eq_valid['eq_net_1sl']>0).mean()*100:>26.2f}%")
    print("-" * 95)
    
    # Yearly breakdown Equity
    print("\n📅 EQUITY CASH: YEAR-BY-YEAR NET PnL (₹ Lakhs) [Kotak MIS Charges]")
    print("-" * 95)
    print(f"{'Year':<6} | {'Trades':<8} | {'3.0% SL Hit %':<14} | {'3.0% SL Net PnL':<17} | {'1.0% SL Hit %':<14} | {'1.0% SL Net PnL':<17} | {'Difference':<12}")
    print("-" * 95)
    for y, g in eq_valid.groupby('year'):
        hit3_p = g['eq_hit_3sl'].mean() * 100
        net3 = g['eq_net_3sl'].sum() / 1e5
        hit1_p = g['eq_hit_1sl'].mean() * 100
        net1 = g['eq_net_1sl'].sum() / 1e5
        diff = net1 - net3
        print(f"{y:<6} | {len(g):<8} | {hit3_p:>12.1f}% | +Rs {net3:>9.2f} L     | {hit1_p:>12.1f}% | +Rs {net1:>9.2f} L     | {diff:>+8.2f} L")
    print("=" * 95)

if __name__ == '__main__':
    main()
