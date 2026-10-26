#!/usr/bin/env python3
"""
experiment_uncapped_runner_5L.py
========================================================================================
EXPERIMENT: UNCAPPED TRAILING RUNNER (NO ₹1,750 CAP) FOR 09:20 SHORT-SELL SCALP
WITH REALISTIC ₹5,00,000 CAPITAL PER STOCK & EXACT LIMIT-ENTRY TRADES
========================================================================================
Core Idea:
- Never cap the profit! When a stock plunges, let it run to ₹3,000, ₹5,000, ₹10,000+.
- Activate trailing once profit reaches ₹1,000 (+0.20% drop).
- Test different trailing mechanisms:
    1. Fixed Dollar Trail (₹250, ₹350, ₹500 from peak)
    2. Tiered Chandelier Trail:
         - At ₹1,000 - ₹2,500 peak: Lock ₹800, trail ₹250 from peak
         - At ₹2,500 - ₹5,000 peak: Lock ₹2,000, trail 15% from peak
         - At ₹5,000+ peak: Lock ₹4,200, trail 15% from peak (at ₹10k, locks ₹8.5k!)
    3. Trailing within Morning Scalp Window (09:25 to 09:40)
    4. Extended Day Runner (09:25 to 14:45 EOD for winners that keep plunging past 09:40!)
========================================================================================
"""

import os
import sys
import time
import math
import pymysql
import numpy as np
import pandas as pd
from concurrent.futures import ThreadPoolExecutor

BASE_DIR = '/home/ubuntu/live_production0920_model'
TRADES_FILE = os.path.join(BASE_DIR, 'limit_sim_0920_trades_10L.csv')

def get_db_conn():
    return pymysql.connect(
        host='localhost', user='root', password='root',
        database='markets', cursorclass=pymysql.cursors.DictCursor
    )

def get_kotak_charges(qty, sell_price, buy_price):
    if qty <= 0 or sell_price <= 0 or buy_price <= 0:
        return 0.0
    sell_value = qty * sell_price
    buy_value = qty * buy_price
    turnover = sell_value + buy_value
    brokerage = 40.0
    stt = math.ceil(sell_value * 0.00025)
    txn = turnover * 0.0000322
    sebi = turnover * 0.000001
    stamp = round(buy_value * 0.00003)
    gst = (brokerage + txn + sebi) * 0.18
    return round(brokerage + stt + txn + sebi + stamp + gst, 2)

def fetch_trade_ticks(row):
    d = row['date']
    s = row['stock']
    sell_t = str(row['sell_time'])
    conn = get_db_conn()
    with conn.cursor() as cur:
        # Fetch full day ticks up to 14:46:00 to test both 09:40 and full day runner!
        cur.execute(
            f"SELECT time, open, high, low, close, price FROM scrapdata "
            f"WHERE date='{d}' AND stockname='{s}' AND time >= '{sell_t}' AND time <= '{d} 14:46:00' "
            f"ORDER BY time ASC"
        )
        ticks = cur.fetchall()
    conn.close()
    return {'meta': row, 'ticks': ticks}

def main():
    print("=" * 110)
    print("🚀 09:20 SCALP UNCAPPED TRAILING RUNNER EXPERIMENT (LET WINNERS RUN TO ₹10K+)")
    print("   Capital: ₹5,00,000 per Stock | Base SL: ₹3,000 (0.60%) | 2020-2026 Audited Trades")
    print("=" * 110)

    df_trades = pd.read_csv(TRADES_FILE)
    print(f"\n1. Loaded {len(df_trades):,} limit-filled trades from {os.path.basename(TRADES_FILE)}")

    cache_file = '/tmp/cleaned_trades_5L_fullday.pkl'
    import pickle
    if os.path.exists(cache_file):
        print("2. Loading full-day candles from cache...")
        with open(cache_file, 'rb') as f:
            cleaned_trades = pickle.load(f)
        print(f"   ✔ Loaded {len(cleaned_trades):,} trades from cache.")
    else:
        print("2. Fetching full-day intraday minute candles (16 threads)...")
        t0 = time.time()
        rows = [r.to_dict() for _, r in df_trades.iterrows()]
        with ThreadPoolExecutor(max_workers=16) as executor:
            trade_data_list = list(executor.map(fetch_trade_ticks, rows))
        print(f"   ✔ Ticks fetched in {time.time()-t0:.1f}s.")

        cleaned_trades = []
        for td in trade_data_list:
            meta = td['meta']
            ticks = td['ticks']
            if not ticks:
                continue
            sp = float(meta['sell_price'])
            if sp <= 0:
                continue
            qty_5L = int(500000.0 / sp)
            if qty_5L <= 0:
                continue

            candle_data = []
            for t in ticks:
                o = float(t['open'] or t['price'] or 0)
                c = float(t['close'] or t['price'] or 0)
                h = float(t['high'] or max(o, c))
                l = float(t['low'] or min(o, c))
                tm = str(t['time'])
                candle_data.append((tm, o, h, l, c))

            cleaned_trades.append({
                'date': str(meta['date']),
                'year': int(str(meta['date'])[:4]),
                'stock': meta['stock'],
                'sell_price': sp,
                'qty': qty_5L,
                'candles': candle_data
            })
        with open(cache_file, 'wb') as f:
            pickle.dump(cleaned_trades, f)
    print(f"   ✔ Prepared {len(cleaned_trades):,} valid trades.")

    # First, let's analyze how many trades reach high profit levels (>₹2.5k, >₹5k, >₹10k)
    high_profits = {'reach_1k': 0, 'reach_2k': 0, 'reach_3k': 0, 'reach_5k': 0, 'reach_10k': 0, 'reach_15k': 0}
    for tr in cleaned_trades:
        sp = tr['sell_price']
        qty = tr['qty']
        min_p = min([c[3] for c in tr['candles']])
        max_profit = (sp - min_p) * qty
        if max_profit >= 1000: high_profits['reach_1k'] += 1
        if max_profit >= 2000: high_profits['reach_2k'] += 1
        if max_profit >= 3000: high_profits['reach_3k'] += 1
        if max_profit >= 5000: high_profits['reach_5k'] += 1
        if max_profit >= 10000: high_profits['reach_10k'] += 1
        if max_profit >= 15000: high_profits['reach_15k'] += 1

    n_tot = len(cleaned_trades)
    print("\n" + "=" * 90)
    print("📈 DISTRIBUTION OF MAXIMUM POTENTIAL PROFIT REACHED PER TRADE (5L CAPITAL):")
    print("=" * 90)
    for k, v in high_profits.items():
        thresh = k.replace('reach_', '₹').replace('k', ',000')
        print(f"   • Reached >= {thresh:<8}: {v:,} trades ({v/n_tot:.1%})")

    def simulate_runner(strategy_name, mode, trail_type, max_time_str='09:40:00'):
        """
        mode: 'MORNING_0940' or 'EXTENDED_1445'
        trail_type:
            - 'FIXED_250': Trail ₹250 from peak once profit >= 1000, min lock 750
            - 'FIXED_350': Trail ₹350 from peak once profit >= 1000, min lock 700
            - 'FIXED_500': Trail ₹500 from peak once profit >= 1000, min lock 600
            - 'TIERED_CHANDELIER':
                 if peak < 2500: trail 250, min lock 750
                 elif peak < 5000: trail 15% of peak (e.g. at 4k, trail is 600 -> locks 3.4k)
                 else (>=5000): trail 15% of peak (e.g. at 10k, trail is 1.5k -> locks 8.5k!)
        """
        results = []
        for tr in cleaned_trades:
            sp = tr['sell_price']
            qty = tr['qty']
            sl_price = round(sp + (3000.0 / qty), 2) # Base ₹3,000 SL

            exit_price = None
            exit_reason = None
            exit_time = None

            peak_profit_rs = 0.0
            dynamic_sl_price = sl_price

            for tm, o, h, l, c in tr['candles']:
                # If mode is morning only and passed 09:40:00 -> exit
                if mode == 'MORNING_0940' and tm[-8:] >= '09:40:00':
                    exit_price = c if c > 0 else o
                    exit_reason = 'TIME_EXIT_0940'
                    exit_time = tm
                    break

                # Full day hard exit at 14:45:00
                if mode == 'EXTENDED_1445' and tm[-8:] >= '14:45:00':
                    exit_price = c if c > 0 else o
                    exit_reason = 'EOD_EXIT_1445'
                    exit_time = tm
                    break

                candle_max_profit = (sp - l) * qty
                if candle_max_profit > peak_profit_rs:
                    peak_profit_rs = candle_max_profit

                # Base / dynamic SL check
                if h >= dynamic_sl_price:
                    exit_price = dynamic_sl_price
                    exit_reason = 'STOP_LOSS' if dynamic_sl_price == sl_price else 'TRAIL_EXIT'
                    exit_time = tm
                    break

                # Trailing logic once profit reaches ₹1,000
                if peak_profit_rs >= 1000.0:
                    if trail_type == 'CAPPED_1750':
                        if peak_profit_rs >= 1750.0:
                            exit_price = round(sp - (1750.0 / qty), 2)
                            exit_reason = 'CAP_TP_1750'
                            exit_time = tm
                            break
                        target_trail_pnl = max(800.0, peak_profit_rs - 200.0)
                    elif trail_type == 'FIXED_250':
                        target_trail_pnl = max(750.0, peak_profit_rs - 250.0)
                    elif trail_type == 'FIXED_350':
                        target_trail_pnl = max(700.0, peak_profit_rs - 350.0)
                    elif trail_type == 'FIXED_500':
                        target_trail_pnl = max(600.0, peak_profit_rs - 500.0)
                    elif trail_type == 'TIERED_CHANDELIER':
                        if peak_profit_rs < 2500.0:
                            target_trail_pnl = max(750.0, peak_profit_rs - 250.0)
                        elif peak_profit_rs < 5000.0:
                            # 15% trail
                            target_trail_pnl = max(2000.0, peak_profit_rs * 0.85)
                        else:
                            # 15% trail for mega runners (locks ₹8,500 on ₹10k peak!)
                            target_trail_pnl = max(4250.0, peak_profit_rs * 0.85)

                    trail_exit_p = round(sp - (target_trail_pnl / qty), 2)
                    if trail_exit_p < dynamic_sl_price:
                        dynamic_sl_price = trail_exit_p

                    if h >= dynamic_sl_price:
                        exit_price = dynamic_sl_price
                        exit_reason = f'TRAIL_LOCK_₹{int(target_trail_pnl)}'
                        exit_time = tm
                        break

            if exit_price is None:
                tm, o, h, l, c = tr['candles'][-1]
                exit_price = c if c > 0 else o
                exit_reason = 'LAST_CANDLE_EXIT'
                exit_time = tm

            comm = get_kotak_charges(qty, sp, exit_price)
            net_pnl = round(((sp - exit_price) * qty) - comm, 2)
            results.append({
                'date': tr['date'],
                'year': tr['year'],
                'stock': tr['stock'],
                'peak_profit': peak_profit_rs,
                'net_pnl': net_pnl,
                'exit_reason': exit_reason,
                'is_win': 1 if net_pnl > 0 else 0
            })
        return pd.DataFrame(results)

    summary_list = []
    all_dfs = {}

    runners_to_run = [
        ('Baseline: Capped Model 2 (Cap ₹1,750, 09:40 Exit)', 'MORNING_0940', 'CAPPED_1750'),
        ('Runner A: Uncapped Morning Trail ₹250 (09:40 Exit)', 'MORNING_0940', 'FIXED_250'),
        ('Runner B: Uncapped Morning Trail ₹350 (09:40 Exit)', 'MORNING_0940', 'FIXED_350'),
        ('Runner C: Uncapped Morning Tiered Chandelier (09:40 Exit)', 'MORNING_0940', 'TIERED_CHANDELIER'),
        ('Runner D: Extended Day Trail ₹350 (14:45 EOD)', 'EXTENDED_1445', 'FIXED_350'),
        ('Runner E: Extended Day Trail ₹500 (14:45 EOD)', 'EXTENDED_1445', 'FIXED_500'),
        ('Runner F: Extended Day Tiered Chandelier (14:45 EOD) 🚀', 'EXTENDED_1445', 'TIERED_CHANDELIER')
    ]

    for name, mode, t_type in runners_to_run:
        df_res = simulate_runner(name, mode, t_type)
        all_dfs[name] = df_res
        n = len(df_res)
        wins = (df_res['net_pnl'] > 0).sum()
        wr = (wins / n) * 100.0
        tot_pnl = df_res['net_pnl'].sum()
        avg_trade = df_res['net_pnl'].mean()

        gross_win = df_res[df_res['net_pnl'] > 0]['net_pnl'].sum()
        gross_loss = abs(df_res[df_res['net_pnl'] <= 0]['net_pnl'].sum())
        pf = gross_win / gross_loss if gross_loss > 0 else 999.0

        # Drawdown
        df_res['dt'] = pd.to_datetime(df_res['date'])
        daily = df_res.groupby('dt')['net_pnl'].sum()
        cum = daily.cumsum()
        max_dd = (cum - cum.cummax()).min()

        # Trades earning >= ₹3,000 and >= ₹5,000
        pnl_3k = (df_res['net_pnl'] >= 3000).sum()
        pnl_5k = (df_res['net_pnl'] >= 5000).sum()
        pnl_10k = (df_res['net_pnl'] >= 10000).sum()

        # Recent 2024-2026
        recent = df_res[df_res['year'] >= 2024]
        rec_pnl = recent['net_pnl'].sum() / 1e5
        rec_wr = (recent['net_pnl'] > 0).mean() * 100.0

        summary_list.append({
            'Model': name,
            'Win_Rate': f"{wr:.2f}%",
            'Total_Net_PnL_Lakhs': round(tot_pnl / 1e5, 2),
            'Avg_Trade_Rs': round(avg_trade, 1),
            'Profit_Factor': round(pf, 2),
            'Max_DD_Lakhs': round(max_dd / 1e5, 2),
            'Trades_>=_₹3K': pnl_3k,
            'Trades_>=_₹5K': pnl_5k,
            'Trades_>=_₹10K': pnl_10k,
            '2024_2026_PnL_Lakhs': round(rec_pnl, 2),
            '2024_2026_Win_Rate': f"{rec_wr:.2f}%"
        })

    df_summary = pd.DataFrame(summary_list)
    print("\n" + "=" * 135)
    print("📊 UNCAPPED TRAILING RUNNER EXPERIMENT RESULTS (₹5,00,000 CAPITAL)")
    print("=" * 135)
    print(df_summary.to_string(index=False))

    summary_file = os.path.join(BASE_DIR, 'uncapped_runner_experiment_5L.csv')
    df_summary.to_csv(summary_file, index=False)
    print(f"\n✔ Uncapped runner experiment saved to: {summary_file}")

    # Detailed Year-by-Year breakdown for Runner F (Tiered Chandelier to 14:45)
    print("\n" + "=" * 110)
    print("🔍 YEAR-BY-YEAR AUDIT FOR RUNNER F (EXTENDED TIERED CHANDELIER TO 14:45 EOD)")
    print("=" * 110)
    best_df = all_dfs['Runner F: Extended Day Tiered Chandelier (14:45 EOD) 🚀']
    y_audit = best_df.groupby('year').agg(
        Trades=('net_pnl', 'count'),
        Win_Rate=('net_pnl', lambda s: f"{(s > 0).mean()*100:.1f}%"),
        Net_PnL_Lakhs=('net_pnl', lambda s: round(s.sum()/100000.0, 2)),
        Avg_Trade_Rs=('net_pnl', lambda s: round(s.mean(), 1)),
        Trades_over_5k=('net_pnl', lambda s: (s >= 5000).sum())
    )
    print(y_audit.to_string())

if __name__ == '__main__':
    main()
