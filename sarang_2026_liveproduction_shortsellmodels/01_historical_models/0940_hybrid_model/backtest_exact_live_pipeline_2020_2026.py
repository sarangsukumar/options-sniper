#!/usr/bin/env python3
"""
backtest_exact_live_pipeline_2020_2026.py
-----------------------------------------
Standalone Historical Backtest of the EXACT Live Production 09:40/09:42 Pipeline
(`live_0940_hybrid_pipeline.py` + `Neo_shortsell_mis_order.py` + `sl_near_alert_monitor.py` + `reconcile_0940_live_mimic_pnl.py`)
across 2020-2026 without modifying any live production files.

Incorporates the exact live pipeline specifications:
  1. Model Training: Walk-forward trained on >= Rs 30 universe (excluding Mondays), plus exact live
     booster (`lgb_0940_rebound_aware_audited_model.txt`) for dates >= 2026-10-12.
  2. Live Candidate Price Filter: `entry_price_0940 >= 50.0` (exact live_0940_hybrid_pipeline.py L717).
  3. Live Nifty % Change for Rule 2: Computed against `nifty_prev_close` (prior day's closing
     price) rather than `nifty_open` (exact live_0940_hybrid_pipeline.py L418-L425).
  4. Live Option A Selection & Replacement Rules:
     - Rule 1: Skip Top 4 if `stock_pct_940 < -1.5%`
     - Rule 2: Skip if `nifty_pct_vs_prev_close < -0.5%` and `stock_pct_940 < -0.5%`
     - Option A Replacements: Ranks 5 & 6 ONLY for Rule 1 drops where `stock_pct_940 >= -0.5%`
       and passing Rule 2.
  5. Evaluates all 6 Execution Simulations (SIM 1A, SIM 1B, SIM 2A, SIM 2B, SIM 3A Live 4-Stage Dynamic Engine,
     SIM 3B Constant 2.25% SL) using the exact tick simulator from `reconcile_0940_live_mimic_pnl.py` at:
     - Flat Rs 10L / stock (for 1:1 comparison with the 5,269 Option A benchmark)
     - Flat Rs 5L / stock
     - Live Dynamic Capital Allocation (Rs 30L daily budget / N active trades, capped at Rs 10L for 1-2 trades)
"""

import os
import sys
import math
import time
import warnings
import pandas as pd
import numpy as np
import lightgbm as lgb
import pyarrow.parquet as pq
import pymysql

warnings.filterwarnings('ignore')

HIST_DATASET = '/home/ubuntu/sarang_verified_shorsellalgo_0940/data/0940_hybrid_dataset_from_scrapdata.csv'
PARQUET_TICKS = '/home/ubuntu/trading2026/sarang_verified_shorsellalgo_0940/data/ticks_0940_cache.parquet'
PARQUET_NIFTY = '/home/ubuntu/trading2026/sarang_verified_shorsellalgo_0940/data/nifty50_ticks_cache.parquet'
LIVE_MODEL_FILE = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_shortsell_t1_2026/02_0942_Hybrid_Model/live_production/lgb_0940_rebound_aware_audited_model.txt'
HIST_BENCHMARK_CSV = '/home/ubuntu/live_production0942_model/option_a_5269_4sims_comparison.csv'
OUT_CSV = '/home/ubuntu/live_production0942_model/exact_live_pipeline_backtest_2020_2026.csv'

PURE_DB_FEATURES = [
    'gap_0907_pct', 'gap_fade_0907_to_940_pct',
    'prev_intraday_vwap_gap', 'prev_intraday_return', 'prev_intraday_roc_last_hour',
    'morn_range_pct', 'rejection_wick',
    'ret_0940_vs_prev_close', 'crash_dip_bounce_risk', 'dip_zone_flag', 'rebound_interaction',
    'bear_mom_acceleration'
]

def get_taxes(qty, sell_price, buy_price):
    if qty <= 0 or sell_price <= 0 or buy_price <= 0:
        return 0.0
    turnover = (qty * sell_price) + (qty * buy_price)
    stt = round(qty * sell_price * 0.00025)
    txn = turnover * 0.0000322
    sebi = turnover * 0.000001
    stamp = round(qty * buy_price * 0.00003)
    gst = (40.0 + txn + sebi) * 0.18
    return round(40.0 + stt + txn + sebi + stamp + gst, 2)

def _clean_ticks(ticks):
    if not ticks:
        return []
    seen = set()
    cleaned = []
    prev_p = None
    for t in ticks:
        raw_p = t.get('price') if t.get('price') is not None else t.get('close')
        if raw_p is None:
            continue
        p = float(raw_p)
        if p <= 0:
            continue
        tm = str(t.get('time', '')).split()[-1]
        if tm in seen:
            continue
        if prev_p is not None and abs(p - prev_p) / prev_p > 0.12:
            continue
        seen.add(tm)
        prev_p = p
        cleaned.append({'time': tm, 'price': p})
    return cleaned

def sim_s1(ticks, qty, use_3min=True):
    valid = _clean_ticks(ticks)
    if not valid or qty <= 0:
        return 0.0, 'NO_TICKS'
    ep = valid[0]['price']
    sl = round(ep * 1.0225, 2)
    breach = 0
    exit_p, reason = None, None
    for t in valid:
        tm, p = t['time'], t['price']
        if p >= sl:
            breach += 1
            if (not use_3min) or breach >= 3:
                exit_p, reason = (p if use_3min else sl), ('SL_3M' if use_3min else 'SL_1T')
                break
        else:
            breach = 0
        if tm >= '14:45:00':
            exit_p, reason = p, 'TIME_EXIT'
            break
    if exit_p is None:
        exit_p, reason = valid[-1]['price'], 'EOD'
    net = round((ep - exit_p) * qty - get_taxes(qty, ep, exit_p), 2)
    return net, reason

def sim_s2(ticks, qty, use_3min=True):
    valid = _clean_ticks(ticks)
    if not valid or qty <= 0:
        return 0.0, 'NO_TICKS', False
    ep = valid[0]['price']
    tp1 = round(ep * 0.9800, 2)
    sl1 = round(ep * 1.0225, 2)
    breach = 0
    l1_p, l1_r, reb_trig, disc_l1 = None, None, None, None
    l2_ep, l2_tp, l2_sl, l2_p, disc_l2 = None, None, None, None, None

    for t in valid:
        tm, p = t['time'], t['price']
        if l1_p is None:
            if p >= sl1:
                breach += 1
                if (not use_3min) or breach >= 3:
                    l1_p, l1_r = (p if use_3min else sl1), ('SL_3M' if use_3min else 'SL_1T')
                    break
            else:
                breach = 0
            if p <= tp1:
                l1_p, l1_r = p, 'TP_2PCT'
                reb_trig = round(l1_p * 1.005, 2)
                continue
            if tm >= '14:30:00':
                if disc_l1 is None:
                    disc_l1 = round(p * 0.998, 2)
                elif p <= disc_l1:
                    l1_p, l1_r = disc_l1, 'DISC_1430'
                    break
            if tm >= '14:45:00':
                l1_p, l1_r = p, 'TIME_EXIT'
                break
        else:
            if l2_ep is None:
                if tm >= '14:30:00':
                    break
                if reb_trig is not None and p >= reb_trig:
                    l2_ep = p
                    l2_tp = round(l2_ep * 0.9825, 2)
                    l2_sl = ep
                    continue
            else:
                if p >= l2_sl:
                    l2_p = p
                    break
                if p <= l2_tp:
                    l2_p = p
                    break
                if tm >= '14:30:00':
                    if disc_l2 is None:
                        disc_l2 = round(p * 0.998, 2)
                    elif p <= disc_l2:
                        l2_p = disc_l2
                        break
                if tm >= '14:45:00':
                    l2_p = p
                    break

    if l1_p is None:
        l1_p, l1_r = valid[-1]['price'], 'EOD'
    if l2_ep is not None and l2_p is None:
        l2_p = valid[-1]['price']

    l1_net = round((ep - l1_p) * qty - get_taxes(qty, ep, l1_p), 2)
    has_l2 = (l2_ep is not None and l2_p is not None)
    l2_net = round((l2_ep - l2_p) * qty - get_taxes(qty, l2_ep, l2_p), 2) if has_l2 else 0.0
    return round(l1_net + l2_net, 2), l1_r, has_l2

def sim_s3_4stage(ticks, qty, decay_sl=True):
    """
    Exact Live 4-Stage Dynamic Engine from reconcile_0940_live_mimic_pnl.py:
      - Stage 1: Time-Decay SL (2.25% / 1.50% / 1.00% if decay_sl=True, else constant 2.25%) with 3-min consecutive breach
      - Stage 2: Pre-TP Profit Lock at +1.25% peak -> locks +0.50% floor (ep * 0.9950)
      - Stage 3: Trailing TP at +2.00% peak -> +1.75% initial floor (ep * 0.9825) & 0.50% trail behind min_ltp
      - Stage 4: Leg 2 Re-entry at +0.50% bounce before 14:30 (1.50% tight SL, 1.50% trailing TP w/ 0.75% trail)
    """
    valid = _clean_ticks(ticks)
    if not valid or qty <= 0:
        return 0.0, 'NO_TICKS', False
    ep = valid[0]['price']
    tp_act = round(ep * 0.9800, 2)
    lock_p = round(ep * 0.9950, 2)
    init_floor = round(ep * 0.9825, 2)

    min_ltp = ep
    trail_act = False
    breach = 0
    l1_p, l1_r, allow_re, reb_trig, disc_l1 = None, None, False, None, None
    l2_ep, min_l2, trail_l2, l2_p, disc_l2 = None, None, False, None, None

    for t in valid:
        tm, p = t['time'], t['price']
        if l1_p is None:
            t_int = int(tm.replace(':', '')[:4]) if len(tm) >= 4 else 942
            if decay_sl:
                sl_pct = 2.25 if t_int < 1100 else (1.50 if t_int < 1230 else 1.00)
            else:
                sl_pct = 2.25
            base_sl = round(ep * (1.0 + sl_pct / 100.0), 2)

            min_ltp = min(min_ltp, p)
            max_prof_pct = ((ep - min_ltp) / ep) * 100.0
            active_sl = base_sl

            if max_prof_pct >= 1.25 and not trail_act:
                active_sl = min(active_sl, lock_p)
            if not trail_act and p <= tp_act:
                trail_act = True
            if trail_act:
                active_sl = min(init_floor, round(min_ltp * 1.005, 2))

            is_prot = bool(trail_act or (max_prof_pct >= 1.25 and active_sl == lock_p))
            if p >= active_sl:
                if is_prot:
                    breach = 0
                    l1_p = p
                    if trail_act:
                        l1_r = 'STAGE3_TRAIL_1.75'
                        allow_re = True
                        reb_trig = round(l1_p * 1.005, 2)
                        continue
                    else:
                        l1_r = 'STAGE2_LOCK_0.50'
                        allow_re = False
                        break
                else:
                    breach += 1
                    if breach >= 3:
                        l1_p = p
                        l1_r = f'STAGE1_SL_{sl_pct:.2f}_3M'
                        allow_re = False
                        break
            else:
                breach = 0

            if tm >= '14:30:00':
                if disc_l1 is None:
                    disc_l1 = round(p * 0.998, 2)
                elif p <= disc_l1:
                    l1_p, l1_r, allow_re = disc_l1, 'DISC_1430', False
                    break
            if tm >= '14:45:00':
                l1_p, l1_r, allow_re = p, 'TIME_EXIT', False
                break
        else:
            if not allow_re:
                break
            if l2_ep is None:
                if tm >= '14:30:00':
                    break
                if reb_trig is not None and p >= reb_trig:
                    l2_ep = p
                    min_l2 = p
                    trail_l2 = False
                    continue
            else:
                min_l2 = min(min_l2, p)
                l2_sl = round(l2_ep * 1.015, 2)
                l2_tp_act = round(l2_ep * 0.985, 2)
                if not trail_l2 and p <= l2_tp_act:
                    trail_l2 = True
                l2_act_sl = min(l2_tp_act, round(min_l2 * 1.0075, 2)) if trail_l2 else l2_sl
                if p >= l2_act_sl:
                    l2_p = p
                    break
                if tm >= '14:30:00':
                    if disc_l2 is None:
                        disc_l2 = round(p * 0.998, 2)
                    elif p <= disc_l2:
                        l2_p = disc_l2
                        break
                if tm >= '14:45:00':
                    l2_p = p
                    break

    if l1_p is None:
        l1_p, l1_r = valid[-1]['price'], 'EOD'
    if l2_ep is not None and l2_p is None:
        l2_p = valid[-1]['price']

    l1_net = round((ep - l1_p) * qty - get_taxes(qty, ep, l1_p), 2)
    has_l2 = (l2_ep is not None and l2_p is not None)
    l2_net = round((l2_ep - l2_p) * qty - get_taxes(qty, l2_ep, l2_p), 2) if has_l2 else 0.0
    return round(l1_net + l2_net, 2), l1_r, has_l2

def main():
    print("=" * 120)
    print("🚀 HISTORICAL BACKTEST OF EXACT LIVE PRODUCTION PIPELINE (2020-2026)")
    print("=" * 120)

    # Load historical Option A 5,269 benchmark
    df_hist_bt = pd.read_csv(HIST_BENCHMARK_CSV)
    hist_lookup = {}
    for _, r in df_hist_bt.iterrows():
        hist_lookup[(str(r['date']), str(r['stock']).strip().upper())] = r.to_dict()

    # 1. Load dataset
    df_feat = pd.read_csv(HIST_DATASET, low_memory=False)
    df_feat['clean_stock'] = df_feat['clean_stock'].astype(str).str.strip().str.upper()
    df_feat['date_dt'] = pd.to_datetime(df_feat['date_str'])
    df_feat['year'], df_feat['ym'], df_lots = df_feat['date_dt'].dt.year, df_feat['date_dt'].dt.to_period('M'), pd.read_csv('/home/ubuntu/intraday_simulation/historical_lotsize_new.csv', low_memory=False)
    # [UPDATE] Point-in-Time Non-Future Priority + Futures Backfill in Top-5
    df_lots['ym'] = pd.to_datetime(df_lots['expdate'], format='%d/%m/%Y', errors='coerce').dt.to_period('M')
    active_by_ym = {ym: (set(df_lots[(df_lots['ym'] >= ym) & (df_lots['ym'] <= ym + 2)]['stockname'].str.strip().str.upper()) or set(df_lots[df_lots['ym'] >= df_lots['ym'].max() - 1]['stockname'].str.strip().str.upper())) for ym in df_feat['ym'].unique()}
    df_feat['in_pit_futures'] = [st in active_by_ym.get(ym, set()) for st, ym in zip(df_feat['clean_stock'], df_feat['ym'])]
    df_feat = df_feat[df_feat['date_dt'].dt.dayofweek != 0].copy()  # Strict Monday Exclusion
    df_feat['short_entry_price'] = pd.to_numeric(df_feat['short_entry_price'], errors='coerce').fillna(0.0)
    df_feat = df_feat[df_feat['short_entry_price'] >= 30.0].copy()  # Training universe >= Rs 30

    for c in ['gap_0907_pct', 'gap_fade_0907_to_940_pct', 'prev_intraday_return']:
        df_feat[c] = pd.to_numeric(df_feat[c], errors='coerce').fillna(0.0)
    df_feat['ret_0940_vs_prev_close'] = ((1.0 + df_feat['gap_0907_pct']/100.0) * (1.0 + df_feat['gap_fade_0907_to_940_pct']/100.0) - 1.0) * 100.0
    df_feat['crash_dip_bounce_risk'] = np.where((df_feat['prev_intraday_return'] < -2.5) & (df_feat['ret_0940_vs_prev_close'] < 0.0), 1.0, 0.0)
    df_feat['dip_zone_flag'] = np.where((df_feat['ret_0940_vs_prev_close'] >= -2.0) & (df_feat['ret_0940_vs_prev_close'] <= -1.0), 1.0, 0.0)
    df_feat['rebound_interaction'] = df_feat['prev_intraday_return'] * df_feat['ret_0940_vs_prev_close']
    df_feat['bear_mom_acceleration'] = df_feat['prev_intraday_return'] * df_feat['gap_fade_0907_to_940_pct']

    for f in PURE_DB_FEATURES:
        df_feat[f] = pd.to_numeric(df_feat[f], errors='coerce').fillna(0.0)
    df_feat['short_target'] = pd.to_numeric(df_feat['short_pct_return'], errors='coerce').fillna(0.0)
    df_feat['stock_pct_940'] = df_feat['gap_0907_pct'] + df_feat['gap_fade_0907_to_940_pct']

    # 2. Compute Live Nifty % baseline (vs_prev_close)
    df_nifty = pq.read_table(PARQUET_NIFTY).to_pandas()
    df_nifty['date_str'] = df_nifty['date_str'].astype(str)
    df_nifty['time_str'] = df_nifty['time_str'].astype(str)

    conn = pymysql.connect(host='localhost', user='root', password='root', database='markets', cursorclass=pymysql.cursors.DictCursor)
    with conn.cursor() as cur:
        cur.execute("SELECT date, time, open, close FROM scrapdata WHERE stockname = 'NIFTY 50' AND date >= '2026-10-12' ORDER BY date ASC, time ASC")
        db_nifty = pd.DataFrame(cur.fetchall())
    if not db_nifty.empty:
        db_nifty['date_str'] = db_nifty['date'].astype(str)
        db_nifty['time_str'] = pd.to_datetime(db_nifty['time']).dt.strftime('%H:%M:%S')
        df_nifty = pd.concat([df_nifty, db_nifty[['date_str', 'time_str', 'open', 'close']]], ignore_index=True)

    nifty_vs_prev_close = {}
    prev_nifty_close = None
    for d_str in sorted(df_nifty['date_str'].unique()):
        g = df_nifty[df_nifty['date_str'] == d_str].sort_values('time_str')
        open_p = float(g.iloc[0]['open'])
        close_p = float(g.iloc[-1]['close'])
        t940 = g[g['time_str'] >= '09:40:00']
        if len(t940) > 0:
            p940 = float(t940.iloc[0]['close'])
            if prev_nifty_close and prev_nifty_close > 0:
                nifty_vs_prev_close[d_str] = ((p940 - prev_nifty_close) / prev_nifty_close * 100.0)
            else:
                nifty_vs_prev_close[d_str] = ((p940 - open_p) / open_p * 100.0) if open_p > 0 else 0.0
        else:
            nifty_vs_prev_close[d_str] = 0.0
        prev_nifty_close = close_p

    # Load actual live booster for post-Oct 12 dates
    live_booster = lgb.Booster(model_file=LIVE_MODEL_FILE) if os.path.exists(LIVE_MODEL_FILE) else None

    years = [2020, 2021, 2022, 2023, 2024, 2025, 2026]
    selected_picks = []
    missing_tick_keys = set()

    for test_year in years:
        df_train = df_feat[df_feat['year'] < test_year].copy()
        df_test = df_feat[df_feat['year'] == test_year].copy()
        if len(df_train) == 0 or len(df_test) == 0:
            continue

        mod = lgb.LGBMRegressor(objective='regression', n_estimators=100, learning_rate=0.05, max_depth=5, random_state=42, n_jobs=-1, verbose=-1)
        mod.fit(df_train[PURE_DB_FEATURES], df_train['short_target'])
        df_test['pred_return'] = mod.predict(df_test[PURE_DB_FEATURES])

        if test_year == 2026 and live_booster is not None:
            mask_live_mod = df_test['date_str'] >= '2026-10-12'
            if mask_live_mod.any():
                df_test.loc[mask_live_mod, 'pred_return'] = live_booster.predict(df_test.loc[mask_live_mod, PURE_DB_FEATURES])

        for d_str in sorted(df_test['date_str'].unique()):
            # LIVE PIPELINE DIFFERENCE 5: Filter daily candidates at entry_price >= 50 (L717)
            day_cands = df_test[(df_test['date_str'] == d_str) & (df_test['short_entry_price'] >= 50.0)].copy()
            day_cands = day_cands.sort_values('pred_return', ascending=False).reset_index(drop=True)
            if day_cands.empty:
                continue

            # LIVE PIPELINE DIFFERENCE 4: Nifty % change from nifty_prev_close (L418-L425)
            nifty_pct = nifty_vs_prev_close.get(d_str, 0.0)

            orig_top4 = pd.concat([day_cands.iloc[:5][~day_cands.iloc[:5]['in_pit_futures']], day_cands.iloc[:5][day_cands.iloc[:5]['in_pit_futures']], day_cands.iloc[5:]], ignore_index=True).iloc[:4]
            passed = []
            r1_dropped = 0

            for idx, r in orig_top4.iterrows():
                spct = r['stock_pct_940']
                if spct < -1.5:
                    r1_dropped += 1
                    continue
                if nifty_pct < -0.5 and spct < -0.5:
                    continue
                r_dict = r.to_dict()
                r_dict['model_rank'] = idx + 1
                r_dict['is_replacement'] = False
                passed.append(r_dict)

            # Option A Replacements (Ranks 5 & 6 ONLY for Rule 1 drops where spct >= -0.5%)
            reps_allowed = min(4 - len(passed), r1_dropped)
            if reps_allowed > 0 and len(day_cands) > 4:
                reps_taken = 0
                for r_idx in range(4, min(6, len(day_cands))):
                    cand = day_cands.iloc[r_idx]
                    spct = cand['stock_pct_940']
                    if spct < -0.5:
                        continue
                    if nifty_pct < -0.5 and spct < -0.5:
                        continue
                    c_dict = cand.to_dict()
                    c_dict['model_rank'] = r_idx + 1
                    c_dict['is_replacement'] = True
                    passed.append(c_dict)
                    reps_taken += 1
                    if reps_taken == reps_allowed or len(passed) == 4:
                        break

            if not passed:
                continue

            n_active = len(passed)
            dyn_cap = 1000000.0 if n_active <= 2 else (3000000.0 / n_active)

            for pick in passed:
                stk = pick['clean_stock']
                selected_picks.append((test_year, d_str, stk, pick, nifty_pct, n_active, dyn_cap))
                if (d_str, stk) not in hist_lookup:
                    missing_tick_keys.add((d_str, stk))

    # Load ticks only for the missing dates/stocks not in hist_lookup
    print(f"Total selected picks: {len(selected_picks):,} (Overlap with 5,269 Historical Option A: {sum(1 for _, d, s, *_ in selected_picks if (d, s) in hist_lookup):,}, New/Diff picks: {len(missing_tick_keys)})")
    needed_dates = list({d for d, _ in missing_tick_keys})
    needed_stocks = list({s for _, s in missing_tick_keys})
    ticks_dict = {}
    if needed_dates:
        ticks_table = pq.read_table(PARQUET_TICKS, columns=['date_str', 'stock', 'time_str', 'close'], filters=[('date_str', 'in', needed_dates), ('stock', 'in', needed_stocks)])
        df_ticks = ticks_table.to_pandas()
        df_ticks['stock'] = df_ticks['stock'].astype(str).str.strip().str.upper()
        df_ticks['date_str'] = df_ticks['date_str'].astype(str)
        for (d_str, stk), g in df_ticks.groupby(['date_str', 'stock']):
            if (d_str, stk) not in missing_tick_keys:
                continue
            g_sorted = g.sort_values('time_str')
            ticks_dict[(d_str, stk)] = [
                {'time': r['time_str'], 'price': r['close']}
                for _, r in g_sorted.iterrows()
            ]

    def get_ticks(d_str, stk):
        if (d_str, stk) in ticks_dict:
            return ticks_dict[(d_str, stk)]
        with conn.cursor() as cur:
            cur.execute("SELECT time, price FROM scrapdata WHERE date=%s AND stockname=%s AND TIME(time)>='09:42:00' AND TIME(time)<='14:45:00' ORDER BY time ASC", (d_str, stk))
            rows = cur.fetchall()
            if not rows:
                cur.execute("SELECT time, price FROM scrapdata WHERE date=%s AND stockname LIKE %s AND TIME(time)>='09:42:00' AND TIME(time)<='14:45:00' ORDER BY time ASC", (d_str, f"%{stk}%"))
                rows = cur.fetchall()
            ticks_dict[(d_str, stk)] = rows
            return rows

    live_records = []
    for test_year, d_str, stk, pick, nifty_pct, n_active, dyn_cap in selected_picks:
        if (d_str, stk) in hist_lookup:
            hr = hist_lookup[(d_str, stk)]
            s1_1t_10L = hr['s1_1t_10L']
            s1_3m_10L = hr['s1_3m_10L']
            s2_1t_10L = hr['s2_1t_10L']
            s2_3m_10L = hr['s2_3m_10L']
            s3_live_10L = hr['s3_live_10L']
            s3_const_10L = hr['s3_const_10L']
            s3_live_5L = hr['s3_live_5L']
            r_s3_live = hr['r_s3_live']
            l2_s3_live = hr['l2_s3_live']
            s3_live_dyn = s3_live_10L if n_active <= 3 else round((s3_live_10L + s3_live_5L) / 2.0, 2)
        else:
            tks = get_ticks(d_str, stk)
            if not tks:
                continue
            valid_tks = _clean_ticks(tks)
            if not valid_tks:
                continue
            ep = valid_tks[0]['price']
            qty_5L = max(1, int(round(500000.0 / ep)))
            qty_10L = max(1, int(round(1000000.0 / ep)))
            qty_dyn = max(1, int(round(dyn_cap / ep)))

            s1_1t_10L, _ = sim_s1(tks, qty_10L, use_3min=False)
            s1_3m_10L, _ = sim_s1(tks, qty_10L, use_3min=True)
            s2_1t_10L, _, _ = sim_s2(tks, qty_10L, use_3min=False)
            s2_3m_10L, _, _ = sim_s2(tks, qty_10L, use_3min=True)
            s3_live_10L, r_s3_live, l2_s3_live = sim_s3_4stage(tks, qty_10L, decay_sl=True)
            s3_const_10L, _, _ = sim_s3_4stage(tks, qty_10L, decay_sl=False)
            s3_live_5L, _, _ = sim_s3_4stage(tks, qty_5L, decay_sl=True)
            s3_live_dyn, _, _ = sim_s3_4stage(tks, qty_dyn, decay_sl=True)

        live_records.append({
            'year': test_year,
            'date': d_str,
            'stock': stk,
            'model_rank': pick['model_rank'],
            'is_replacement': pick['is_replacement'],
            'in_hist_option_a': (d_str, stk) in hist_lookup,
            'entry_price_0940': float(pick['short_entry_price']),
            'stock_pct_940': pick['stock_pct_940'],
            'nifty_pct_prev_close': nifty_pct,
            'n_active_day': n_active,
            'dyn_capital': dyn_cap,
            's1_1t_10L': s1_1t_10L,
            's1_3m_10L': s1_3m_10L,
            's2_1t_10L': s2_1t_10L,
            's2_3m_10L': s2_3m_10L,
            's3_live_10L': s3_live_10L,
            's3_const_10L': s3_const_10L,
            's3_live_5L': s3_live_5L,
            's3_live_dyn30L': s3_live_dyn,
            'r_s3_live': r_s3_live,
            'l2_s3_live': l2_s3_live
        })

    conn.close()
    df_live_bt = pd.DataFrame(live_records)
    df_live_bt.to_csv(OUT_CSV, index=False)

    print(f"\n✅ Saved {len(df_live_bt):,} Exact Live Pipeline trades to: {OUT_CSV}")
    print("\n" + "=" * 125)
    print("📊 1. SIDE-BY-SIDE COMPARISON AT ₹10L/STOCK (SIM 3A LIVE 4-STAGE ENGINE): HISTORICAL OPTION A vs EXACT LIVE PIPELINE")
    print("=" * 125)
    print(f"{'Year':<6} | {'Historical Option A Walk-Forward (SIM 3A)':<42} | {'Exact Live Pipeline Model (SIM 3A)':<42} | {'Difference':<15}")
    print(f"{'':<6} | {'Trades':<8} {'Win%':<8} {'Net PnL (₹10L)':<16} {'PF':<6} | {'Trades':<8} {'Win%':<8} {'Net PnL (₹10L)':<16} {'PF':<6} | {'PnL Diff':<15}")
    print("-" * 125)

    for y in years:
        h_sub = df_hist_bt[df_hist_bt['year'] == y]
        l_sub = df_live_bt[df_live_bt['year'] == y]

        h_cnt = len(h_sub)
        h_wr = (h_sub['s3_live_10L'] > 0).mean() * 100.0 if h_cnt else 0.0
        h_pnl = h_sub['s3_live_10L'].sum() / 100000.0
        h_pf = h_sub[h_sub['s3_live_10L'] > 0]['s3_live_10L'].sum() / abs(h_sub[h_sub['s3_live_10L'] < 0]['s3_live_10L'].sum()) if (h_sub['s3_live_10L'] < 0).any() else 0.0

        l_cnt = len(l_sub)
        l_wr = (l_sub['s3_live_10L'] > 0).mean() * 100.0 if l_cnt else 0.0
        l_pnl = l_sub['s3_live_10L'].sum() / 100000.0
        l_pf = l_sub[l_sub['s3_live_10L'] > 0]['s3_live_10L'].sum() / abs(l_sub[l_sub['s3_live_10L'] < 0]['s3_live_10L'].sum()) if (l_sub['s3_live_10L'] < 0).any() else 0.0

        diff = l_pnl - h_pnl
        print(f"{y:<6} | {h_cnt:<8} {h_wr:5.1f}%   ₹{h_pnl:+8.2f} Lakhs   {h_pf:4.2f}  | {l_cnt:<8} {l_wr:5.1f}%   ₹{l_pnl:+8.2f} Lakhs   {l_pf:4.2f}  | {diff:+7.2f} Lakhs")

    print("-" * 125)
    h_tot_cnt = len(df_hist_bt)
    h_tot_wr = (df_hist_bt['s3_live_10L'] > 0).mean() * 100.0
    h_tot_pnl = df_hist_bt['s3_live_10L'].sum() / 100000.0
    h_tot_pf = df_hist_bt[df_hist_bt['s3_live_10L'] > 0]['s3_live_10L'].sum() / abs(df_hist_bt[df_hist_bt['s3_live_10L'] < 0]['s3_live_10L'].sum())

    l_tot_cnt = len(df_live_bt)
    l_tot_wr = (df_live_bt['s3_live_10L'] > 0).mean() * 100.0
    l_tot_pnl = df_live_bt['s3_live_10L'].sum() / 100000.0
    l_tot_pf = df_live_bt[df_live_bt['s3_live_10L'] > 0]['s3_live_10L'].sum() / abs(df_live_bt[df_live_bt['s3_live_10L'] < 0]['s3_live_10L'].sum())
    tot_diff = l_tot_pnl - h_tot_pnl

    print(f"{'TOTAL':<6} | {h_tot_cnt:<8} {h_tot_wr:5.1f}%   ₹{h_tot_pnl:+8.2f} Lakhs   {h_tot_pf:4.2f}  | {l_tot_cnt:<8} {l_tot_wr:5.1f}%   ₹{l_tot_pnl:+8.2f} Lakhs   {l_tot_pf:4.2f}  | {tot_diff:+7.2f} Lakhs")
    print("=" * 125)

    # Print all simulations on Exact Live Pipeline Model
    print("\n" + "=" * 125)
    print("📊 2. ALL EXECUTION SIMULATIONS ON THE EXACT LIVE PIPELINE MODEL (2020-2026)")
    print("=" * 125)
    for col, label in [
        ('s1_1t_10L', 'SIM 1A: No TP | 2.25% SL (1-Tick) | Exit 14:45            [₹10L/Stock]'),
        ('s1_3m_10L', 'SIM 1B: No TP | 2.25% SL (3-Min Cont. Breach) | Exit 14:45[₹10L/Stock]'),
        ('s2_1t_10L', 'SIM 2A: 2.0% TP | 2.25% SL (1-Tick) | +0.50% Re-Entry     [₹10L/Stock]'),
        ('s2_3m_10L', 'SIM 2B: 2.0% TP | 2.25% SL (3-Min Breach) | +0.50% Re-Ent [₹10L/Stock]'),
        ('s3_live_10L', 'SIM 3A: Active Live 4-Stage Dynamic Engine (Decay SL)     [₹10L/Stock]'),
        ('s3_const_10L', 'SIM 3B: 4-Stage Engine w/ Constant 2.25% SL (No Decay)    [₹10L/Stock]'),
        ('s3_live_5L', 'SIM 3A (₹5L): Active Live 4-Stage Dynamic Engine          [₹5L/Stock] '),
        ('s3_live_dyn30L', 'SIM 3A (Live Sizing): Dynamic ₹30L/N (Max ₹10L)           [Live Sizing]')
    ]:
        s = df_live_bt[col]
        pnl = s.sum() / 100000.0
        wr = (s > 0).mean() * 100.0
        pf = s[s > 0].sum() / abs(s[s < 0].sum())
        daily = df_live_bt.groupby('date')[col].sum()
        cum = daily.cumsum()
        dd = (cum - cum.cummax()).min() / 100000.0
        sharpe = (daily.mean() / daily.std()) * np.sqrt(200) if daily.std() > 0 else 0.0
        y26 = df_live_bt[df_live_bt['year'] == 2026][col].sum() / 100000.0
        print(f"• {label:<70} | Net: ₹{pnl:+7.2f}L | 2026: ₹{y26:+6.2f}L | WR: {wr:5.1f}% | PF: {pf:4.2f} | MaxDD: ₹{dd:6.2f}L | Sharpe: {sharpe:4.2f}")
    print("=" * 125)

if __name__ == '__main__':
    main()
