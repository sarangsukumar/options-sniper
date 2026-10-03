#!/usr/bin/env python3
"""
mine_loss_patterns_post_entry.py
================================
Deep forensic analysis of LOSING TRADES post-entry (09:42 -> 14:45).
Training / Discovery Period: 2020 - 2025 (In-Sample)
Validation / Test Period:   2026 (Strict Out-of-Sample)

Investigates:
1. Minute-by-minute trajectory of losing trades vs winning trades.
2. Initial Loss Severity & Velocity (at +15m, +30m, +48m, +78m, +108m).
3. Post-Entry New High of Day (HOD) breaks.
4. Persistent Loss duration (trades that never went positive).
5. Testing early exit rules on 2020-2025 and blind validation on 2026.
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

def extract_trade_trajectory(trade):
    d = trade['date']
    s = trade['stockname']
    qty = int(trade['total_quantity'])
    lots = int(trade['lots_to_trade'])
    yr = int(d[:4])
    
    conn = get_db()
    cur = conn.cursor(pymysql.cursors.DictCursor)
    
    # 1. Fetch morning high from 09:15 to 09:42
    cur.execute(f"""
    SELECT MAX(high) as morn_high, MAX(price) as morn_max_p
    FROM scrapdata 
    WHERE date = '{d}' AND stockname IN ('{s}', '\"{s}\"', '{s} ')
      AND time >= '{d} 09:15:00' AND time < '{d} 09:42:00'
    """)
    m_row = cur.fetchone()
    pre_entry_high = float(m_row['morn_high'] or m_row['morn_max_p'] or 0)
    
    # 2. Fetch all ticks from 09:42 to 14:45
    cur.execute(f"""
    SELECT time, price, high, low, close 
    FROM scrapdata 
    WHERE date = '{d}' AND stockname IN ('{s}', '\"{s}\"', '{s} ') 
      AND time >= '{d} 09:42:00' AND time <= '{d} 14:45:59' 
    ORDER BY time ASC
    """)
    ticks_eq = cur.fetchall()
    conn.close()
    
    if not ticks_eq or len(ticks_eq) < 10:
        return None
        
    en = float(ticks_eq[0]['price'] or ticks_eq[0]['close'] or ticks_eq[0]['open'])
    final_p = float(ticks_eq[-1]['close'] or ticks_eq[-1]['price'])
    sl3 = round(en * 1.03, 2)
    
    # Baseline trade exit (with 3.0% SL)
    ex_base = final_p
    sl_hit = False
    sl_hit_time = None
    for t in ticks_eq:
        h = float(t['high'] or t['price'] or 0)
        if h >= sl3:
            ex_base = sl3
            sl_hit = True
            sl_hit_time = str(t['time'])
            break
            
    chg_base = calculate_kotak_charges(en, ex_base, qty)['total_charges']
    net_base = (en - ex_base) * qty - chg_base
    is_win = (net_base > 0)
    
    # Checkpoints post-entry
    checkpoints = [
        ('09:55', '13m'),
        ('10:00', '18m'),
        ('10:15', '33m'),
        ('10:30', '48m'),
        ('11:00', '78m'),
        ('11:30', '108m'),
    ]
    
    cp_data = {}
    for cp_time, cp_lbl in checkpoints:
        t_sub = [t for t in ticks_eq if str(t['time']) <= f"{d} {cp_time}:59"]
        if t_sub:
            cur_p = float(t_sub[-1]['close'] or t_sub[-1]['price'])
            cur_loss_pct = ((cur_p - en) / en) * 100.0  # Positive means in loss for short
            max_p = max([float(t['high'] or t['price'] or 0) for t in t_sub])
            max_loss_pct = ((max_p - en) / en) * 100.0
            time_in_loss = sum(1 for t in t_sub if float(t['close'] or t['price']) > en) / len(t_sub) * 100.0
            new_hod = (max_p > pre_entry_high) if pre_entry_high > 0 else False
        else:
            cur_p = en
            cur_loss_pct = 0.0
            max_loss_pct = 0.0
            time_in_loss = 0.0
            new_hod = False
            
        cp_data[f'loss_{cp_lbl}'] = cur_loss_pct
        cp_data[f'max_loss_{cp_lbl}'] = max_loss_pct
        cp_data[f'time_in_loss_{cp_lbl}'] = time_in_loss
        cp_data[f'new_hod_{cp_lbl}'] = new_hod
        cp_data[f'p_{cp_lbl}'] = cur_p
        
    res = {
        'date': d, 'stockname': s, 'year': yr, 'qty': qty, 'lots': lots,
        'en': en, 'ex_base': ex_base, 'net_base': net_base, 'is_win': is_win,
        'sl_hit': sl_hit, 'sl_hit_time': sl_hit_time, 'final_p': final_p,
        'pre_entry_high': pre_entry_high
    }
    res.update(cp_data)
    return res

def main():
    print("Loading Model 2 trade records...")
    df_m2 = pd.read_csv(M2_CSV)
    trades = df_m2.to_dict('records')
    print(f"Extracting trajectory for {len(trades):,} trades across 2020-2026...")
    
    with ThreadPoolExecutor(max_workers=24) as ex:
        results = [r for r in ex.map(extract_trade_trajectory, trades) if r is not None]
        
    df = pd.DataFrame(results)
    print(f"✔ Successfully extracted trajectories for {len(df):,} trades.")
    
    # Split: In-Sample (2020-2025) vs Out-of-Sample (2026)
    ins = df[df['year'] <= 2025].copy()
    oos = df[df['year'] == 2026].copy()
    
    print(f"\nDataset Split: IN-SAMPLE (2020-2025): {len(ins):,} trades | OUT-OF-SAMPLE (2026): {len(oos):,} trades")
    
    # -------------------------------------------------------------
    # PART 1: FORENSIC COMPARISON — WINNERS VS LOSERS IN-SAMPLE
    # -------------------------------------------------------------
    print("\n" + "=" * 115)
    print("🔬 PART 1: POST-ENTRY ANATOMY — WINNERS vs LOSERS (IN-SAMPLE: 2020-2025)")
    print("=" * 115)
    
    ins_win = ins[ins['is_win']]
    ins_loss = ins[~ins['is_win']]
    
    print(f"{'Checkpoint':<18} | {'Avg Loss % (Winners)':<22} | {'Avg Loss % (Losers)':<22} | {'% Losers in Loss':<20} | {'% Winners in Loss'}")
    print("-" * 115)
    
    cps = [('13m', '09:55 (+13 mins)'), ('18m', '10:00 (+18 mins)'), ('33m', '10:15 (+33 mins)'), 
           ('48m', '10:30 (+48 mins)'), ('78m', '11:00 (+78 mins)'), ('108m', '11:30 (+108 mins)')]
           
    for cp_key, cp_name in cps:
        w_l = ins_win[f'loss_{cp_key}'].mean()
        l_l = ins_loss[f'loss_{cp_key}'].mean()
        l_in_l = (ins_loss[f'loss_{cp_key}'] > 0).mean() * 100
        w_in_l = (ins_win[f'loss_{cp_key}'] > 0).mean() * 100
        print(f"{cp_name:<18} | {w_l:>+20.2f}% | {l_l:>+20.2f}% | {l_in_l:>18.1f}% | {w_in_l:>17.1f}%")
    print("=" * 115)
    
    # -------------------------------------------------------------
    # PART 2: TESTING CANDIDATE LOSS PATTERNS IN-SAMPLE (2020-2025)
    # -------------------------------------------------------------
    print("\n" + "=" * 115)
    print("🎯 PART 2: CANDIDATE EARLY-LOSS IDENTIFICATION RULES (IN-SAMPLE 2020-2025)")
    print("=" * 115)
    print(f"{'Candidate Loss Pattern':<55} | {'Trds Triggered':<16} | {'Final Loss %':<14} | {'Base Net PnL':<14} | {'Cut Net PnL':<14} | {'Saved (₹)'}")
    print("-" * 115)
    
    rules = [
        # 1. Rapid Adverse Move in first 18 mins (by 10:00)
        ("1. Rapid Adverse Move: Loss >= +1.0% by 10:00 AM", 
         ins['loss_18m'] >= 1.0, 'p_18m'),
        ("2. Rapid Adverse Move: Loss >= +1.5% by 10:00 AM", 
         ins['loss_18m'] >= 1.5, 'p_18m'),
         
        # 2. Breakout: Post-Entry New High of Day by 10:15 / 10:30
        ("3. New HOD Breakout by 10:15 AM (Broke morning high)", 
         ins['new_hod_33m'], 'p_33m'),
        ("4. New HOD Breakout by 10:30 AM (Broke morning high)", 
         ins['new_hod_48m'], 'p_48m'),
        ("5. New HOD Breakout AND Loss >= 1.0% by 10:30 AM", 
         ins['new_hod_48m'] & (ins['loss_48m'] >= 1.0), 'p_48m'),
         
        # 3. Persistent 100% time in loss
        ("6. 100% of first 33m in Loss (Never below entry)", 
         ins['time_in_loss_33m'] >= 99.0, 'p_33m'),
        ("7. 100% of first 48m in Loss (Never below entry)", 
         ins['time_in_loss_48m'] >= 99.0, 'p_48m'),
        ("8. 100% of first 48m in Loss AND Loss >= 1.0%", 
         (ins['time_in_loss_48m'] >= 99.0) & (ins['loss_48m'] >= 1.0), 'p_48m'),
        ("9. 100% of first 48m in Loss AND Loss >= 1.5%", 
         (ins['time_in_loss_48m'] >= 99.0) & (ins['loss_48m'] >= 1.5), 'p_48m'),

        # 4. Midday Loss Traps
        ("10. Loss >= 1.5% at 10:30 AM", 
         ins['loss_48m'] >= 1.5, 'p_48m'),
        ("11. Loss >= 2.0% at 10:30 AM", 
         ins['loss_48m'] >= 2.0, 'p_48m'),
        ("12. Loss >= 2.0% at 11:00 AM", 
         ins['loss_78m'] >= 2.0, 'p_78m'),
        ("13. Loss >= 2.2% at 11:30 AM (Proven severe cutoff)", 
         ins['loss_108m'] >= 2.2, 'p_108m'),
    ]
    
    for rname, mask, p_col in rules:
        sub = ins[mask]
        cnt = len(sub)
        if cnt == 0:
            continue
        final_loss_pct = (~sub['is_win']).mean() * 100
        b_net = sub['net_base'].sum() / 1e5
        
        # If we square off at this pattern's checkpoint
        cut_chgs = [calculate_kotak_charges(en, p_exit, q)['total_charges'] 
                    for en, p_exit, q in zip(sub['en'], sub[p_col], sub['qty'])]
        cut_net = ((sub['en'] - sub[p_col]) * sub['qty'] - pd.Series(cut_chgs, index=sub.index)).sum() / 1e5
        saved = cut_net - b_net
        
        print(f"{rname:<55} | {cnt:>5} ({cnt/len(ins)*100:>4.1f}%)   | {final_loss_pct:>10.1f}%  | Rs {b_net:>7.2f} L | Rs {cut_net:>7.2f} L | {saved:>+7.2f} L")
    print("=" * 115)
    
    # -------------------------------------------------------------
    # PART 3: STRICT OUT-OF-SAMPLE VALIDATION ON 2026
    # -------------------------------------------------------------
    print("\n" + "#" * 115)
    print("🛡️ PART 3: STRICT OUT-OF-SAMPLE VALIDATION ON 2026 (UNSEEN BLIND TEST)")
    print("#" * 115)
    print(f"{'Rule Tested on 2026 OOS':<55} | {'2026 Triggers':<15} | {'Final Loss %':<14} | {'Base Net (L)':<14} | {'Cut Net (L)':<14} | {'Saved (₹)'}")
    print("-" * 115)
    
    oos_rules = [
        ("1. Rapid Adverse Move: Loss >= +1.5% by 10:00 AM", 
         oos['loss_18m'] >= 1.5, 'p_18m'),
        ("2. New HOD Breakout AND Loss >= 1.0% by 10:30 AM", 
         oos['new_hod_48m'] & (oos['loss_48m'] >= 1.0), 'p_48m'),
        ("3. 100% of first 48m in Loss AND Loss >= 1.5%", 
         (oos['time_in_loss_48m'] >= 99.0) & (oos['loss_48m'] >= 1.5), 'p_48m'),
        ("4. Loss >= 2.0% at 10:30 AM", 
         oos['loss_48m'] >= 2.0, 'p_48m'),
        ("5. Loss >= 2.0% at 11:00 AM", 
         oos['loss_78m'] >= 2.0, 'p_78m'),
        ("6. Loss >= 2.2% at 11:30 AM (Proven severe cutoff)", 
         oos['loss_108m'] >= 2.2, 'p_108m'),
    ]
    
    for rname, mask, p_col in oos_rules:
        sub = oos[mask]
        cnt = len(sub)
        if cnt == 0:
            print(f"{rname:<55} |      0 ( 0.0%)   |        N/A   | Rs    0.00 L | Rs    0.00 L |   +0.00 L")
            continue
        final_loss_pct = (~sub['is_win']).mean() * 100
        b_net = sub['net_base'].sum() / 1e5
        cut_chgs = [calculate_kotak_charges(en, p_exit, q)['total_charges'] 
                    for en, p_exit, q in zip(sub['en'], sub[p_col], sub['qty'])]
        cut_net = ((sub['en'] - sub[p_col]) * sub['qty'] - pd.Series(cut_chgs, index=sub.index)).sum() / 1e5
        saved = cut_net - b_net
        print(f"{rname:<55} | {cnt:>5} ({cnt/len(oos)*100:>4.1f}%)   | {final_loss_pct:>10.1f}%  | Rs {b_net:>7.2f} L | Rs {cut_net:>7.2f} L | {saved:>+7.2f} L")
    print("=" * 115)

if __name__ == '__main__':
    main()
