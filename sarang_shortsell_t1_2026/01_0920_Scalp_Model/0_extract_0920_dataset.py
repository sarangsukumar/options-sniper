#!/usr/bin/env python3
"""
0_extract_0920_dataset.py
=============================================================================
Extracts / Rebuilds scalp_0920_ml_dataset.csv.gz from MySQL `scrapdata`.

Key Properties:
  - 100% Pure MySQL Database Ticks (Zero lookahead bias)
  - Hardcoded Official 180+ NSE F&O Universe
  - Dual Mode:
      * Builds full historical dataset from 2015-01-01 to today if file absent.
      * Incrementally appends new trading days if dataset already exists.
  - Matches live_0920_scalp_pipeline.py feature formulas exactly:
      * morn_range_pct          : (high_0919 - low_0919) / (open_0915 + 1e-9)
      * rejection_wick          : (high_0919 - close_0919) / (high_0919 - low_0919 + 1e-9)
      * positive_arc_ratio      : pos_arcs / total_arcs (0 to 1 ratio)
      * Gap_Pct                 : ((open_0915 - prev_close) / prev_close) * 100.0
      * gap_0907_pct            : ((p_0907 - prev_close) / prev_close) * 100.0
      * prev_intraday_vwap_gap  : ((prev_close - prev_vwap) / prev_vwap) * 100.0
      * prev_intraday_roc_last_hour: ((prev_close - prev_1430) / prev_1430) * 100.0
      * prev_intraday_return    : ((prev_close - prev_open) / prev_open) * 100.0
=============================================================================
"""

import os
import sys
import pymysql
import numpy as np
import pandas as pd
from datetime import datetime
import warnings

warnings.filterwarnings('ignore')

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_FILE   = os.path.join(SCRIPT_DIR, 'data', 'scalp_0920_ml_dataset.csv.gz')
LIVE_OUT_FILE = os.path.join(SCRIPT_DIR, 'live_production', 'data', 'scalp_0920_ml_dataset.csv.gz')
os.makedirs(os.path.join(SCRIPT_DIR, 'data'), exist_ok=True)
os.makedirs(os.path.join(SCRIPT_DIR, 'live_production', 'data'), exist_ok=True)

# Dynamic historical F&O Universe to eliminate Survivorship Bias
LOTSIZE_FILE = '/home/ubuntu/intraday_simulation/historical_lotsize_new.csv'
print(f"Loading historical F&O universe from {LOTSIZE_FILE}...")
df_fo = pd.read_csv(LOTSIZE_FILE)
df_fo['expdate'] = pd.to_datetime(df_fo['expdate'], format='%d/%m/%Y')
df_fo['exp_period'] = df_fo['expdate'].dt.to_period('M')

def get_active_fo_stocks(target_date_str):
    target_period = pd.to_datetime(target_date_str).to_period('M')
    active_stocks = df_fo[df_fo['exp_period'] == target_period]['stockname'].unique()
    return set([str(s).strip().upper() for s in active_stocks])

def get_conn():
    return pymysql.connect(
        host='localhost', user='root', password='root',
        database='markets', cursorclass=pymysql.cursors.DictCursor
    )

def calc_arc_features(prices):
    if len(prices) < 3:
        return 0.0
    p = np.array(prices)
    norm_p = (p - p[0]) / (p[0] + 1e-9)
    changes = np.diff(norm_p)
    pos_arcs = np.sum(changes > 0)
    total_arcs = len(changes)
    return float(pos_arcs / total_arcs) if total_arcs > 0 else 0.0

def get_kotak_charges(qty, sell_price, buy_price):
    turnover = (qty * sell_price) + (qty * buy_price)
    stt      = round(qty * sell_price * 0.00025)
    txn      = turnover * 0.0000322
    sebi     = turnover * 0.000001
    stamp    = round(qty * buy_price * 0.00003)
    gst      = (40.0 + txn + sebi) * 0.18
    return round(40.0 + stt + txn + sebi + stamp + gst, 2)

def extract_features():
    print("=" * 80)
    print("🚀 EXTRACTING / UPDATING 09:20 DATASET FROM PURE MYSQL scrapdata")
    print("=" * 80)

    existing_df = None
    last_date = '2015-01-01'
    if os.path.exists(OUT_FILE):
        try:
            existing_df = pd.read_csv(OUT_FILE, low_memory=False)
            last_date = str(existing_df['short_date'].max())
            print(f"   • Existing dataset loaded: {len(existing_df):,} rows (up to {last_date})")
        except Exception as e:
            print(f"   ⚠️ Could not read existing dataset ({e}), building from scratch.")

    conn = get_conn()
    cur = conn.cursor()

    # Query all available dates from MySQL
    cur.execute("SELECT DISTINCT date FROM scrapdata WHERE date >= '2022-01-01' ORDER BY date ASC")
    all_dates = [str(r['date']) for r in cur.fetchall()]

    if existing_df is not None:
        target_dates = [d for d in all_dates if d > last_date]
        if not target_dates:
            print(f"   ✅ Dataset is already up to date! (Last date: {last_date})")
            conn.close()
            return
        print(f"   • Found {len(target_dates)} new dates to extract ({target_dates[0]} to {target_dates[-1]}).")
    else:
        target_dates = all_dates
        print(f"   • Extracting full historical dataset: {len(target_dates)} trading sessions (2015-present).")

    records = []
    prev_day_dict = {}

    for idx, target_date in enumerate(target_dates):
        # Fetch previous day date
        cur.execute(f"SELECT MAX(date) as pd FROM scrapdata WHERE date < '{target_date}'")
        row = cur.fetchone()
        prev_date = str(row['pd']) if row and row['pd'] else None
        if not prev_date:
            continue

        # Fetch prev day ticks (for VWAP and overnight features)
        cur.execute(f"""
            SELECT stockname, time, price, volume FROM scrapdata
            WHERE date = '{prev_date}'
              AND TIME(time) >= '09:15:00' AND TIME(time) <= '15:30:00'
            ORDER BY stockname, time ASC
        """)
        prev_rows = cur.fetchall()

        # Fetch today's morning ticks (09:07 - 09:19)
        cur.execute(f"""
            SELECT stockname, time, price FROM scrapdata
            WHERE date = '{target_date}'
              AND TIME(time) >= '09:07:00' AND TIME(time) <= '09:19:59'
            ORDER BY stockname, time ASC
        """)
        morn_rows = cur.fetchall()

        # Fetch today's ticks for execution PnL (09:21 - 09:41)
        cur.execute(f"""
            SELECT stockname, time, price FROM scrapdata
            WHERE date = '{target_date}'
              AND TIME(time) >= '09:21:00' AND TIME(time) <= '09:40:59'
            ORDER BY stockname, time ASC
        """)
        pnl_rows = cur.fetchall()

        # Group ticks by stock
        pday = {}
        for r in prev_rows:
            stk = r['stockname'].strip().upper()
            if stk not in pday: pday[stk] = []
            pday[stk].append(r)

        today_morn = {}
        for r in morn_rows:
            stk = r['stockname'].strip().upper()
            if stk not in today_morn: today_morn[stk] = []
            today_morn[stk].append(r)

        today_pnl = {}
        for r in pnl_rows:
            stk = r['stockname'].strip().upper()
            if stk not in today_pnl: today_pnl[stk] = []
            today_pnl[stk].append(r)

        active_stocks = get_active_fo_stocks(target_date)
        for stock in active_stocks:
            if stock not in today_morn or stock not in pday or stock not in today_pnl:
                continue

            pticks = pday[stock]
            if len(pticks) < 10:
                continue

            p_prices = [float(x['price']) for x in pticks]
            p_vols   = [float(x['volume']) if x.get('volume') is not None else 1.0 for x in pticks]
            p_times  = [str(x['time']).split()[-1] for x in pticks]

            p_open  = p_prices[0]
            p_close = p_prices[-1]

            cum_pv = sum(p * v for p, v in zip(p_prices, p_vols))
            cum_v  = sum(p_vols)
            vwap   = cum_pv / cum_v if cum_v > 0 else p_close
            prev_intraday_vwap_gap = ((p_close - vwap) / vwap) * 100.0

            lh_prices = [p for t, p in zip(p_times, p_prices) if t >= '14:30:00']
            p_1430 = lh_prices[0] if lh_prices else p_close
            prev_intraday_roc_last_hour = ((p_close - p_1430) / p_1430) * 100.0
            prev_intraday_return = ((p_close - p_open) / p_open) * 100.0

            # Morning ticks
            mticks = today_morn[stock]
            p_0907_ticks = [float(x['price']) for x in mticks if str(x['time']).split()[-1] < '09:15:00']
            morn_15_19   = [x for x in mticks if str(x['time']).split()[-1] >= '09:15:00']
            if not morn_15_19:
                continue

            p_0915_ticks = [float(x['price']) for x in morn_15_19]
            open_0915  = p_0915_ticks[0]
            close_0919 = p_0915_ticks[-1]
            high_0919  = max(p_0915_ticks)
            low_0919   = min(p_0915_ticks)

            Gap_Pct = ((open_0915 - p_close) / p_close) * 100.0
            gap_0907_pct = ((p_0907_ticks[0] - p_close) / p_close) * 100.0 if p_0907_ticks else Gap_Pct

            morn_range_pct = (high_0919 - low_0919) / (open_0915 + 1e-9)
            rejection_wick = (high_0919 - close_0919) / (high_0919 - low_0919 + 1e-9)
            pos_arc_ratio  = calc_arc_features(p_0915_ticks)

            # PnL simulation (entry 09:21, exit 09:41)
            pnl_ticks = today_pnl[stock]
            if not pnl_ticks:
                continue

            entry_price = float(pnl_ticks[0]['price'])
            if entry_price < 50:
                continue

            sl_price = entry_price * 1.03
            exit_price = 0
            qty = int(500000.0 / entry_price)

            for t in pnl_ticks:
                p = float(t['price'])
                if p >= sl_price:
                    exit_price = sl_price
                    break

            if exit_price == 0:
                exit_price = float(pnl_ticks[-1]['price'])

            charges = get_kotak_charges(qty, entry_price, exit_price)
            pnl_net = ((entry_price - exit_price) * qty) - charges

            records.append({
                'short_date'                 : target_date,
                'clean_stock'                : stock,
                'morn_range_pct'             : round(morn_range_pct, 8),
                'pnl_net'                    : round(pnl_net, 2),
                'prev_intraday_vwap_gap'     : round(prev_intraday_vwap_gap, 6),
                'prev_intraday_roc_last_hour' : round(prev_intraday_roc_last_hour, 6),
                'prev_intraday_return'       : round(prev_intraday_return, 6),
                'positive_arc_ratio'         : round(pos_arc_ratio, 6),
                'Gap_Pct'                    : round(Gap_Pct, 6),
                'gap_0907_pct'               : round(gap_0907_pct, 6),
                'rejection_wick'             : round(rejection_wick, 8),
                'entry_price'                : round(entry_price, 2),
                'exit_price'                 : round(exit_price, 2)
            })

        if (idx + 1) % 25 == 0 or idx == len(target_dates) - 1:
            print(f"   • Extracted [{idx+1}/{len(target_dates)}] sessions ({len(records)} rows)...")

    conn.close()

    new_df = pd.DataFrame(records)
    if existing_df is not None:
        combined = pd.concat([existing_df, new_df], ignore_index=True)
    else:
        combined = new_df

    combined = combined.drop_duplicates(subset=['short_date', 'clean_stock'])
    combined.to_csv(OUT_FILE, index=False, compression='gzip')
    combined.to_csv(LIVE_OUT_FILE, index=False, compression='gzip')
    print(f"✅ Success! Updated dataset: {len(combined):,} total rows saved to {OUT_FILE} and {LIVE_OUT_FILE}")

if __name__ == '__main__':
    extract_features()
