#!/usr/bin/env python3
"""
experiment_sl_sweep_tp1500.py
========================================================================================
EXPERIMENT: EVALUATE DIFFERENT STOP LOSS (SL) BUCKETS WITH TP FIXED AT ₹1,500
ON 09:20 SHORT-SELL SCALP (₹5,00,000 CAPITAL PER STOCK)
========================================================================================
- Capital: ₹5,00,000 per stock (Qty = int(500,000 / sell_price))
- Trades: Audited 5,734 limit-filled trades (2020-2026)
- TP: Fixed at ₹1,500 (0.30% drop)
- SL Sweep in Rupees:
    ₹1,000 (0.20%), ₹1,500 (0.30%), ₹2,000 (0.40%), ₹2,500 (0.50%),
    ₹3,000 (0.60%), ₹3,500 (0.70%), ₹4,000 (0.80%), ₹5,000 (1.00%),
    ₹7,500 (1.50%), and Baseline 2.0% (₹10,000)
- Candle-by-candle simulation between 09:25:00 and 09:40:00:
    At each minute candle:
    - If candle high >= SL price -> Stopped out
    - If candle low <= TP price -> TP hit
    - (If both high >= SL and low <= TP in same candle, assume worst-case: SL hit first)
    - At 09:40:00 -> Time exit at market close
- Friction: Realistic Kotak institutional charges deducted on every trade
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
    print("=" * 95)
    print("🚀 09:20 SCALP STOP LOSS (SL) OPTIMIZATION EXPERIMENT")
    print("   Capital: ₹5,00,000 per Stock | Fixed TP: ₹1,500 | Sweep: ₹1,000 to ₹10,000 (2%) SL")
    print("=" * 95)

    df_trades = pd.read_csv(TRADES_FILE)
    print(f"\n1. Loaded {len(df_trades):,} limit-filled trades from {os.path.basename(TRADES_FILE)}")

    print("2. Fetching intraday minute candles (16 threads)...")
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

    print(f"   ✔ Prepared {len(cleaned_trades):,} valid trades for simulation.")

    FIXED_TP = 1500.0

    # SL sweep buckets:
    # (sl_rs, label, pct)
    sl_configs = [
        (1000.0, "₹1,000", "0.20%"),
        (1250.0, "₹1,250", "0.25%"),
        (1500.0, "₹1,500", "0.30%"),
        (1750.0, "₹1,750", "0.35%"),
        (2000.0, "₹2,000", "0.40%"),
        (2500.0, "₹2,500", "0.50%"),
        (3000.0, "₹3,000", "0.60%"),
        (3500.0, "₹3,500", "0.70%"),
        (4000.0, "₹4,000", "0.80%"),
        (5000.0, "₹5,000", "1.00%"),
        (7500.0, "₹7,500", "1.50%"),
        (10000.0, "₹10,000 (2.0%)", "2.00%")
    ]

    sweep_results = []
    detailed_sl_data = {}

    for sl_rs, sl_label, sl_pct_str in sl_configs:
        trades_sim = []
        for tr in cleaned_trades:
            sp = tr['sell_price']
            qty = tr['qty']

            # Target TP price
            tp_price = round(sp - (FIXED_TP / qty), 2)

            # SL price
            if sl_rs >= 10000.0:
                sl_price = round(sp * 1.02, 2) # exact 2%
            else:
                sl_price = round(sp + (sl_rs / qty), 2)

            exit_price = None
            exit_reason = None
            exit_time = None

            for tm, o, h, l, c in tr['candles']:
                # Conservative intra-bar collision:
                # If high touches SL and low touches TP in same minute, assume SL hit first
                hit_sl = (h >= sl_price)
                hit_tp = (l <= tp_price)

                if hit_sl and hit_tp:
                    # If open was closer to SL or adverse move
                    exit_price = sl_price
                    exit_reason = 'STOP_LOSS'
                    exit_time = tm
                    break
                elif hit_sl:
                    exit_price = sl_price
                    exit_reason = 'STOP_LOSS'
                    exit_time = tm
                    break
                elif hit_tp:
                    exit_price = tp_price
                    exit_reason = 'HIT_TP'
                    exit_time = tm
                    break

                # 09:40:00 time exit
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
        detailed_sl_data[sl_rs] = df_sim

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

        # Drawdown calculation
        df_sim['dt'] = pd.to_datetime(df_sim['date'])
        daily_pnl = df_sim.groupby('dt')['net_pnl'].sum()
        cum_pnl = daily_pnl.cumsum()
        peak = cum_pnl.cummax()
        dd = cum_pnl - peak
        max_dd = dd.min()

        # Recent 2024-2026 performance
        recent = df_sim[df_sim['year'] >= 2024]
        rec_pnl_lakhs = recent['net_pnl'].sum() / 100000.0
        rec_wr = (recent['net_pnl'] > 0).mean() * 100.0
        rec_tp_rate = (recent['exit_reason'] == 'HIT_TP').mean() * 100.0
        rec_sl_rate = (recent['exit_reason'] == 'STOP_LOSS').mean() * 100.0

        sweep_results.append({
            'SL_Bucket': sl_label,
            'SL_Pct_Move': sl_pct_str,
            'Risk_Reward_Ratio': f"1 : {(sl_rs / FIXED_TP):.2f}",
            'TP_Hit_Rate': tp_rate,
            'SL_Hit_Rate': sl_rate,
            'Time_Exit_Rate': time_rate,
            'Win_Rate': win_rate,
            'Total_Net_PnL_Lakhs': tot_pnl_lakhs,
            'Profit_Factor': profit_factor,
            'Max_Drawdown_Lakhs': max_dd / 100000.0,
            'Avg_Trade_Rs': avg_trade,
            '2024_2026_PnL_Lakhs': rec_pnl_lakhs,
            '2024_2026_TP_Rate': rec_tp_rate,
            '2024_2026_SL_Rate': rec_sl_rate,
            '2024_2026_Win_Rate': rec_wr
        })

    df_sweep = pd.DataFrame(sweep_results)
    print("\n" + "=" * 115)
    print("📊 STOP LOSS (SL) SWEEP RESULTS (FIXED TP = ₹1,500 | ₹5,00,000 CAPITAL PER STOCK)")
    print("=" * 115)
    print(df_sweep.to_string(index=False))

    summary_path = os.path.join(BASE_DIR, 'sl_optimization_sweep_tp1500_5L.csv')
    df_sweep.to_csv(summary_path, index=False)
    print(f"\n✔ Full SL sweep saved to: {summary_path}")

    # Year-by-year for selected SL targets: ₹1,500, ₹2,000, ₹2,500, ₹3,000, ₹4,000, ₹10,000
    print("\n" + "=" * 115)
    print("🔍 YEAR-BY-YEAR DETAILED AUDIT FOR KEY SL BUCKETS")
    print("=" * 115)
    key_sls = [1500.0, 2000.0, 2500.0, 3000.0, 4000.0, 10000.0]
    for ksl in key_sls:
        df_k = detailed_sl_data[ksl]
        label = "₹10,000 (2.0% Baseline)" if ksl >= 10000 else f"₹{int(ksl):,}"
        y_summary = df_k.groupby('year').agg(
            Trades=('net_pnl', 'count'),
            TP_Hit_Pct=('exit_reason', lambda s: f"{(s == 'HIT_TP').mean()*100:.1f}%"),
            SL_Hit_Pct=('exit_reason', lambda s: f"{(s == 'STOP_LOSS').mean()*100:.1f}%"),
            Win_Rate=('net_pnl', lambda s: f"{(s > 0).mean()*100:.1f}%"),
            Net_PnL_Lakhs=('net_pnl', lambda s: round(s.sum()/100000.0, 2))
        )
        print(f"\n--- SL Bucket: {label} (TP = ₹1,500) ---")
        print(y_summary.to_string())

if __name__ == '__main__':
    main()
