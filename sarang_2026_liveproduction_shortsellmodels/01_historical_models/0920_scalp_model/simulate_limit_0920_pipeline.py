#!/usr/bin/env python3
"""
simulate_limit_0920_pipeline.py
========================================================================================
REALISTIC LIMIT BUY & LIMIT SELL SIMULATION FOR 09:20 SHORT-SELL PIPELINE (2020-2026)
========================================================================================
Architecture & Matching Rules:
1. Movement Analysis (09:20 to 09:24):
   - Examines open and close prices from 09:20:00 to 09:24:59.
   - Categorizes price action into 5 regimes:
       • CRASHING   : Move <= -0.25% (sharp downward dump)
       • GOING_DOWN : -0.25% < Move <= -0.05% (mild downward drift)
       • NEUTRAL    : -0.05% < Move < +0.05% (flat / stationary)
       • GOING_UP   : +0.05% <= Move < +0.25% (mild upward drift)
       • CLIMBING   : Move >= +0.25% (strong upward surge)

2. Adaptive Limit Sell Price Setting at 09:24:
   - Base Price = 09:24:00 bar Close (or Open if Close is unavailable).
   - Tick Offset (NSE Equity tick = ₹0.05):
       • CRASHING   : Base - 2 ticks (-₹0.10) to secure execution as stock dumps.
       • GOING_DOWN : Base - 1 tick (-₹0.05).
       • NEUTRAL    : Base (0 offset).
       • GOING_UP   : Base + 1 tick (+₹0.05) to capture upward drift.
       • CLIMBING   : Base + 2 ticks (+₹0.10) to short at the crest of the climb.

3. Limit Entry Matching (09:25:00 to 09:30:59):
   - Checked minute-by-minute across open, close, and high:
       a) If minute open >= limit_sell_price: Fill at minute open (price improvement).
       b) Else if minute close >= limit_sell_price: Fill at minute close.
       c) Else if minute high >= limit_sell_price: Fill at set limit_sell_price (NOT high).
   - If not filled by 09:30:59: Order is cancelled (UNFILLED / skipped).

4. Realistic Limit Exit Matching (₹500 Profit Lock & SL):
   - Capital: Flat ₹10,00,000 per stock (Qty = int(1,000,000 / entry_price)).
   - Friction: Flat ₹40 brokerage + STT + Txn + SEBI + Stamp + GST (~₹405/trade).
   - Hard Stop Loss: 2.0% above entry price (fill at SL price if high >= SL).
   - At 09:35:00 bar close:
       • Calculates exact buyback limit price required for >= ₹500 Net Profit.
       • Sets Limit Buy order at target price.
   - Scalp Window (09:36:00 to 09:39:59):
       a) If minute open <= limit_buy_price: Fill at minute open.
       b) Else if minute close <= limit_buy_price: Fill at minute close.
       c) Else if minute low <= limit_buy_price: Fill at set limit_buy_price (NOT low).
   - If neither SL nor ₹500 limit exit filled by 09:40:00:
       • Market square-off at 09:40:00 bar open/price (HARD_EXIT_0940).
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
CANDIDATE_FILE = os.path.join(BASE_DIR, 'walkforward_0920_trades_10L_2020_2026.csv')
OUT_FILE = os.path.join(BASE_DIR, 'limit_sim_0920_trades_10L.csv')

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
    conn = get_db_conn()
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT time, open, high, low, close, price FROM scrapdata "
            f"WHERE date='{d}' AND stockname='{s}' AND time >= '{d} 09:20:00' AND time <= '{d} 09:41:00' "
            f"ORDER BY time ASC"
        )
        ticks = cur.fetchall()
    conn.close()
    return {'meta': row, 'ticks': ticks}

def classify_movement(ticks_0920_0924):
    """
    Classifies 09:20 - 09:24 movement into 5 regimes:
    CRASHING, GOING_DOWN, NEUTRAL, GOING_UP, CLIMBING
    """
    if not ticks_0920_0924:
        return 'NEUTRAL', 0.0, 0.0, 0.0

    p_start = float(ticks_0920_0924[0]['open'] or ticks_0920_0924[0]['price'] or 0)
    p_end = float(ticks_0920_0924[-1]['close'] or ticks_0920_0924[-1]['price'] or p_start)
    p_0924_open = float(ticks_0920_0924[-1]['open'] or ticks_0920_0924[-1]['price'] or p_end)

    if p_start <= 0:
        return 'NEUTRAL', 0.0, p_end, p_0924_open

    pct_move = ((p_end - p_start) / p_start) * 100.0

    if pct_move <= -0.25:
        regime = 'CRASHING'
    elif pct_move <= -0.05:
        regime = 'GOING_DOWN'
    elif pct_move < 0.05:
        regime = 'NEUTRAL'
    elif pct_move < 0.25:
        regime = 'GOING_UP'
    else:
        regime = 'CLIMBING'

    return regime, pct_move, p_end, p_0924_open

def simulate_limit_trade(data):
    meta = data['meta']
    ticks = data['ticks']
    d = meta['date']
    s = meta['stock']

    if not ticks:
        return {'status': 'NO_DATA', 'date': d, 'stock': s}

    # 1. Filter 09:20:00 - 09:24:59 bars
    bars_pre = [t for t in ticks if f"{d} 09:20:00" <= str(t['time']) <= f"{d} 09:24:59"]
    if not bars_pre:
        bars_pre = [t for t in ticks if str(t['time']) < f"{d} 09:25:00"]
    if not bars_pre:
        return {'status': 'NO_PRE_TICKS', 'date': d, 'stock': s}

    regime, pct_move, p_0924_close, p_0924_open = classify_movement(bars_pre)

    # 2. Adaptive Limit Sell Price
    # Standard NSE equity tick = 0.05
    base_price = p_0924_close if p_0924_close > 0 else p_0924_open
    if base_price <= 0:
        return {'status': 'INVALID_BASE_PRICE', 'date': d, 'stock': s}

    tick_unit = 0.05
    if regime == 'CRASHING':
        limit_sell = round(base_price - 2 * tick_unit, 2)
    elif regime == 'GOING_DOWN':
        limit_sell = round(base_price - 1 * tick_unit, 2)
    elif regime == 'NEUTRAL':
        limit_sell = round(base_price, 2)
    elif regime == 'GOING_UP':
        limit_sell = round(base_price + 1 * tick_unit, 2)
    else: # CLIMBING
        limit_sell = round(base_price + 2 * tick_unit, 2)

    # 3. Limit Entry Matching (09:25:00 to 09:30:59)
    entry_filled = False
    sell_price = None
    sell_time = None
    entry_fill_type = None
    entry_idx = None

    for idx, t in enumerate(ticks):
        tm = str(t['time'])
        if tm < f"{d} 09:25:00":
            continue
        if tm > f"{d} 09:30:59":
            break

        o = float(t['open'] or t['price'] or 0)
        c = float(t['close'] or t['price'] or 0)
        h = float(t['high'] or max(o, c))

        if o >= limit_sell:
            sell_price = o
            sell_time = tm
            entry_fill_type = 'OPEN_GE_LIMIT'
            entry_filled = True
            entry_idx = idx
            break
        elif c >= limit_sell:
            sell_price = c
            sell_time = tm
            entry_fill_type = 'CLOSE_GE_LIMIT'
            entry_filled = True
            entry_idx = idx
            break
        elif h >= limit_sell:
            sell_price = limit_sell
            sell_time = tm
            entry_fill_type = 'HIGH_TOUCH_LIMIT'
            entry_filled = True
            entry_idx = idx
            break

    if not entry_filled:
        return {
            'status': 'UNFILLED',
            'date': d,
            'stock': s,
            'rank': int(meta['rank']),
            'prob': float(meta['prob']),
            'regime': regime,
            'pct_move_0920_0924': round(pct_move, 3),
            'p_0924_close': base_price,
            'limit_sell_price': limit_sell
        }

    # 4. Position Sizing
    qty = int(1000000.0 / sell_price)
    if qty <= 0:
        return {'status': 'ZERO_QTY', 'date': d, 'stock': s}

    sl_price = round(sell_price * 1.02, 2) # 2.0% Stop Loss

    # 5. Exit Matching
    buy_price = None
    buy_time = None
    exit_reason = None
    limit_buy_price = None

    subsequent_ticks = ticks[entry_idx:]

    for t in subsequent_ticks:
        tm = str(t['time'])
        if tm < sell_time:
            continue

        o = float(t['open'] or t['price'] or 0)
        c = float(t['close'] or t['price'] or 0)
        h = float(t['high'] or max(o, c))
        l = float(t['low'] or min(o, c))

        # Check Hard Stop Loss first
        if h >= sl_price:
            buy_price = sl_price
            buy_time = tm
            exit_reason = 'SL_2PCT'
            break

        # At 09:35:00 bar, compute limit buyback price for ₹500 Net Profit
        if tm[:16] == f"{d} 09:35":
            # Solve buy_price for net_pnl >= 500
            # Approx taxes = ~405 => required gross profit = 500 + 405 = 905
            # Target = sell_price - (905 / qty)
            est_tax = 405.0
            target_p = sell_price - ((500.0 + est_tax) / qty)
            limit_buy_price = round(target_p, 2)

        # Scalp Window (09:36:00 to 09:39:59): Match Limit Buy
        if f"{d} 09:36:00" <= tm <= f"{d} 09:39:59":
            if limit_buy_price is not None and limit_buy_price > 0:
                if o <= limit_buy_price:
                    buy_price = o
                    buy_time = tm
                    exit_reason = 'PROFIT_LIMIT_OPEN'
                    break
                elif c <= limit_buy_price:
                    buy_price = c
                    buy_time = tm
                    exit_reason = 'PROFIT_LIMIT_CLOSE'
                    break
                elif l <= limit_buy_price:
                    buy_price = limit_buy_price
                    buy_time = tm
                    exit_reason = 'PROFIT_LIMIT_TOUCH'
                    break

        # Hard Market Square-off at 09:40:00
        if tm >= f"{d} 09:40:00":
            buy_price = o if o > 0 else (float(t['price']) if t.get('price') else c)
            buy_time = tm
            exit_reason = 'HARD_EXIT_0940'
            break

    if not buy_price:
        buy_price = float(subsequent_ticks[-1]['close'] or subsequent_ticks[-1]['price'] or sell_price)
        buy_time = str(subsequent_ticks[-1]['time'])
        exit_reason = 'LAST_TICK_FALLBACK'

    comm = get_kotak_charges(qty, sell_price, buy_price)
    net_pnl = round(((sell_price - buy_price) * qty) - comm, 2)

    return {
        'status': 'FILLED',
        'date': d,
        'stock': s,
        'rank': int(meta['rank']),
        'prob': float(meta['prob']),
        'regime': regime,
        'pct_move_0920_0924': round(pct_move, 3),
        'p_0924_close': base_price,
        'limit_sell_price': limit_sell,
        'sell_time': sell_time,
        'sell_price': sell_price,
        'entry_fill_type': entry_fill_type,
        'limit_buy_price': limit_buy_price,
        'buy_time': buy_time,
        'buy_price': buy_price,
        'exit_reason': exit_reason,
        'qty': qty,
        'margin_req': 1000000,
        'commission': comm,
        'net_pnl': net_pnl
    }

def main():
    print("=" * 85)
    print("🚀 09:20 SHORT-SELL PIPELINE: REALISTIC LIMIT BUY & LIMIT SELL SIMULATION")
    print("   Period: 2020-01-01 to 2026-10-16 | Capital: ₹10,00,000 | Flat ₹40 Brokerage")
    print("=" * 85)

    df_cand = pd.read_csv(CANDIDATE_FILE)
    print(f"\n1. Loaded {len(df_cand):,} historical candidate trades across {df_cand['date'].nunique()} trading days.")

    t0 = time.time()
    rows = [r.to_dict() for _, r in df_cand.iterrows()]

    print("2. Fetching MySQL scrapdata ticks and executing limit matching engine (16 threads)...")
    with ThreadPoolExecutor(max_workers=16) as executor:
        tick_data_list = list(executor.map(fetch_trade_ticks, rows))

    fetch_time = time.time() - t0
    print(f"   ✔ Ticks fetched in {fetch_time:.1f}s. Simulating limit entries and exits...")

    sim_results = [simulate_limit_trade(td) for td in tick_data_list]

    filled = [r for r in sim_results if r.get('status') == 'FILLED']
    unfilled = [r for r in sim_results if r.get('status') == 'UNFILLED']
    no_data = [r for r in sim_results if r.get('status') not in ('FILLED', 'UNFILLED')]

    df_filled = pd.DataFrame(filled)
    df_filled.to_csv(OUT_FILE, index=False)
    print(f"   ✔ Saved filled trades ledger to: {OUT_FILE}")

    print("\n" + "=" * 85)
    print("📊 1. LIMIT ORDER FILL RATE & EXECUTION EFFICIENCY")
    print("=" * 85)
    print(f"Total Signals Evaluated     : {len(df_cand):,}")
    print(f"Successfully Filled Trades  : {len(filled):,} ({len(filled)/len(df_cand):.2%})")
    print(f"Unfilled / Order Expired    : {len(unfilled):,} ({len(unfilled)/len(df_cand):.2%})")
    if no_data:
        print(f"Missing / Irregular Data    : {len(no_data):,}")

    print("\nFill Rate Breakdown by 09:20-09:24 Market Regime:")
    df_all_status = pd.DataFrame(sim_results)
    reg_summary = df_all_status.groupby('regime').agg(
        Total=('status', 'count'),
        Filled=('status', lambda s: (s == 'FILLED').sum()),
        Fill_Rate=('status', lambda s: f"{(s == 'FILLED').mean():.2%}")
    )
    print(reg_summary.to_string())

    print("\nEntry Fill Mechanism Breakdown:")
    fill_types = df_filled['entry_fill_type'].value_counts()
    for ft, count in fill_types.items():
        print(f"   • {ft:<20}: {count:,} ({count/len(df_filled):.2%})")

    print("\n" + "=" * 85)
    print("🏆 2. PERFORMANCE SCORECARD: REALISTIC LIMIT EXECUTION MODEL")
    print("=" * 85)
    total_pnl = df_filled['net_pnl'].sum()
    wins = (df_filled['net_pnl'] > 0).sum()
    losses = (df_filled['net_pnl'] <= 0).sum()
    win_rate = wins / len(df_filled)
    gross_win = df_filled[df_filled['net_pnl'] > 0]['net_pnl'].sum()
    gross_loss = abs(df_filled[df_filled['net_pnl'] <= 0]['net_pnl'].sum())
    profit_factor = gross_win / gross_loss if gross_loss > 0 else 999.0

    # Max Drawdown & Sharpe
    df_filled['date'] = pd.to_datetime(df_filled['date'])
    cum_pnl = df_filled['net_pnl'].cumsum()
    peak = cum_pnl.cummax()
    dd = cum_pnl - peak
    max_dd = dd.min()

    daily_pnl = df_filled.groupby('date')['net_pnl'].sum()
    sharpe = (daily_pnl.mean() / daily_pnl.std()) * np.sqrt(252) if daily_pnl.std() > 0 else 0.0

    print(f"Total Filled Trades         : {len(df_filled):,}")
    print(f"Total Net Realized PnL      : 💰 +₹{total_pnl:,.2f} (+₹{total_pnl/100000:.2f} Lakhs / +₹{total_pnl/10000000:.3f} Crores)")
    print(f"Win Rate                    : {win_rate:.2%} ({wins:,} wins / {losses:,} losses)")
    print(f"Profit Factor               : {profit_factor:.2f}")
    print(f"Annualized Sharpe Ratio     : {sharpe:.2f}")
    print(f"Maximum Drawdown            : ₹{max_dd:,.2f} (₹{max_dd/100000:.2f} Lakhs)")
    print(f"Average Profit / Trade      : ₹{df_filled['net_pnl'].mean():,.2f}")

    print("\n" + "=" * 85)
    print("📅 3. YEAR-BY-YEAR AUDIT BREAKDOWN (2020 - 2026)")
    print("=" * 85)
    df_filled['year'] = df_filled['date'].dt.year
    yearly = df_filled.groupby('year').agg(
        Filled_Trades=('net_pnl', 'count'),
        Win_Rate=('net_pnl', lambda s: f"{(s > 0).mean():.2%}"),
        Gross_Profit=('net_pnl', lambda s: round(s[s > 0].sum(), 2)),
        Gross_Loss=('net_pnl', lambda s: round(s[s <= 0].sum(), 2)),
        Net_PnL_Rs=('net_pnl', lambda s: round(s.sum(), 2)),
        Net_PnL_Lakhs=('net_pnl', lambda s: round(s.sum() / 1e5, 2))
    )
    print(yearly.to_string())

    print("\n" + "=" * 85)
    print("🚪 4. EXIT REASON BREAKDOWN")
    print("=" * 85)
    exit_summary = df_filled.groupby('exit_reason').agg(
        Trades=('net_pnl', 'count'),
        Share=('net_pnl', lambda s: f"{len(s)/len(df_filled):.2%}"),
        Win_Rate=('net_pnl', lambda s: f"{(s > 0).mean():.2%}"),
        Avg_PnL=('net_pnl', lambda s: round(s.mean(), 2)),
        Total_Net_PnL=('net_pnl', lambda s: round(s.sum(), 2))
    )
    print(exit_summary.to_string())

    # October 2026 Performance
    oct_df = df_filled[df_filled['date'] >= '2026-10-01']
    print("\n" + "=" * 85)
    print("🔍 5. OCTOBER 2026 PERFORMANCE UNDER LIMIT EXECUTION")
    print("=" * 85)
    oct_pnl = oct_df['net_pnl'].sum()
    oct_wr = (oct_df['net_pnl'] > 0).mean()
    print(f"October 2026 Filled Trades  : {len(oct_df)}")
    print(f"October 2026 Net PnL        : ₹{oct_pnl:,.2f} ({oct_pnl/1e5:.2f} Lakhs)")
    print(f"October 2026 Win Rate       : {oct_wr:.2%}")
    daily_oct = oct_df.groupby(oct_df['date'].dt.strftime('%Y-%m-%d')).agg(
        Trades=('net_pnl', 'count'),
        Net_PnL=('net_pnl', 'sum'),
        Win_Rate=('net_pnl', lambda s: f"{(s > 0).mean():.2%}")
    )
    print(daily_oct.to_string())

if __name__ == '__main__':
    main()
