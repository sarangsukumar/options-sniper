#!/usr/bin/env python3
"""
optimize_safety_systems.py
Systematic evaluation of:
1. Entry Filter Safety: Filtering stocks by % gain from previous close.
2. Trade Profit Protection Safety: Trailing stops and profit locks once in gain.
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

def main():
    prev_map = load_prev_closes()
    df = pd.read_csv(M2_CSV)
    
    # Map prev close
    prev_closes = [prev_map.get((str(s).strip().upper().replace('\"', '').strip(), str(d).strip()[:10])) for s, d in zip(df['stockname'], df['date'])]
    df['prev_close'] = prev_closes
    valid = df[df['prev_close'].notna() & (df['prev_close'] > 0)].copy()
    valid['stock_gain_pct'] = ((valid['eq_entry_price'] - valid['prev_close']) / valid['prev_close']) * 100.0
    
    print("=" * 115)
    print("PART 1: PRE-TRADE SAFETY SYSTEM — STOCK % GAIN FROM PREV CLOSE AT 09:42")
    print("=" * 115)
    
    # We want to test different combinations of entry filters on stock_gain_pct
    # Baseline: No filter
    base_trades = len(valid)
    base_kotak = valid['eq_net'].sum() / 1e5
    base_f1 = valid['f1_net'].sum() / 1e5
    base_wr = (valid['eq_net'] > 0).mean() * 100
    
    print(f"Baseline (All Trades): {base_trades:,} trades | Net Kotak: Rs {base_kotak:.2f} L | Net F1: Rs {base_f1:.2f} L | WR: {base_wr:.2f}%")
    print("-" * 115)
    print(f"{'Safety Filter Description':<50} | {'Trades':<10} | {'Kotak Net':<14} | {'Kotak Delta':<12} | {'F1 Net':<14} | {'Kotak WR%'}")
    print("-" * 115)
    
    entry_filters = [
        ("1. Avoid Dumped Only: stock_gain >= -1.5%", valid['stock_gain_pct'] >= -1.5),
        ("2. Avoid Dumped Only: stock_gain >= -1.0%", valid['stock_gain_pct'] >= -1.0),
        ("3. Avoid Dumped + Momentum Trap: >= -1.5% AND != [2.0%, 3.0%]", 
         (valid['stock_gain_pct'] >= -1.5) & ~((valid['stock_gain_pct'] >= 2.0) & (valid['stock_gain_pct'] < 3.0))),
        ("4. Avoid Dumped + Momentum Trap: >= -1.0% AND != [2.0%, 3.0%]", 
         (valid['stock_gain_pct'] >= -1.0) & ~((valid['stock_gain_pct'] >= 2.0) & (valid['stock_gain_pct'] < 3.0))),
        ("5. Sweet Spot + Gaps: [-1.0%, +2.0%] OR > +3.0%",
         ((valid['stock_gain_pct'] >= -1.0) & (valid['stock_gain_pct'] <= 2.0)) | (valid['stock_gain_pct'] > 3.0)),
        ("6. Conservative Cap: [-1.5%, +2.0%]",
         (valid['stock_gain_pct'] >= -1.5) & (valid['stock_gain_pct'] <= 2.0)),
        ("7. Only Positive Open: stock_gain >= 0.0%",
         valid['stock_gain_pct'] >= 0.0),
        ("8. Only Moderate Green: [0.0%, +2.0%]",
         (valid['stock_gain_pct'] >= 0.0) & (valid['stock_gain_pct'] <= 2.0)),
    ]
    
    for name, mask in entry_filters:
        sub = valid[mask]
        cnt = len(sub)
        k_net = sub['eq_net'].sum() / 1e5
        f1_net = sub['f1_net'].sum() / 1e5
        k_diff = k_net - base_kotak
        wr = (sub['eq_net'] > 0).mean() * 100
        print(f"{name:<50} | {cnt:>5} ({cnt/base_trades*100:>4.1f}%) | Rs {k_net:>8.2f} L | {k_diff:>+8.2f} L   | Rs {f1_net:>8.2f} L | {wr:>8.2f}%")
    print("=" * 115)

if __name__ == '__main__':
    main()
