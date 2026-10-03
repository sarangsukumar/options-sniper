#!/usr/bin/env python3
"""
test_entry_control_strategies.py
Exhaustive evaluation of candidate Entry Control Strategies on Model 2 (09:42 -> 14:45).
Tests:
1. Entry % from Prev Close thresholds
2. Gap Fade Direction (09:07 to 09:42)
3. Rejection Wick presence
4. Combined Multi-Factor Entry Rules
"""

import os, sys, pymysql
import pandas as pd
import numpy as np

M2_CSV = '/home/ubuntu/sarang_2026_shortsell_algos/model2_equity_kotak_vs_f1_flat600.csv'
HIST_DATASET = '/home/ubuntu/v5_from_scratch/data/short_sell_ml_dataset_v5_scratch.csv'

def main():
    df_m2 = pd.read_csv(M2_CSV)
    df_hist = pd.read_csv(HIST_DATASET, low_memory=False)
    df_hist['date'] = df_hist['short_sell_date'].astype(str)
    df_hist['stockname'] = df_hist['clean_stock'].astype(str)
    
    cols = ['date', 'stockname', 'prev_close', 'rejection_wick', 'morn_range_pct', 'gap_0907_pct', 'gap_fade_0907_to_940_pct']
    df_hist_sub = df_hist[cols].drop_duplicates(['date', 'stockname'])
    
    merged = pd.merge(df_m2, df_hist_sub, on=['date', 'stockname'], how='inner')
    valid = merged[merged['prev_close'].notna() & (merged['prev_close'] > 0)].copy()
    
    # Calculate Entry Metrics
    valid['stock_gain_pct'] = ((valid['eq_entry_price'] - valid['prev_close']) / valid['prev_close']) * 100.0
    valid['gap_fade'] = valid['gap_fade_0907_to_940_pct'].astype(float)
    valid['rejection'] = valid['rejection_wick'].astype(float)
    
    base_n = len(valid)
    base_k = valid['eq_net'].sum() / 1e5
    base_f1 = valid['f1_net'].sum() / 1e5
    base_wr = (valid['eq_net'] > 0).mean() * 100
    base_pf = valid[valid['eq_net'] > 0]['eq_net'].sum() / abs(valid[valid['eq_net'] < 0]['eq_net'].sum())
    
    # Daily max drawdown helper
    def calc_max_dd(sub_df):
        d_net = sub_df.groupby('date')['eq_net'].sum()
        cum = d_net.cumsum()
        peak = cum.cummax()
        return (peak - cum).max() / 1e5
        
    base_dd = calc_max_dd(valid)
    
    print("=" * 125)
    print(f"BASELINE: {base_n:,} Trades | Net Kotak: Rs {base_k:.2f} L | Net F1: Rs {base_f1:.2f} L | WR: {base_wr:.2f}% | PF: {base_pf:.2f} | Max DD: Rs {base_dd:.2f} L")
    print("=" * 125)
    
    strategies = [
        # --- Group 1: Gap / Stock Gain % Filters ---
        ("1. Avoid Dumped Only: Gain >= -1.5%", 
         valid['stock_gain_pct'] >= -1.5),
         
        ("2. Avoid Dumped Only: Gain >= -1.0%", 
         valid['stock_gain_pct'] >= -1.0),
         
        ("3. Avoid Dumped & Momentum Trap: Gain >= -1.5% and not [2.0%, 3.0%]", 
         (valid['stock_gain_pct'] >= -1.5) & ~((valid['stock_gain_pct'] >= 2.0) & (valid['stock_gain_pct'] < 3.0))),
         
        ("4. Avoid Dumped & Momentum Trap: Gain >= -1.0% and not [2.0%, 3.0%]", 
         (valid['stock_gain_pct'] >= -1.0) & ~((valid['stock_gain_pct'] >= 2.0) & (valid['stock_gain_pct'] < 3.0))),
         
        ("5. Sweet Spot + Gaps: [-1.0%, +2.0%] or > +3.0%", 
         ((valid['stock_gain_pct'] >= -1.0) & (valid['stock_gain_pct'] <= 2.0)) | (valid['stock_gain_pct'] > 3.0)),

        # --- Group 2: Price Action / Rejection Filters ---
        ("6. Require Rejection Wick > 0 (Stock hit high and pulled back)", 
         valid['rejection'] > 0.0),
         
        ("7. Gap Fade Negative (Fading morning high from 09:07 to 09:42)", 
         valid['gap_fade'] < 0.0),

        # --- Group 3: Multi-Factor Combined Strategies ---
        ("8. Strategy A: Gain >= -1.5% + Rejection Wick > 0", 
         (valid['stock_gain_pct'] >= -1.5) & (valid['rejection'] > 0.0)),
         
        ("9. Strategy B: Gain >= -1.5% + Gap Fade < 0", 
         (valid['stock_gain_pct'] >= -1.5) & (valid['gap_fade'] < 0.0)),
         
        ("10. Strategy C (Triple Filter): Gain >= -1.5%, not [2%, 3%], Rejection > 0", 
         (valid['stock_gain_pct'] >= -1.5) & ~((valid['stock_gain_pct'] >= 2.0) & (valid['stock_gain_pct'] < 3.0)) & (valid['rejection'] > 0.0)),
         
        ("11. Strategy D (Optimal Institutional): Gain in [-1.5%, 2.0%] or > 3.0%, Rejection > 0", 
         (((valid['stock_gain_pct'] >= -1.5) & (valid['stock_gain_pct'] <= 2.0)) | (valid['stock_gain_pct'] > 3.0)) & (valid['rejection'] > 0.0)),
         
        ("12. Strategy E (High Precision): Gain in [-1.0%, 2.0%] or > 3.0%, Rejection > 0, Gap Fade < 0", 
         (((valid['stock_gain_pct'] >= -1.0) & (valid['stock_gain_pct'] <= 2.0)) | (valid['stock_gain_pct'] > 3.0)) & (valid['rejection'] > 0.0) & (valid['gap_fade'] < 0.0)),
    ]
    
    print(f"{'Strategy Name':<50} | {'Trades':<11} | {'Kotak Net':<14} | {'F1 Net':<14} | {'WR %':<8} | {'PF':<6} | {'Max DD':<10} | {'Avg/Trd'}")
    print("-" * 130)
    
    for name, mask in strategies:
        sub = valid[mask]
        cnt = len(sub)
        k_net = sub['eq_net'].sum() / 1e5
        f1_net = sub['f1_net'].sum() / 1e5
        wr = (sub['eq_net'] > 0).mean() * 100
        
        wins = sub[sub['eq_net'] > 0]['eq_net'].sum()
        losses = abs(sub[sub['eq_net'] < 0]['eq_net'].sum())
        pf = (wins / losses) if losses > 0 else np.nan
        
        dd = calc_max_dd(sub)
        avg_t = sub['eq_net'].mean()
        
        print(f"{name:<50} | {cnt:>5} ({cnt/base_n*100:>4.1f}%) | Rs {k_net:>8.2f} L | Rs {f1_net:>8.2f} L | {wr:>5.2f}% | {pf:>4.2f} | Rs {dd:>6.2f} L | Rs {avg_t:>7.2f}")
    print("=" * 130)

if __name__ == '__main__':
    main()
