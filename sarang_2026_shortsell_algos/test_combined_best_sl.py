#!/usr/bin/env python3
"""
test_combined_best_sl.py
Tests combinations of:
1. Baseline 3.0% SL
2. 3.5% Fixed SL
3. 4.0% Fixed SL
4. 3.5% SL + Dynamic Trailing 2.0% from Low once +2.0% profit
5. 3.0% SL + Dynamic Trailing 2.0% from Low once +2.0% profit
6. 3.5% SL + Dynamic Trailing 1.5% from Low once +1.5% profit
7. 3.5% SL + Dynamic Trailing 2.5% from Low once +2.0% profit
8. Severe 2.5% Midday Cut + 3.5% SL

Evaluated across all 4,424 trades in Model 2 on both:
- Near-month Futures F1 (Flat Rs 600)
- Equity Cash (Kotak MIS Charges)
"""
import os, sys, pymysql
import pandas as pd
import numpy as np
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, '/home/ubuntu/sarang_2026_shortsell_algos')
from kotak_mis_calculator import calculate_kotak_charges

BASE_DIR = '/home/ubuntu/sarang_2026_shortsell_algos'
M2_FILE = os.path.join(BASE_DIR, '02_Best_Longer_Window_0942_1445', 'audited_0940_hybrid_trades.csv')

def get_db():
    return pymysql.connect(host='localhost', user='root', password='root', database='markets', autocommit=True)

def sim_sl_combos(trade):
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
    ticks_f1 = cur.fetchall()
    
    cur.execute(f"""
    SELECT time, price, high, low, close 
    FROM scrapdata 
    WHERE date = '{d}' AND stockname IN ('{s}', '\"{s}\"', '{s} ') 
      AND time >= '{d} 09:42:00' AND time <= '{d} 14:45:59' 
    ORDER BY time ASC
    """)
    ticks_eq = cur.fetchall()
    conn.close()
    
    res = {'date': d, 'stockname': s, 'year': yr, 'qty': qty, 'lots': lots}
    
    # Process F1
    if ticks_f1 and len(ticks_f1) >= 10:
        p_f1 = [float(t['price']) for t in ticks_f1 if t['price'] is not None]
        t_f1 = [str(t['time']) for t in ticks_f1 if t['price'] is not None]
        if len(p_f1) >= 10:
            en = p_f1[0]
            final_p = p_f1[-1]
            n = len(p_f1)
            
            # Helper to run rules
            # 1. Fixed SL X%
            def run_fixed(pct):
                sl = round(en * (1.0 + pct/100.0), 2)
                for p in p_f1:
                    if p >= sl:
                        return sl, True
                return final_p, False
                
            # 2. Dynamic Trailing (init_sl_pct, activation_profit_pct, trail_pct)
            def run_trail(init_sl_pct, act_pct, trail_pct):
                sl = round(en * (1.0 + init_sl_pct/100.0), 2)
                trough = en
                trail_active = False
                for p in p_f1:
                    if p < trough:
                        trough = p
                    if not trail_active and trough <= en * (1.0 - act_pct/100.0):
                        trail_active = True
                    if trail_active:
                        new_sl = round(trough * (1.0 + trail_pct/100.0), 2)
                        if new_sl < sl:
                            sl = new_sl
                    if p >= sl:
                        return sl, True
                return final_p, False
                
            # 3. Fixed SL with Midday 11:30 cut if loss >= cut_pct
            def run_fixed_with_midday_cut(init_sl_pct, cut_pct):
                sl = round(en * (1.0 + init_sl_pct/100.0), 2)
                p_1130 = en
                for t, p in zip(t_f1, p_f1):
                    if t <= f"{d} 11:30:59":
                        p_1130 = p
                        if p >= sl:
                            return sl, True
                # At 11:30 check
                loss_1130 = ((p_1130 - en) / en) * 100.0
                if loss_1130 >= cut_pct:
                    return p_1130, True # Cut at 11:30
                # After 11:30
                for t, p in zip(t_f1, p_f1):
                    if t > f"{d} 11:30:59":
                        if p >= sl:
                            return sl, True
                return final_p, False

            ex_base, hit_base = run_fixed(3.0)
            ex_f35, hit_f35 = run_fixed(3.5)
            ex_f40, hit_f40 = run_fixed(4.0)
            ex_tr30_20, hit_tr30_20 = run_trail(3.0, 2.0, 2.0)
            ex_tr35_20, hit_tr35_20 = run_trail(3.5, 2.0, 2.0)
            ex_tr35_15, hit_tr35_15 = run_trail(3.5, 1.5, 1.5)
            ex_cut22_f35, hit_cut22_f35 = run_fixed_with_midday_cut(3.5, 2.2)
            ex_cut25_f35, hit_cut25_f35 = run_fixed_with_midday_cut(3.5, 2.5)
            
            res.update({
                'f1_en': en,
                'f1_ex_base': ex_base,
                'f1_ex_f35': ex_f35,
                'f1_ex_f40': ex_f40,
                'f1_ex_tr30_20': ex_tr30_20,
                'f1_ex_tr35_20': ex_tr35_20,
                'f1_ex_tr35_15': ex_tr35_15,
                'f1_ex_cut22_f35': ex_cut22_f35,
                'f1_ex_cut25_f35': ex_cut25_f35,
            })
            
    # Process Equity Cash
    if ticks_eq and len(ticks_eq) >= 10:
        highs = [float(t.get('high') or t['price'] or 0) for t in ticks_eq]
        lows = [float(t.get('low') or t['price'] or 999999) for t in ticks_eq]
        closes = [float(t.get('close') or t['price']) for t in ticks_eq]
        times_eq = [str(t['time']) for t in ticks_eq]
        en_eq = float(ticks_eq[0].get('price') or ticks_eq[0].get('close') or ticks_eq[0].get('open'))
        final_eq = closes[-1]
        n_eq = len(ticks_eq)
        
        def run_fixed_eq(pct):
            sl = round(en_eq * (1.0 + pct/100.0), 2)
            for i in range(n_eq):
                if highs[i] >= sl:
                    return sl, True
            return final_eq, False
            
        def run_trail_eq(init_sl_pct, act_pct, trail_pct):
            sl = round(en_eq * (1.0 + init_sl_pct/100.0), 2)
            trough = en_eq
            trail_active = False
            for i in range(n_eq):
                if lows[i] < trough:
                    trough = lows[i]
                if not trail_active and trough <= en_eq * (1.0 - act_pct/100.0):
                    trail_active = True
                if trail_active:
                    new_sl = round(trough * (1.0 + trail_pct/100.0), 2)
                    if new_sl < sl:
                        sl = new_sl
                if highs[i] >= sl:
                    return sl, True
            return final_eq, False
            
        def run_fixed_with_midday_cut_eq(init_sl_pct, cut_pct):
            sl = round(en_eq * (1.0 + init_sl_pct/100.0), 2)
            p_1130 = en_eq
            for i in range(n_eq):
                if times_eq[i] <= f"{d} 11:30:59":
                    p_1130 = closes[i]
                    if highs[i] >= sl:
                        return sl, True
            loss_1130 = ((p_1130 - en_eq) / en_eq) * 100.0
            if loss_1130 >= cut_pct:
                return p_1130, True
            for i in range(n_eq):
                if times_eq[i] > f"{d} 11:30:59":
                    if highs[i] >= sl:
                        return sl, True
            return final_eq, False

        eq_base, _ = run_fixed_eq(3.0)
        eq_f35, _ = run_fixed_eq(3.5)
        eq_f40, _ = run_fixed_eq(4.0)
        eq_tr30_20, _ = run_trail_eq(3.0, 2.0, 2.0)
        eq_tr35_20, _ = run_trail_eq(3.5, 2.0, 2.0)
        eq_tr35_15, _ = run_trail_eq(3.5, 1.5, 1.5)
        eq_cut22_f35, _ = run_fixed_with_midday_cut_eq(3.5, 2.2)
        eq_cut25_f35, _ = run_fixed_with_midday_cut_eq(3.5, 2.5)
        
        res.update({
            'eq_en': en_eq,
            'eq_ex_base': eq_base,
            'eq_ex_f35': eq_f35,
            'eq_ex_f40': eq_f40,
            'eq_ex_tr30_20': eq_tr30_20,
            'eq_ex_tr35_20': eq_tr35_20,
            'eq_ex_tr35_15': eq_tr35_15,
            'eq_ex_cut22_f35': eq_cut22_f35,
            'eq_ex_cut25_f35': eq_cut25_f35,
        })
        
    return res

def main():
    df = pd.read_csv(M2_FILE)
    df = df[df['status'] == 'COMPLETED'].copy()
    trades = df.to_dict('records')
    print(f"Simulating SL combos on {len(trades):,} trades...")
    with ThreadPoolExecutor(max_workers=24) as ex:
        results = [r for r in ex.map(sim_sl_combos, trades) if r is not None]
    rdf = pd.DataFrame(results)
    
    # Analyze Futures F1 (Flat Rs 600)
    f1_df = rdf[rdf['f1_en'].notna()].copy()
    f1_rules = [
        ('1. Baseline Fixed 3.0% SL', 'f1_ex_base'),
        ('2. Fixed 3.5% SL', 'f1_ex_f35'),
        ('3. Fixed 4.0% SL', 'f1_ex_f40'),
        ('4. 3.0% Initial SL + Trailing 2.0% from Low', 'f1_ex_tr30_20'),
        ('5. 3.5% Initial SL + Trailing 2.0% from Low', 'f1_ex_tr35_20'),
        ('6. 3.5% Initial SL + Trailing 1.5% from Low', 'f1_ex_tr35_15'),
        ('7. 3.5% SL + Severe Midday Cut @ 2.2%', 'f1_ex_cut22_f35'),
        ('8. 3.5% SL + Severe Midday Cut @ 2.5%', 'f1_ex_cut25_f35'),
    ]
    
    print("\n" + "=" * 115)
    print("🏆 FUTURES F1 (Flat Rs 600) STOP LOSS & LOSS CONTROL BENCHMARK (2020-2026)")
    print("=" * 115)
    print(f"{'Mechanism':<45} | {'Gross Profit':<14} | {'Net PnL (Flat 600)':<20} | {'Win Rate %':<10} | {'Max DD (L)':<10}")
    print("-" * 115)
    
    for name, col in f1_rules:
        gross = (f1_df['f1_en'] - f1_df[col]) * f1_df['qty']
        chg = 600.0 * f1_df['lots']
        net = gross - chg
        
        # Max Drawdown
        day_net = f1_df.groupby('date').apply(lambda g: ((g['f1_en'] - g[col]) * g['qty'] - 600.0 * g['lots']).sum())
        cum = day_net.cumsum()
        peak = cum.cummax()
        dd = (peak - cum).max() / 1e5
        
        wr = (net > 0).mean() * 100
        print(f"{name:<45} | Rs {gross.sum()/1e5:>8.2f} L | Rs {net.sum()/1e5:>8.2f} L (+Rs {net.sum()/1e7:.3f} Cr) | {wr:>8.2f}% | Rs {dd:>6.2f} L")
    print("=" * 115)
    
    # Analyze Equity Cash (Kotak MIS)
    eq_df = rdf[rdf['eq_en'].notna()].copy()
    eq_rules = [
        ('1. Baseline Fixed 3.0% SL', 'eq_ex_base'),
        ('2. Fixed 3.5% SL', 'eq_ex_f35'),
        ('3. Fixed 4.0% SL', 'eq_ex_f40'),
        ('4. 3.0% Initial SL + Trailing 2.0% from Low', 'eq_ex_tr30_20'),
        ('5. 3.5% Initial SL + Trailing 2.0% from Low', 'eq_ex_tr35_20'),
        ('6. 3.5% Initial SL + Trailing 1.5% from Low', 'eq_ex_tr35_15'),
        ('7. 3.5% SL + Severe Midday Cut @ 2.2%', 'eq_ex_cut22_f35'),
        ('8. 3.5% SL + Severe Midday Cut @ 2.5%', 'eq_ex_cut25_f35'),
    ]
    
    print("\n" + "=" * 115)
    print("🏆 EQUITY CASH (Kotak MIS Charges) STOP LOSS & LOSS CONTROL BENCHMARK (2020-2026)")
    print("=" * 115)
    print(f"{'Mechanism':<45} | {'Gross Profit':<14} | {'Net Kotak MIS':<20} | {'Win Rate %':<10} | {'Max DD (L)':<10}")
    print("-" * 115)
    
    for name, col in eq_rules:
        gross = (eq_df['eq_en'] - eq_df[col]) * eq_df['qty']
        chgs = [calculate_kotak_charges(float(en), float(ex), int(q))['total_charges']
                for en, ex, q in zip(eq_df['eq_en'], eq_df[col], eq_df['qty'])]
        net = gross - pd.Series(chgs, index=eq_df.index)
        
        # Max DD
        eq_df['temp_net'] = net
        day_net = eq_df.groupby('date')['temp_net'].sum()
        cum = day_net.cumsum()
        peak = cum.cummax()
        dd = (peak - cum).max() / 1e5
        
        wr = (net > 0).mean() * 100
        print(f"{name:<45} | Rs {gross.sum()/1e5:>8.2f} L | Rs {net.sum()/1e5:>8.2f} L (+Rs {net.sum()/1e7:.3f} Cr) | {wr:>8.2f}% | Rs {dd:>6.2f} L")
    print("=" * 115)

if __name__ == '__main__':
    main()
