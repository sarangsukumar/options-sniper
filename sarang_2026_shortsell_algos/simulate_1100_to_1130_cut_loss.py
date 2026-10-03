#!/usr/bin/env python3
"""
simulate_1100_to_1130_cut_loss.py
==================================
Simulates User's Hypothesis on Model 2 (09:42 -> 14:45):
"If a stock is in loss at 11:00 AM AND it continues to be in loss till 11:30 AM, square off that trade at 11:30 AM."

Tested across all 4,424 completed trades (2020-2026) on:
1. Equity Cash (`markets.scrapdata`) with Kotak MIS Charges (+Rs 50 buffer)
2. Equity Cash (`markets.scrapdata`) with Flat Rs 600 Charges
3. Near-Month Futures (`markets.scrapdata_F1`) with Flat Rs 600 Charges
"""

import os, sys, time, pymysql
import pandas as pd
import numpy as np
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, '/home/ubuntu/sarang_2026_shortsell_algos')
from kotak_mis_calculator import calculate_kotak_charges

BASE_DIR = '/home/ubuntu/sarang_2026_shortsell_algos'
M2_FILE = os.path.join(BASE_DIR, '02_Best_Longer_Window_0942_1445', 'audited_0940_hybrid_trades.csv')
OUT_CSV = os.path.join(BASE_DIR, 'model2_1100_1130_cut_loss_trades.csv')

def get_db_connection():
    return pymysql.connect(host='localhost', user='root', password='root', database='markets', autocommit=True)

def sim_trade_cut_loss(trade):
    d = trade['date']
    s = trade['stockname']
    qty = int(trade['total_quantity'])
    mult = int(trade['lots_to_trade'])
    yr = int(d[:4])
    
    conn = get_db_connection()
    cur = conn.cursor(pymysql.cursors.DictCursor)
    
    # 1. Equity ticks
    cur.execute(f"""
    SELECT time, price, high, low, close 
    FROM scrapdata 
    WHERE date = '{d}' AND stockname IN ('{s}', '\"{s}\"', '{s} ') 
      AND time >= '{d} 09:42:00' AND time <= '{d} 14:45:59' 
    ORDER BY time ASC
    """)
    ticks_eq = cur.fetchall()
    
    # 2. Futures ticks
    cur.execute(f"""
    SELECT time, price 
    FROM scrapdata_F1 
    WHERE date = '{d}' AND stockname IN ('{s}', '\"{s}\"', '{s} ') 
      AND time >= '{d} 09:42:00' AND time <= '{d} 14:45:59' 
    ORDER BY time ASC
    """)
    ticks_f1 = cur.fetchall()
    conn.close()
    
    res = {'date': d, 'stockname': s, 'year': yr, 'qty': qty, 'lots': mult}
    
    # --- EVALUATE EQUITY CASH ---
    if ticks_eq:
        en_eq = float(ticks_eq[0]['price'] or ticks_eq[0]['close'] or ticks_eq[0]['open'])
        sl3_eq = round(en_eq * 1.03, 2)
        final_eq = float(ticks_eq[-1]['close'] or ticks_eq[-1]['price'])
        
        # 1. Baseline 3% SL
        ex_eq_base = final_eq
        hit_eq_base = False
        for t in ticks_eq:
            h = float(t['high'] or t['price'] or 0)
            if h >= sl3_eq:
                ex_eq_base = sl3_eq
                hit_eq_base = True
                break
                
        # 2. User Rule: Loss at 11:00 AND Loss at 11:30 -> Square off at 11:30
        ex_eq_rule = final_eq
        rule_triggered_eq = False
        exit_reason_eq = 'TIME_EXIT'
        
        # Find 11:00 and 11:30 ticks
        t_1100 = None
        t_1130 = None
        hit_sl_before_1130 = False
        
        for t in ticks_eq:
            tm = str(t['time'])
            h = float(t['high'] or t['price'] or 0)
            
            # SL check
            if h >= sl3_eq and not hit_sl_before_1130:
                if tm <= f"{d} 11:30:00":
                    hit_sl_before_1130 = True
                    ex_eq_rule = sl3_eq
                    exit_reason_eq = 'STOP_LOSS_3PCT'
                    break
                    
            if tm <= f"{d} 11:00:59":
                t_1100 = t
            if tm <= f"{d} 11:30:59":
                t_1130 = t
                
        if not hit_sl_before_1130:
            p_1100 = float(t_1100['close'] or t_1100['price']) if t_1100 else en_eq
            p_1130 = float(t_1130['close'] or t_1130['price']) if t_1130 else en_eq
            
            loss_at_1100 = (p_1100 > en_eq)
            loss_at_1130 = (p_1130 > en_eq)
            
            if loss_at_1100 and loss_at_1130:
                # Square off at 11:30!
                rule_triggered_eq = True
                ex_eq_rule = p_1130
                exit_reason_eq = 'CUT_LOSS_1130'
            else:
                # Ride through afternoon with 3% SL
                for t in ticks_eq:
                    tm = str(t['time'])
                    if tm > f"{d} 11:30:00":
                        h = float(t['high'] or t['price'] or 0)
                        if h >= sl3_eq:
                            ex_eq_rule = sl3_eq
                            exit_reason_eq = 'STOP_LOSS_3PCT'
                            break
                            
        res['eq_en'] = en_eq
        res['eq_ex_base'] = ex_eq_base
        res['eq_gross_base'] = (en_eq - ex_eq_base) * qty
        res['eq_ex_rule'] = ex_eq_rule
        res['eq_gross_rule'] = (en_eq - ex_eq_rule) * qty
        res['eq_cut_1130'] = 1 if rule_triggered_eq else 0
        res['eq_reason_rule'] = exit_reason_eq
    else:
        res['eq_en'] = None
        
    # --- EVALUATE FUTURES F1 ---
    if ticks_f1:
        prices_f1 = [float(t['price']) for t in ticks_f1 if t['price'] is not None]
        times_f1 = [str(t['time']) for t in ticks_f1 if t['price'] is not None]
        if prices_f1:
            en_f1 = prices_f1[0]
            sl3_f1 = round(en_f1 * 1.03, 2)
            final_f1 = prices_f1[-1]
            
            # Baseline
            ex_f1_base = final_f1
            for p in prices_f1:
                if p >= sl3_f1:
                    ex_f1_base = sl3_f1
                    break
                    
            # User Rule
            ex_f1_rule = final_f1
            rule_triggered_f1 = False
            exit_reason_f1 = 'TIME_EXIT'
            hit_sl_f1_early = False
            
            p_1100_f1 = en_f1
            p_1130_f1 = en_f1
            
            for tm, p in zip(times_f1, prices_f1):
                if p >= sl3_f1 and not hit_sl_f1_early:
                    if tm <= f"{d} 11:30:00":
                        hit_sl_f1_early = True
                        ex_f1_rule = sl3_f1
                        exit_reason_f1 = 'STOP_LOSS_3PCT'
                        break
                if tm <= f"{d} 11:00:59":
                    p_1100_f1 = p
                if tm <= f"{d} 11:30:59":
                    p_1130_f1 = p
                    
            if not hit_sl_f1_early:
                loss_1100_f1 = (p_1100_f1 > en_f1)
                loss_1130_f1 = (p_1130_f1 > en_f1)
                
                if loss_1100_f1 and loss_1130_f1:
                    rule_triggered_f1 = True
                    ex_f1_rule = p_1130_f1
                    exit_reason_f1 = 'CUT_LOSS_1130'
                else:
                    for tm, p in zip(times_f1, prices_f1):
                        if tm > f"{d} 11:30:00":
                            if p >= sl3_f1:
                                ex_f1_rule = sl3_f1
                                exit_reason_f1 = 'STOP_LOSS_3PCT'
                                break
                                
            res['f1_en'] = en_f1
            res['f1_ex_base'] = ex_f1_base
            res['f1_gross_base'] = (en_f1 - ex_f1_base) * qty
            res['f1_ex_rule'] = ex_f1_rule
            res['f1_gross_rule'] = (en_f1 - ex_f1_rule) * qty
            res['f1_cut_1130'] = 1 if rule_triggered_f1 else 0
            res['f1_reason_rule'] = exit_reason_f1
        else:
            res['f1_en'] = None
    else:
        res['f1_en'] = None
        
    return res

def main():
    print("=" * 95)
    print("🔬 SIMULATING 11:00 AM -> 11:30 AM CUT-LOSS RULE ON MODEL 2 (2020-2026)")
    print("   Hypothesis: If in LOSS at 11:00 AM AND in LOSS at 11:30 AM -> Square off at 11:30 AM")
    print("=" * 95)
    
    df = pd.read_csv(M2_FILE)
    df = df[df['status'] == 'COMPLETED'].copy()
    print(f"Loaded {len(df):,} completed trades.")
    
    trades = df.to_dict('records')
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=24) as executor:
        results = list(executor.map(sim_trade_cut_loss, trades))
    t1 = time.time()
    print(f"✔ Completed simulation in {t1-t0:.2f} seconds.")
    
    res_df = pd.DataFrame(results)
    
    # Compute Charges
    flat_chg = 600.0 * res_df['lots']
    
    # 1. Equity Net PnL (Kotak MIS)
    eq_valid = res_df[res_df['eq_en'].notna()].copy()
    eq_chg_base = [calculate_kotak_charges(float(en), float(ex), int(q))['total_charges']
                   for en, ex, q in zip(eq_valid['eq_en'], eq_valid['eq_ex_base'], eq_valid['qty'])]
    eq_chg_rule = [calculate_kotak_charges(float(en), float(ex), int(q))['total_charges']
                   for en, ex, q in zip(eq_valid['eq_en'], eq_valid['eq_ex_rule'], eq_valid['qty'])]
    eq_valid['eq_net_base'] = eq_valid['eq_gross_base'] - pd.Series(eq_chg_base)
    eq_valid['eq_net_rule'] = eq_valid['eq_gross_rule'] - pd.Series(eq_chg_rule)
    eq_valid['eq_net_base_flat'] = eq_valid['eq_gross_base'] - (600.0 * eq_valid['lots'])
    eq_valid['eq_net_rule_flat'] = eq_valid['eq_gross_rule'] - (600.0 * eq_valid['lots'])
    
    # 2. Futures Net PnL (Flat 600)
    f1_valid = res_df[res_df['f1_en'].notna()].copy()
    f1_valid['f1_net_base'] = f1_valid['f1_gross_base'] - (600.0 * f1_valid['lots'])
    f1_valid['f1_net_rule'] = f1_valid['f1_gross_rule'] - (600.0 * f1_valid['lots'])
    
    res_df.to_csv(OUT_CSV, index=False)
    print(f"✔ Saved full trade comparison ledger to:\n  {OUT_CSV}")
    
    # -------------------------------------------------------------
    # 1. EQUITY CASH RESULTS
    # -------------------------------------------------------------
    print("\n" + "#" * 95)
    print("📊 1. EQUITY CASH (`scrapdata`) RESULTS: BASELINE vs 11:30 CUT-LOSS RULE")
    print("#" * 95)
    cut_eq_cnt = eq_valid['eq_cut_1130'].sum()
    print(f"Trades cut at 11:30 AM      : {cut_eq_cnt:,} / {len(eq_valid):,} ({cut_eq_cnt/len(eq_valid)*100:.1f}% of trades)")
    print("-" * 95)
    print(f"{'Metric':<32} | {'Baseline (Hold till 14:45)':<28} | {'11:30 Cut-Loss Rule':<28} | {'Variance':<12}")
    print("-" * 95)
    print(f"{'Gross Profit':<32} | +Rs {eq_valid['eq_gross_base'].sum()/1e5:>8.2f} L (+Rs {eq_valid['eq_gross_base'].sum()/1e7:.3f} Cr) | +Rs {eq_valid['eq_gross_rule'].sum()/1e5:>8.2f} L (+Rs {eq_valid['eq_gross_rule'].sum()/1e7:.3f} Cr) | {(eq_valid['eq_gross_rule'].sum() - eq_valid['eq_gross_base'].sum())/1e5:>+8.2f} L")
    print(f"{'Net Profit (Kotak MIS)':<32} | +Rs {eq_valid['eq_net_base'].sum()/1e5:>8.2f} L (+Rs {eq_valid['eq_net_base'].sum()/1e7:.3f} Cr) | +Rs {eq_valid['eq_net_rule'].sum()/1e5:>8.2f} L (+Rs {eq_valid['eq_net_rule'].sum()/1e7:.3f} Cr) | {(eq_valid['eq_net_rule'].sum() - eq_valid['eq_net_base'].sum())/1e5:>+8.2f} L")
    print(f"{'Net Profit (Flat Rs 600)':<32} | +Rs {eq_valid['eq_net_base_flat'].sum()/1e5:>8.2f} L (+Rs {eq_valid['eq_net_base_flat'].sum()/1e7:.3f} Cr) | +Rs {eq_valid['eq_net_rule_flat'].sum()/1e5:>8.2f} L (+Rs {eq_valid['eq_net_rule_flat'].sum()/1e7:.3f} Cr) | {(eq_valid['eq_net_rule_flat'].sum() - eq_valid['eq_net_base_flat'].sum())/1e5:>+8.2f} L")
    print(f"{'Trade Win Rate %':<32} | { (eq_valid['eq_net_base']>0).mean()*100:>26.2f}% | { (eq_valid['eq_net_rule']>0).mean()*100:>26.2f}% | {(eq_valid['eq_net_rule']>0).mean()*100 - (eq_valid['eq_net_base']>0).mean()*100:>+8.2f}%")
    
    # Year-by-year Equity
    print("\n📅 EQUITY CASH (Kotak MIS Charges) YEAR-BY-YEAR COMPARISON (₹ Lakhs):")
    print("-" * 95)
    print(f"{'Year':<6} | {'Trades':<8} | {'Cut @ 11:30 %':<14} | {'Baseline Net (L)':<18} | {'11:30 Rule Net (L)':<18} | {'Variance':<12}")
    print("-" * 95)
    for y, g in eq_valid.groupby('year'):
        cut_p = g['eq_cut_1130'].mean() * 100
        net_b = g['eq_net_base'].sum() / 1e5
        net_r = g['eq_net_rule'].sum() / 1e5
        diff = net_r - net_b
        print(f"{y:<6} | {len(g):<8} | {cut_p:>12.1f}% | +Rs {net_b:>10.2f} L     | +Rs {net_r:>10.2f} L     | {diff:>+8.2f} L")
    print("-" * 95)
    
    # -------------------------------------------------------------
    # 2. FUTURES F1 RESULTS
    # -------------------------------------------------------------
    print("\n" + "#" * 95)
    print("📊 2. FUTURES F1 (`scrapdata_F1`) RESULTS: BASELINE vs 11:30 CUT-LOSS RULE (FLAT ₹600)")
    print("#" * 95)
    cut_f1_cnt = f1_valid['f1_cut_1130'].sum()
    print(f"Trades cut at 11:30 AM      : {cut_f1_cnt:,} / {len(f1_valid):,} ({cut_f1_cnt/len(f1_valid)*100:.1f}% of trades)")
    print("-" * 95)
    print(f"{'Metric':<32} | {'Baseline (Hold till 14:45)':<28} | {'11:30 Cut-Loss Rule':<28} | {'Variance':<12}")
    print("-" * 95)
    print(f"{'Gross Profit':<32} | +Rs {f1_valid['f1_gross_base'].sum()/1e5:>8.2f} L (+Rs {f1_valid['f1_gross_base'].sum()/1e7:.3f} Cr) | +Rs {f1_valid['f1_gross_rule'].sum()/1e5:>8.2f} L (+Rs {f1_valid['f1_gross_rule'].sum()/1e7:.3f} Cr) | {(f1_valid['f1_gross_rule'].sum() - f1_valid['f1_gross_base'].sum())/1e5:>+8.2f} L")
    print(f"{'Net Profit (Flat Rs 600)':<32} | +Rs {f1_valid['f1_net_base'].sum()/1e5:>8.2f} L (+Rs {f1_valid['f1_net_base'].sum()/1e7:.3f} Cr) | +Rs {f1_valid['f1_net_rule'].sum()/1e5:>8.2f} L (+Rs {f1_valid['f1_net_rule'].sum()/1e7:.3f} Cr) | {(f1_valid['f1_net_rule'].sum() - f1_valid['f1_net_base'].sum())/1e5:>+8.2f} L")
    print(f"{'Trade Win Rate %':<32} | { (f1_valid['f1_net_base']>0).mean()*100:>26.2f}% | { (f1_valid['f1_net_rule']>0).mean()*100:>26.2f}% | {(f1_valid['f1_net_rule']>0).mean()*100 - (f1_valid['f1_net_base']>0).mean()*100:>+8.2f}%")
    
    # Year-by-year Futures
    print("\n📅 FUTURES F1 (Flat ₹600 Charges) YEAR-BY-YEAR COMPARISON (₹ Lakhs):")
    print("-" * 95)
    print(f"{'Year':<6} | {'Trades':<8} | {'Cut @ 11:30 %':<14} | {'Baseline Net (L)':<18} | {'11:30 Rule Net (L)':<18} | {'Variance':<12}")
    print("-" * 95)
    for y, g in f1_valid.groupby('year'):
        cut_p = g['f1_cut_1130'].mean() * 100
        net_b = g['f1_net_base'].sum() / 1e5
        net_r = g['f1_net_rule'].sum() / 1e5
        diff = net_r - net_b
        print(f"{y:<6} | {len(g):<8} | {cut_p:>12.1f}% | +Rs {net_b:>10.2f} L     | +Rs {net_r:>10.2f} L     | {diff:>+8.2f} L")
    print("=" * 95)

if __name__ == '__main__':
    main()
