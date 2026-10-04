#!/usr/bin/env python3
"""
========================================================================================
👑 09:40 HYBRID MODEL: ANNUAL vs MONTHLY WALK-FORWARD RETRAINING COMPARISON
========================================================================================
Compares:
1. Annual Walk-Forward Retraining (Retrains once per year on Jan 1)
2. Monthly Walk-Forward Retraining (Retrains on the 1st of every month)
Across both:
- Baseline Execution (Hold to 14:45:00 IST with 3.0% Stop Loss)
- 14:00 (2:00 PM) 50/50 Profit Booking Strategy
========================================================================================
"""

import os
import pickle
import pandas as pd
import numpy as np

DIR = os.path.dirname(os.path.abspath(__file__))
ANNUAL_CSV = os.path.join(DIR, 'audited_0940_hybrid_trades.csv')
MONTHLY_CSV = os.path.join(DIR, 'audited_0940_monthly_trades_1x.csv')
CACHE_FILE = os.path.join(DIR, 'data', 'ticks_1400_cache.pkl')

def apply_1400_rule(df, ticks_by_date):
    pts_1400 = []
    for idx, row in df.iterrows():
        d_str = row['date']
        stk = row['stockname'] if 'stockname' in row else row['clean_stock']
        ep = row['entry_price']
        orig_pts = row['points']
        
        ticks = ticks_by_date.get(d_str, {}).get(stk, [])
        if not ticks:
            pts_1400.append(orig_pts)
            continue
            
        sl_price = ep * 1.03
        ticks_pre = [p for t_r, p in ticks if str(t_r).zfill(8) <= '14:00:00']
        ticks_post = [p for t_r, p in ticks if str(t_r).zfill(8) > '14:00:00']
        
        if ticks_pre and max(ticks_pre) >= sl_price:
            pts_1400.append(-(ep * 0.03))
            continue
            
        p_1400 = ticks_pre[-1] if ticks_pre else ep
        max_post = max(ticks_post) if ticks_post else p_1400
        p_1445 = ticks_post[-1] if ticks_post else p_1400
        
        if p_1400 < ep: # In profit at 14:00
            pts_leg1 = ep - p_1400
            pts_leg2 = -(ep * 0.03) if max_post >= sl_price else (ep - p_1445)
            pts_1400.append(0.5 * pts_leg1 + 0.5 * pts_leg2)
        else: # In loss at 14:00 -> Hold 100% to 14:45
            pts_1400.append(-(ep * 0.03) if max_post >= sl_price else (ep - p_1445))

    df['pts_1400'] = pts_1400
    df['net_5L_1400'] = 500000.0 * (df['pts_1400'] / df['entry_price']) - 400.0
    df['net_10L_1400'] = df['net_5L_1400'] * 2.0
    return df

def main():
    print("=" * 115)
    print("👑 09:40 HYBRID MODEL: ANNUAL vs MONTHLY WALK-FORWARD RETRAINING AUDIT")
    print("=" * 115)
    
    df_ann = pd.read_csv(ANNUAL_CSV)
    df_mon = pd.read_csv(MONTHLY_CSV)
    df_ann['year'] = df_ann['date'].str[:4].astype(int)
    df_mon['year'] = df_mon['date'].str[:4].astype(int)
    
    with open(CACHE_FILE, 'rb') as f:
        ticks_by_date = pickle.load(f)
        
    df_ann = apply_1400_rule(df_ann, ticks_by_date)
    df_mon = apply_1400_rule(df_mon, ticks_by_date)
    
    years = sorted(df_ann['year'].unique())
    
    print("\n" + "=" * 115)
    print("1. BASELINE EXECUTION (HOLD TO 14:45:00 IST): ANNUAL vs MONTHLY RETRAINING")
    print("=" * 115)
    print(f"{'Year':<6} | {'Ann Trds':<8} | {'Mon Trds':<8} | {'Ann Base WR%':<12} | {'Mon Base WR%':<12} | {'Ann Base 5L':<12} | {'Mon Base 5L':<12} | {'Delta (5L)':<10}")
    print("-" * 115)
    for y in years:
        ga = df_ann[df_ann['year'] == y]
        gm = df_mon[df_mon['year'] == y]
        wra = (ga['net_5L'] > 0).mean() * 100
        wrm = (gm['net_5L'] > 0).mean() * 100 if len(gm) > 0 else 0
        pnla = ga['net_5L'].sum() / 1e5
        pnlm = gm['net_5L'].sum() / 1e5 if len(gm) > 0 else 0
        diff = pnlm - pnla
        print(f"{y:<6} | {len(ga):<8} | {len(gm):<8} | {wra:6.2f}%      | {wrm:6.2f}%      | +Rs {pnla:5.2f} L   | +Rs {pnlm:5.2f} L   | {diff:>+6.2f} L")
    print("-" * 115)
    t_wra = (df_ann['net_5L'] > 0).mean() * 100
    t_wrm = (df_mon['net_5L'] > 0).mean() * 100
    t_pnla = df_ann['net_5L'].sum() / 1e5
    t_pnlm = df_mon['net_5L'].sum() / 1e5
    print(f"{'TOTAL':<6} | {len(df_ann):<8} | {len(df_mon):<8} | {t_wra:6.2f}%      | {t_wrm:6.2f}%      | +Rs {t_pnla:5.2f} L   | +Rs {t_pnlm:5.2f} L   | {t_pnlm - t_pnla:>+6.2f} L")
    print("=" * 115)

    print("\n" + "=" * 115)
    print("2. 14:00 (2:00 PM) 50/50 PROFIT BOOKING: ANNUAL vs MONTHLY RETRAINING")
    print("=" * 115)
    print(f"{'Year':<6} | {'Ann 1400 WR%':<12} | {'Mon 1400 WR%':<12} | {'Ann 1400 5L':<13} | {'Mon 1400 5L':<13} | {'Delta (5L)':<10} | {'Mon 1400 10L':<13}")
    print("-" * 115)
    for y in years:
        ga = df_ann[df_ann['year'] == y]
        gm = df_mon[df_mon['year'] == y]
        wra = (ga['net_5L_1400'] > 0).mean() * 100
        wrm = (gm['net_5L_1400'] > 0).mean() * 100 if len(gm) > 0 else 0
        pnla = ga['net_5L_1400'].sum() / 1e5
        pnlm = gm['net_5L_1400'].sum() / 1e5 if len(gm) > 0 else 0
        diff = pnlm - pnla
        pnlm_10 = gm['net_10L_1400'].sum() / 1e5 if len(gm) > 0 else 0
        print(f"{y:<6} | {wra:6.2f}%      | {wrm:6.2f}%      | +Rs {pnla:5.2f} L    | +Rs {pnlm:5.2f} L    | {diff:>+6.2f} L   | +Rs {pnlm_10:5.2f} L")
    print("-" * 115)
    t_wra = (df_ann['net_5L_1400'] > 0).mean() * 100
    t_wrm = (df_mon['net_5L_1400'] > 0).mean() * 100
    t_pnla = df_ann['net_5L_1400'].sum() / 1e5
    t_pnlm = df_mon['net_5L_1400'].sum() / 1e5
    t_pnlm_10 = df_mon['net_10L_1400'].sum() / 1e5
    print(f"{'TOTAL':<6} | {t_wra:6.2f}%      | {t_wrm:6.2f}%      | +Rs {t_pnla:5.2f} L    | +Rs {t_pnlm:5.2f} L    | {t_pnlm - t_pnla:>+6.2f} L   | +Rs {t_pnlm_10:5.2f} L")
    print("=" * 115)

if __name__ == '__main__':
    main()
