#!/usr/bin/env python3
"""
experiment_trailing_tp_5L.py
========================================================================================
EXPERIMENT: TRAILING TAKE-PROFIT (TP) & PEAK-PROFIT LOCK ON 09:20 SHORT-SELL SCALP
WITH REALISTIC ₹5,00,000 CAPITAL PER STOCK & EXACT LIMIT-ENTRY TRADES
========================================================================================
Core Idea:
When a trade reaches ₹1,000 in profit:
  - If profit is increasing (making new peaks), we hold to let it run.
  - If profit pulls back from peak or drops back towards ₹1,000, we exit to protect gains.
  - We test various trailing buffers and step-locks vs. the fixed ₹1,500 TP baseline.
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
    print("=" * 105)
    print("🚀 09:20 SCALP TRAILING TAKE-PROFIT (TP) & PEAK-LOCK EXPERIMENT")
    print("   Capital: ₹5,00,000 per Stock | Base SL: ₹3,000 (0.60%) | 2020-2026 Audited Trades")
    print("=" * 105)

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

    print(f"   ✔ Prepared {len(cleaned_trades):,} valid trades.")

    # Strategy Configurations to Compare:
    # 0. Baseline: Fixed ₹1,500 TP, ₹3,000 SL
    # 1. Trail A: Activate at ₹1,000, Trail ₹250 from peak, Min Lock ₹750, Hard Cap ₹1,500
    # 2. Trail B: Activate at ₹1,000, Trail ₹200 from peak, Min Lock ₹800, Hard Cap ₹1,750
    # 3. Trail C: Activate at ₹1,000, Trail ₹300 from peak, Min Lock ₹700, Let Runner run to ₹2,000
    # 4. Trail D (Step-Lock): 
    #      Reach ₹1,000 -> SL moves to BE + ₹500
    #      Reach ₹1,250 -> SL moves to ₹1,000
    #      Reach ₹1,500 -> Take Profit
    # 5. Trail E (Reversal Candle Exit):
    #      Once profit >= ₹1,000, if a candle closes green (close > open) or price rises by ₹200, exit immediately!

    def simulate_strategy(strategy_type, p_params):
        results = []
        for tr in cleaned_trades:
            sp = tr['sell_price']
            qty = tr['qty']
            sl_price = round(sp + (3000.0 / qty), 2) # Base ₹3,000 SL

            exit_price = None
            exit_reason = None
            exit_time = None

            peak_profit_rs = 0.0
            trail_active = False
            dynamic_sl_price = sl_price

            for idx, (tm, o, h, l, c) in enumerate(tr['candles']):
                # Current max profit reached in this candle
                candle_max_profit = (sp - l) * qty
                candle_open_profit = (sp - o) * qty
                candle_close_profit = (sp - c) * qty

                # Update peak profit
                if candle_max_profit > peak_profit_rs:
                    peak_profit_rs = candle_max_profit

                # ── Base SL Check ──
                if h >= dynamic_sl_price:
                    exit_price = dynamic_sl_price
                    exit_reason = 'STOP_LOSS' if dynamic_sl_price == sl_price else 'TRAIL_STOP_HIT'
                    exit_time = tm
                    break

                # ── STRATEGY LOGIC ──
                if strategy_type == 'FIXED_1500':
                    tp_price = round(sp - (1500.0 / qty), 2)
                    if l <= tp_price:
                        exit_price = tp_price
                        exit_reason = 'FIXED_TP_HIT'
                        exit_time = tm
                        break

                elif strategy_type in ('TRAIL_PEAK', 'TRAIL_RUNNER'):
                    act_thresh = p_params['activate']
                    trail_buf = p_params['trail_buf']
                    min_lock = p_params['min_lock']
                    hard_cap = p_params.get('hard_cap', 999999)

                    # Check hard cap first
                    if hard_cap and candle_max_profit >= hard_cap:
                        exit_price = round(sp - (hard_cap / qty), 2)
                        exit_reason = 'HARD_CAP_HIT'
                        exit_time = tm
                        break

                    # Check activation
                    if peak_profit_rs >= act_thresh:
                        trail_active = True
                        target_trail_pnl = max(min_lock, peak_profit_rs - trail_buf)
                        trail_exit_p = round(sp - (target_trail_pnl / qty), 2)
                        # Dynamic SL cannot be worse than original SL
                        if trail_exit_p < dynamic_sl_price:
                            dynamic_sl_price = trail_exit_p

                        # If candle high touches or crosses our trailing stop price
                        if h >= dynamic_sl_price:
                            exit_price = dynamic_sl_price
                            exit_reason = 'TRAIL_PROFIT_LOCK'
                            exit_time = tm
                            break

                elif strategy_type == 'STEP_LOCK':
                    # Milestone locks
                    if peak_profit_rs >= 1500.0:
                        exit_price = round(sp - (1500.0 / qty), 2)
                        exit_reason = 'STEP_TP_1500'
                        exit_time = tm
                        break
                    elif peak_profit_rs >= 1250.0:
                        lock_p = round(sp - (1000.0 / qty), 2)
                        if lock_p < dynamic_sl_price: dynamic_sl_price = lock_p
                    elif peak_profit_rs >= 1000.0:
                        lock_p = round(sp - (500.0 / qty), 2)
                        if lock_p < dynamic_sl_price: dynamic_sl_price = lock_p

                    if h >= dynamic_sl_price:
                        exit_price = dynamic_sl_price
                        exit_reason = 'STEP_LOCK_HIT'
                        exit_time = tm
                        break

                elif strategy_type == 'REVERSAL_EXIT':
                    # If profit was >= 1000, and this candle closes green (c > o) or pulls back
                    if peak_profit_rs >= 1000.0:
                        if candle_max_profit >= 1500.0:
                            exit_price = round(sp - (1500.0 / qty), 2)
                            exit_reason = 'HARD_TP_1500'
                            exit_time = tm
                            break
                        # Check candle reversal (bullish candle during short)
                        if c > o and candle_close_profit < peak_profit_rs - 200.0:
                            exit_price = c
                            exit_reason = 'REVERSAL_EXIT'
                            exit_time = tm
                            break

                # ── 09:40:00 Time Exit ──
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
            results.append({
                'date': tr['date'],
                'year': tr['year'],
                'stock': tr['stock'],
                'net_pnl': net_pnl,
                'exit_reason': exit_reason,
                'is_win': 1 if net_pnl > 0 else 0
            })
        return pd.DataFrame(results)

    test_models = [
        ('Baseline: Fixed ₹1500 TP (No Trail)', 'FIXED_1500', {}),
        ('Model 1: Act ₹1000 -> Trail ₹250, MinLock ₹750, Cap ₹1500', 'TRAIL_PEAK', {'activate': 1000.0, 'trail_buf': 250.0, 'min_lock': 750.0, 'hard_cap': 1500.0}),
        ('Model 2: Act ₹1000 -> Trail ₹200, MinLock ₹800, Cap ₹1750', 'TRAIL_PEAK', {'activate': 1000.0, 'trail_buf': 200.0, 'min_lock': 800.0, 'hard_cap': 1750.0}),
        ('Model 3: Act ₹1000 -> Trail ₹300, MinLock ₹700, Runner to ₹2000', 'TRAIL_RUNNER', {'activate': 1000.0, 'trail_buf': 300.0, 'min_lock': 700.0, 'hard_cap': 2000.0}),
        ('Model 4: Step-Lock (₹1000->Lock ₹500, ₹1250->Lock ₹1000, TP ₹1500)', 'STEP_LOCK', {}),
        ('Model 5: Act ₹1000 -> Reversal Candle Exit (or Cap ₹1500)', 'REVERSAL_EXIT', {})
    ]

    summary_list = []
    for name, m_type, params in test_models:
        df_res = simulate_strategy(m_type, params)
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

        # Recent 2024-2026
        recent = df_res[df_res['year'] >= 2024]
        rec_pnl = recent['net_pnl'].sum() / 1e5
        rec_wr = (recent['net_pnl'] > 0).mean() * 100.0

        # Profit exit count (either TP or Trail lock)
        exit_counts = df_res['exit_reason'].value_counts()
        sl_count = exit_counts.get('STOP_LOSS', 0)
        time_count = exit_counts.get('TIME_EXIT', 0)
        profit_exit_rate = ((n - sl_count - time_count) / n) * 100.0

        summary_list.append({
            'Model': name,
            'Win_Rate': f"{wr:.2f}%",
            'Profit_Exit_Rate': f"{profit_exit_rate:.2f}%",
            'Time_Exit_Rate': f"{(time_count/n)*100:.2f}%",
            'SL_Rate': f"{(sl_count/n)*100:.2f}%",
            'Total_Net_PnL_Lakhs': round(tot_pnl / 1e5, 2),
            'Profit_Factor': round(pf, 2),
            'Max_DD_Lakhs': round(max_dd / 1e5, 2),
            'Avg_Trade_Rs': round(avg_trade, 1),
            '2024_2026_PnL_Lakhs': round(rec_pnl, 2),
            '2024_2026_Win_Rate': f"{rec_wr:.2f}%"
        })

    df_summary = pd.DataFrame(summary_list)
    print("\n" + "=" * 125)
    print("📊 TRAILING TP / PROFIT LOCK STRATEGIES COMPARISON (₹5,00,000 CAPITAL)")
    print("=" * 125)
    print(df_summary.to_string(index=False))

    summary_file = os.path.join(BASE_DIR, 'trailing_tp_experiment_5L.csv')
    df_summary.to_csv(summary_file, index=False)
    print(f"\n✔ Trailing experiment saved to: {summary_file}")

if __name__ == '__main__':
    main()
