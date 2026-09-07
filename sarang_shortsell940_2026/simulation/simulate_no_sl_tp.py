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

_current_trades = None

def process_date(date_val):
    conn = mysql.connector.connect(**DB_CONFIG)
    try:
        day_trades = _current_trades[_current_trades['date'] == date_val]
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
            close_arr = df_stock['close'].values

            ent_t = time(9, 45)
            ext_t = time(14, 45)

            ent_mask = time_arr >= ent_t
            if not ent_mask.any(): continue
            entry_idx = np.argmax(ent_mask)
            entry_price = close_arr[entry_idx]

            ext_mask = time_arr >= ext_t
            if ext_mask.any():
                exit_idx = np.argmax(ext_mask)
            else:
                exit_idx = len(time_arr) - 1

            exit_price = close_arr[exit_idx]

            # Pure hold from 09:45 to 14:45 without SL or TP
            net_pnl = ((entry_price - exit_price) * qty) - 300
            gross_pnl = (entry_price - exit_price) * qty
            ret_pct = ((entry_price - exit_price) / entry_price) * 100

            results.append({
                'date': date_val,
                'stock': stock,
                'rank': rank,
                'net_pnl': net_pnl,
                'gross_pnl': gross_pnl,
                'ret_pct': ret_pct,
                'entry_price': entry_price,
                'exit_price': exit_price
            })
        return results
    except Exception as e:
        return []
    finally:
        conn.close()

def run_simulation(input_file):
    global _current_trades
    _current_trades = pd.read_csv(os.path.join(OUTPUT_DIR, input_file))
    unique_dates = _current_trades['date'].unique()

    with multiprocessing.Pool(processes=12) as pool:
        all_results = pool.map(process_date, unique_dates)

    flat_results = [item for sublist in all_results for item in sublist]
    df_res = pd.DataFrame(flat_results)
    df_res['date'] = pd.to_datetime(df_res['date'])
    df_res['year'] = df_res['date'].dt.year
    return df_res

if __name__ == '__main__':
    print("Simulating NO SL / NO TP on predictions_advanced_top10.csv...")
    df_no_sltp = run_simulation('predictions_advanced_top10.csv')
    df_no_sltp.to_csv(os.path.join(OUTPUT_DIR, 'sim_trades_adv_no_sltp.csv'), index=False)

    print("\n================================================================================")
    print("                    NO SL / NO TP SIMULATION RESULTS (09:45 -> 14:45)")
    print("================================================================================")

    combos = [
        ("TOP 4 FORTRESS (Ranks 2, 3, 4, 5) [NO SL / NO TP]", [2, 3, 4, 5]),
        ("TOP 5 BALANCED (Ranks 2, 3, 4, 5, 6) [NO SL / NO TP]", [2, 3, 4, 5, 6]),
        ("GOLDEN PAIR (Ranks 2, 5) [NO SL / NO TP]", [2, 5]),
        ("RANK 1 ONLY [NO SL / NO TP]", [1]),
        ("RANK 2 ONLY [NO SL / NO TP]", [2]),
        ("RANK 3 ONLY [NO SL / NO TP]", [3]),
        ("RANK 4 ONLY [NO SL / NO TP]", [4]),
        ("RANK 5 ONLY [NO SL / NO TP]", [5]),
    ]

    for name, ranks in combos:
        sub = df_no_sltp[df_no_sltp['rank'].isin(ranks)].drop_duplicates(subset=['date', 'stock'])
        yearly = sub.groupby('year').agg(
            trades=('net_pnl', 'count'),
            wins=('net_pnl', lambda x: (x > 0).sum()),
            pnl=('net_pnl', 'sum'),
            avg=('net_pnl', 'mean')
        ).reset_index()
        yearly['win_pct'] = (yearly['wins'] / yearly['trades']) * 100

        total_trades = yearly['trades'].sum()
        total_wins = yearly['wins'].sum()
        total_pnl = yearly['pnl'].sum()
        avg_trade = total_pnl / total_trades if total_trades > 0 else 0
        avg_annual = yearly['pnl'].mean()
        all_pos = (yearly['pnl'] > 0).all()

        daily_pnl = sub.groupby('date')['net_pnl'].sum()
        sharpe = (daily_pnl.mean() / daily_pnl.std()) * np.sqrt(252) if daily_pnl.std() != 0 else 0
        cum_pnl = daily_pnl.cumsum()
        peak = cum_pnl.cummax()
        max_dd = (cum_pnl - peak).min()

        print(f"\n--------------------------------------------------------------------------------")
        print(f"  {name}")
        print(f"--------------------------------------------------------------------------------")
        print(f"| Year | Trades | Win Rate | Avg PnL / Trade | Total Annual PnL |")
        print(f"| :--- | :----: | :------: | :-------------: | :--------------: |")
        for _, r in yearly.iterrows():
            print(f"| {int(r['year'])} | {int(r['trades']):>6} | {r['win_pct']:>7.1f}% | ₹{r['avg']:>13.2f} | ₹{r['pnl']:>14,.2f} |")
        print(f"--------------------------------------------------------------------------------")
        print(f"TOTAL: Trades: {total_trades:,} | Win Rate: {(total_wins/total_trades)*100:.1f}% | Avg Trade: ₹{avg_trade:,.2f} | Avg Annual: ₹{avg_annual:,.2f} | Total PnL: ₹{total_pnl:,.2f}")
        print(f"Sharpe: {sharpe:.2f} | Max Drawdown: ₹{max_dd:,.2f} | All-Year Positive: {'YES ⭐⭐⭐' if all_pos else 'NO ❌'}")
