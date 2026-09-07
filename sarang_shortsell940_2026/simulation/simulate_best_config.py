import pandas as pd
import numpy as np
import mysql.connector
import os
import multiprocessing
import traceback
from datetime import datetime, time
import warnings

warnings.filterwarnings('ignore')

DB_CONFIG = {'host': 'localhost', 'user': 'root', 'password': 'root', 'database': 'markets'}
OUTPUT_DIR = '/home/ubuntu/short_sell_simulation_algo/output'

df_trades = pd.read_csv(os.path.join(OUTPUT_DIR, 'predictions_rank_1_and_4.csv'))
unique_dates = df_trades['date'].unique()

def process_date(date_val):
    conn = mysql.connector.connect(**DB_CONFIG)
    try:
        day_trades = df_trades[df_trades['date'] == date_val]
        stocks = day_trades['stock'].unique().tolist()
        if not stocks: return []
        
        format_strings = ','.join(['%s'] * len(stocks))
        query = f"SELECT stockname, time, open, high, low, close FROM scrapdata_F1 WHERE date = %s AND is_future = 'F1' AND stockname IN ({format_strings}) ORDER BY time"
        df_ticks = pd.read_sql(query, conn, params=[date_val] + stocks)
        
        if df_ticks.empty: return []
        df_ticks['time'] = pd.to_datetime(df_ticks['time'])
        df_ticks['time_only'] = df_ticks['time'].dt.time
        
        results = []
        
        for _, trade in day_trades.iterrows():
            stock = trade['stock']
            qty = trade['qty']
            rank = trade['rank']
            
            df_stock = df_ticks[df_ticks['stockname'] == stock].copy()
            if df_stock.empty: continue
            df_stock.sort_values('time', inplace=True)
            
            time_arr = df_stock['time_only'].values
            high_arr = df_stock['high'].values
            low_arr = df_stock['low'].values
            close_arr = df_stock['close'].values
            
            ent_t = time(9, 45)
            ext_t = time(14, 45)
            sl_pct = 2.0
            tp_pct = 3.0
            
            ent_mask = time_arr >= ent_t
            if not ent_mask.any(): continue
            entry_idx = np.argmax(ent_mask)
            entry_price = close_arr[entry_idx]
            
            ext_mask = time_arr > ext_t
            if ext_mask.any():
                exit_idx = np.argmax(ext_mask)
            else:
                exit_idx = len(time_arr) - 1
                
            eval_high = high_arr[entry_idx+1:exit_idx+1]
            eval_low = low_arr[entry_idx+1:exit_idx+1]
            
            default_exit_price = close_arr[exit_idx] if len(eval_high) > 0 else close_arr[entry_idx]
            
            sl_price = entry_price * (1 + sl_pct / 100.0)
            tp_price = entry_price * (1 - tp_pct / 100.0)
            
            exit_price = default_exit_price
            hit_type = "Time"
            
            for i in range(len(eval_high)):
                h = eval_high[i]
                l = eval_low[i]
                
                if h >= sl_price:
                    exit_price = sl_price
                    hit_type = "SL"
                    break
                elif l <= tp_price:
                    exit_price = tp_price
                    hit_type = "TP"
                    break
            
            net_pnl = ((entry_price - exit_price) * qty) - 300
            
            results.append({
                'date': date_val,
                'stock': stock,
                'net_pnl': net_pnl,
                'hit_type': hit_type
            })
        return results
    except Exception as e:
        traceback.print_exc()
        return []
    finally:
        conn.close()

if __name__ == '__main__':
    pool = multiprocessing.Pool(processes=10)
    all_results = pool.map(process_date, unique_dates)
    pool.close()
    pool.join()
    
    flat_results = [item for sublist in all_results for item in sublist]
    df_res = pd.DataFrame(flat_results)
    
    df_res['date'] = pd.to_datetime(df_res['date'])
    df_res['year'] = df_res['date'].dt.year
    
    print("\n========= OPTIMAL CONFIGURATION: Rank 1 + 4 (09:45 to 14:45 | 2.0% SL | 3.0% TP) =========")
    agg = df_res.groupby('year').agg(
        trades=('net_pnl', 'count'),
        wins=('net_pnl', lambda x: (x > 0).sum()),
        pnl=('net_pnl', 'sum'),
        avg=('net_pnl', 'mean')
    ).reset_index()
    agg['win_pct'] = (agg['wins'] / agg['trades']) * 100
    
    for _, row in agg.iterrows():
        print(f"| {int(row['year'])} | {int(row['trades'])} | {row['win_pct']:.1f}% | ₹{row['avg']:.2f} | ₹{row['pnl']:,.2f} |")
        
    print("-" * 60)
    print(f"TOTAL: Trades: {agg['trades'].sum()} | Win Rate: {(agg['wins'].sum() / agg['trades'].sum())*100:.1f}% | Avg PnL: ₹{agg['pnl'].sum() / agg['trades'].sum():.2f} | Total PnL: ₹{agg['pnl'].sum():,.2f}")
    
    print("\nExit Types Distribution:")
    print(df_res['hit_type'].value_counts())
