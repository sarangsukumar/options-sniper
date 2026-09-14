#!/usr/bin/env python3
"""
eval_1130_midday_optimization.py
---------------------------------
Quantifies the exact impact of the 11:30 AM Midday Cut-Loss Rule
across the full 4,994 trades of the 09:40 Hybrid Strategy.

Rule Logic:
  - If trade is in LOSS at 11:30 AM (close_1130 > entry_price), exit immediately at 11:30 AM close.
  - If trade is in PROFIT at 11:30 AM (close_1130 <= entry_price), ride position to 14:45 PM (or 3% SL).
"""

import pymysql
import pandas as pd
import numpy as np
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(SCRIPT_DIR, 'longer_window_trades_futures_and_eq.csv')

def run_evaluation():
    print("=" * 80)
    print("🔬 11:30 AM MIDDAY CUT-LOSS OPTIMIZATION AUDIT (PURE DATABASE)")
    print("=" * 80)

    if not os.path.exists(CSV_PATH):
        print(f"Error: Could not find {CSV_PATH}")
        return

    df_hyb = pd.read_csv(CSV_PATH)
    print(f"Loaded {len(df_hyb):,} hybrid trades.")
    base_pnl_lakhs = df_hyb['f1_net_pnl'].sum() / 1e5
    print(f"Baseline Net PnL (Hold to 14:45 PM): ₹{base_pnl_lakhs:.2f} Lakhs (+₹{base_pnl_lakhs/100:.2f} Cr)")

    # Load entry price from dataset
    ds_path = '/home/ubuntu/v5_from_scratch/data/short_sell_ml_dataset_v5_scratch.csv'
    if os.path.exists(ds_path):
        ds = pd.read_csv(ds_path, usecols=['date_str', 'clean_stock', 'short_entry_price'])
        ds['clean_stock'] = ds['clean_stock'].astype(str).str.strip().str.upper()
        ds = ds.drop_duplicates(subset=['date_str', 'clean_stock'])
        df_hyb = pd.merge(df_hyb, ds, on=['date_str', 'clean_stock'], how='left')
        df_hyb['entry_price'] = df_hyb['short_entry_price']

    conn = pymysql.connect(host='localhost', user='root', password='root', database='markets')
    q = """
    SELECT date, TRIM(BOTH '"' FROM TRIM(stockname)) as clean_stock, close as close_1130
    FROM scrapdata_F1
    WHERE date >= '2020-01-01' AND TIME(time) = '11:30:00' AND is_future = 'F1'
    """
    df_1130 = pd.read_sql(q, conn)
    conn.close()

    df_1130['date_str'] = df_1130['date'].astype(str)
    df_1130['clean_stock'] = df_1130['clean_stock'].astype(str).str.strip().str.upper()
    df_1130 = df_1130.drop_duplicates(subset=['date_str', 'clean_stock'])

    m = pd.merge(df_hyb, df_1130, on=['date_str', 'clean_stock'], how='left')

    # Short position: loss if price > entry
    lot_col = 'lotsize' if 'lotsize' in m.columns else 'dynamic_lotsize'
    m['loss_at_1130'] = m['close_1130'] > m['entry_price']
    m['pnl_1130_exit'] = (m['entry_price'] - m['close_1130']) * m[lot_col] - 300.0

    # Policy 3: Cut loss at 11:30, else keep baseline exit
    m['pnl_opt_1130'] = np.where(m['loss_at_1130'] & m['close_1130'].notnull(), m['pnl_1130_exit'], m['f1_net_pnl'])

    opt_pnl_lakhs = m['pnl_opt_1130'].sum() / 1e5
    alpha_gain = opt_pnl_lakhs - base_pnl_lakhs
    base_wr = (m['f1_net_pnl'] > 0).mean() * 100
    opt_wr = (m['pnl_opt_1130'] > 0).mean() * 100

    print("-" * 80)
    print(f"11:30 Opt Net PnL: ₹{opt_pnl_lakhs:.2f} Lakhs (+₹{opt_pnl_lakhs/100:.2f} Cr)")
    print(f"Alpha Boost from 11:30 Rule: +₹{alpha_gain:.2f} Lakhs")
    print(f"Win Rate: Baseline {base_wr:.2f}%  -->  Optimized {opt_wr:.2f}%")
    print("=" * 80)

    # Year over Year Breakdown
    print(f"{'Year':<6} | {'Trades':<7} | {'Baseline Net PnL':<18} | {'11:30 Opt Net PnL':<18} | {'Delta':<12} | {'Opt WR':<8}")
    print("-" * 80)
    for y in sorted(m['year'].unique()):
        sub = m[m['year'] == y]
        b_pnl = sub['f1_net_pnl'].sum() / 1e5
        o_pnl = sub['pnl_opt_1130'].sum() / 1e5
        wr = (sub['pnl_opt_1130'] > 0).mean() * 100
        print(f"{y:<6} | {len(sub):<7} | ₹{b_pnl:>14.2f} L | ₹{o_pnl:>14.2f} L | +₹{o_pnl-b_pnl:>7.2f} L | {wr:>6.1f}%")
    print("=" * 80)

if __name__ == '__main__':
    run_evaluation()
