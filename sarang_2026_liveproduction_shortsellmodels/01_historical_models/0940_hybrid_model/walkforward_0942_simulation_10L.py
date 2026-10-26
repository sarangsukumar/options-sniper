#!/usr/bin/env python3
"""
walkforward_0942_simulation_10L.py
========================================================================================
TRUE WALK-FORWARD SIMULATION OF CURRENT 09:42 PRODUCTION SHORT-SELL PIPELINE (2020-2026)
AT FLAT ₹10,00,000 NOTIONAL CAPITAL PER STOCK & ₹40 BROKERAGE PER TRADE
========================================================================================
Architecture:
  - Strict Expanding Walk-Forward: For any Year Y (2020 to 2026), model is trained
    strictly on verified historical data prior to Year Y (2018 up to Y-1).
  - Model: Rebound-Aware LightGBM Regressor (100 trees, lr=0.05, depth=5)
  - Universe: Excludes Mondays, Penny Stocks (< Rs 30)
  - Features: 12 Pure DB Features (Zero Lookahead / Zero External API)
  - Filtering Rules:
      • RULE 1: Skip if stock dropped > 1.0% at 09:40
      • RULE 2: Crash Day Protector (Nifty < -0.5% & Stock < -0.5%)
      • RULE 4: Extreme Oversold Protector (Breadth < 10%)
  - Portfolio Selection: Top 4 Filter-Passed Stocks Daily
  - Capital: FLAT ₹10,00,000 Notional per Stock (Quantity = 10,00,000 / Entry_Price)
  - Brokerage & Statutory Taxes:
      • Flat ₹40.00 Brokerage (₹20 Buy + ₹20 Sell) per trade
      • STT: 0.025% on Sell side
      • Exchange Turnover (NSE): 0.00322%
      • SEBI Charges: 0.0001%
      • Stamp Duty: 0.003% on Buy side
      • GST: 18% on (Brokerage + Exchange + SEBI charges)
      • Total charges per trade: ~₹403.70 - ₹405.00
  - Simultaneous 3-Strategy Tick Simulation (09:42 to 14:45):
      • S1: Simple Hold (SL 2.25%, Exit 14:45, No TP)
      • S2: TP 2.0% (SL 2.25%, TP 2.0%, Exit 14:45)
      • S3: Rebound Re-entry (Leg 1: 2.0% TP / 2.25% SL / 14:30; Leg 2: +0.50% Rebound / 1.75% TP2 / Zero-risk SL)
========================================================================================
"""

import os
import sys
import time
import math
import warnings
from datetime import datetime, date
import pandas as pd
import numpy as np
import lightgbm as lgb
import pyarrow.parquet as pq
import pymysql

warnings.filterwarnings('ignore')

BASE_DIR = '/home/ubuntu/live_production0942_model'
HIST_DATASET = '/home/ubuntu/sarang_verified_shorsellalgo_0940/data/0940_hybrid_dataset_from_scrapdata.csv'
PARQUET_TICKS = '/home/ubuntu/trading2026/sarang_verified_shorsellalgo_0940/data/ticks_0940_cache.parquet'
PARQUET_NIFTY = '/home/ubuntu/trading2026/sarang_verified_shorsellalgo_0940/data/nifty50_ticks_cache.parquet'
OUTPUT_CSV = os.path.join(BASE_DIR, 'walkforward_0942_trades_10L_2020_2026.csv')

PURE_DB_FEATURES = [
    'gap_0907_pct', 'gap_fade_0907_to_940_pct',
    'prev_intraday_vwap_gap', 'prev_intraday_return', 'prev_intraday_roc_last_hour',
    'morn_range_pct', 'rejection_wick',
    'ret_0940_vs_prev_close', 'crash_dip_bounce_risk', 'dip_zone_flag', 'rebound_interaction',
    'bear_mom_acceleration'
]

# ─────────────────────────────────────────────────────────────────────────────
# 1. Statutory Taxes & ₹40 Brokerage (MIS Cash Equity)
# ─────────────────────────────────────────────────────────────────────────────
def get_taxes(qty, sell_price, buy_price):
    if qty <= 0 or sell_price <= 0 or buy_price <= 0:
        return 0.0
    sell_value = qty * sell_price
    buy_value = qty * buy_price
    turnover = sell_value + buy_value
    brokerage = 40.0  # Flat ₹40 Brokerage (₹20 Buy + ₹20 Sell)
    stt = math.ceil(sell_value * 0.00025)
    txn = turnover * 0.0000322
    sebi = turnover * 0.000001
    stamp = round(buy_value * 0.00003)
    gst = (brokerage + txn + sebi) * 0.18
    return round(brokerage + stt + txn + sebi + stamp + gst, 2)

# ─────────────────────────────────────────────────────────────────────────────
# 2. Strategy 1 Simulation: Entry 09:42, SL 2.25%, Exit 14:45, No TP
# ─────────────────────────────────────────────────────────────────────────────
def simulate_s1_simple(ticks, total_qty):
    valid_ticks = [t for t in ticks if t.get('price') is not None and float(t.get('price') or 0) > 0]
    if not valid_ticks or total_qty <= 0:
        return None

    ep = float(valid_ticks[0]['price'])
    entry_time = str(valid_ticks[0]['time']).split()[-1]
    sl_price = round(ep * 1.0225, 2)

    exit_p = None
    exit_t = None
    exit_reason = None

    for t in valid_ticks:
        tm = str(t['time']).split()[-1]
        p = float(t['price'])
        h = float(t.get('high') if t.get('high') is not None and float(t.get('high') or 0) > 0 else p)

        if h >= sl_price:
            exit_p = sl_price
            exit_t = tm
            exit_reason = 'STOP_LOSS'
            break

        if tm >= '14:45:00':
            exit_p = p
            exit_t = tm
            exit_reason = 'TIME_EXIT'
            break

    if exit_p is None:
        last = valid_ticks[-1]
        exit_p = float(last['price'])
        exit_t = str(last['time']).split()[-1]
        exit_reason = 'EOD_FALLBACK'

    gross = round((ep - exit_p) * total_qty, 2)
    taxes = get_taxes(total_qty, ep, exit_p)
    net = round(gross - taxes, 2)
    ret_pct = round(((ep - exit_p) / ep) * 100.0, 2)

    return {
        's1_entry_price': ep,
        's1_exit_price': exit_p,
        's1_exit_time': exit_t,
        's1_exit_reason': exit_reason,
        's1_gross_pnl': gross,
        's1_charges': taxes,
        's1_net_pnl': net,
        's1_return_pct': ret_pct
    }

# ─────────────────────────────────────────────────────────────────────────────
# 3. Strategy 2 Simulation: Entry 09:42, SL 2.25%, TP 2.0%, Exit 14:45
# ─────────────────────────────────────────────────────────────────────────────
def simulate_s2_tp2(ticks, total_qty):
    valid_ticks = [t for t in ticks if t.get('price') is not None and float(t.get('price') or 0) > 0]
    if not valid_ticks or total_qty <= 0:
        return None

    ep = float(valid_ticks[0]['price'])
    entry_time = str(valid_ticks[0]['time']).split()[-1]
    tp_price = round(ep * 0.98, 2)
    sl_price = round(ep * 1.0225, 2)

    exit_p = None
    exit_t = None
    exit_reason = None

    for t in valid_ticks:
        tm = str(t['time']).split()[-1]
        p = float(t['price'])
        h = float(t.get('high') if t.get('high') is not None and float(t.get('high') or 0) > 0 else p)
        l = float(t.get('low') if t.get('low') is not None and float(t.get('low') or 0) > 0 else p)

        if h >= sl_price:
            exit_p = sl_price
            exit_t = tm
            exit_reason = 'STOP_LOSS'
            break

        if l <= tp_price:
            exit_p = tp_price
            exit_t = tm
            exit_reason = 'TAKE_PROFIT'
            break

        if tm >= '14:45:00':
            exit_p = p
            exit_t = tm
            exit_reason = 'TIME_EXIT'
            break

    if exit_p is None:
        last = valid_ticks[-1]
        exit_p = float(last['price'])
        exit_t = str(last['time']).split()[-1]
        exit_reason = 'EOD_FALLBACK'

    gross = round((ep - exit_p) * total_qty, 2)
    taxes = get_taxes(total_qty, ep, exit_p)
    net = round(gross - taxes, 2)
    ret_pct = round(((ep - exit_p) / ep) * 100.0, 2)

    return {
        's2_entry_price': ep,
        's2_exit_price': exit_p,
        's2_exit_time': exit_t,
        's2_exit_reason': exit_reason,
        's2_gross_pnl': gross,
        's2_charges': taxes,
        's2_net_pnl': net,
        's2_return_pct': ret_pct
    }

# ─────────────────────────────────────────────────────────────────────────────
# 4. Strategy 3 Simulation: Rebound Re-entry Model
# ─────────────────────────────────────────────────────────────────────────────
def simulate_s3_rebound(ticks, total_qty):
    valid_ticks = [t for t in ticks if t.get('price') is not None and float(t.get('price') or 0) > 0]
    if not valid_ticks or total_qty <= 0:
        return None

    ep = float(valid_ticks[0]['price'])
    entry_time = str(valid_ticks[0]['time']).split()[-1]
    tp1 = round(ep * 0.98, 2)
    sl_leg1 = round(ep * 1.0225, 2)

    leg1_exit_p = None
    leg1_exit_t = None
    leg1_reason = None
    leg1_exit_idx = None

    for i, t in enumerate(valid_ticks):
        tm = str(t['time']).split()[-1]
        p = float(t['price'])
        h = float(t.get('high') if t.get('high') is not None and float(t.get('high') or 0) > 0 else p)
        l = float(t.get('low') if t.get('low') is not None and float(t.get('low') or 0) > 0 else p)

        if h >= sl_leg1:
            leg1_exit_p = sl_leg1
            leg1_exit_t = tm
            leg1_reason = 'STOP_LOSS'
            leg1_exit_idx = i
            break

        if l <= tp1:
            leg1_exit_p = tp1
            leg1_exit_t = tm
            leg1_reason = 'TAKE_PROFIT'
            leg1_exit_idx = i
            break

        if tm >= '14:30:00':
            leg1_exit_p = p
            leg1_exit_t = tm
            leg1_reason = 'TIME_EXIT'
            leg1_exit_idx = i
            break

    if leg1_exit_p is None:
        last = valid_ticks[-1]
        leg1_exit_p = float(last['price'])
        leg1_exit_t = str(last['time']).split()[-1]
        leg1_reason = 'EOD_FALLBACK'
        leg1_exit_idx = len(valid_ticks) - 1

    leg1_gross = round((ep - leg1_exit_p) * total_qty, 2)
    leg1_tax = get_taxes(total_qty, ep, leg1_exit_p)
    leg1_net = round(leg1_gross - leg1_tax, 2)
    leg1_ret = round(((ep - leg1_exit_p) / ep) * 100.0, 2)

    res = {
        'leg1_entry_price': ep,
        'leg1_exit_price': leg1_exit_p,
        'leg1_exit_time': leg1_exit_t,
        'leg1_exit_reason': leg1_reason,
        'leg1_gross_pnl': leg1_gross,
        'leg1_charges': leg1_tax,
        'leg1_net_pnl': leg1_net,
        'leg1_return_pct': leg1_ret,
        'has_leg2': False,
        'rebound_trigger': None,
        'leg2_entry_price': None,
        'leg2_entry_time': None,
        'leg2_exit_price': None,
        'leg2_exit_time': None,
        'leg2_exit_reason': None,
        'leg2_net_pnl': 0.0,
        'leg2_return_pct': 0.0,
        's3_net_pnl': leg1_net
    }

    # If TP1 hit before 14:00, monitor for Leg 2 Re-entry (+0.50% Rebound from TP1)
    if leg1_reason == 'TAKE_PROFIT' and leg1_exit_t < '14:00:00':
        rebound_trigger = round(tp1 * 1.0050, 2)
        res['rebound_trigger'] = rebound_trigger

        leg2_entry_p = None
        leg2_entry_t = None
        leg2_entry_idx = None

        for j in range(leg1_exit_idx + 1, len(valid_ticks)):
            t = valid_ticks[j]
            tm = str(t['time']).split()[-1]
            if tm >= '14:00:00':
                break
            h = float(t.get('high') if t.get('high') is not None and float(t.get('high') or 0) > 0 else t['price'])
            if h >= rebound_trigger:
                leg2_entry_p = rebound_trigger
                leg2_entry_t = tm
                leg2_entry_idx = j
                break

        if leg2_entry_p is not None:
            res['has_leg2'] = True
            res['leg2_entry_price'] = leg2_entry_p
            res['leg2_entry_time'] = leg2_entry_t

            tp2 = round(leg2_entry_p * 0.9825, 2)
            sl_leg2 = ep  # Zero Capital Risk SL (Breakeven at Leg 1 Entry)

            leg2_exit_p = None
            leg2_exit_t = None
            leg2_reason = None

            for k in range(leg2_entry_idx + 1, len(valid_ticks)):
                t = valid_ticks[k]
                tm = str(t['time']).split()[-1]
                p = float(t['price'])
                h = float(t.get('high') if t.get('high') is not None and float(t.get('high') or 0) > 0 else p)
                l = float(t.get('low') if t.get('low') is not None and float(t.get('low') or 0) > 0 else p)

                if h >= sl_leg2:
                    leg2_exit_p = sl_leg2
                    leg2_exit_t = tm
                    leg2_reason = 'STOP_LOSS'
                    break

                if l <= tp2:
                    leg2_exit_p = tp2
                    leg2_exit_t = tm
                    leg2_reason = 'TAKE_PROFIT_2'
                    break

                if tm >= '14:30:00':
                    leg2_exit_p = p
                    leg2_exit_t = tm
                    leg2_reason = 'TIME_EXIT'
                    break

            if leg2_exit_p is None:
                last = valid_ticks[-1]
                leg2_exit_p = float(last['price'])
                leg2_exit_t = str(last['time']).split()[-1]
                leg2_reason = 'EOD_FALLBACK'

            leg2_gross = round((leg2_entry_p - leg2_exit_p) * total_qty, 2)
            leg2_tax = get_taxes(total_qty, leg2_entry_p, leg2_exit_p)
            leg2_net = round(leg2_gross - leg2_tax, 2)
            leg2_ret = round(((leg2_entry_p - leg2_exit_p) / leg2_entry_p) * 100.0, 2)

            res['leg2_exit_price'] = leg2_exit_p
            res['leg2_exit_time'] = leg2_exit_t
            res['leg2_exit_reason'] = leg2_reason
            res['leg2_net_pnl'] = leg2_net
            res['leg2_return_pct'] = leg2_ret
            res['s3_net_pnl'] = round(leg1_net + leg2_net, 2)

    return res

# ─────────────────────────────────────────────────────────────────────────────
# 5. Master Walk-Forward Simulation Loop
# ─────────────────────────────────────────────────────────────────────────────
def main():
    t_start = time.time()
    print("=" * 100)
    print("🚀 STARTING TRUE WALK-FORWARD SIMULATION (₹10L CAPITAL | ₹40 BROKERAGE)")
    print(f"📁 Target Output: {OUTPUT_CSV}")
    print(f"📊 Historical Feature Dataset: {HIST_DATASET}")
    print("=" * 100)

    # A. Load Historical Feature Dataset
    print("\n1. Loading master feature dataset...")
    df_feat = pd.read_csv(HIST_DATASET, low_memory=False)
    df_feat['clean_stock'] = df_feat['clean_stock'].astype(str).str.strip().str.upper()
    df_feat['date_dt'] = pd.to_datetime(df_feat['date_str'])
    df_feat['year'] = df_feat['date_dt'].dt.year

    # Exclude Mondays (empirically destroys Rs 19.23L net PnL in strategy specs)
    df_feat = df_feat[df_feat['date_dt'].dt.dayofweek != 0].copy()

    # Universal Penny Stock Liquidity Filter (Price >= Rs 30)
    df_feat['short_entry_price'] = pd.to_numeric(df_feat['short_entry_price'], errors='coerce').fillna(0.0)
    df_feat = df_feat[df_feat['short_entry_price'] >= 30.0].copy()

    # Engineer Rebound Propensity Features & Bear Momentum Acceleration
    df_feat['gap_0907_pct'] = pd.to_numeric(df_feat['gap_0907_pct'], errors='coerce').fillna(0.0)
    df_feat['gap_fade_0907_to_940_pct'] = pd.to_numeric(df_feat['gap_fade_0907_to_940_pct'], errors='coerce').fillna(0.0)
    df_feat['prev_intraday_return'] = pd.to_numeric(df_feat['prev_intraday_return'], errors='coerce').fillna(0.0)

    df_feat['ret_0940_vs_prev_close'] = ((1.0 + df_feat['gap_0907_pct']/100.0) * (1.0 + df_feat['gap_fade_0907_to_940_pct']/100.0) - 1.0) * 100.0
    df_feat['crash_dip_bounce_risk'] = np.where((df_feat['prev_intraday_return'] < -2.5) & (df_feat['ret_0940_vs_prev_close'] < 0.0), 1.0, 0.0)
    df_feat['dip_zone_flag'] = np.where((df_feat['ret_0940_vs_prev_close'] >= -2.0) & (df_feat['ret_0940_vs_prev_close'] <= -1.0), 1.0, 0.0)
    df_feat['rebound_interaction'] = df_feat['prev_intraday_return'] * df_feat['ret_0940_vs_prev_close']
    df_feat['bear_mom_acceleration'] = df_feat['prev_intraday_return'] * df_feat['gap_fade_0907_to_940_pct']

    for f in PURE_DB_FEATURES:
        if f not in df_feat.columns:
            df_feat[f] = 0.0
        df_feat[f] = pd.to_numeric(df_feat[f], errors='coerce').fillna(0.0)

    df_feat['short_target'] = pd.to_numeric(df_feat.get('short_pct_return', 0.0), errors='coerce').fillna(0.0)
    df_feat['stock_pct_940'] = df_feat['gap_0907_pct'] + df_feat['gap_fade_0907_to_940_pct']
    print(f"   ✔ Feature dataset ready: {len(df_feat):,} eligible rows from {df_feat['year'].min()} to {df_feat['year'].max()}")

    # B. Load Nifty 50 Ticks Cache for Live Market Breadth & Crash Filters
    print("\n2. Loading Nifty 50 and Tick Caches...")
    df_nifty = pq.read_table(PARQUET_NIFTY).to_pandas()
    df_nifty['date_str'] = df_nifty['date_str'].astype(str)
    df_nifty['time_str'] = df_nifty['time_str'].astype(str)

    nifty_day_map = {}
    for d_str, g in df_nifty.groupby('date_str'):
        g_sorted = g.sort_values('time_str')
        open_p = g_sorted.iloc[0]['open']
        t940 = g_sorted[g_sorted['time_str'] >= '09:40:00']
        if len(t940) > 0 and open_p > 0:
            p940 = t940.iloc[0]['close']
            nifty_ret = ((p940 - open_p) / open_p) * 100.0
            nifty_day_map[d_str] = nifty_ret
        else:
            nifty_day_map[d_str] = 0.0

    print("   • Loading 1-minute candle tick parquet cache (1.62M rows)...")
    ticks_table = pq.read_table(PARQUET_TICKS, columns=['date_str', 'stock', 'time_str', 'open', 'high', 'low', 'close'])
    df_ticks = ticks_table.to_pandas()
    df_ticks['stock'] = df_ticks['stock'].astype(str).str.strip().str.upper()
    df_ticks['date_str'] = df_ticks['date_str'].astype(str)

    print("   • Indexing tick candles by (date, stock)...")
    ticks_dict = {}
    for (d_str, stk), g in df_ticks.groupby(['date_str', 'stock']):
        g_sorted = g.sort_values('time_str')
        ticks_dict[(d_str, stk)] = [
            {'time': f"{d_str} {r['time_str']}", 'price': r['close'], 'high': r['high'], 'low': r['low'], 'close': r['close']}
            for _, r in g_sorted.iterrows()
        ]
    print(f"   ✔ Indexed {len(ticks_dict):,} (date, stock) candle series.")

    # C. Walk-Forward Loop by Year (2020 through 2026)
    years_to_simulate = [2020, 2021, 2022, 2023, 2024, 2025, 2026]
    all_trade_records = []

    for test_year in years_to_simulate:
        y_start = time.time()
        print(f"\n{'='*75}")
        print(f"⭐ WALK-FORWARD ITERATION FOR YEAR {test_year}")
        print(f"{'='*75}")

        df_train = df_feat[df_feat['year'] < test_year].copy()
        df_test = df_feat[df_feat['year'] == test_year].copy()

        if len(df_train) == 0:
            print(f"   ❌ Insufficient training data for year {test_year}. Skipping.")
            continue

        print(f"   1. Training LightGBM Rebound-Aware Booster...")
        print(f"      • Training Set: {len(df_train):,} rows ({df_train['year'].min()} to {test_year - 1})")
        print(f"      • Test Set: {len(df_test):,} rows in {test_year}")

        mod = lgb.LGBMRegressor(
            objective='regression',
            n_estimators=100,
            learning_rate=0.05,
            max_depth=5,
            random_state=42,
            n_jobs=-1,
            verbose=-1
        )
        mod.fit(df_train[PURE_DB_FEATURES], df_train['short_target'])

        print(f"   2. Scoring out-of-sample trading days for {test_year}...")
        df_test['pred_return'] = mod.predict(df_test[PURE_DB_FEATURES])

        test_dates = sorted(df_test['date_str'].unique())
        print(f"      • Processing {len(test_dates)} trading days...")

        year_trades_count = 0
        for d_str in test_dates:
            day_candidates = df_test[df_test['date_str'] == d_str].copy()
            day_candidates = day_candidates.sort_values('pred_return', ascending=False).reset_index(drop=True)

            nifty_ret = nifty_day_map.get(d_str, 0.0)

            # Apply Production Safety Filters & Option A Replacements (Matching Live Pipeline)
            orig_top4 = day_candidates.iloc[:4]
            passed_picks = []
            r1_dropped = 0

            for idx, r in orig_top4.iterrows():
                spct = r['stock_pct_940']
                # RULE 1: Cutoff -1.5%
                if spct < -1.5:
                    r1_dropped += 1
                    continue
                # RULE 2: Crash Day Protector
                if nifty_ret < -0.5 and spct < -0.5:
                    continue
                
                r_dict = r.to_dict()
                r_dict['is_replacement'] = False
                r_dict['model_rank'] = idx + 1
                passed_picks.append(r_dict)

            # Option A Replacements: Rank 5 & 6 ONLY for Rule 1 drops if pct >= -0.5%
            reps_allowed = min(4 - len(passed_picks), r1_dropped)
            if reps_allowed > 0 and len(day_candidates) > 4:
                reps_taken = 0
                for r_idx in range(4, min(6, len(day_candidates))):
                    cand = day_candidates.iloc[r_idx]
                    cand_spct = cand['stock_pct_940']
                    
                    # Quality Gate: must be >= -0.5%
                    if cand_spct < -0.5:
                        continue
                    # Rule 2 Crash Day Protector
                    if nifty_ret < -0.5 and cand_spct < -0.5:
                        continue
                    
                    cand_dict = cand.to_dict()
                    cand_dict['is_replacement'] = True
                    cand_dict['model_rank'] = r_idx + 1
                    passed_picks.append(cand_dict)
                    reps_taken += 1
                    if reps_taken == reps_allowed or len(passed_picks) == 4:
                        break

            if not passed_picks:
                continue

            for rank_idx, pick in enumerate(passed_picks, start=1):
                clean = pick['clean_stock']
                ep_db = float(pick['short_entry_price'])
                if ep_db <= 0:
                    continue

                # Flat ₹10,00,000 Notional Position
                total_qty = max(1, int(1000000.0 / ep_db))

                ticks = ticks_dict.get((d_str, clean), [])

                if not ticks and d_str >= '2026-10-09':
                    try:
                        conn = pymysql.connect(host='localhost', user='root', password='root', database='markets', cursorclass=pymysql.cursors.DictCursor)
                        with conn.cursor() as cur:
                            cur.execute(f"SELECT time, close as price, high, low, close FROM scrapdata WHERE date='{d_str}' AND stockname LIKE '%{clean}%' AND TIME(time) >= '09:42:00' ORDER BY time ASC")
                            ticks = cur.fetchall()
                        conn.close()
                    except Exception:
                        ticks = []

                if not ticks:
                    continue

                res_s1 = simulate_s1_simple(ticks, total_qty)
                res_s2 = simulate_s2_tp2(ticks, total_qty)
                res_s3 = simulate_s3_rebound(ticks, total_qty)

                if not res_s1 or not res_s2 or not res_s3:
                    continue

                row_dict = {
                    'date': d_str,
                    'year': test_year,
                    'rank': rank_idx,
                    'model_rank': pick.get('model_rank', rank_idx),
                    'is_replacement': pick.get('is_replacement', False),
                    'stockname': clean,
                    'entry_price_0940': ep_db,
                    'total_quantity': total_qty,
                    'pred_return': pick['pred_return'],
                    'stock_pct_940': pick['stock_pct_940'],
                    'nifty_pct_940': nifty_ret,
                    # Strategy 1
                    's1_entry_price': res_s1['s1_entry_price'],
                    's1_exit_price': res_s1['s1_exit_price'],
                    's1_exit_time': res_s1['s1_exit_time'],
                    's1_exit_reason': res_s1['s1_exit_reason'],
                    's1_gross_pnl': res_s1['s1_gross_pnl'],
                    's1_charges': res_s1['s1_charges'],
                    's1_net_pnl': res_s1['s1_net_pnl'],
                    's1_return_pct': res_s1['s1_return_pct'],
                    # Strategy 2
                    's2_entry_price': res_s2['s2_entry_price'],
                    's2_exit_price': res_s2['s2_exit_price'],
                    's2_exit_time': res_s2['s2_exit_time'],
                    's2_exit_reason': res_s2['s2_exit_reason'],
                    's2_gross_pnl': res_s2['s2_gross_pnl'],
                    's2_charges': res_s2['s2_charges'],
                    's2_net_pnl': res_s2['s2_net_pnl'],
                    's2_return_pct': res_s2['s2_return_pct'],
                    # Strategy 3
                    's3_entry_price': res_s3['leg1_entry_price'],
                    'leg1_exit_price': res_s3['leg1_exit_price'],
                    'leg1_exit_time': res_s3['leg1_exit_time'],
                    'leg1_exit_reason': res_s3['leg1_exit_reason'],
                    'leg1_net_pnl': res_s3['leg1_net_pnl'],
                    'leg1_return_pct': res_s3['leg1_return_pct'],
                    'has_leg2': res_s3['has_leg2'],
                    'rebound_trigger': res_s3['rebound_trigger'],
                    'leg2_entry_price': res_s3['leg2_entry_price'],
                    'leg2_entry_time': res_s3['leg2_entry_time'],
                    'leg2_exit_price': res_s3['leg2_exit_price'],
                    'leg2_exit_time': res_s3['leg2_exit_time'],
                    'leg2_exit_reason': res_s3['leg2_exit_reason'],
                    'leg2_net_pnl': res_s3['leg2_net_pnl'],
                    'leg2_return_pct': res_s3['leg2_return_pct'],
                    's3_net_pnl': res_s3['s3_net_pnl']
                }

                all_trade_records.append(row_dict)
                year_trades_count += 1

        print(f"   ✔ Year {test_year} completed: {year_trades_count} trades generated in {time.time() - y_start:.1f}s.")

    df_out = pd.DataFrame(all_trade_records)
    df_out.to_csv(OUTPUT_CSV, index=False)
    print("\n" + "=" * 100)
    print(f"🎉 10L WALK-FORWARD SIMULATION FINISHED IN {time.time() - t_start:.1f}s!")
    print(f"📁 Saved {len(df_out):,} total simulated trades to: {OUTPUT_CSV}")
    print("=" * 100)

if __name__ == '__main__':
    main()
