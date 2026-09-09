#!/usr/bin/env python3
"""
4_simulate_v5_pnl.py
--------------------
Simulates portfolio performance across all rank selection strategies:
  • Standard Top 3 (Ranks 1, 2, 3)
  • Alpha Top 3 (Ranks 1, 2, 4) -- RECOMMENDED!
  • Ranks 2, 3, 4 (Excl. Rank 1)
  • Top 4 Combined Engine (Ranks 1, 2, 3, 4)

Provides side-by-side comparison:
  1. ALL TRADING DAYS (Mon-Fri)
  2. NO MONDAYS (Tue-Fri Only)
"""

import pandas as pd
import numpy as np
import os

BASE_DIR = '/home/ubuntu/v5_from_scratch'
PREDS_FILE = os.path.join(BASE_DIR, 'output', 'predictions_top10_v5_scratch.csv')
ALPHA_OUT = os.path.join(BASE_DIR, 'output', 'simulated_trades_v5_alpha_top3.csv')

def main():
    print("==================================================================")
    print("STEP 4: MODEL v5 RANK COMBINATION SIMULATION & PORTFOLIO EVALUATION")
    print("==================================================================")
    
    if not os.path.exists(PREDS_FILE):
        raise FileNotFoundError(f"Prediction file {PREDS_FILE} missing! Run step 3 first.")
        
    df = pd.read_csv(PREDS_FILE)
    df['date'] = pd.to_datetime(df['date_str'], format='mixed')
    df['year'] = df['date'].dt.year
    df['dayofweek'] = df['date'].dt.dayofweek
    df['rank'] = df.groupby('date_str')['prob_win'].rank(ascending=False, method='first').astype(int)
    
    combos = {
        'Alpha Top 3 (Ranks 1, 2, 4) ⭐': [1, 2, 4],
        'Top 4 Engine (Ranks 1, 2, 3, 4) 🚀': [1, 2, 3, 4],
        'Standard Top 3 (Ranks 1, 2, 3)': [1, 2, 3],
        'Ranks 2, 3, 4 (Excl. Rank 1)': [2, 3, 4]
    }
    
    print("\n📊 1. FULL DATASET (ALL 5 DAYS: MON - FRI):")
    print("-" * 95)
    for name, ranks in combos.items():
        sub = df[df['rank'].isin(ranks)].copy()
        pnl = sub['short_pnl_net'].sum()
        trades = len(sub)
        wins = sub[sub['short_pnl_net'] > 0]
        losses = sub[sub['short_pnl_net'] < 0]
        win_rate = (len(wins) / trades) * 100 if trades > 0 else 0
        pf = wins['short_pnl_net'].sum() / abs(losses['short_pnl_net'].sum()) if len(losses) > 0 else np.nan
        avg_pnl = sub['short_pnl_net'].mean()
        print(f"{name:36s} | Net PnL: ₹{pnl/1e7:6.3f} Cr | Avg PnL: ₹{avg_pnl:,.2f} | Win Rate: {win_rate:5.2f}% | PF: {pf:.2f} | Trades: {trades:,}")

    df_no_mon = df[df['dayofweek'] != 0].copy()

    print("\n📊 2. EXCLUDING MONDAYS (TUESDAY - FRIDAY ONLY):")
    print("-" * 95)
    for name, ranks in combos.items():
        sub = df_no_mon[df_no_mon['rank'].isin(ranks)].copy()
        pnl = sub['short_pnl_net'].sum()
        trades = len(sub)
        wins = sub[sub['short_pnl_net'] > 0]
        losses = sub[sub['short_pnl_net'] < 0]
        win_rate = (len(wins) / trades) * 100 if trades > 0 else 0
        pf = wins['short_pnl_net'].sum() / abs(losses['short_pnl_net'].sum()) if len(losses) > 0 else np.nan
        avg_pnl = sub['short_pnl_net'].mean()
        print(f"{name:36s} | Net PnL: ₹{pnl/1e7:6.3f} Cr | Avg PnL: ₹{avg_pnl:,.2f} | Win Rate: {win_rate:5.2f}% | PF: {pf:.2f} | Trades: {trades:,}")

    # Detailed Yearly Breakdown without Mondays for Alpha Top 3
    print("\n📅 RECOMMENDED ALPHA TOP 3 (RANKS 1, 2, 4) YEARLY BREAKDOWN (NO MONDAYS):")
    print("-" * 80)
    alpha_df = df_no_mon[df_no_mon['rank'].isin([1, 2, 4])].copy()
    alpha_df.to_csv(ALPHA_OUT, index=False)
    
    yearly = alpha_df.groupby('year')['short_pnl_net'].sum()
    for y, pnl in yearly.items():
        sub_y = alpha_df[alpha_df['year'] == y]
        t_cnt = len(sub_y)
        w_cnt = len(sub_y[sub_y['short_pnl_net'] > 0])
        wr = (w_cnt / t_cnt) * 100
        avg_y = sub_y['short_pnl_net'].mean()
        print(f"Year {y} | Net PnL: ₹{pnl/1e5:7.2f} Lakhs | Trades: {t_cnt:4d} | Win Rate: {wr:5.2f}% | Avg Trade: ₹{avg_y:,.2f}")
        
    tot_pnl = alpha_df['short_pnl_net'].sum()
    tot_t = len(alpha_df)
    tot_wr = (len(alpha_df[alpha_df['short_pnl_net'] > 0]) / tot_t) * 100
    tot_avg = alpha_df['short_pnl_net'].mean()
    print("-" * 80)
    print(f"TOTAL     | Net PnL: ₹{tot_pnl/1e7:7.3f} Crore | Trades: {tot_t:4d} | Win Rate: {tot_wr:5.2f}% | Avg Trade: ₹{tot_avg:,.2f}")
    print("=" * 95)

if __name__ == '__main__':
    main()
