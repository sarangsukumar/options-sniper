#!/usr/bin/env python3
"""
3_simulate_pnl_v6.py
---------------------
Simulates PnL for Model v6 (100% Pure 09:42 AM Entry -> 14:45 PM Exit).

Execution Rules:
  1. Top 4 Engine: Ranks 1 to 4 per trading day
  2. No Mondays: Filter out Monday trading days
  3. F&O Ban Filter: Exclude stocks in NSE F&O Ban list
  4. Contract Lot Sizes: Match official historical F&O lot sizes
  5. Entry Price: Exact 09:42:00 AM market tick in `scrapdata_F1`
  6. Exit Price: Exact 14:45:00 PM market tick in `scrapdata_F1`
  7. NO Stop Loss and NO Take Profit at all (100% held to 14:45 PM market tick)
  8. Brokerage: ₹200 / trade deduction

Outputs:
  /home/ubuntu/daily_prediction_sytem_Dynamic_threshold/v6_pure_0942_1445_scratch/output/model_v6_simulated_pnl_0942_1445_no_sl.csv
"""

import os
import pandas as pd
import numpy as np

BASE_DIR = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/v6_pure_0942_1445_scratch'
PREDS_FILE = os.path.join(BASE_DIR, 'output', 'predictions_v6.csv')
BAN_FILE = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/config/nse_blocked_list_history.csv'
LOTS_FILE = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/config/historical_lotsize_new.csv'

OUT_FILE = os.path.join(BASE_DIR, 'output', 'model_v6_simulated_pnl_0942_1445_no_sl.csv')

def main():
    print("===================================================================================")
    print("🚀 STEP 3: SIMULATING MODEL v6 PNL (100% PURE 09:42 AM -> 14:45 PM, NO SL/TP)")
    print("===================================================================================\n")

    if not os.path.exists(PREDS_FILE):
        raise FileNotFoundError(f"Predictions missing! Run 2_train_model_v6.py first.")

    df_preds = pd.read_csv(PREDS_FILE)
    df_preds['date'] = pd.to_datetime(df_preds['date_str'])
    df_preds['dayofweek'] = df_preds['date'].dt.dayofweek
    df_preds['year'] = df_preds['date'].dt.year

    # 1. Filter out Mondays
    df_preds = df_preds[df_preds['dayofweek'] != 0].copy()

    # 2. No Ban List Filter (REMOVED BAN LIST FILTER PER USER DIRECTIVE)
    df_clean = df_preds.copy()

    # 3. Recalculate Ranks for Non-Monday Candidates
    df_clean['rank'] = df_clean.groupby('date_str')['prob_win'].rank(ascending=False, method='first').astype(int)

    # 4. Filter Top 4 Engine (Ranks 1 to 4)
    df_top4 = df_clean[df_clean['rank'].isin([1, 2, 3, 4])].copy()

    # 5. Merge Lot Sizes
    df_lots = pd.read_csv(LOTS_FILE)
    df_lots['clean_stock'] = df_lots['stockname']
    df_lots_stock = df_lots.groupby('clean_stock')['lotsize'].last().reset_index()

    df_top4 = df_top4.merge(df_lots_stock, on='clean_stock', how='left')
    df_top4['lotsize'] = df_top4['lotsize'].fillna(df_top4['quantity']).astype(int)

    # 6. PnL Calculation (NO SL, NO TP at all, Dynamic Commission: ₹300 till 2025 | ₹600 in 2026)
    df_top4['entry_price'] = df_top4['db_entry_0942_f1']
    df_top4['exit_price'] = df_top4['db_exit_1445_f1']

    df_top4['year'] = pd.to_datetime(df_top4['date_str']).dt.year
    df_top4['brokerage_rupees'] = df_top4['year'].apply(lambda y: 600.0 if y == 2026 else 300.0)

    df_top4['return_pct'] = ((df_top4['entry_price'] - df_top4['exit_price']) / df_top4['entry_price']) * 100.0
    df_top4['gross_pnl_rupees'] = (df_top4['entry_price'] - df_top4['exit_price']) * df_top4['lotsize']
    df_top4['net_pnl_rupees'] = df_top4['gross_pnl_rupees'] - df_top4['brokerage_rupees']

    # Organize Output Columns
    out_cols = [
        'date_str', 'clean_stock', 'rank', 'prob_win', 'entry_price', 'exit_price',
        'lotsize', 'return_pct', 'gross_pnl_rupees', 'brokerage_rupees', 'net_pnl_rupees'
    ]
    df_out = df_top4[out_cols].copy()
    df_out.sort_values(by=['date_str', 'rank'], inplace=True)

    df_out.to_csv(OUT_FILE, index=False)

    total_net = df_out['net_pnl_rupees'].sum()
    total_gross = df_out['gross_pnl_rupees'].sum()
    total_brokerage = df_out['brokerage_rupees'].sum()
    total_trades = len(df_out)
    win_rate = (df_out['net_pnl_rupees'] > 0).mean() * 100.0

    print("===================================================================================")
    print("🏆 MODEL v6 RESULTS: 100% PURE scrapdata_F1 TICKS (NO SL, NO TP AT ALL)")
    print("===================================================================================\n")
    print(f"• Total Out-of-Sample Trades (2021-2026): {total_trades:,} Trades")
    print(f"• Total Gross Profit:                     ₹{total_gross/1e7:.5f} Crore")
    print(f"• Total Brokerage Deduction (₹200/trade): ₹{total_brokerage/1e5:.2f} Lakhs")
    print(f"• OVERALL NET SUM PNL:                    ₹{total_net/1e7:.5f} Crore (₹{total_net:,.2f})")
    print(f"• Overall Win Rate:                       {win_rate:.2f}%")
    print(f"• Average Net PnL per Trade:              ₹{df_out['net_pnl_rupees'].mean():,.2f}\n")

    print("📅 YEAR-BY-YEAR BREAKDOWN:")
    df_out['year'] = pd.to_datetime(df_out['date_str']).dt.year
    yearly = df_out.groupby('year').agg(
        trades=('net_pnl_rupees', 'count'),
        win_rate=('net_pnl_rupees', lambda x: (x > 0).mean() * 100.0),
        net_pnl=('net_pnl_rupees', 'sum')
    ).reset_index()

    for idx, r in yearly.iterrows():
        print(f"  {int(r['year'])}: {int(r['trades']):>4} trades | Win Rate: {r['win_rate']:>5.2f}% | NET PNL: ₹{r['net_pnl']/1e7:>7.4f} Cr (₹{r['net_pnl']:>12,.2f})")

    print(f"\n✅ Step 3 complete! Saved PnL sheet to: {OUT_FILE}")

if __name__ == '__main__':
    main()
