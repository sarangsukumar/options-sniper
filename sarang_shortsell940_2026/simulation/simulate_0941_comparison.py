import pandas as pd
import numpy as np
import mysql.connector
import os
import multiprocessing
from datetime import datetime, time
import warnings

warnings.filterwarnings('ignore')

DB_CONFIG = {'host': 'localhost', 'user': 'root', 'password': 'root', 'database': 'markets'}
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'output')
if not os.path.exists(os.path.join(OUTPUT_DIR, 'predictions_advanced_top10.csv')):
    OUTPUT_DIR = '/home/ubuntu/short_sell_simulation_algo/output'

# Load trades
preds_adv = pd.read_csv(os.path.join(OUTPUT_DIR, 'predictions_advanced_top10.csv'))
top4_trades = preds_adv[preds_adv['rank'].isin([2, 3, 4, 5])].drop_duplicates(subset=['date', 'stock']).copy()
top4_trades['strategy'] = 'Top 4 Fortress'

preds_r14 = pd.read_csv(os.path.join(OUTPUT_DIR, 'predictions_rank_1_and_4.csv'))
preds_r14 = preds_r14.drop_duplicates(subset=['date', 'stock']).copy()
preds_r14['strategy'] = 'Rank 1 & 4'

all_trades = pd.concat([top4_trades[['date', 'stock', 'qty', 'strategy']], 
                        preds_r14[['date', 'stock', 'qty', 'strategy']]], ignore_index=True)
all_trades.drop_duplicates(subset=['date', 'stock', 'strategy'], inplace=True)

unique_dates = sorted(all_trades['date'].unique())

CONFIGS = [
    # (name, entry_time, exit_time, sl_pct, tp_pct)
    ('09:45 | SL 4.0% | TP 1.0%', time(9, 45), time(14, 45), 4.0, 1.0),
    ('09:41 | SL 4.0% | TP 1.0%', time(9, 41), time(14, 45), 4.0, 1.0),
    ('09:45 | SL 2.0% | TP 3.0%', time(9, 45), time(14, 45), 2.0, 3.0),
    ('09:41 | SL 2.0% | TP 3.0%', time(9, 41), time(14, 45), 2.0, 3.0),
    ('09:45 | No SL/TP (14:45 Exit)', time(9, 45), time(14, 45), 999.0, 999.0),
    ('09:41 | No SL/TP (14:45 Exit)', time(9, 41), time(14, 45), 999.0, 999.0),
]

def process_date(date_val):
    conn = mysql.connector.connect(**DB_CONFIG)
    try:
        day_trades = all_trades[all_trades['date'] == date_val]
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
            strat = trade['strategy']
            
            df_stock = df_ticks[df_ticks['stockname'] == stock].copy()
            if df_stock.empty: continue
            df_stock.sort_values('time', inplace=True)
            
            time_arr = df_stock['time_only'].values
            close_arr = df_stock['close'].values
            high_arr = df_stock['high'].values
            low_arr = df_stock['low'].values
            
            for (cfg_name, ent_t, ext_t, sl_pct, tp_pct) in CONFIGS:
                ent_mask = time_arr >= ent_t
                if not ent_mask.any(): continue
                entry_idx = np.argmax(ent_mask)
                entry_price = close_arr[entry_idx]
                
                ext_mask = time_arr >= ext_t
                exit_idx = np.argmax(ext_mask) if ext_mask.any() else len(time_arr) - 1
                
                h_slice = high_arr[entry_idx+1:exit_idx+1]
                l_slice = low_arr[entry_idx+1:exit_idx+1]
                end_price = close_arr[exit_idx]
                
                sl_hit_idx = float('inf')
                if sl_pct != 999.0:
                    sl_p = entry_price * (1 + sl_pct / 100.0)
                    hits = np.where(h_slice >= sl_p)[0]
                    if len(hits) > 0: sl_hit_idx = hits[0]
                    
                tp_hit_idx = float('inf')
                if tp_pct != 999.0:
                    tp_p = entry_price * (1 - tp_pct / 100.0)
                    hits = np.where(l_slice <= tp_p)[0]
                    if len(hits) > 0: tp_hit_idx = hits[0]
                    
                if sl_hit_idx == float('inf') and tp_hit_idx == float('inf'):
                    ex_p = end_price
                    hit_type = 'Time'
                elif sl_hit_idx < tp_hit_idx:
                    ex_p = entry_price * (1 + sl_pct / 100.0)
                    hit_type = 'SL'
                elif tp_hit_idx < sl_hit_idx:
                    ex_p = entry_price * (1 - tp_pct / 100.0)
                    hit_type = 'TP'
                else:
                    ex_p = entry_price * (1 + sl_pct / 100.0)
                    hit_type = 'SL'
                    
                net_pnl = ((entry_price - ex_p) * qty) - 300
                results.append({
                    'date': date_val,
                    'stock': stock,
                    'strategy': strat,
                    'config': cfg_name,
                    'entry_time': ent_t.strftime('%H:%M'),
                    'sl_pct': sl_pct,
                    'tp_pct': tp_pct,
                    'net_pnl': net_pnl,
                    'hit_type': hit_type
                })
        return results
    except Exception as e:
        return []
    finally:
        conn.close()

if __name__ == '__main__':
    print(f"Running simulation comparing 09:41 vs 09:45 across {len(unique_dates)} dates...")
    pool = multiprocessing.Pool(processes=10)
    all_results = pool.map(process_date, unique_dates)
    pool.close()
    pool.join()
    
    flat = [r for sub in all_results for r in sub]
    df_res = pd.DataFrame(flat)
    df_res['year'] = pd.to_datetime(df_res['date']).dt.year
    
    output_path = os.path.join(OUTPUT_DIR, 'compare_0941_vs_0945_results.csv')
    df_res.to_csv(output_path, index=False)
    print(f"Saved raw simulation to {output_path}")
    
    for strat in ['Top 4 Fortress', 'Rank 1 & 4']:
        print(f"\n{'='*80}")
        print(f"             STRATEGY: {strat.upper()} (2018–2026)")
        print(f"{'='*80}")
        strat_df = df_res[df_res['strategy'] == strat]
        
        summary = []
        for cfg_name in [c[0] for c in CONFIGS]:
            sub = strat_df[strat_df['config'] == cfg_name]
            if len(sub) == 0: continue
            trades = len(sub)
            wins = (sub['net_pnl'] > 0).sum()
            win_rate = (wins / trades) * 100
            total_pnl = sub['net_pnl'].sum()
            avg_pnl = sub['net_pnl'].mean()
            tp_pct = (sub['hit_type'] == 'TP').mean() * 100
            sl_pct = (sub['hit_type'] == 'SL').mean() * 100
            time_pct = (sub['hit_type'] == 'Time').mean() * 100
            
            summary.append({
                'Configuration': cfg_name,
                'Trades': trades,
                'Win Rate': f"{win_rate:.1f}%",
                'Avg PnL': f"₹{avg_pnl:,.0f}",
                'Total PnL': f"₹{total_pnl:,.0f}",
                'TP / SL / Time %': f"{tp_pct:.0f}% / {sl_pct:.0f}% / {time_pct:.0f}%"
            })
        print(pd.DataFrame(summary).to_string(index=False))
        
        # Year by Year for best configs
        for best_cfg in ['09:45 | SL 4.0% | TP 1.0%', '09:41 | SL 4.0% | TP 1.0%']:
            sub_cfg = strat_df[strat_df['config'] == best_cfg]
            if len(sub_cfg) == 0: continue
            yoy = sub_cfg.groupby('year').agg(
                trades=('net_pnl', 'count'),
                wins=('net_pnl', lambda x: (x > 0).sum()),
                pnl=('net_pnl', 'sum'),
                avg=('net_pnl', 'mean')
            ).reset_index()
            yoy['win_rate'] = (yoy['wins'] / yoy['trades']) * 100
            print(f"\n--- YoY Breakdown for {best_cfg} ---")
            for _, r in yoy.iterrows():
                print(f"| {int(r['year'])} | {int(r['trades'])} trades | {r['win_rate']:.1f}% win | Avg ₹{r['avg']:,.0f} | Total: ₹{r['pnl']:,.0f} |")
