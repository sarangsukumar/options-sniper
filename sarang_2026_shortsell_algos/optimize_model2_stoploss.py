#!/usr/bin/env python3
"""
optimize_model2_stoploss.py
============================
Systematic Stop Loss Optimization for Model 2 (09:42 -> 14:45).
Evaluates 10 distinct Stop Loss mechanisms on MySQL `scrapdata` (Equity Cash)
and `scrapdata_F1` (Futures) across all 4,424 completed trades (2020-2026).

Candidate Mechanisms Tested:
1. Fixed SL 2.0%
2. Fixed SL 2.5%
3. Fixed SL 3.0% (Current Production Baseline)
4. Fixed SL 3.5%
5. Fixed SL 4.0%
6. Fixed SL 5.0%
7. No Stop Loss (100% Time Exit at 14:45)
8. Breakeven Guard @ +1.5% (Initial 3% SL -> Move to Entry once +1.5% profit)
9. Breakeven Guard @ +2.0% (Initial 3% SL -> Move to Entry once +2.0% profit)
10. Dynamic Trailing 2.0% (Initial 3% SL -> Trail 2% from trough once +2.0% profit)
11. Mid-Day Time Tightening (3% SL until 11:30 -> Tighten to 2% after 11:30)
"""

import os, sys, time, pymysql
import pandas as pd
import numpy as np
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, '/home/ubuntu/sarang_2026_shortsell_algos')
from kotak_mis_calculator import calculate_kotak_charges

BASE_DIR = '/home/ubuntu/sarang_2026_shortsell_algos'
M2_FILE = os.path.join(BASE_DIR, '02_Best_Longer_Window_0942_1445', 'audited_0940_hybrid_trades.csv')
OUT_SUMMARY = os.path.join(BASE_DIR, 'model2_sl_optimization_matrix.csv')

def get_db_connection():
    return pymysql.connect(host='localhost', user='root', password='root', database='markets', autocommit=True)

def evaluate_rules_on_ticks(ticks, is_equity=True):
    if not ticks:
        return None
    
    # Extract series
    t_times = [t['time'] for t in ticks]
    t_highs = [float(t.get('high') or t['price'] or 0) for t in ticks]
    t_lows  = [float(t.get('low') or t['price'] or 999999) for t in ticks]
    t_closes = [float(t.get('close') or t['price']) for t in ticks]
    
    en = float(ticks[0].get('price') or ticks[0].get('close') or ticks[0].get('open'))
    final_p = float(t_closes[-1])
    n_ticks = len(ticks)
    
    results = {}
    
    # --- 1. Fixed SL Sweep: 2.0, 2.5, 3.0, 3.5, 4.0, 5.0, None ---
    fixed_pcts = [2.0, 2.5, 3.0, 3.5, 4.0, 5.0]
    for pct in fixed_pcts:
        sl_val = round(en * (1.0 + pct / 100.0), 2)
        ex = final_p
        hit = False
        for i in range(n_ticks):
            if t_highs[i] >= sl_val:
                ex = sl_val
                hit = True
                break
        results[f'fixed_{pct}'] = {'exit': ex, 'hit': hit}
        
    # No SL (pure EOD exit)
    results['no_sl'] = {'exit': final_p, 'hit': False}
    
    # --- 2. Breakeven Guard @ +1.5% ---
    sl_val = round(en * 1.03, 2)
    be_active = False
    ex_be15 = final_p
    hit_be15 = False
    for i in range(n_ticks):
        if not be_active and t_lows[i] <= en * 0.985: # +1.5% profit
            be_active = True
            sl_val = en # Move to entry
        if t_highs[i] >= sl_val:
            ex_be15 = sl_val
            hit_be15 = True
            break
    results['be_1.5pct'] = {'exit': ex_be15, 'hit': hit_be15}
    
    # --- 3. Breakeven Guard @ +2.0% ---
    sl_val = round(en * 1.03, 2)
    be_active = False
    ex_be20 = final_p
    hit_be20 = False
    for i in range(n_ticks):
        if not be_active and t_lows[i] <= en * 0.980: # +2.0% profit
            be_active = True
            sl_val = en
        if t_highs[i] >= sl_val:
            ex_be20 = sl_val
            hit_be20 = True
            break
    results['be_2.0pct'] = {'exit': ex_be20, 'hit': hit_be20}
    
    # --- 4. Dynamic Trailing 2.0% once +2.0% profit ---
    sl_val = round(en * 1.03, 2)
    trough = en
    trail_active = False
    ex_trail = final_p
    hit_trail = False
    for i in range(n_ticks):
        if t_lows[i] < trough:
            trough = t_lows[i]
        if not trail_active and trough <= en * 0.980:
            trail_active = True
        if trail_active:
            new_sl = round(trough * 1.020, 2)
            if new_sl < sl_val:
                sl_val = new_sl
        if t_highs[i] >= sl_val:
            ex_trail = sl_val
            hit_trail = True
            break
    results['trail_2.0pct'] = {'exit': ex_trail, 'hit': hit_trail}
    
    # --- 5. Mid-Day Tighten @ 11:30 AM (3% before 11:30 -> 2% after 11:30) ---
    sl_val = round(en * 1.03, 2)
    ex_tight = final_p
    hit_tight = False
    for i in range(n_ticks):
        tm = str(t_times[i])
        if ' 11:30:' in tm or tm >= f"{tm[:10]} 11:30:00":
            sl_val = min(sl_val, round(en * 1.02, 2))
        if t_highs[i] >= sl_val:
            ex_tight = sl_val
            hit_tight = True
            break
    results['time_tighten_1130'] = {'exit': ex_tight, 'hit': hit_tight}
    
    return {'entry': en, 'rules': results}

def process_trade(trade):
    d = trade['date']
    s = trade['stockname']
    qty = int(trade['total_quantity'])
    mult = int(trade['lots_to_trade'])
    yr = int(d[:4])
    
    conn = get_db_connection()
    cur = conn.cursor(pymysql.cursors.DictCursor)
    
    q_eq = f"""
    SELECT time, price, high, low, close 
    FROM scrapdata 
    WHERE date = '{d}' AND stockname IN ('{s}', '\"{s}\"', '{s} ') 
      AND time >= '{d} 09:42:00' AND time <= '{d} 14:45:59' 
    ORDER BY time ASC
    """
    cur.execute(q_eq)
    ticks_eq = cur.fetchall()
    conn.close()
    
    out = {'date': d, 'stockname': s, 'year': yr, 'qty': qty, 'lots': mult}
    eq_eval = evaluate_rules_on_ticks(ticks_eq, is_equity=True)
    if eq_eval:
        out['entry'] = eq_eval['entry']
        for r_name, r_data in eq_eval['rules'].items():
            out[f'{r_name}_exit'] = r_data['exit']
            out[f'{r_name}_hit'] = r_data['hit']
            out[f'{r_name}_gross'] = (eq_eval['entry'] - r_data['exit']) * qty
    else:
        out['entry'] = None
        
    return out

def main():
    print("=" * 95)
    print("🔬 COMPREHENSIVE STOP LOSS OPTIMIZATION MATRIX (MODEL 2: 09:42 -> 14:45)")
    print("=" * 95)
    
    df = pd.read_csv(M2_FILE)
    df = df[df['status'] == 'COMPLETED'].copy()
    print(f"Loaded {len(df):,} completed trades.")
    
    trades = df.to_dict('records')
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=24) as executor:
        res = list(executor.map(process_trade, trades))
    t1 = time.time()
    print(f"✔ Completed simulation in {t1-t0:.2f} seconds.")
    
    res_df = pd.DataFrame(res)
    valid = res_df[res_df['entry'].notna()].copy()
    print(f"Valid trade simulations: {len(valid):,} / {len(res_df):,}")
    
    rules = [
        ('fixed_2.0', '1. Fixed 2.0% SL'),
        ('fixed_2.5', '2. Fixed 2.5% SL'),
        ('fixed_3.0', '3. Fixed 3.0% SL (Baseline)'),
        ('fixed_3.5', '4. Fixed 3.5% SL'),
        ('fixed_4.0', '5. Fixed 4.0% SL'),
        ('fixed_5.0', '6. Fixed 5.0% SL'),
        ('no_sl',     '7. No Stop Loss (Pure EOD Exit)'),
        ('be_1.5pct', '8. Breakeven Guard @ +1.5% Profit'),
        ('be_2.0pct', '9. Breakeven Guard @ +2.0% Profit'),
        ('trail_2.0pct', '10. Dynamic Trailing 2.0% from Low'),
        ('time_tighten_1130', '11. Time Tighten 3% -> 2% @ 11:30 AM')
    ]
    
    matrix = []
    for r_key, r_label in rules:
        gross = valid[f'{r_key}_gross'].sum()
        hit_cnt = valid[f'{r_key}_hit'].sum()
        hit_pct = valid[f'{r_key}_hit'].mean() * 100
        
        # Charges: Kotak MIS
        kotak_charges = [calculate_kotak_charges(float(en), float(ex), int(q))['total_charges']
                         for en, ex, q in zip(valid['entry'], valid[f'{r_key}_exit'], valid['qty'])]
        net_kotak = valid[f'{r_key}_gross'] - pd.Series(kotak_charges)
        
        # Charges: Flat 600 per lot
        flat_charges = 600.0 * valid['lots']
        net_flat = valid[f'{r_key}_gross'] - flat_charges
        
        wr_kotak = (net_kotak > 0).mean() * 100
        
        # Max Drawdown
        cum = net_kotak.cumsum()
        max_dd = (cum - cum.cummax()).min()
        
        matrix.append({
            'Rule Key': r_key,
            'Mechanism': r_label,
            'SL Hit %': hit_pct,
            'Gross Profit (L)': round(gross / 1e5, 2),
            'Net Kotak MIS (L)': round(net_kotak.sum() / 1e5, 2),
            'Net Kotak (Cr)': round(net_kotak.sum() / 1e7, 3),
            'Net Flat 600 (L)': round(net_flat.sum() / 1e5, 2),
            'Win Rate %': round(wr_kotak, 2),
            'Max Drawdown (L)': round(abs(max_dd) / 1e5, 2)
        })
        
    m_df = pd.DataFrame(matrix)
    m_df.to_csv(OUT_SUMMARY, index=False)
    
    print("\n" + "=" * 100)
    print("🏆 STOP LOSS OPTIMIZATION LEADERBOARD (SORTED BY NET PROFIT)")
    print("=" * 100)
    m_sorted = m_df.sort_values(by='Net Kotak MIS (L)', ascending=False).reset_index(drop=True)
    print(f"{'Rank':<4} | {'Mechanism':<38} | {'SL Hit %':<9} | {'Net PnL (Kotak)':<16} | {'Net PnL (Flat 600)':<18} | {'Win Rate %':<10} | {'Max DD':<9}")
    print("-" * 100)
    for idx, r in m_sorted.iterrows():
        medal = "👑" if idx == 0 else ("🥈" if idx == 1 else ("🥉" if idx == 2 else "  "))
        print(f"{medal} {idx+1:<2} | {r['Mechanism']:<38} | {r['SL Hit %']:>7.1f}% | +Rs {r['Net Kotak MIS (L)']:>7.2f} L   | +Rs {r['Net Flat 600 (L)']:>7.2f} L    | {r['Win Rate %']:>8.2f}% | -Rs {r['Max Drawdown (L)']:>4.2f} L")
    print("=" * 100)

if __name__ == '__main__':
    main()
