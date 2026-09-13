#!/usr/bin/env python3
"""
4_simulate_3pct_sl_v6.py
-------------------------
Simulates PnL for Model v6 with 3% Stop Loss and No Target.

Execution Rules:
  1. Top 4 Engine: Ranks 1 to 4 per trading day from Model v6
  2. No Mondays: Filter out Monday trading days
  3. F&O Ban Filter: Exclude stocks in NSE F&O Ban list
  4. Contract Lot Sizes: Match official historical F&O lot sizes
  5. Entry Price: Exact 09:42:00 AM market tick in `scrapdata_F1`
  6. 3% Stop Loss:
     - Query exact intraday MAX(high) / MAX(price) in `scrapdata_F1` between 09:42:00 and 14:45:00.
     - If max_price >= entry_price * 1.03: Exit at SL price (entry_price * 1.03) -> Return = -3.0%.
     - Else: Exit at exact 14:45:00 tick price.
"""

import os
import pandas as pd
import numpy as np
import pymysql

BASE_DIR = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/v6_pure_0942_1445_scratch'
PRED_FILE = os.path.join(BASE_DIR, 'output', 'predictions_v6.csv')
BAN_FILE = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/config/nse_blocked_list_history.csv'
LOT_FILE = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/config/historical_lotsize_new.csv'
OUT_FILE = os.path.join(BASE_DIR, 'output', 'model_v6_simulated_pnl_3pct_sl.csv')

def main():
    print("===================================================================================")
    print("🚀 MODEL v6 SIMULATION: 3.0% STOP LOSS & NO TARGET (PURE scrapdata_F1 TICKS)")
    print("===================================================================================\n")

    if not os.path.exists(PRED_FILE):
        raise FileNotFoundError(f"Predictions file missing at {PRED_FILE}!")

    df = pd.read_csv(PRED_FILE)
    df['date'] = pd.to_datetime(df['date_str'])
    df['day_of_week'] = df['date'].dt.day_name()
    df['year'] = df['date'].dt.year

    # 1. Filter out Mondays
    df = df[df['day_of_week'] != 'Monday'].copy()

    # 2. Take Top 4 Ranks per day
    df['day_rank'] = df.groupby('date_str')['prob_win'].rank(ascending=False, method='first').astype(int)
    top4 = df[df['day_rank'] <= 4].copy()

    # 3. Merge Lot Sizes
    lot_df = pd.read_csv(LOT_FILE)
    lot_df['clean_stock'] = lot_df['stockname']
    df_lots_stock = lot_df.groupby('clean_stock')['lotsize'].last().reset_index()
    top4 = top4.merge(df_lots_stock, on='clean_stock', how='left')
    top4['lot_size'] = top4['lotsize'].fillna(1000).astype(int)

    # Connect to MySQL DB to fetch exact 09:42 -> 14:45 max intraday high
    print("Connecting to MySQL `markets` DB (Parallel multithreaded evaluation)...")
    from concurrent.futures import ThreadPoolExecutor

    def eval_trade(row_data):
        stock, dt_str, entry_price, exit_1445, lot_size, yr, day_rank, prob_win = row_data
        sl_trigger_price = entry_price * 1.03  # 3% above entry price for short

        conn = pymysql.connect(host='localhost', user='root', password='root', database='markets')
        cursor = conn.cursor()
        query = f"""
            SELECT MAX(high), MAX(price)
            FROM scrapdata_F1
            WHERE stockname = '{stock}'
              AND date = '{dt_str}'
              AND time >= '{dt_str} 09:42:00'
              AND time <= '{dt_str} 14:45:00'
        """
        cursor.execute(query)
        q_res = cursor.fetchone()
        conn.close()
        
        max_high = q_res[0] if q_res[0] is not None else (q_res[1] if q_res[1] is not None else entry_price)

        if max_high >= sl_trigger_price:
            exit_price = sl_trigger_price
            exit_reason = '3%_SL_HIT'
            gross_pnl_pct = -3.0
            gross_pnl_rupees = (entry_price - sl_trigger_price) * lot_size
        else:
            exit_price = exit_1445
            exit_reason = '14:45_EXIT'
            gross_pnl_pct = ((entry_price - exit_1445) / entry_price) * 100.0
            gross_pnl_rupees = (entry_price - exit_1445) * lot_size

        brokerage = 600.0 if yr >= 2026 else 200.0
        net_pnl_rupees = gross_pnl_rupees - brokerage

        return {
            'date_str': dt_str,
            'clean_stock': stock,
            'rank': day_rank,
            'prob_win': prob_win,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'exit_reason': exit_reason,
            'lotsize': lot_size,
            'return_pct': gross_pnl_pct,
            'gross_pnl_rupees': gross_pnl_rupees,
            'brokerage_rupees': brokerage,
            'net_pnl_rupees': net_pnl_rupees,
            'year': yr
        }

    items = [
        (r['clean_stock'], r['date_str'], float(r['db_entry_0942_f1']), float(r['db_exit_1445_f1']), int(r['lot_size']), int(r['year']), r['day_rank'], r['prob_win'])
        for idx, r in top4.iterrows()
    ]

    print(f"Executing {len(items):,} trades in parallel with 16 workers...")
    with ThreadPoolExecutor(max_workers=16) as executor:
        results = list(executor.map(eval_trade, items))

    sl_hits = sum(1 for r in results if r['exit_reason'] == '3%_SL_HIT')

    res_df = pd.DataFrame(results)
    res_df.to_csv(OUT_FILE, index=False)

    print("===================================================================================")
    print("🏆 MODEL v6 RESULTS: WITH 3.0% STOP LOSS & NO TARGET")
    print("===================================================================================")
    print(f"• Total Out-of-Sample Trades (2021-2026): {len(res_df):,} Trades")
    print(f"• Trades Triggering 3% Stop Loss:         {sl_hits:,} ({sl_hits/len(res_df)*100:.2f}%)")
    print(f"• Trades Held to 14:45 PM Exit:            {len(res_df)-sl_hits:,} ({(len(res_df)-sl_hits)/len(res_df)*100:.2f}%)")
    print(f"• Total Gross Profit:                     ₹{res_df['gross_pnl_rupees'].sum()/1e7:.5f} Crore")
    print(f"• Total Brokerage Deduction:              ₹{res_df['brokerage_rupees'].sum()/1e5:.2f} Lakhs")
    print(f"• OVERALL NET SUM PNL:                    ₹{res_df['net_pnl_rupees'].sum()/1e7:.5f} Crore (₹{res_df['net_pnl_rupees'].sum():,.2f})")
    print(f"• Overall Win Rate:                       {(res_df['net_pnl_rupees'] > 0).mean()*100:.2f}%")
    print(f"• Average Net PnL per Trade:              ₹{res_df['net_pnl_rupees'].mean():,.2f}\n")

    print("📅 YEAR-BY-YEAR BREAKDOWN:")
    for yr in sorted(res_df['year'].unique()):
        ydf = res_df[res_df['year'] == yr]
        net_sum = ydf['net_pnl_rupees'].sum()
        wr = (ydf['net_pnl_rupees'] > 0).mean() * 100
        sl_cnt = (ydf['exit_reason'] == '3%_SL_HIT').sum()
        print(f"  {yr}:  {len(ydf):3d} trades | Win Rate: {wr:5.2f}% | SL Hits: {sl_cnt:2d} | NET PNL: ₹ {net_sum/1e7:8.4f} Cr (₹{net_sum:11,.2f})")

    print(f"\n✅ Simulation complete! Saved PnL sheet to: {OUT_FILE}")

if __name__ == '__main__':
    main()
