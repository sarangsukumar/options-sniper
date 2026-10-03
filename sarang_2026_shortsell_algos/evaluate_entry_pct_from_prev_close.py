#!/usr/bin/env python3
"""
evaluate_entry_pct_from_prev_close.py
======================================
Empirical Investigation of User's Hypothesis:
"If the algo selects stocks to short sell and they are already in huge loss
(> 2% down from prev close at entry time), do we tend to lose on such trades?"

Evaluates entry % from previous day close across:
1. Model 2 (09:42 -> 14:45 Hybrid Intraday Engine)
2. Model 1 (09:20 -> 09:40 Morning Scalp Engine)

Tested on both Equity Cash (Kotak MIS) and Futures F1 (Flat Rs 600).
"""

import os, sys, pymysql
import pandas as pd
import numpy as np

M1_CSV = '/home/ubuntu/sarang_2026_shortsell_algos/model1_equity_kotak_vs_f1_flat600.csv'
M2_CSV = '/home/ubuntu/sarang_2026_shortsell_algos/model2_equity_kotak_vs_f1_flat600.csv'
HIST_DATASET = '/home/ubuntu/v5_from_scratch/data/short_sell_ml_dataset_v5_scratch.csv'

def get_db():
    return pymysql.connect(host='localhost', user='root', password='root', database='markets', autocommit=True)

def load_prev_closes():
    print("Loading historical dataset for previous close mapping...")
    df_h = pd.read_csv(HIST_DATASET, usecols=['clean_stock', 'short_sell_date', 'prev_close'], low_memory=False)
    df_h = df_h.dropna(subset=['clean_stock', 'short_sell_date', 'prev_close'])
    df_h['clean_stock'] = df_h['clean_stock'].astype(str).str.strip().str.upper()
    df_h['date'] = df_h['short_sell_date'].astype(str).str.strip()
    # Drop duplicates
    df_h = df_h.drop_duplicates(subset=['clean_stock', 'date'])
    return dict(zip(zip(df_h['clean_stock'], df_h['date']), df_h['prev_close'].astype(float)))

def analyze_model(model_name, df, stock_col, date_col, entry_col, net_kotak_col, net_f1_col, gross_col, prev_map):
    print("\n" + "=" * 115)
    print(f"📊 EMPIRICAL AUDIT: {model_name} ENTRY PRICE VS PREVIOUS CLOSE")
    print("=" * 115)
    
    # Map prev close
    prev_closes = []
    missing_cnt = 0
    for s, d in zip(df[stock_col], df[date_col]):
        s_clean = str(s).strip().upper().replace('"', '').strip()
        d_clean = str(d).strip()[:10]
        pc = prev_map.get((s_clean, d_clean))
        if pc is None or pc <= 0:
            missing_cnt += 1
            prev_closes.append(np.nan)
        else:
            prev_closes.append(pc)
            
    df['prev_close'] = prev_closes
    valid = df[df['prev_close'].notna() & (df['prev_close'] > 0)].copy()
    print(f"Total Trades: {len(df):,} | Valid with Prev Close: {len(valid):,} (Missing: {missing_cnt})")
    
    # Calculate % change from prev close at entry: (entry - prev_close) / prev_close * 100
    valid['entry_chg_pct'] = ((valid[entry_col] - valid['prev_close']) / valid['prev_close']) * 100.0
    
    # Bins
    bins = [-999.0, -3.0, -2.0, -1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5, 2.0, 3.0, 999.0]
    labels = [
        '< -3.0% (Dumped)',
        '-3.0% to -2.0%',
        '-2.0% to -1.5%',
        '-1.5% to -1.0%',
        '-1.0% to -0.5%',
        '-0.5% to 0.0%',
        '0.0% to +0.5%',
        '+0.5% to +1.0%',
        '+1.0% to +1.5%',
        '+1.5% to +2.0%',
        '+2.0% to +3.0%',
        '> +3.0% (Pumped)'
    ]
    valid['bucket'] = pd.cut(valid['entry_chg_pct'], bins=bins, labels=labels)
    
    print("\n" + "-" * 115)
    print(f"{'Entry % from Prev Close':<20} | {'Trades':<10} | {'Kotak WR%':<10} | {'Avg Net (Kotak)':<16} | {'Total Kotak (L)':<16} | {'Total F1 (L)':<15} | {'Profit Factor'}")
    print("-" * 115)
    
    for lbl in labels:
        sub = valid[valid['bucket'] == lbl]
        if len(sub) == 0:
            continue
        cnt = len(sub)
        pct_of_all = (cnt / len(valid)) * 100.0
        wr = (sub[net_kotak_col] > 0).mean() * 100.0
        avg_net = sub[net_kotak_col].mean()
        tot_k = sub[net_kotak_col].sum() / 1e5
        tot_f1 = sub[net_f1_col].sum() / 1e5
        
        wins = sub[sub[net_kotak_col] > 0][net_kotak_col].sum()
        losses = abs(sub[sub[net_kotak_col] < 0][net_kotak_col].sum())
        pf = (wins / losses) if losses > 0 else np.nan
        
        print(f"{lbl:<20} | {cnt:>5} ({pct_of_all:>4.1f}%) | {wr:>8.2f}% | Rs {avg_net:>10.2f}    | Rs {tot_k:>10.2f} L   | Rs {tot_f1:>9.2f} L  | {pf:>6.2f}")
    print("-" * 115)
    
    # Summary of User Hypothesis: Down > 2% from prev close vs Others
    down_2pct = valid[valid['entry_chg_pct'] <= -2.0]
    between_minus2_and_plus2 = valid[(valid['entry_chg_pct'] > -2.0) & (valid['entry_chg_pct'] < 2.0)]
    up_2pct = valid[valid['entry_chg_pct'] >= 2.0]
    
    print("\n🎯 MACRO HYPOTHESIS TEST: DOES SHORTING DUMPED STOCKS (< -2.0%) DESTROY PERFORMANCE?")
    print("-" * 115)
    print(f"{'Condition':<35} | {'Trades':<10} | {'Kotak WR%':<10} | {'Total Kotak (L)':<16} | {'Avg Net/Trd':<14} | {'F1 Net (L)'}")
    print("-" * 115)
    
    groups = [
        ("A. Already Dumped (Down <= -2.0%)", down_2pct),
        ("B. Normal Range (-2.0% to +2.0%)", between_minus2_and_plus2),
        ("C. Pumped / Rallying (Up >= +2.0%)", up_2pct),
        ("ALL TRADES BASELINE", valid)
    ]
    for gname, g_df in groups:
        if len(g_df) == 0:
            continue
        g_cnt = len(g_df)
        g_wr = (g_df[net_kotak_col] > 0).mean() * 100
        g_tot_k = g_df[net_kotak_col].sum() / 1e5
        g_avg_k = g_df[net_kotak_col].mean()
        g_tot_f1 = g_df[net_f1_col].sum() / 1e5
        print(f"{gname:<35} | {g_cnt:>5} ({g_cnt/len(valid)*100:>4.1f}%) | {g_wr:>8.2f}% | Rs {g_tot_k:>10.2f} L   | Rs {g_avg_k:>8.2f}    | Rs {g_tot_f1:>9.2f} L")
    print("-" * 115)
    
    # Filter Evaluation: What happens if we add filter "Skip if Entry % < Threshold"?
    print("\n🔍 IMPACT OF SKIPPING OVEREXTENDED SHORT SETUPS:")
    print("-" * 115)
    print(f"{'Filter Mechanism':<42} | {'Trades Left':<12} | {'Kotak Net':<14} | {'Kotak Diff':<12} | {'F1 Net':<14} | {'Kotak WR%'}")
    print("-" * 115)
    
    base_k = valid[net_kotak_col].sum() / 1e5
    base_f1 = valid[net_f1_col].sum() / 1e5
    
    filters = [
        ("Baseline (No Entry Filter)", valid['entry_chg_pct'] > -999),
        ("Filter 1: Skip if Down <= -3.0%", valid['entry_chg_pct'] > -3.0),
        ("Filter 2: Skip if Down <= -2.5%", valid['entry_chg_pct'] > -2.5),
        ("Filter 3: Skip if Down <= -2.0% (User Rule)", valid['entry_chg_pct'] > -2.0),
        ("Filter 4: Skip if Down <= -1.5%", valid['entry_chg_pct'] > -1.5),
        ("Filter 5: Skip if Down <= -1.0%", valid['entry_chg_pct'] > -1.0),
        ("Filter 6: Skip if Down <= -2.0% OR Up >= +2.5%", (valid['entry_chg_pct'] > -2.0) & (valid['entry_chg_pct'] < 2.5)),
        ("Filter 7: Sweet Spot Only (-1.5% to +2.0%)", (valid['entry_chg_pct'] >= -1.5) & (valid['entry_chg_pct'] <= 2.0)),
    ]
    
    for fname, mask in filters:
        sub = valid[mask]
        sub_cnt = len(sub)
        sub_k = sub[net_kotak_col].sum() / 1e5
        sub_f1 = sub[net_f1_col].sum() / 1e5
        diff_k = sub_k - base_k
        wr = (sub[net_kotak_col] > 0).mean() * 100
        print(f"{fname:<42} | {sub_cnt:>5} ({sub_cnt/len(valid)*100:>4.1f}%) | Rs {sub_k:>8.2f} L | {diff_k:>+8.2f} L   | Rs {sub_f1:>8.2f} L | {wr:>8.2f}%")
    print("=" * 115)

def main():
    prev_map = load_prev_closes()
    print(f"✔ Loaded {len(prev_map):,} unique (stock, date) previous close mappings.")
    
    # 1. MODEL 2 (09:42 -> 14:45)
    df_m2 = pd.read_csv(M2_CSV)
    analyze_model(
        "MODEL 2 (09:42 -> 14:45 HYBRID ENGINE)",
        df_m2,
        stock_col='stockname',
        date_col='date',
        entry_col='eq_entry_price',
        net_kotak_col='eq_net',
        net_f1_col='f1_net',
        gross_col='eq_gross',
        prev_map=prev_map
    )
    
    # 2. MODEL 1 (09:20 -> 09:40)
    df_m1 = pd.read_csv(M1_CSV)
    analyze_model(
        "MODEL 1 (09:20 -> 09:40 MORNING SCALP ENGINE)",
        df_m1,
        stock_col='clean_stock',
        date_col='date_str',
        entry_col='eq_entry',
        net_kotak_col='eq_net',
        net_f1_col='f1_net',
        gross_col='eq_gross',
        prev_map=prev_map
    )

if __name__ == '__main__':
    main()
