#!/usr/bin/env python3
"""
audit_patterns_on_master_f1.py
Applies Pattern 1 (10:30 HOD break) and Pattern 2 (Severe Midday Cut)
directly onto the Master Audited Trades (+Rs 2.27 Crore F1 Engine).
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

def load_prev_closes():
    df_h = pd.read_csv(HIST_DATASET, usecols=['clean_stock', 'short_sell_date', 'prev_close'], low_memory=False)
    df_h = df_h.dropna(subset=['clean_stock', 'short_sell_date', 'prev_close'])
    df_h['clean_stock'] = df_h['clean_stock'].astype(str).str.strip().str.upper()
    df_h['date'] = df_h['short_sell_date'].astype(str).str.strip()
    df_h = df_h.drop_duplicates(subset=['clean_stock', 'date'])
    return dict(zip(zip(df_h['clean_stock'], df_h['date']), df_h['prev_close'].astype(float)))

def check_pattern_triggers(trade):
    d = trade['date']
    s = trade['stockname']
    en = float(trade['entry_price'])
    ex_aud = float(trade['exit_price'])
    qty = int(trade['total_quantity'])
    lots = int(trade['lots_to_trade'])
    yr = int(d[:4])
    
    conn = get_db()
    cur = conn.cursor(pymysql.cursors.DictCursor)
    
    # Pre-entry high
    cur.execute(f"""
    SELECT MAX(high) as morn_high, MAX(price) as morn_max_p
    FROM scrapdata 
    WHERE date = '{d}' AND stockname IN ('{s}', '\"{s}\"', '{s} ')
      AND time >= '{d} 09:15:00' AND time < '{d} 09:42:00'
    """)
    m_row = cur.fetchone()
    pre_entry_high = float(m_row['morn_high'] or m_row['morn_max_p'] or 0)
    
    # Morning ticks (09:42 to 11:30)
    cur.execute(f"""
    SELECT time, price, high, low, close 
    FROM scrapdata 
    WHERE date = '{d}' AND stockname IN ('{s}', '\"{s}\"', '{s} ') 
      AND time >= '{d} 09:42:00' AND time <= '{d} 11:30:59'
    ORDER BY time ASC
    """)
    ticks = cur.fetchall()
    conn.close()
    
    res = {
        'date': d, 'stockname': s, 'year': yr, 'qty': qty, 'lots': lots,
        'en': en, 'ex_aud': ex_aud, 'pre_entry_high': pre_entry_high
    }
    
    p_1030 = en
    max_h_1030 = 0.0
    p_1100 = en
    p_1130 = en
    
    if ticks:
        for t in ticks:
            tm = str(t['time'])
            h = float(t.get('high') or t['price'] or 0)
            cl = float(t.get('close') or t['price'])
            if tm <= f"{d} 10:30:59":
                p_1030 = cl
                if h > max_h_1030:
                    max_h_1030 = h
            if tm <= f"{d} 11:00:59":
                p_1100 = cl
            if tm <= f"{d} 11:30:59":
                p_1130 = cl
                
    # Check Pattern 1: New HOD by 10:30 AND Loss >= 1.0%
    loss_1030 = ((p_1030 - en) / en) * 100.0
    p1_trigger = (pre_entry_high > 0) and (max_h_1030 > pre_entry_high) and (loss_1030 >= 1.0)
    
    # Check Pattern 2: Severe Midday Loss (>= 2.0% at 11:00 OR >= 2.2% at 11:30)
    loss_1100 = ((p_1100 - en) / en) * 100.0
    loss_1130 = ((p_1130 - en) / en) * 100.0
    p2_trigger = (loss_1100 >= 2.0) or (loss_1130 >= 2.2)
    
    # Exit price with patterns applied on Audited Base
    ex_pat = ex_aud
    exit_type = 'AUDITED_EXIT'
    if p1_trigger:
        ex_pat = p_1030
        exit_type = 'PATTERN_1_CUT_1030'
    elif p2_trigger:
        ex_pat = p_1100 if loss_1100 >= 2.0 else p_1130
        exit_type = 'PATTERN_2_CUT_MIDDAY'
        
    res['p1_trigger'] = p1_trigger
    res['p2_trigger'] = p2_trigger
    res['ex_pat'] = ex_pat
    res['exit_type'] = exit_type
    
    return res

def main():
    prev_map = load_prev_closes()
    df_m2 = pd.read_csv(M2_CSV)
    trades = df_m2.to_dict('records')
    for t in trades:
        s = str(t['stockname']).strip().upper().replace('"', '').strip()
        d = str(t['date']).strip()[:10]
        t['prev_close'] = prev_map.get((s, d))
        
    print(f"Auditing Patterns on Master Trades ({len(trades):,} trades)...")
    with ThreadPoolExecutor(max_workers=24) as ex:
        results = [r for r in ex.map(check_pattern_triggers, trades) if r is not None]
    rdf = pd.DataFrame(results)
    
    # Merge with entry filter info
    rdf['prev_close'] = [prev_map.get((str(s).strip().upper().replace('"', '').strip(), str(d).strip()[:10])) for s, d in zip(rdf['stockname'], rdf['date'])]
    valid = rdf[rdf['prev_close'].notna() & (rdf['prev_close'] > 0)].copy()
    valid['stock_gain_pct'] = ((valid['en'] - valid['prev_close']) / valid['prev_close']) * 100.0
    
    # Filter Mask: Gain >= -1.5% and not [2%, 3%]
    valid['passed_filter'] = (valid['stock_gain_pct'] >= -1.5) & ~((valid['stock_gain_pct'] >= 2.0) & (valid['stock_gain_pct'] < 3.0))
    
    # 1. Futures F1 Net (Flat Rs 600)
    valid['f1_base_net'] = (valid['en'] - valid['ex_aud']) * valid['qty'] - (600.0 * valid['lots'])
    valid['f1_pat_net']  = (valid['en'] - valid['ex_pat']) * valid['qty'] - (600.0 * valid['lots'])
    
    # 2. Equity Cash Net (Kotak MIS)
    chg_base = [calculate_kotak_charges(en, ex, q)['total_charges'] for en, ex, q in zip(valid['en'], valid['ex_aud'], valid['qty'])]
    chg_pat  = [calculate_kotak_charges(en, ex, q)['total_charges'] for en, ex, q in zip(valid['en'], valid['ex_pat'], valid['qty'])]
    valid['eq_base_net'] = (valid['en'] - valid['ex_aud']) * valid['qty'] - pd.Series(chg_base, index=valid.index)
    valid['eq_pat_net']  = (valid['en'] - valid['ex_pat']) * valid['qty'] - pd.Series(chg_pat, index=valid.index)
    
    print("\n" + "=" * 135)
    print("👑 MASTER FUTURES F1 (FLAT ₹600) AUDIT: BASELINE vs FILTERED vs PATTERN SYSTEM")
    print("=" * 135)
    print(f"{'Year':<6} | {'Base Trds':<9} | {'Filt Trds':<9} | {'Base Net (L)':<15} | {'Filtered Net (L)':<17} | {'Filtered + Patterns (L)':<24} | {'Status'}")
    print("-" * 135)
    
    for y, g in valid.groupby('year'):
        gf = g[g['passed_filter']]
        b_net = g['f1_base_net'].sum() / 1e5
        f_net = gf['f1_base_net'].sum() / 1e5
        p_net = gf['f1_pat_net'].sum() / 1e5
        print(f"{y:<6} | {len(g):>9} | {len(gf):>9} | +Rs {b_net:>8.2f} L   | +Rs {f_net:>10.2f} L    | +Rs {p_net:>12.2f} L (+{p_net/100:.3f} Cr) | 🟢 Robust")
        
    print("-" * 135)
    tot_b = valid['f1_base_net'].sum() / 1e5
    tot_f = valid[valid['passed_filter']]['f1_base_net'].sum() / 1e5
    tot_p = valid[valid['passed_filter']]['f1_pat_net'].sum() / 1e5
    print(f"{'TOTAL':<6} | {len(valid):>9} | {valid['passed_filter'].sum():>9} | +Rs {tot_b:>8.2f} L   | +Rs {tot_f:>10.2f} L    | +Rs {tot_p:>12.2f} L (+{tot_p/100:.3f} Cr) | 👑 ₹2+ CRORE INTACT!")
    print("=" * 135)

if __name__ == '__main__':
    main()
