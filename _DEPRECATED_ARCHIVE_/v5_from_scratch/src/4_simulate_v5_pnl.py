#!/usr/bin/env python3
"""
4_simulate_v5_pnl.py
--------------------
Model v5 Production Simulation & Strategy Runner:
  • Primary Production Standard Strategy: Top 4 Engine (Ranks 1, 2, 3, 4)
  • Standard Stop Loss: Strictly 1.50% SL Across All Years
  • Schedule: Tuesday – Friday Only (Mondays Excluded)
  • Risk Filter: Excludes Stocks in NSE F&O Ban List (config/nse_blocked_list_history.csv)
  • Lot Size Lookup: Matches exact F&O contract lot sizes from config/historical_lotsize_new.csv

Outputs:
  • Production Trade Log: /home/ubuntu/v5_from_scratch/output/model_v5_top4_1_5sl_production_trades.csv
"""

import pandas as pd
import numpy as np
import os
import warnings
warnings.filterwarnings('ignore')

BASE_DIR = '/home/ubuntu/v5_from_scratch'
MAIN_REPO_DIR = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold'

PREDS_FILE = os.path.join(BASE_DIR, 'output', 'predictions_top10_v5_scratch.csv')
BAN_FILE = os.path.join(MAIN_REPO_DIR, 'config', 'nse_blocked_list_history.csv')
LOTS_FILE = os.path.join(MAIN_REPO_DIR, 'config', 'historical_lotsize_new.csv')

PROD_OUT = os.path.join(BASE_DIR, 'output', 'model_v5_top4_1_5sl_production_trades.csv')
PROD_OUT_REPO = os.path.join(MAIN_REPO_DIR, 'v5_from_scratch', 'output', 'model_v5_top4_1_5sl_production_trades.csv')

def main():
    print("==================================================================")
    print("STEP 4: MODEL v5 STANDARDIZED PRODUCTION SIMULATION (TOP 4 ENGINE, 1.5% SL)")
    print("==================================================================")
    
    if not os.path.exists(PREDS_FILE):
        raise FileNotFoundError(f"Prediction file {PREDS_FILE} missing! Run step 3 first.")
        
    df_preds = pd.read_csv(PREDS_FILE)
    df_preds['date'] = pd.to_datetime(df_preds['date_str'], format='mixed')
    df_preds['date_str'] = df_preds['date'].dt.strftime('%Y-%m-%d')
    df_preds['year'] = df_preds['date'].dt.year
    df_preds['dayofweek'] = df_preds['date'].dt.dayofweek
    df_preds['rank'] = df_preds.groupby('date_str')['prob_win'].rank(ascending=False, method='first').astype(int)

    # 1. Apply F&O Ban List Filter
    if os.path.exists(BAN_FILE):
        df_ban = pd.read_csv(BAN_FILE)
        df_ban['date_str'] = pd.to_datetime(df_ban['date']).dt.strftime('%Y-%m-%d')
        df_ban['banned'] = True
        merged = df_preds.merge(df_ban[['date_str', 'stockname', 'banned']], left_on=['date_str', 'clean_stock'], right_on=['date_str', 'stockname'], how='left')
        merged['banned'] = merged['banned'].fillna(False)
    else:
        merged = df_preds.copy()
        merged['banned'] = False

    # 2. Filter: Exclude Mondays, Banned Stocks, and Select Top 4 Engine (Ranks 1 to 4)
    df_prod = merged[(merged['dayofweek'] != 0) & (~merged['banned']) & (merged['rank'].isin([1, 2, 3, 4]))].copy()

    # 3. Apply Standard 1.50% Stop Loss Capping
    df_prod['capped_ret_pct'] = df_prod['short_pct_return'].clip(lower=-1.50)
    df_prod['sl_triggered'] = df_prod['short_pct_return'] < -1.50

    # 4. Load Historical Contract Lot Sizes
    if os.path.exists(LOTS_FILE):
        df_lots = pd.read_csv(LOTS_FILE)
        df_lots['clean_stock'] = df_lots['stockname']
        df_lots_stock = df_lots.groupby('clean_stock')['lotsize'].last().reset_index()
        df_prod = df_prod.merge(df_lots_stock, on='clean_stock', how='left')
        df_prod['lotsize'] = df_prod['lotsize'].fillna(df_prod['quantity']).astype(int)
    else:
        df_prod['lotsize'] = df_prod['quantity'].astype(int)

    # Entry and Exit Prices
    df_prod['entry_price'] = df_prod['short_entry_price'].round(2)
    df_prod['exit_price'] = np.where(
        df_prod['sl_triggered'],
        (df_prod['entry_price'] * 1.015).round(2),
        df_prod['short_exit_price'].round(2)
    )

    # Compute PnL
    df_prod['gross_pnl_rupees'] = ((df_prod['entry_price'] - df_prod['exit_price']) * df_prod['lotsize']).round(2)
    df_prod['brokerage_rupees'] = 200.0
    df_prod['net_pnl_rupees'] = (df_prod['gross_pnl_rupees'] - df_prod['brokerage_rupees']).round(2)

    # Standardized 1 Lot Proxy PnL
    df_prod['net_pnl_proxy_rupees'] = (df_prod['capped_ret_pct'] * 10000.0 - 200.0).round(2)

    # Sort & Export
    df_prod.sort_values(by=['date', 'rank'], inplace=True)
    
    os.makedirs(os.path.dirname(PROD_OUT), exist_ok=True)
    os.makedirs(os.path.dirname(PROD_OUT_REPO), exist_ok=True)
    
    df_prod.to_csv(PROD_OUT, index=False)
    df_prod.to_csv(PROD_OUT_REPO, index=False)

    print("\n📅 YEAR-BY-YEAR STANDARDIZED PRODUCTION PERFORMANCE (TOP 4 ENGINE, 1.5% SL):")
    print("-" * 110)
    print(f"{'Year':<6} | {'Trades':<8} | {'Win Rate':<10} | {'Exact Lot Net PnL (₹)':<24} | {'1 Lot Proxy Net PnL (₹)':<24} | {'Avg Net PnL / Trade':<20}")
    print("-" * 110)

    yearly = df_prod.groupby('year')
    for y, group in yearly:
        trades = len(group)
        wr = (group['net_pnl_rupees'] > 0).mean() * 100
        pnl_exact = group['net_pnl_rupees'].sum()
        pnl_proxy = group['net_pnl_proxy_rupees'].sum()
        avg_pnl = group['net_pnl_rupees'].mean()
        print(f"{y:<6} | {trades:<8,d} | {wr:5.2f}%    | ₹{pnl_exact/1e5:8.2f} Lakhs           | ₹{pnl_proxy/1e5:8.2f} Lakhs           | ₹{avg_pnl:,.2f}")

    tot_trades = len(df_prod)
    tot_wr = (df_prod['net_pnl_rupees'] > 0).mean() * 100
    tot_pnl_exact = df_prod['net_pnl_rupees'].sum()
    tot_pnl_proxy = df_prod['net_pnl_proxy_rupees'].sum()
    tot_avg_pnl = df_prod['net_pnl_rupees'].mean()

    print("-" * 110)
    print(f"{'TOTAL':<6} | {tot_trades:<8,d} | {tot_wr:5.2f}%    | ₹{tot_pnl_exact/1e7:8.3f} Crore           | ₹{tot_pnl_proxy/1e7:8.3f} Crore           | ₹{tot_avg_pnl:,.2f}")
    print("=" * 110)

    print(f"\n✅ Production Trade Log saved to:")
    print(f"   • {PROD_OUT}")
    print(f"   • {PROD_OUT_REPO}")

if __name__ == '__main__':
    main()
