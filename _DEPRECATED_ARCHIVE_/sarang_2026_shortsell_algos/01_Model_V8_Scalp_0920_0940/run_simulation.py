#!/usr/bin/env python3
"""
2_train_walk_forward_v8.py
--------------------------
Walk-Forward LightGBM Training & Simulation Engine for Model V8.

Data Source: MySQL `scrapdata` Equity Table
Entry Time: Exact 09:20:00 AM IST
Exit Time: Exact 09:40:00 AM IST
Selection Rule: Top 4 highest probability short sell candidates per day
Charges: ₹300 flat commission per trade
Lot Sizes: Matched from historical_lotsize_new.csv
"""

import os
import sys
import pandas as pd
import numpy as np
import lightgbm as lgb
import warnings
warnings.filterwarnings('ignore')

BASE_DIR = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/v8_model'
DATA_FILE = os.path.join(BASE_DIR, 'data', 'short_sell_ml_dataset_v8.csv')
LOTS_FILE = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/config/historical_lotsize_new.csv'
OUTPUT_CSV = os.path.join(BASE_DIR, 'output', 'model_v8_simulated_pnl.csv')

FEATURE_COLS = [
    'prev_intraday_vwap_gap',
    'prev_intraday_roc_last_hour',
    'prev_intraday_return',
    'positive_arc_ratio',
    'rejection_wick',
    'Gap_Pct',
    'gap_0907_pct',
    'morn_range_pct_0920'
]

def load_lot_sizes():
    df_lots = pd.read_csv(LOTS_FILE)
    df_lots['exp_dt'] = pd.to_datetime(df_lots['expdate'], format='%d/%m/%Y', errors='coerce')
    return df_lots

def get_lot_size(stock, date_str, df_lots):
    dt = pd.to_datetime(date_str)
    sub = df_lots[df_lots['stockname'] == stock]
    if len(sub) == 0:
        return 100
    future_exps = sub[sub['exp_dt'] >= dt]
    if len(future_exps) > 0:
        return int(future_exps.sort_values('exp_dt').iloc[0]['lotsize'])
    return int(sub.sort_values('exp_dt', ascending=False).iloc[0]['lotsize'])

def main():
    print("===================================================================================")
    print("🏆 MODEL V8 WALK-FORWARD SIMULATION (EQUITY `scrapdata` | 09:20 -> 09:40 | ₹300 CHARGES)")
    print("===================================================================================")
    
    if not os.path.exists(DATA_FILE):
        print(f"Error: Dataset {DATA_FILE} not found. Build dataset first!")
        sys.exit(1)
        
    df = pd.read_csv(DATA_FILE, low_memory=False)
    print(f"1. Loaded {len(df):,} total records from {DATA_FILE}")
    
    df['year'] = pd.to_datetime(df['date_str']).dt.year
    df_lots = load_lot_sizes()
    
    # Fill missing feature values with 0
    for col in FEATURE_COLS:
        if col in df.columns:
            df[col] = df[col].fillna(0.0)
        else:
            df[col] = 0.0
            
    test_years = [2021, 2022, 2023, 2024, 2025, 2026]
    all_oos_trades = []
    
    lgb_params = {
        'objective': 'binary',
        'metric': 'auc',
        'boosting_type': 'gbdt',
        'n_estimators': 300,
        'learning_rate': 0.03,
        'num_leaves': 15,
        'max_depth': 4,
        'min_child_samples': 50,
        'subsample': 0.8,
        'colsample_bytree': 0.8,
        'random_state': 42,
        'verbose': -1
    }
    
    print("\n2. Executing Expanding Window Walk-Forward Validation (2021–2026)...")
    
    for yr in test_years:
        df_train = df[df['year'] < yr]
        df_test = df[df['year'] == yr].copy()
        
        if len(df_test) == 0:
            continue
            
        X_train = df_train[FEATURE_COLS]
        y_train = df_train['target_v8']
        
        X_test = df_test[FEATURE_COLS]
        
        clf = lgb.LGBMClassifier(**lgb_params)
        clf.fit(X_train, y_train)
        
        df_test['prob_win'] = clf.predict_proba(X_test)[:, 1]
        
        # Rank candidates per day by win probability
        df_test['rank'] = df_test.groupby('date_str')['prob_win'].rank(ascending=False, method='first')
        
        # Select Top 4 candidates per day
        df_top4 = df_test[df_test['rank'] <= 4].copy()
        
        for idx, row in df_top4.iterrows():
            stock = row['clean_stock']
            d_str = row['date_str']
            p_0920 = row['p_0920']
            p_0940 = row['p_0940']
            
            lotsize = get_lot_size(stock, d_str, df_lots)
            
            gross_pnl = (p_0920 - p_0940) * lotsize
            comm = 300.0 # Flat commission per trade (₹300)
            net_pnl = gross_pnl - comm
            ret_pct = ((p_0920 - p_0940) / p_0920) * 100.0
            
            all_oos_trades.append({
                'year': yr,
                'date_str': d_str,
                'clean_stock': stock,
                'rank': int(row['rank']),
                'prob_win': float(row['prob_win']),
                'p_0920': p_0920,
                'p_0940': p_0940,
                'lotsize': lotsize,
                'return_pct': ret_pct,
                'gross_pnl_rupees': gross_pnl,
                'commission_rupees': comm,
                'net_pnl_rupees': net_pnl
            })
            
    df_results = pd.DataFrame(all_oos_trades)
    
    print("\n===================================================================================")
    print("🏆 ULTIMATE V8 TOP-4 RESULTS (EQUITY `scrapdata` | ₹300 CHARGES)")
    print("===================================================================================")
    
    yearly = df_results.groupby('year').agg(
        trades=('net_pnl_rupees', 'count'),
        win_rate=('net_pnl_rupees', lambda x: (x > 0).mean() * 100),
        gross_pnl=('gross_pnl_rupees', 'sum'),
        charges=('commission_rupees', 'sum'),
        net_pnl=('net_pnl_rupees', 'sum'),
        avg_trade=('net_pnl_rupees', 'mean')
    ).reset_index()
    
    print("Year | Trades | Win Rate % | Gross PnL (₹ L) | Charges (₹ L) | NET PnL (₹ L) | Avg/Trade")
    print("-" * 90)
    for idx, r in yearly.iterrows():
        print(f"{int(r['year'])} | {int(r['trades']):6d} | {r['win_rate']:10.2f}% | {r['gross_pnl']/1e5:15.2f} | {r['charges']/1e5:13.2f} | {r['net_pnl']/1e5:13.2f} | ₹{r['avg_trade']:,.2f}")
        
    tot_t = len(df_results)
    tot_wr = (df_results['net_pnl_rupees'] > 0).mean() * 100
    tot_gross = df_results['gross_pnl_rupees'].sum()
    tot_comm = df_results['commission_rupees'].sum()
    tot_net = df_results['net_pnl_rupees'].sum()
    tot_avg = df_results['net_pnl_rupees'].mean()
    
    print("-" * 90)
    print(f"TOTAL| {tot_t:6d} | {tot_wr:10.2f}% | {tot_gross/1e5:15.2f} | {tot_comm/1e5:13.2f} | {tot_net/1e5:13.2f} | ₹{tot_avg:,.2f}")
    
    os.makedirs(os.path.dirname(OUTPUT_CSV), exist_ok=True)
    df_results.to_csv(OUTPUT_CSV, index=False)
    print(f"\n✅ Detailed trades saved to:\n   {OUTPUT_CSV}")

if __name__ == '__main__':
    main()
