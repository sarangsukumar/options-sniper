#!/usr/bin/env python3
"""
2_build_dataset_v5.py
---------------------
Merges 09:07 AM Pre-Market ticks with base intraday indicators and engineers
100% leak-free Model v5 features.

Key Leak-Free Features Engineered:
  1. `gap_0907_pct` = ((Price_0907 - Prev_Close) / Prev_Close) * 100
  2. `gap_fade_0907_to_940_pct` = ((Morning_Close_0940 - Price_0907) / Price_0907) * 100

Strictly excludes full-day volume (Volume_Change_Pct) to maintain 0% lookahead bias.
Outputs: /home/ubuntu/v5_from_scratch/data/short_sell_ml_dataset_v5_scratch.csv
"""

import pandas as pd
import numpy as np
import os

BASE_DIR = '/home/ubuntu/v5_from_scratch'
CACHE_FILE = os.path.join(BASE_DIR, 'data', 'premarket_ticks_cache.csv')
V2_BASE_FILE = '/home/ubuntu/short_sell_simulation_algo/output/short_sell_ml_dataset_v2.csv'
MORN_FILE = '/home/ubuntu/shortsellmodel940v3/morning_features_v3.csv'
OUT_FILE = os.path.join(BASE_DIR, 'data', 'short_sell_ml_dataset_v5_scratch.csv')

def main():
    print("==================================================================")
    print("STEP 2: BUILDING LEAK-FREE MODEL v5 DATASET FROM SCRATCH")
    print("==================================================================")
    
    print("1. Loading base dataset and morning indicators...")
    df = pd.read_csv(V2_BASE_FILE, low_memory=False)
    df['date_str'] = pd.to_datetime(df['short_sell_date'], format='mixed').dt.strftime('%Y-%m-%d')
    df['clean_stock'] = df['clean_stock'].astype(str).str.strip().str.upper()
    df = df[df['date_str'] >= '2018-01-01'].copy()
    
    # Merge morning 09:15-09:40 technical features
    if os.path.exists(MORN_FILE):
        m_df = pd.read_csv(MORN_FILE)
        m_df['clean_stock'] = m_df['clean_stock'].astype(str).str.strip().str.upper()
        df = df.merge(m_df[['date_str', 'clean_stock', 'stock_ret_940', 'morn_range_pct', 'rejection_wick']], on=['date_str', 'clean_stock'], how='left')
        
    print("2. Merging pre-market 09:07 AM ticks from cache...")
    if not os.path.exists(CACHE_FILE):
        raise FileNotFoundError(f"Cache file {CACHE_FILE} missing! Run step 1 first.")
        
    cache_df = pd.read_csv(CACHE_FILE)
    cache_df = cache_df[cache_df['clean_stock'] != '_NONE_'].copy()
    cache_df['clean_stock'] = cache_df['clean_stock'].astype(str).str.strip().str.upper()
    
    df_eq = cache_df.dropna(subset=['price_0907_eq']).groupby(['date_str', 'clean_stock'])['price_0907_eq'].last().reset_index()
    df_f1 = cache_df.dropna(subset=['price_0907_f1']).groupby(['date_str', 'clean_stock'])['price_0907_f1'].last().reset_index()
    
    df = df.merge(df_eq, on=['date_str', 'clean_stock'], how='left')
    df = df.merge(df_f1, on=['date_str', 'clean_stock'], how='left')
    
    # Unified premarket price (prioritizing Futures F1, fallback to Equity Cash)
    df['price_0907_unified'] = df['price_0907_f1'].fillna(df['price_0907_eq'])
    
    print("3. Engineering leak-free pre-market features...")
    df['Gap_Pct'] = pd.to_numeric(df['Gap_Pct'], errors='coerce').fillna(0.0)
    df['prev_close'] = pd.to_numeric(df['prev_close'], errors='coerce')
    df['morning_close'] = pd.to_numeric(df['morning_close'], errors='coerce')
    
    # 100% Leak-Free Pre-Market Return: ((Price_0907 - Prev_Close) / Prev_Close) * 100
    df['gap_0907_pct'] = np.where(
        (df['price_0907_unified'].notna()) & (df['prev_close'].notna()) & (df['prev_close'] > 0),
        ((df['price_0907_unified'] - df['prev_close']) / df['prev_close']) * 100.0,
        df['Gap_Pct']
    )
    
    # 100% Leak-Free Pre-Market to 09:40 Fade Return: ((Morning_Close_0940 - Price_0907) / Price_0907) * 100
    df['gap_fade_0907_to_940_pct'] = np.where(
        (df['price_0907_unified'].notna()) & (df['price_0907_unified'] > 0) & (df['morning_close'].notna()),
        ((df['morning_close'] - df['price_0907_unified']) / df['price_0907_unified']) * 100.0,
        0.0
    )
    
    # Fill remaining NaNs
    df['gap_0907_pct'] = df['gap_0907_pct'].fillna(df['Gap_Pct']).fillna(0.0)
    df['gap_fade_0907_to_940_pct'] = df['gap_fade_0907_to_940_pct'].fillna(0.0)
    df['stock_ret_940'] = df['stock_ret_940'].fillna(0.0)
    df['morn_range_pct'] = df['morn_range_pct'].fillna(0.0)
    df['rejection_wick'] = df['rejection_wick'].fillna(0.0)
    
    # Drop full-day Volume_Change_Pct if present
    if 'Volume_Change_Pct' in df.columns:
        df.drop(columns=['Volume_Change_Pct'], inplace=True)
        
    print("4. Saving dataset v5...")
    df.to_csv(OUT_FILE, index=False)
    print(f"✅ Step 2 complete! Saved dataset v5 to: {OUT_FILE} ({len(df):,} rows).")

if __name__ == '__main__':
    main()
