import pandas as pd
import numpy as np
import mysql.connector
import os
import multiprocessing
from datetime import datetime, time
import warnings
warnings.filterwarnings('ignore')

DB_CONFIG = {'host': 'localhost', 'user': 'root', 'password': 'root', 'database': 'markets'}
OUTPUT_DIR = '/home/ubuntu/short_sell_simulation_algo/output'

preds = pd.read_csv(os.path.join(OUTPUT_DIR, 'predictions_advanced_top10.csv'))
_top4_trades = preds[preds['rank'].isin([2, 3, 4, 5])].drop_duplicates(subset=['date', 'stock'])

SL_LIST = [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 6.0, 999.0]
TP_LIST = [1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 6.0, 999.0]

def process_date(date_val):
    conn = mysql.connector.connect(**DB_CONFIG)
    try:
        day_trades = _top4_trades[_top4_trades['date'] == date_val]
        stocks = day_trades['stock'].unique().tolist()
        if not stocks: return []
        
        format_strings = ','.join(['%s'] * len(stocks))
        query = f"SELECT stockname, time, open, high, low, close FROM scrapdata_F1 WHERE date = %s AND is_future = 'F1' AND stockname IN ({format_strings}) ORDER BY time"
        df_ticks = pd.read_sql(query, conn, params=[date_val] + stocks)
        
        if df_ticks.empty: return []
        df_ticks['time'] = pd.to_datetime(df_ticks['time'])
        df_ticks['time_only'] = df_ticks['time'].dt.time
        
        day_res = []
        for _, trade in day_trades.iterrows():
            stock = trade['stock']
            qty = trade['qty']
            
            df_stock = df_ticks[df_ticks['stockname'] == stock].copy()
            if df_stock.empty: continue
            df_stock.sort_values('time', inplace=True)
            
            time_arr = df_stock['time_only'].values
            close_arr = df_stock['close'].values
            high_arr = df_stock['high'].values
            low_arr = df_stock['low'].values
            
            ent_mask = time_arr >= time(9, 45)
            if not ent_mask.any(): continue
            entry_idx = np.argmax(ent_mask)
            entry_price = close_arr[entry_idx]
            
            ext_mask = time_arr >= time(14, 45)
            exit_idx = np.argmax(ext_mask) if ext_mask.any() else len(time_arr) - 1
            
            h_slice = high_arr[entry_idx+1:exit_idx+1]
            l_slice = low_arr[entry_idx+1:exit_idx+1]
            end_price = close_arr[exit_idx]
            
            sl_hit_idx = {}
            for sl in SL_LIST:
                if sl == 999.0:
                    sl_hit_idx[sl] = float('inf')
                else:
                    sl_p = entry_price * (1 + sl/100.0)
                    hits = np.where(h_slice >= sl_p)[0]
                    sl_hit_idx[sl] = hits[0] if len(hits) > 0 else float('inf')
            
            tp_hit_idx = {}
            for tp in TP_LIST:
                if tp == 999.0:
                    tp_hit_idx[tp] = float('inf')
                else:
                    tp_p = entry_price * (1 - tp/100.0)
                    hits = np.where(l_slice <= tp_p)[0]
                    tp_hit_idx[tp] = hits[0] if len(hits) > 0 else float('inf')
            
            for sl in SL_LIST:
                for tp in TP_LIST:
                    i_sl = sl_hit_idx[sl]
                    i_tp = tp_hit_idx[tp]
                    
                    if i_sl == float('inf') and i_tp == float('inf'):
                        ex_p = end_price
                    elif i_sl < i_tp:
                        ex_p = entry_price * (1 + sl/100.0)
                    elif i_tp < i_sl:
                        ex_p = entry_price * (1 - tp/100.0)
                    else:
                        ex_p = entry_price * (1 + sl/100.0) # SL takes precedence if same tick
                        
                    pnl = ((entry_price - ex_p) * qty) - 300
                    day_res.append({'date': date_val, 'sl': sl, 'tp': tp, 'pnl': pnl})
        return day_res
    except Exception as e:
        return []
    finally:
        conn.close()

if __name__ == '__main__':
    print(f"Testing {len(SL_LIST)*len(TP_LIST)} SL/TP combinations on Top 4 Fortress Trades...")
    unique_dates = _top4_trades['date'].unique()
    with multiprocessing.Pool(processes=12) as pool:
        all_res = pool.map(process_date, unique_dates)
    
    flat_res = [item for sublist in all_res for item in sublist]
    df = pd.DataFrame(flat_res)
    
    summary = []
    grouped = df.groupby(['sl', 'tp'])
    
    for (sl, tp), group in grouped:
        trades = len(group)
        wins = (group['pnl'] > 0).sum()
        win_rate = (wins / trades) * 100 if trades > 0 else 0
        total_pnl = group['pnl'].sum()
        avg_pnl = total_pnl / trades if trades > 0 else 0
        
        daily_pnl = group.groupby('date')['pnl'].sum()
        cum_pnl = daily_pnl.cumsum()
        peak = cum_pnl.cummax()
        max_dd = (cum_pnl - peak).min()
        sharpe = (daily_pnl.mean() / daily_pnl.std()) * np.sqrt(252) if daily_pnl.std() != 0 else 0
        
        summary.append({
            'SL': sl, 'TP': tp, 'Trades': trades, 'WinRate': win_rate,
            'TotalPnL': total_pnl, 'AvgPnL': avg_pnl, 'MaxDD': max_dd, 'Sharpe': sharpe
        })
        
    df_sum = pd.DataFrame(summary)
    
    def format_lbl(val):
        return "None" if val == 999.0 else f"{val}%"
    
    df_sum['SL_str'] = df_sum['SL'].apply(format_lbl)
    df_sum['TP_str'] = df_sum['TP'].apply(format_lbl)
    
    cols_to_print = ['SL_str', 'TP_str', 'TotalPnL', 'WinRate', 'MaxDD', 'Sharpe']
    
    top_pnl = df_sum.sort_values('TotalPnL', ascending=False).head(20)
    sl_only = df_sum[df_sum['TP'] == 999.0].sort_values('TotalPnL', ascending=False)
    tp_only = df_sum[df_sum['SL'] == 999.0].sort_values('TotalPnL', ascending=False)
    top_sharpe = df_sum.sort_values('Sharpe', ascending=False).head(20)
    
    with open(os.path.join(OUTPUT_DIR, 'sl_tp_optimization_results.txt'), 'w') as f:
        f.write("=== SL & TP GRID OPTIMIZATION (TOP 4 FORTRESS) ===\n\n")
        
        f.write("1. TOP 20 COMBINATIONS BY TOTAL PROFIT\n")
        f.write(top_pnl[cols_to_print].to_string(index=False))
        f.write("\n\n")
        
        f.write("2. STOP LOSS ONLY (NO TARGET)\n")
        f.write(sl_only[cols_to_print].to_string(index=False))
        f.write("\n\n")
        
        f.write("3. TARGET ONLY (NO STOP LOSS)\n")
        f.write(tp_only[cols_to_print].to_string(index=False))
        f.write("\n\n")
        
        f.write("4. TOP 20 BY SHARPE RATIO (RISK-ADJUSTED)\n")
        f.write(top_sharpe[cols_to_print].to_string(index=False))
        f.write("\n")
        
    print("Optimization complete!")
