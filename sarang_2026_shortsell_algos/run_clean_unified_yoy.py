#!/usr/bin/env python3
"""
run_clean_unified_yoy.py
Clean Year-over-Year comparison using audited cleaned base ticks (with JUBLFOOD split fix).
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

def sim_trade(trade):
    d = trade['date']
    s = trade['stockname']
    qty = int(trade['total_quantity'])
    lots = int(trade['lots_to_trade'])
    yr = int(d[:4])
    prev_close = trade.get('prev_close')
    clean_en_eq = float(trade.get('eq_entry_price', 0) or 0)
    clean_en_f1 = float(trade.get('f1_entry_price', 0) or 0)
    
    conn = get_db()
    cur = conn.cursor(pymysql.cursors.DictCursor)
    
    # 1. Pre-entry high (09:15 to 09:41:59)
    # Exclude split corrupted ticks if 2020 JUBLFOOD
    price_cond = f"AND price BETWEEN {clean_en_eq * 0.75} AND {clean_en_eq * 1.25}" if clean_en_eq > 0 else ""
    cur.execute(f"""
    SELECT MAX(high) as morn_high, MAX(price) as morn_max_p
    FROM scrapdata 
    WHERE date = '{d}' AND stockname IN ('{s}', '\"{s}\"', '{s} ')
      AND time >= '{d} 09:15:00' AND time < '{d} 09:42:00' {price_cond}
    """)
    m_row = cur.fetchone()
    pre_entry_high = float(m_row['morn_high'] or m_row['morn_max_p'] or 0)
    
    # 2. Equity ticks from 09:42 to 14:45
    cur.execute(f"""
    SELECT time, price, high, low, close 
    FROM scrapdata 
    WHERE date = '{d}' AND stockname IN ('{s}', '\"{s}\"', '{s} ') 
      AND time >= '{d} 09:42:00' AND time <= '{d} 14:45:59' {price_cond}
    ORDER BY time ASC
    """)
    ticks_eq = cur.fetchall()
    
    # 3. Futures ticks from 09:42 to 14:45
    cur.execute(f"""
    SELECT time, price 
    FROM scrapdata_F1 
    WHERE date = '{d}' AND stockname IN ('{s}', '\"{s}\"', '{s} ') 
      AND time >= '{d} 09:42:00' AND time <= '{d} 14:45:59' 
    ORDER BY time ASC
    """)
    ticks_f1 = cur.fetchall()
    conn.close()
    
    res = {'date': d, 'stockname': s, 'year': yr, 'qty': qty, 'lots': lots, 'prev_close': prev_close}
    
    en_eq = clean_en_eq if clean_en_eq > 0 else (float(ticks_eq[0]['price'] or ticks_eq[0]['close']) if ticks_eq else None)
    res['eq_en'] = en_eq
    
    if en_eq and prev_close and prev_close > 0:
        gain_pct = ((en_eq - prev_close) / prev_close) * 100.0
        res['gain_pct'] = gain_pct
        passed_filter = (gain_pct >= -1.5) and not (2.0 <= gain_pct < 3.0)
    else:
        res['gain_pct'] = 0.0
        passed_filter = True
    res['passed_filter'] = passed_filter
    
    # --- SIMULATE EQUITY CASH ---
    if ticks_eq and len(ticks_eq) >= 10 and en_eq:
        final_eq = float(ticks_eq[-1]['close'] or ticks_eq[-1]['price'])
        n_ticks = len(ticks_eq)
        highs = [float(t.get('high') or t['price'] or 0) for t in ticks_eq]
        lows = [float(t.get('low') or t['price'] or 999999) for t in ticks_eq]
        closes = [float(t.get('close') or t['price']) for t in ticks_eq]
        times = [str(t['time']) for t in ticks_eq]
        
        # Baseline 3.0% SL
        sl3 = round(en_eq * 1.03, 2)
        ex_base = final_eq
        for i in range(n_ticks):
            if highs[i] >= sl3:
                ex_base = sl3
                break
        res['eq_ex_base'] = ex_base
        
        # System V1: Entry Filter + Pattern 1 + Pattern 2 + 3.5% SL
        sl35 = round(en_eq * 1.035, 2)
        ex_v1 = final_eq
        max_h_1030 = 0.0
        p_1030 = en_eq
        p_1100 = en_eq
        p_1130 = en_eq
        
        for i in range(n_ticks):
            tm = times[i]
            h = highs[i]
            cl = closes[i]
            
            if h >= sl35:
                ex_v1 = sl35
                break
            if tm <= f"{d} 10:30:59":
                p_1030 = cl
                if h > max_h_1030:
                    max_h_1030 = h
            if tm <= f"{d} 11:00:59":
                p_1100 = cl
            if tm <= f"{d} 11:30:59":
                p_1130 = cl
                
            if tm == f"{d} 10:30:00" or (i > 0 and times[i-1] < f"{d} 10:30:00" <= tm):
                loss_1030 = ((p_1030 - en_eq) / en_eq) * 100.0
                if (max_h_1030 > pre_entry_high) and (loss_1030 >= 1.0):
                    ex_v1 = p_1030
                    break
            if tm == f"{d} 11:00:00" or (i > 0 and times[i-1] < f"{d} 11:00:00" <= tm):
                loss_1100 = ((p_1100 - en_eq) / en_eq) * 100.0
                if loss_1100 >= 2.0:
                    ex_v1 = p_1100
                    break
            if tm == f"{d} 11:30:00" or (i > 0 and times[i-1] < f"{d} 11:30:00" <= tm):
                loss_1130 = ((p_1130 - en_eq) / en_eq) * 100.0
                if loss_1130 >= 2.2:
                    ex_v1 = p_1130
                    break
        res['eq_ex_v1'] = ex_v1
        
        # System V2: Entry Filter + Pattern 1 + Pattern 2 + Trailing 2.0% from Low
        ex_v2 = final_eq
        cur_sl = sl35
        trough = en_eq
        trail_active = False
        
        for i in range(n_ticks):
            tm = times[i]
            h = highs[i]
            l = lows[i]
            cl = closes[i]
            
            if l < trough:
                trough = l
            if not trail_active and trough <= en_eq * 0.980:
                trail_active = True
            if trail_active:
                new_sl = round(trough * 1.020, 2)
                if new_sl < cur_sl:
                    cur_sl = new_sl
            if h >= cur_sl:
                ex_v2 = cur_sl
                break
            if (tm == f"{d} 10:30:00" or (i > 0 and times[i-1] < f"{d} 10:30:00" <= tm)) and not trail_active:
                loss_1030 = ((cl - en_eq) / en_eq) * 100.0
                if (max_h_1030 > pre_entry_high) and (loss_1030 >= 1.0):
                    ex_v2 = cl
                    break
            if (tm == f"{d} 11:00:00" or (i > 0 and times[i-1] < f"{d} 11:00:00" <= tm)) and not trail_active:
                loss_1100 = ((cl - en_eq) / en_eq) * 100.0
                if loss_1100 >= 2.0:
                    ex_v2 = cl
                    break
            if (tm == f"{d} 11:30:00" or (i > 0 and times[i-1] < f"{d} 11:30:00" <= tm)) and not trail_active:
                loss_1130 = ((cl - en_eq) / en_eq) * 100.0
                if loss_1130 >= 2.2:
                    ex_v2 = cl
                    break
        res['eq_ex_v2'] = ex_v2
        
    # --- SIMULATE FUTURES F1 ---
    if ticks_f1 and len(ticks_f1) >= 10:
        p_f1 = [float(t['price']) for t in ticks_f1 if t['price'] is not None]
        t_f1 = [str(t['time']) for t in ticks_f1 if t['price'] is not None]
        if len(p_f1) >= 10:
            en_f1 = p_f1[0]
            final_f1 = p_f1[-1]
            res['f1_en'] = en_f1
            
            # Baseline 3.0% SL
            sl3_f1 = round(en_f1 * 1.03, 2)
            ex_f1_base = final_f1
            for p in p_f1:
                if p >= sl3_f1:
                    ex_f1_base = sl3_f1
                    break
            res['f1_ex_base'] = ex_f1_base
            
            # V1: 3.5% SL + Patterns
            sl35_f1 = round(en_f1 * 1.035, 2)
            ex_f1_v1 = final_f1
            max_h_1030_f1 = 0.0
            p_1030_f1 = en_f1
            p_1100_f1 = en_f1
            p_1130_f1 = en_f1
            
            for tm, p in zip(t_f1, p_f1):
                if p >= sl35_f1:
                    ex_f1_v1 = sl35_f1
                    break
                if tm <= f"{d} 10:30:59":
                    p_1030_f1 = p
                    if p > max_h_1030_f1:
                        max_h_1030_f1 = p
                if tm <= f"{d} 11:00:59":
                    p_1100_f1 = p
                if tm <= f"{d} 11:30:59":
                    p_1130_f1 = p
                if tm == f"{d} 10:30:00":
                    loss_1030 = ((p_1030_f1 - en_f1) / en_f1) * 100.0
                    if (max_h_1030_f1 > pre_entry_high) and (loss_1030 >= 1.0):
                        ex_f1_v1 = p_1030_f1
                        break
                if tm == f"{d} 11:00:00":
                    loss_1100 = ((p_1100_f1 - en_f1) / en_f1) * 100.0
                    if loss_1100 >= 2.0:
                        ex_f1_v1 = p_1100_f1
                        break
                if tm == f"{d} 11:30:00":
                    loss_1130 = ((p_1130_f1 - en_f1) / en_f1) * 100.0
                    if loss_1130 >= 2.2:
                        ex_f1_v1 = p_1130_f1
                        break
            res['f1_ex_v1'] = ex_f1_v1
            
            # V2: Trailing 2.0% + Patterns
            cur_sl_f1 = sl35_f1
            trough_f1 = en_f1
            trail_active_f1 = False
            ex_f1_v2 = final_f1
            for tm, p in zip(t_f1, p_f1):
                if p < trough_f1:
                    trough_f1 = p
                if not trail_active_f1 and trough_f1 <= en_f1 * 0.980:
                    trail_active_f1 = True
                if trail_active_f1:
                    new_sl = round(trough_f1 * 1.020, 2)
                    if new_sl < cur_sl_f1:
                        cur_sl_f1 = new_sl
                if p >= cur_sl_f1:
                    ex_f1_v2 = cur_sl_f1
                    break
                if tm == f"{d} 10:30:00" and not trail_active_f1:
                    loss_1030 = ((p - en_f1) / en_f1) * 100.0
                    if (max_h_1030_f1 > pre_entry_high) and (loss_1030 >= 1.0):
                        ex_f1_v2 = p
                        break
                if tm == f"{d} 11:00:00" and not trail_active_f1:
                    loss_1100 = ((p - en_f1) / en_f1) * 100.0
                    if loss_1100 >= 2.0:
                        ex_f1_v2 = p
                        break
                if tm == f"{d} 11:30:00" and not trail_active_f1:
                    loss_1130 = ((p - en_f1) / en_f1) * 100.0
                    if loss_1130 >= 2.2:
                        ex_f1_v2 = p
                        break
            res['f1_ex_v2'] = ex_f1_v2
            
    return res

def main():
    prev_map = load_prev_closes()
    df_m2 = pd.read_csv(M2_CSV)
    trades = df_m2.to_dict('records')
    for t in trades:
        s = str(t['stockname']).strip().upper().replace('"', '').strip()
        d = str(t['date']).strip()[:10]
        t['prev_close'] = prev_map.get((s, d))
        
    print(f"Simulating Clean Unified System on {len(trades):,} trades...")
    with ThreadPoolExecutor(max_workers=24) as ex:
        results = [r for r in ex.map(sim_trade, trades) if r is not None]
    rdf = pd.DataFrame(results)
    
    # 1. Equity Cash
    eq_valid = rdf[rdf['eq_en'].notna()].copy()
    chg_base = [calculate_kotak_charges(en, ex, q)['total_charges'] for en, ex, q in zip(eq_valid['eq_en'], eq_valid['eq_ex_base'], eq_valid['qty'])]
    chg_v1   = [calculate_kotak_charges(en, ex, q)['total_charges'] for en, ex, q in zip(eq_valid['eq_en'], eq_valid['eq_ex_v1'], eq_valid['qty'])]
    chg_v2   = [calculate_kotak_charges(en, ex, q)['total_charges'] for en, ex, q in zip(eq_valid['eq_en'], eq_valid['eq_ex_v2'], eq_valid['qty'])]
    
    eq_valid['net_base'] = (eq_valid['eq_en'] - eq_valid['eq_ex_base']) * eq_valid['qty'] - pd.Series(chg_base, index=eq_valid.index)
    eq_valid['net_v1']   = (eq_valid['eq_en'] - eq_valid['eq_ex_v1']) * eq_valid['qty'] - pd.Series(chg_v1, index=eq_valid.index)
    eq_valid['net_v2']   = (eq_valid['eq_en'] - eq_valid['eq_ex_v2']) * eq_valid['qty'] - pd.Series(chg_v2, index=eq_valid.index)
    
    # 2. Futures F1
    f1_valid = rdf[rdf['f1_en'].notna()].copy()
    f1_valid['f1_net_base'] = (f1_valid['f1_en'] - f1_valid['f1_ex_base']) * f1_valid['qty'] - (600.0 * f1_valid['lots'])
    f1_valid['f1_net_v1']   = (f1_valid['f1_en'] - f1_valid['f1_ex_v1']) * f1_valid['qty'] - (600.0 * f1_valid['lots'])
    f1_valid['f1_net_v2']   = (f1_valid['f1_en'] - f1_valid['f1_ex_v2']) * f1_valid['qty'] - (600.0 * f1_valid['lots'])
    
    print("\n" + "=" * 135)
    print("📊 1. EQUITY CASH (Kotak MIS Charges) CLEAN YEAR-OVER-YEAR PERFORMANCE")
    print("=" * 135)
    print(f"{'Year':<6} | {'Base Trds':<9} | {'Filt Trds':<9} | {'Base Net (L)':<14} | {'Unified V1 (L)':<15} | {'Unified V2 (L)':<15} | {'V2 Gain vs Base':<15} | {'V2 WR%'}")
    print("-" * 135)
    
    years = sorted(eq_valid['year'].unique())
    tot_b_k, tot_v1_k, tot_v2_k = 0.0, 0.0, 0.0
    for y in years:
        g = eq_valid[eq_valid['year'] == y]
        gf = g[g['passed_filter']]
        
        bk = g['net_base'].sum() / 1e5
        v1k = gf['net_v1'].sum() / 1e5
        v2k = gf['net_v2'].sum() / 1e5
        diff = v2k - bk
        wr_v2 = (gf['net_v2'] > 0).mean() * 100
        
        tot_b_k += bk
        tot_v1_k += v1k
        tot_v2_k += v2k
        print(f"{y:<6} | {len(g):>9} | {len(gf):>9} | +Rs {bk:>8.2f} L | +Rs {v1k:>9.2f} L  | +Rs {v2k:>9.2f} L  | {diff:>+11.2f} L   | {wr_v2:>6.2f}%")
        
    print("-" * 135)
    all_f_eq = eq_valid[eq_valid['passed_filter']]
    tot_wr_eq = (all_f_eq['net_v2'] > 0).mean() * 100
    print(f"{'TOTAL':<6} | {len(eq_valid):>9} | {len(all_f_eq):>9} | +Rs {tot_b_k:>8.2f} L | +Rs {tot_v1_k:>9.2f} L  | +Rs {tot_v2_k:>9.2f} L  | {tot_v2_k - tot_b_k:>+11.2f} L   | {tot_wr_eq:>6.2f}%")
    print("=" * 135)
    
    print("\n" + "=" * 135)
    print("📊 2. FUTURES F1 (Flat ₹600 Charges) CLEAN YEAR-OVER-YEAR PERFORMANCE")
    print("=" * 135)
    print(f"{'Year':<6} | {'Base Trds':<9} | {'Filt Trds':<9} | {'Base Net (L)':<14} | {'Unified V1 (L)':<15} | {'Unified V2 (L)':<15} | {'V2 Gain vs Base':<15} | {'V2 WR%'}")
    print("-" * 135)
    
    tot_b_f1, tot_v1_f1, tot_v2_f1 = 0.0, 0.0, 0.0
    for y in years:
        g = f1_valid[f1_valid['year'] == y]
        gf = g[g['passed_filter']]
        
        bf = g['f1_net_base'].sum() / 1e5
        v1f = gf['f1_net_v1'].sum() / 1e5
        v2f = gf['f1_net_v2'].sum() / 1e5
        diff_f = v2f - bf
        wr_f1 = (gf['f1_net_v2'] > 0).mean() * 100
        
        tot_b_f1 += bf
        tot_v1_f1 += v1f
        tot_v2_f1 += v2f
        print(f"{y:<6} | {len(g):>9} | {len(gf):>9} | +Rs {bf:>8.2f} L | +Rs {v1f:>9.2f} L  | +Rs {v2f:>9.2f} L  | {diff_f:>+11.2f} L   | {wr_f1:>6.2f}%")
        
    print("-" * 135)
    all_f_f1 = f1_valid[f1_valid['passed_filter']]
    tot_wr_f1 = (all_f_f1['f1_net_v2'] > 0).mean() * 100
    print(f"{'TOTAL':<6} | {len(f1_valid):>9} | {len(all_f_f1):>9} | +Rs {tot_b_f1:>8.2f} L | +Rs {tot_v1_f1:>9.2f} L  | +Rs {tot_v2_f1:>9.2f} L  | {tot_v2_f1 - tot_b_f1:>+11.2f} L   | {tot_wr_f1:>6.2f}%")
    print("=" * 135)

if __name__ == '__main__':
    main()
