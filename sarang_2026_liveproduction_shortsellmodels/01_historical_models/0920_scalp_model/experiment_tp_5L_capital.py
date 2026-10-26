#!/usr/bin/env python3
"""
experiment_tp_5L_capital.py
========================================================================================
EXPERIMENT: EVALUATE DIFFERENT TAKE-PROFIT (TP) TARGETS ON 09:20 SHORT-SELL SCALP
WITH REALISTIC ₹5,00,000 CAPITAL PER STOCK & EXACT LIMIT-ENTRY TRADES
========================================================================================
- Capital: ₹5,00,000 per stock (Qty = int(500,000 / sell_price))
- Trades: Audited 5,734 filled limit-order trades (2020-2026)
- Sweep of Rupee TP Targets: ₹500, ₹750, ₹1000, ₹1250, ₹1500, ₹1750, ₹2000, ₹2500, ₹3000, ₹4000, ₹5000
- Exit rules:
    1. 2.0% Hard Stop Loss
    2. Hard TP Hit (if candle low <= sell_price - (target_tp / qty))
    3. 09:40:00 Time Exit (if neither SL nor TP hit)
- Friction: Realistic Kotak charges (STT, Exchange, SEBI, Stamp, GST, Brokerage)
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
        cur.execute(
            f"SELECT time, open, high, low, close, price FROM scrapdata "
            f"WHERE date='{d}' AND stockname='{s}' AND time >= '{sell_t}' AND time <= '{d} 09:40:59' "
            f"ORDER BY time ASC"
        )
        ticks = cur.fetchall()
    conn.close()
    return {'meta': row, 'ticks': ticks}

def main():
    print("=" * 90)
    print("🚀 09:20 SCALP TAKE PROFIT (TP) OPTIMIZATION EXPERIMENT")
    print("   Capital: ₹5,00,000 per Stock | Sweep: ₹500 to ₹5,000 TP")
    print("=" * 90)

    if not os.path.exists(TRADES_FILE):
        print(f"Error: {TRADES_FILE} not found.")
        sys.exit(1)

    df_trades = pd.read_csv(TRADES_FILE)
    print(f"\n1. Loaded {len(df_trades):,} limit-filled trades from {os.path.basename(TRADES_FILE)}")

    # We will simulate all trades from 2020-2026
    # Let's parallel fetch the 09:25 - 09:40 ticks
    print("2. Fetching intraday minute candles (16 threads)...")
    t0 = time.time()
    rows = [r.to_dict() for _, r in df_trades.iterrows()]
    with ThreadPoolExecutor(max_workers=16) as executor:
        trade_data_list = list(executor.map(fetch_trade_ticks, rows))
    print(f"   ✔ Ticks fetched in {time.time()-t0:.1f}s.")

    # TP targets to test in Rupees
    tp_targets = [500, 750, 1000, 1250, 1500, 1750, 2000, 2500, 3000, 4000, 5000]

    # Pre-extract candles for fast vector/loop processing
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

    print(f"   ✔ Prepared {len(cleaned_trades):,} valid trades for sweep.")

    # Run sweep across TP targets
    sweep_results = []
    detailed_tp_data = {}

    for tp in tp_targets:
        trades_sim = []
        for tr in cleaned_trades:
            sp = tr['sell_price']
            qty = tr['qty']
            sl_price = round(sp * 1.02, 2) # 2.0% SL
            target_drop = tp / qty
            tp_price = round(sp - target_drop, 2)

            exit_price = None
            exit_reason = None
            exit_time = None

            for tm, o, h, l, c in tr['candles']:
                # 1. Stop loss check
                if h >= sl_price:
                    exit_price = sl_price
                    exit_reason = 'STOP_LOSS'
                    exit_time = tm
                    break

                # 2. Take profit check
                if l <= tp_price:
                    exit_price = tp_price
                    exit_reason = 'HIT_TP'
                    exit_time = tm
                    break

                # 3. 09:40:00 time exit
                if tm[-8:] >= '09:40:00':
                    exit_price = c if c > 0 else o
                    exit_reason = 'TIME_EXIT'
                    exit_time = tm
                    break

            if exit_price is None:
                tm, o, h, l, c = tr['candles'][-1]
                exit_price = c if c > 0 else o
                exit_reason = 'TIME_EXIT'
                exit_time = tm

            comm = get_kotak_charges(qty, sp, exit_price)
            net_pnl = round(((sp - exit_price) * qty) - comm, 2)
            trades_sim.append({
                'date': tr['date'],
                'year': tr['year'],
                'stock': tr['stock'],
                'sell_price': sp,
                'exit_price': exit_price,
                'qty': qty,
                'exit_reason': exit_reason,
                'exit_time': exit_time,
                'net_pnl': net_pnl,
                'commission': comm,
                'is_win': 1 if net_pnl > 0 else 0
            })

        df_sim = pd.DataFrame(trades_sim)
        detailed_tp_data[tp] = df_sim

        n_trades = len(df_sim)
        n_tp = (df_sim['exit_reason'] == 'HIT_TP').sum()
        n_sl = (df_sim['exit_reason'] == 'STOP_LOSS').sum()
        n_time = (df_sim['exit_reason'] == 'TIME_EXIT').sum()
        tp_rate = (n_tp / n_trades) * 100.0
        sl_rate = (n_sl / n_trades) * 100.0
        time_rate = (n_time / n_trades) * 100.0

        wins = (df_sim['net_pnl'] > 0).sum()
        win_rate = (wins / n_trades) * 100.0
        tot_pnl = df_sim['net_pnl'].sum()
        tot_pnl_lakhs = tot_pnl / 100000.0
        avg_trade = df_sim['net_pnl'].mean()

        gross_win = df_sim[df_sim['net_pnl'] > 0]['net_pnl'].sum()
        gross_loss = abs(df_sim[df_sim['net_pnl'] <= 0]['net_pnl'].sum())
        profit_factor = gross_win / gross_loss if gross_loss > 0 else 999.0

        # Recent 2024-2026 performance
        recent = df_sim[df_sim['year'] >= 2024]
        rec_pnl_lakhs = recent['net_pnl'].sum() / 100000.0
        rec_wr = (recent['net_pnl'] > 0).mean() * 100.0
        rec_tp_rate = (recent['exit_reason'] == 'HIT_TP').mean() * 100.0

        sweep_results.append({
            'TP_Target_Rs': tp,
            'Drop_Pct_Req': f"{(tp / 500000.0) * 100:.2f}%",
            'TP_Hit_Rate': tp_rate,
            'Win_Rate': win_rate,
            'Time_Exit_Rate': time_rate,
            'SL_Rate': sl_rate,
            'Total_Net_PnL_Lakhs': tot_pnl_lakhs,
            'Profit_Factor': profit_factor,
            'Avg_Trade_Rs': avg_trade,
            '2024_2026_PnL_Lakhs': rec_pnl_lakhs,
            '2024_2026_TP_Rate': rec_tp_rate,
            '2024_2026_Win_Rate': rec_wr
        })

    df_sweep = pd.DataFrame(sweep_results)
    print("\n" + "=" * 100)
    print("📊 TAKE PROFIT (TP) TARGET SWEEP RESULTS (₹5,00,000 CAPITAL PER STOCK)")
    print("=" * 100)
    print(df_sweep.to_string(index=False))

    # Save summary table
    summary_path = os.path.join(BASE_DIR, 'tp_optimization_sweep_5L.csv')
    df_sweep.to_csv(summary_path, index=False)
    print(f"\n✔ Full sweep table saved to: {summary_path}")

    # Breakdown for the top candidate TP values
    print("\n" + "=" * 100)
    print("🔍 YEAR-BY-YEAR DETAILED AUDIT FOR KEY TP TARGETS (₹1,000, ₹1,500, ₹2,000, ₹2,500, ₹5,000)")
    print("=" * 100)
    key_tps = [1000, 1500, 2000, 2500, 5000]
    for ktp in key_tps:
        df_k = detailed_tp_data[ktp]
        y_summary = df_k.groupby('year').agg(
            Trades=('net_pnl', 'count'),
            TP_Hit_Pct=('exit_reason', lambda s: f"{(s == 'HIT_TP').mean()*100:.1f}%"),
            Win_Rate=('net_pnl', lambda s: f"{(s > 0).mean()*100:.1f}%"),
            Net_PnL_Lakhs=('net_pnl', lambda s: round(s.sum()/100000.0, 2))
        )
        print(f"\n--- TP Target: ₹{ktp:,} (Requires {(ktp/500000)*100:.2f}% drop) ---")
        print(y_summary.to_string())

if __name__ == '__main__':
    main()
