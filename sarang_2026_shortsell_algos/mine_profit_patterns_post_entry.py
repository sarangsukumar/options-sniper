#!/usr/bin/env python3
"""
mine_profit_patterns_post_entry.py
==================================
Deep forensic analysis of WINNING TRADES post-entry (09:42 -> 14:45).
Training / Discovery Period: 2020 - 2025 (In-Sample)
Validation / Test Period:   2026 (Strict Out-of-Sample)

Investigates:
1. Velocity & Early MFE (Maximum Favorable Excursion) of winning trades.
2. New Low of Day (LOD) Breakouts post-entry.
3. Monotonic Lower Low downtrends.
4. Morning (09:42-11:30) vs Afternoon (11:30-14:45) profit capture.
5. Evaluating Profit-Taking / Scaling / Runner rules on 2020-2025 and blind testing on 2026.
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

def extract_profit_trajectory(trade):
    d = trade['date']
    s = trade['stockname']
    qty = int(trade['total_quantity'])
    lots = int(trade['lots_to_trade'])
    yr = int(d[:4])
    
    conn = get_db()
    cur = conn.cursor(pymysql.cursors.DictCursor)
    
    # 1. Fetch morning low from 09:15 to 09:42
    cur.execute(f"""
    SELECT MIN(low) as morn_low, MIN(price) as morn_min_p, MAX(high) as morn_high
    FROM scrapdata 
    WHERE date = '{d}' AND stockname IN ('{s}', '\"{s}\"', '{s} ')
      AND time >= '{d} 09:15:00' AND time < '{d} 09:42:00'
    """)
    m_row = cur.fetchone()
    pre_entry_low = float(m_row['morn_low'] or m_row['morn_min_p'] or 999999)
    
    # 2. Fetch all ticks from 09:42 to 14:45
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
    final_p = float(ticks[-1]['close'] or ticks[-1]['price'])
    sl35 = round(en * 1.035, 2)
    
    # Baseline trade exit (with 3.5% SL)
    ex_base = final_p
    sl_hit = False
    for t in ticks:
        h = float(t['high'] or t['price'] or 0)
        if h >= sl35:
            ex_base = sl35
            sl_hit = True
            break
            
    chg_base = calculate_kotak_charges(en, ex_base, qty)['total_charges']
    net_base = (en - ex_base) * qty - chg_base
    pct_return_base = ((en - ex_base) / en) * 100.0  # Positive is profit for short
    is_win = (net_base > 0)
    
    # Track Checkpoints
    checkpoints = [
        ('09:55', '13m'),
        ('10:00', '18m'),
        ('10:15', '33m'),
        ('10:30', '48m'),
        ('11:00', '78m'),
        ('11:30', '108m'),
        ('12:30', '168m'),
        ('13:30', '228m'),
    ]
    
    cp_data = {}
    for cp_time, cp_lbl in checkpoints:
        t_sub = [t for t in ticks if str(t['time']) <= f"{d} {cp_time}:59"]
        if t_sub:
            cur_p = float(t_sub[-1]['close'] or t_sub[-1]['price'])
            cur_gain_pct = ((en - cur_p) / en) * 100.0  # Positive is profit
            min_p = min([float(t['low'] or t['price'] or 999999) for t in t_sub])
            max_gain_pct = ((en - min_p) / en) * 100.0  # MFE up to this time
            new_lod = (min_p < pre_entry_low) if pre_entry_low < 999999 else False
        else:
            cur_p = en
            cur_gain_pct = 0.0
            max_gain_pct = 0.0
            new_lod = False
            
        cp_data[f'gain_{cp_lbl}'] = cur_gain_pct
        cp_data[f'mfe_{cp_lbl}'] = max_gain_pct
        cp_data[f'new_lod_{cp_lbl}'] = new_lod
        cp_data[f'p_{cp_lbl}'] = cur_p
        
    # Total Day MFE
    day_min_p = min([float(t['low'] or t['price'] or 999999) for t in ticks])
    day_mfe_pct = ((en - day_min_p) / en) * 100.0
    
    # Morning gain vs Afternoon gain
    p_1130 = cp_data['p_108m']
    morn_gain_pct = ((en - p_1130) / en) * 100.0
    aft_gain_pct = ((p_1130 - final_p) / en) * 100.0
    
    res = {
        'date': d, 'stockname': s, 'year': yr, 'qty': qty, 'lots': lots,
        'en': en, 'ex_base': ex_base, 'net_base': net_base, 'pct_return_base': pct_return_base,
        'is_win': is_win, 'day_mfe_pct': day_mfe_pct,
        'morn_gain_pct': morn_gain_pct, 'aft_gain_pct': aft_gain_pct,
        'pre_entry_low': pre_entry_low
    }
    res.update(cp_data)
    return res

def main():
    print("Loading Model 2 trade records...")
    df_m2 = pd.read_csv(M2_CSV)
    trades = df_m2.to_dict('records')
    print(f"Extracting profit trajectory for {len(trades):,} trades across 2020-2026...")
    
    with ThreadPoolExecutor(max_workers=24) as ex:
        results = [r for r in ex.map(extract_profit_trajectory, trades) if r is not None]
        
    df = pd.DataFrame(results)
    print(f"✔ Successfully extracted trajectories for {len(df):,} trades.")
    
    # Split In-Sample (2020-2025) vs Out-of-Sample (2026)
    ins = df[df['year'] <= 2025].copy()
    oos = df[df['year'] == 2026].copy()
    
    print(f"\nDataset Split: IN-SAMPLE (2020-2025): {len(ins):,} trades | OUT-OF-SAMPLE (2026): {len(oos):,} trades")
    
    # -------------------------------------------------------------
    # PART 1: THE ANATOMY OF WINNING TRADES (IN-SAMPLE 2020-2025)
    # -------------------------------------------------------------
    print("\n" + "=" * 115)
    print("🏆 PART 1: ANATOMY OF PROFITABLE TRADES (IN-SAMPLE: 2020-2025)")
    print("=" * 115)
    
    ins_wins = ins[ins['is_win']].copy()
    
    # Buckets of Final Win Size
    bins = [0.0, 1.0, 2.0, 3.0, 5.0, 999.0]
    labels = ['Small Win (+0% to +1%)', 'Medium Win (+1% to +2%)', 'Large Win (+2% to +3%)', 'Super Win (+3% to +5%)', 'Monster Win (> +5%)']
    ins_wins['win_bucket'] = pd.cut(ins_wins['pct_return_base'], bins=bins, labels=labels)
    
    print(f"{'Win Category':<25} | {'Count':<8} | {'Avg Final Return':<18} | {'MFE @ 10:00':<14} | {'MFE @ 10:30':<14} | {'MFE @ 11:30':<14} | {'Day MFE'}")
    print("-" * 115)
    
    for lbl in labels:
        sub = ins_wins[ins_wins['win_bucket'] == lbl]
        if len(sub) == 0: continue
        avg_ret = sub['pct_return_base'].mean()
        mfe_1000 = sub['mfe_18m'].mean()
        mfe_1030 = sub['mfe_48m'].mean()
        mfe_1130 = sub['mfe_108m'].mean()
        day_mfe = sub['day_mfe_pct'].mean()
        print(f"{lbl:<25} | {len(sub):>8} | {avg_ret:>+16.2f}% | {mfe_1000:>+12.2f}% | {mfe_1030:>+12.2f}% | {mfe_1130:>+12.2f}% | {day_mfe:>+8.2f}%")
    print("=" * 115)
    
    # -------------------------------------------------------------
    # PART 2: THE 3 PROFIT PATTERNS (IN-SAMPLE 2020-2025)
    # -------------------------------------------------------------
    print("\n" + "=" * 115)
    print("🔬 PART 2: TESTING CANDIDATE PROFIT-SIDE PATTERNS (IN-SAMPLE: 2020-2025)")
    print("=" * 115)
    print(f"{'Pattern Description':<55} | {'Trades':<8} | {'Win Rate %':<12} | {'Avg Return':<14} | {'Total Profit':<14} | {'Day MFE'}")
    print("-" * 115)
    
    patterns = [
        ("1. Early Velocity: Gain >= +1.0% by 10:00 AM", 
         ins['gain_18m'] >= 1.0),
        ("2. Early Velocity: Gain >= +1.5% by 10:00 AM", 
         ins['gain_18m'] >= 1.5),
        ("3. New LOD Breakout by 10:15 AM (Broke morning low)", 
         ins['new_lod_33m']),
        ("4. New LOD Breakout by 10:30 AM (Broke morning low)", 
         ins['new_lod_48m']),
        ("5. Fast Runner: New LOD AND Gain >= +1.0% by 10:30 AM", 
         ins['new_lod_48m'] & (ins['gain_48m'] >= 1.0)),
        ("6. Fast Runner: New LOD AND Gain >= +1.5% by 10:30 AM", 
         ins['new_lod_48m'] & (ins['gain_48m'] >= 1.5)),
        ("7. Sustained Downtrend: Gain_1030 > Gain_1015 > Gain_1000 > 0", 
         (ins['gain_48m'] > ins['gain_33m']) & (ins['gain_33m'] > ins['gain_18m']) & (ins['gain_18m'] > 0)),
        ("8. Big Midday Runner: Gain >= +2.0% by 11:30 AM", 
         ins['gain_108m'] >= 2.0),
        ("9. Super Midday Runner: Gain >= +3.0% by 11:30 AM", 
         ins['gain_108m'] >= 3.0),
        ("10. ALL TRADES BASELINE", 
         ins['en'] > 0),
    ]
    
    for pname, mask in patterns:
        sub = ins[mask]
        if len(sub) == 0: continue
        wr = (sub['is_win']).mean() * 100
        avg_ret = sub['pct_return_base'].mean()
        tot_prof = sub['net_base'].sum() / 1e5
        day_mfe = sub['day_mfe_pct'].mean()
        print(f"{pname:<55} | {len(sub):>8} | {wr:>10.2f}% | {avg_ret:>+12.2f}% | Rs {tot_prof:>8.2f} L | {day_mfe:>+8.2f}%")
    print("=" * 115)
    
    # -------------------------------------------------------------
    # PART 3: OUT-OF-SAMPLE VALIDATION ON 2026
    # -------------------------------------------------------------
    print("\n" + "#" * 115)
    print("🛡️ PART 3: STRICT OUT-OF-SAMPLE BLIND VALIDATION ON 2026")
    print("#" * 115)
    print(f"{'Pattern Tested on 2026 OOS':<55} | {'Trades':<8} | {'Win Rate %':<12} | {'Avg Return':<14} | {'Total Profit':<14} | {'Day MFE'}")
    print("-" * 115)
    
    for pname, mask_ins in patterns[:-1]: # exclude baseline
        # define same mask on oos
        if "1. Early Velocity: Gain >= +1.0% by 10:00 AM" in pname:
            mask = oos['gain_18m'] >= 1.0
        elif "2. Early Velocity: Gain >= +1.5% by 10:00 AM" in pname:
            mask = oos['gain_18m'] >= 1.5
        elif "3. New LOD Breakout by 10:15 AM" in pname:
            mask = oos['new_lod_33m']
        elif "4. New LOD Breakout by 10:30 AM" in pname:
            mask = oos['new_lod_48m']
        elif "5. Fast Runner: New LOD AND Gain >= +1.0%" in pname:
            mask = oos['new_lod_48m'] & (oos['gain_48m'] >= 1.0)
        elif "6. Fast Runner: New LOD AND Gain >= +1.5%" in pname:
            mask = oos['new_lod_48m'] & (oos['gain_48m'] >= 1.5)
        elif "7. Sustained Downtrend" in pname:
            mask = (oos['gain_48m'] > oos['gain_33m']) & (oos['gain_33m'] > oos['gain_18m']) & (oos['gain_18m'] > 0)
        elif "8. Big Midday Runner: Gain >= +2.0%" in pname:
            mask = oos['gain_108m'] >= 2.0
        elif "9. Super Midday Runner: Gain >= +3.0%" in pname:
            mask = oos['gain_108m'] >= 3.0
        else:
            continue
            
        sub = oos[mask]
        if len(sub) == 0:
            print(f"{pname:<55} |        0 |        N/A   |          N/A | Rs    0.00 L |      N/A")
            continue
        wr = (sub['is_win']).mean() * 100
        avg_ret = sub['pct_return_base'].mean()
        tot_prof = sub['net_base'].sum() / 1e5
        day_mfe = sub['day_mfe_pct'].mean()
        print(f"{pname:<55} | {len(sub):>8} | {wr:>10.2f}% | {avg_ret:>+12.2f}% | Rs {tot_prof:>8.2f} L | {day_mfe:>+8.2f}%")
        
    print("-" * 115)
    # OOS Baseline
    wr_oos = (oos['is_win']).mean() * 100
    ret_oos = oos['pct_return_base'].mean()
    prof_oos = oos['net_base'].sum() / 1e5
    mfe_oos = oos['day_mfe_pct'].mean()
    print(f"{'2026 OOS ALL TRADES BASELINE':<55} | {len(oos):>8} | {wr_oos:>10.2f}% | {ret_oos:>+12.2f}% | Rs {prof_oos:>8.2f} L | {mfe_oos:>+8.2f}%")
    print("=" * 115)
    
    # -------------------------------------------------------------
    # PART 4: MORNING VS AFTERNOON PROFIT EXPANSION
    # -------------------------------------------------------------
    print("\n" + "=" * 115)
    print("📈 PART 4: WHERE DO PROFITS COME FROM? MORNING (09:42-11:30) vs AFTERNOON (11:30-14:45)")
    print("=" * 115)
    
    # For winning trades in In-Sample
    m_win_g = ins_wins['morn_gain_pct'].mean()
    a_win_g = ins_wins['aft_gain_pct'].mean()
    tot_win_g = ins_wins['pct_return_base'].mean()
    print(f"In-Sample Winning Trades ({len(ins_wins):,} trades):")
    print(f"  • Average Gain generated in Morning   (09:42 to 11:30): +{m_win_g:.2f}% ({(m_win_g/tot_win_g)*100:.1f}% of total profit)")
    print(f"  • Average Gain expanded in Afternoon (11:30 to 14:45): +{a_win_g:.2f}% ({(a_win_g/tot_win_g)*100:.1f}% of total profit)")
    print(f"  • Total Final Return:                                  +{tot_win_g:.2f}%")
    
    # For 2026 OOS Winning Trades
    oos_wins = oos[oos['is_win']].copy()
    m_win_g_oos = oos_wins['morn_gain_pct'].mean()
    a_win_g_oos = oos_wins['aft_gain_pct'].mean()
    tot_win_g_oos = oos_wins['pct_return_base'].mean()
    print(f"\n2026 Out-of-Sample Winning Trades ({len(oos_wins):,} trades):")
    print(f"  • Average Gain generated in Morning   (09:42 to 11:30): +{m_win_g_oos:.2f}% ({(m_win_g_oos/tot_win_g_oos)*100:.1f}% of total profit)")
    print(f"  • Average Gain expanded in Afternoon (11:30 to 14:45): +{a_win_g_oos:.2f}% ({(a_win_g_oos/tot_win_g_oos)*100:.1f}% of total profit)")
    print(f"  • Total Final Return:                                  +{tot_win_g_oos:.2f}%")
    print("=" * 115)

if __name__ == '__main__':
    main()
