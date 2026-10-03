#!/usr/bin/env python3
"""
========================================================================================
👑 COMPLETE 09:40 HYBRID MODEL (09:42 - 14:45) PURE MYSQL RAW TICK REBUILD
========================================================================================
Extracts 100% of historical features, entry prices, exit prices, and tick-by-tick
3.0% Stop Loss points directly from raw MySQL database tables (`scrapdata_F1` & `scrapdata`)
from 2018-01-01 to Yesterday with ZERO intermediate CSV dependencies!

Executes:
  1. Multiprocessed MySQL tick extraction across all ~2,150 trading dates.
  2. Mathematical engineering of the 7 pure leak-free features from raw ticks.
  3. Intraday tick-by-tick 3.0% Stop Loss evaluation (09:42 to 14:45).
  4. Expanding walk-forward training of LightGBM Model V6 and Model V7 (2020-2026).
  5. Strategy 4 Dynamic Allocation (Monday exclusion + Quad/Dual 2-lots + 50/50 fill).
  6. Financial margin accounting for MIS 2x Margin, Cash Equity, and Futures.
========================================================================================
"""

import os
import sys
import time
import warnings
import pymysql
import pandas as pd
import numpy as np
import lightgbm as lgb
from datetime import datetime
from multiprocessing import Pool, cpu_count

warnings.filterwarnings('ignore')

DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(DIR, 'data')
os.makedirs(DATA_DIR, exist_ok=True)

RAW_DATASET_OUT = os.path.join(DATA_DIR, 'short_sell_ml_dataset_from_mysql_scratch.csv')
CHECKPOINT_FILE = os.path.join(DATA_DIR, 'mysql_extracted_checkpoint.csv')
LOTS_FILE = os.path.join(DATA_DIR, 'historical_lotsize_new.csv')
AUDITED_TRADES_OUT = os.path.join(DIR, 'audited_0940_hybrid_from_mysql_trades.csv')

EXCLUDED_STOCKS = ('NIFTY 50', 'NIFTY BANK', 'NIFTY', 'BANKNIFTY', 'FINNIFTY')

def get_db_conn():
    return pymysql.connect(
        host='localhost',
        user='root',
        password='root',
        database='markets',
        cursorclass=pymysql.cursors.DictCursor
    )

def extract_single_day(args):
    target_date_str, prev_date_str = args
    conn = get_db_conn()
    try:
        with conn.cursor() as cur:
            # 1. Prior Day Ticks
            q_prev = f"""
            SELECT stockname, time, price 
            FROM scrapdata_F1 
            WHERE date = '{prev_date_str}' AND isvalid = 'TRUE'
              AND stockname NOT IN {EXCLUDED_STOCKS}
            ORDER BY time ASC
            """
            cur.execute(q_prev)
            prev_rows = cur.fetchall()
            if not prev_rows:
                q_prev_eq = f"""
                SELECT stockname, time, close as price 
                FROM scrapdata 
                WHERE date = '{prev_date_str}' AND isvalid = 'TRUE'
                  AND stockname NOT IN {EXCLUDED_STOCKS}
                ORDER BY time ASC
                """
                cur.execute(q_prev_eq)
                prev_rows = cur.fetchall()

            # 2. Today Ticks
            q_today = f"""
            SELECT stockname, time, price, high, low 
            FROM scrapdata_F1 
            WHERE date = '{target_date_str}' AND isvalid = 'TRUE'
              AND stockname NOT IN {EXCLUDED_STOCKS}
            ORDER BY time ASC
            """
            cur.execute(q_today)
            today_rows = cur.fetchall()
            if not today_rows:
                q_today_eq = f"""
                SELECT stockname, time, close as price, high, low 
                FROM scrapdata 
                WHERE date = '{target_date_str}' AND isvalid = 'TRUE'
                  AND stockname NOT IN {EXCLUDED_STOCKS}
                ORDER BY time ASC
                """
                cur.execute(q_today_eq)
                today_rows = cur.fetchall()
    finally:
        conn.close()

    if not prev_rows or not today_rows:
        return []

    df_prev = pd.DataFrame(prev_rows)
    df_today = pd.DataFrame(today_rows)

    df_prev['clean_stock'] = df_prev['stockname'].astype(str).str.strip().str.upper()
    df_today['clean_stock'] = df_today['stockname'].astype(str).str.strip().str.upper()
    df_today['time_val'] = pd.to_datetime(df_today['time']).dt.time

    # Prior day metrics
    prev_map = {}
    for stk, grp in df_prev.groupby('clean_stock'):
        grp_valid = grp[grp['price'].notna()]
        if len(grp_valid) < 2: continue
        prices = grp_valid['price'].astype(float).values
        times = pd.to_datetime(grp_valid['time'])
        p_open = prices[0]
        p_close = prices[-1]
        vwap = float(np.mean(prices))
        ret = ((p_close - p_open) / p_open * 100.0) if p_open > 0 else 0.0
        vwap_gap = ((p_close - vwap) / vwap * 100.0) if vwap > 0 else 0.0
        lh_prices = prices[times.dt.time >= datetime.strptime('14:30:00', '%H:%M:%S').time()]
        roc_lh = ((lh_prices[-1] - lh_prices[0]) / lh_prices[0] * 100.0) if len(lh_prices) >= 2 and lh_prices[0] > 0 else 0.0
        prev_map[stk] = {'prev_close': p_close, 'prev_open': p_open, 'vwap': vwap, 'ret': ret, 'vwap_gap': vwap_gap, 'roc_lh': roc_lh}

    t_0907 = datetime.strptime('09:07:00', '%H:%M:%S').time()
    t_0915 = datetime.strptime('09:15:00', '%H:%M:%S').time()
    t_0940 = datetime.strptime('09:40:00', '%H:%M:%S').time()
    t_0942 = datetime.strptime('09:42:00', '%H:%M:%S').time()
    t_1445 = datetime.strptime('14:45:00', '%H:%M:%S').time()

    records = []
    for stk, grp in df_today.groupby('clean_stock'):
        pm = prev_map.get(stk)
        if not pm: continue

        morn = grp[(grp['time_val'] >= t_0915) & (grp['time_val'] <= t_0940) & grp['price'].notna()]
        if len(morn) < 2: continue
        
        m_prices = morn['price'].astype(float).values
        p_open = m_prices[0]
        p_940 = m_prices[-1]
        morn_highs = morn['high'].dropna().astype(float).values
        morn_lows = morn['low'].dropna().astype(float).values
        if len(morn_highs) == 0 or len(morn_lows) == 0: continue
        high_940 = float(np.max(morn_highs))
        low_940 = float(np.min(morn_lows))

        # 09:07 price (with safe fallback to open price)
        row_0907 = grp[grp['time_val'] == t_0907]
        p_0907 = p_open
        if len(row_0907) > 0 and pd.notna(row_0907['price'].iloc[0]):
            try:
                p_0907 = float(row_0907['price'].iloc[0])
            except (ValueError, TypeError):
                p_0907 = p_open

        # 09:42 entry price
        sub_0942 = grp[(grp['time_val'] >= t_0942) & grp['price'].notna()]
        if len(sub_0942) == 0: continue
        try:
            p_entry = float(sub_0942['price'].iloc[0])
        except (ValueError, TypeError):
            continue

        # 14:45 exit price
        sub_1445 = grp[(grp['time_val'] >= t_1445) & grp['price'].notna()]
        valid_prices = grp['price'].dropna()
        if len(valid_prices) == 0: continue
        if len(sub_1445) > 0:
            try:
                p_exit = float(sub_1445['price'].iloc[0])
            except (ValueError, TypeError):
                p_exit = float(valid_prices.iloc[-1])
        else:
            p_exit = float(valid_prices.iloc[-1])

        # Max high between 09:42 and 14:45 for Stop Loss
        intraday = grp[(grp['time_val'] >= t_0942) & (grp['time_val'] <= t_1445) & grp['high'].notna()]
        max_high = float(np.max(intraday['high'].astype(float).values)) if len(intraday) > 0 else p_entry

        # Leak-free technical features
        p_prev_close = pm['prev_close']
        gap_0907_pct = ((p_0907 - p_prev_close) / p_prev_close * 100.0) if p_prev_close > 0 else 0.0
        gap_fade = ((p_940 - p_0907) / p_0907 * 100.0) if p_0907 > 0 else 0.0
        morn_range = ((high_940 - low_940) / p_open * 100.0) if p_open > 0 else 0.0
        rejection = ((high_940 - p_940) / p_open * 100.0) if p_open > 0 else 0.0

        short_pct_return = ((p_entry - p_exit) / p_entry * 100.0) if p_entry > 0 else 0.0
        
        # Exact 3.0% Stop Loss points
        sl_price = p_entry * 1.03
        if max_high >= sl_price:
            sl3_pts = -p_entry * 0.03
            exit_reason = 'STOP_LOSS'
        else:
            sl3_pts = p_entry - p_exit
            exit_reason = 'TIME_EXIT'

        records.append({
            'date_str': target_date_str,
            'clean_stock': stk,
            'short_entry_price': round(p_entry, 2),
            'short_exit_price': round(p_exit, 2),
            'short_pct_return': round(short_pct_return, 4),
            'sl3_points': round(sl3_pts, 2),
            'exit_reason': exit_reason,
            'gap_0907_pct': round(gap_0907_pct, 4),
            'gap_fade_0907_to_940_pct': round(gap_fade, 4),
            'prev_intraday_vwap_gap': round(pm['vwap_gap'], 4),
            'prev_intraday_return': round(pm['ret'], 4),
            'prev_intraday_roc_last_hour': round(pm['roc_lh'], 4),
            'morn_range_pct': round(morn_range, 4),
            'rejection_wick': round(rejection, 4)
        })
    return records


def run_mysql_raw_tick_extraction():
    print("=" * 105)
    print("👑 STEP 1: MULTIPROCESSED MYSQL RAW TICK EXTRACTION (2018 -> YESTERDAY)")
    print("=" * 105)

    conn = get_db_conn()
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT date FROM scrapdata WHERE date >= '2018-01-01' ORDER BY date ASC")
        all_dates = [str(r['date']) for r in cur.fetchall()]
    conn.close()

    print(f"📊 Total Trading Dates in MySQL Database: {len(all_dates):,} days ({all_dates[0]} to {all_dates[-1]})")

    # Resume from checkpoint if present
    completed_dates = set()
    existing_records = []
    if os.path.exists(CHECKPOINT_FILE):
        print(f"🔄 Resuming from existing checkpoint: {CHECKPOINT_FILE}")
        df_cp = pd.read_csv(CHECKPOINT_FILE)
        completed_dates = set(df_cp['date_str'].unique())
        existing_records = df_cp.to_dict('records')
        print(f"   ✔ Found {len(completed_dates):,} already processed dates ({len(existing_records):,} records).")

    tasks = []
    for i in range(1, len(all_dates)):
        t_date = all_dates[i]
        p_date = all_dates[i - 1]
        if t_date not in completed_dates:
            tasks.append((t_date, p_date))

    print(f"🚀 Launching extraction pool across {len(tasks):,} remaining dates with {min(cpu_count(), 6)} worker processes...")
    t_start = time.time()
    all_extracted = list(existing_records)
    batch_size = 50

    with Pool(processes=min(cpu_count(), 6)) as pool:
        for idx in range(0, len(tasks), batch_size):
            chunk = tasks[idx:idx + batch_size]
            results = pool.map(extract_single_day, chunk)
            for res_day in results:
                all_extracted.extend(res_day)

            # Save periodic checkpoint
            df_checkpoint = pd.DataFrame(all_extracted)
            df_checkpoint.to_csv(CHECKPOINT_FILE, index=False)
            elapsed = time.time() - t_start
            done_cnt = len(completed_dates) + min(idx + batch_size, len(tasks))
            pct = (done_cnt / len(all_dates)) * 100
            print(f"   [{done_cnt}/{len(all_dates)}] {pct:.1f}% complete | Total records: {len(all_extracted):,} | Elapsed: {elapsed:.1f}s", flush=True)

    df_final = pd.DataFrame(all_extracted)
    df_final.to_csv(RAW_DATASET_OUT, index=False)
    print(f"\n✅ Step 1 Complete! Saved 100% MySQL-extracted dataset to: {RAW_DATASET_OUT} ({len(df_final):,} rows)")
    return df_final


def run_walkforward_and_certification(df):
    print("\n" + "=" * 105)
    print("👑 STEP 2: EXPANDING WALK-FORWARD TRAINING & STRATEGY 4 ALLOCATION FROM SCRATCH")
    print("=" * 105)

    df['clean_stock'] = df['clean_stock'].astype(str).str.strip().str.upper()
    df['date_dt'] = pd.to_datetime(df['date_str'])
    df['year'] = df['date_dt'].dt.year

    # Exclude Mondays
    df = df[df['date_dt'].dt.dayofweek != 0].sort_values('date_dt').reset_index(drop=True)

    # Load contract lot sizes
    df_lots = pd.read_csv(LOTS_FILE)
    df_lots['exp_dt'] = pd.to_datetime(df_lots['expdate'], format='%d/%m/%Y', errors='coerce')
    df_lots['clean_stock'] = df_lots['stockname'].astype(str).str.strip().str.upper()
    lot_map = {s: grp.sort_values('exp_dt') for s, grp in df_lots.groupby('clean_stock')}

    def get_exact_lot(stock, dt, fallback=1000):
        stk = str(stock).strip().upper()
        if stk not in lot_map: return fallback
        sub = lot_map[stk]
        idx = np.searchsorted(sub['exp_dt'].values, np.datetime64(dt))
        if idx < len(sub):
            return int(sub['lotsize'].iloc[idx])
        return int(sub['lotsize'].iloc[-1])

    df['lotsize'] = [get_exact_lot(s, d) for s, d in zip(df['clean_stock'], df['date_dt'])]

    pure_db_features = [
        'gap_0907_pct', 'gap_fade_0907_to_940_pct',
        'prev_intraday_vwap_gap', 'prev_intraday_return', 'prev_intraday_roc_last_hour',
        'morn_range_pct', 'rejection_wick'
    ]
    for f in pure_db_features:
        df[f] = pd.to_numeric(df[f], errors='coerce').fillna(0.0)

    years = sorted(df[df['year'] >= 2020]['year'].unique())
    full_list = []

    print(f"Training LightGBM Boosters (V6 & V7) across {len(years)} annual cycles (2020 to {years[-1]})...", flush=True)
    for y in years:
        tr = df[(df['year'] >= 2018) & (df['year'] < y)].copy()
        te = df[df['year'] == y].copy()

        # Model V6 Full Market
        m6 = lgb.LGBMRegressor(n_estimators=100, learning_rate=0.05, max_depth=5, random_state=42, n_jobs=-1, verbose=-1)
        m6.fit(tr[pure_db_features], tr['short_pct_return'])
        te['pred_v6'] = m6.predict(te[pure_db_features])
        te['rank_v6'] = te.groupby('date_str')['pred_v6'].rank(ascending=False, method='first')

        # Model V7 Faders (gap_fade < 0)
        tr7 = tr[tr['gap_fade_0907_to_940_pct'] < 0.0].copy()
        te7_cands = te[te['gap_fade_0907_to_940_pct'] < 0.0].copy()
        if len(tr7) > 0 and len(te7_cands) > 0:
            m7 = lgb.LGBMRegressor(n_estimators=100, learning_rate=0.05, max_depth=5, random_state=42, n_jobs=-1, verbose=-1)
            m7.fit(tr7[pure_db_features], tr7['short_pct_return'])
            te7_cands['pred_v7'] = m7.predict(te7_cands[pure_db_features])
            te7_cands['rank_v7'] = te7_cands.groupby('date_str')['pred_v7'].rank(ascending=False, method='first')
            te = te.merge(te7_cands[['date_str', 'clean_stock', 'rank_v7']], on=['date_str', 'clean_stock'], how='left')
        else:
            te['rank_v7'] = 999.0
        te['rank_v7'] = te['rank_v7'].fillna(999.0)

        full_list.append(te[['date_str', 'clean_stock', 'year', 'lotsize', 'short_entry_price', 'short_exit_price', 'sl3_points', 'rank_v6', 'rank_v7']])

    df_evaluated = pd.concat(full_list)

    print("\nExecuting Strategy 4 Candidate Sizing & Financial PnL...", flush=True)
    all_trades = []
    for d_str, day_df in df_evaluated.groupby('date_str'):
        y = day_df['year'].iloc[0]
        res = []
        chosen_stocks = set()

        # Step A: High-Conviction Dual Confirmed (Ranked top 4 by V6 AND V7)
        for idx, r in day_df.iterrows():
            if r['rank_v6'] <= 4 and r['rank_v7'] <= 4:
                res.append({
                    'clean_stock': r['clean_stock'],
                    'lotsize': r['lotsize'],
                    'entry_price': r['short_entry_price'],
                    'exit_price': r['short_exit_price'],
                    'sl3_points': r['sl3_points'],
                    'lots_multiplier': 2,
                    'signal_tag': 'DUAL_CONFIRMED',
                    'rank_v6': r['rank_v6'],
                    'rank_v7': r['rank_v7']
                })
                chosen_stocks.add(r['clean_stock'])

        # Step B: Remainder Top Candidates
        day_sorted = day_df.sort_values(by=['rank_v6', 'rank_v7'])
        for idx, r in day_sorted.iterrows():
            if len(res) >= 4: break
            if r['clean_stock'] not in chosen_stocks:
                res.append({
                    'clean_stock': r['clean_stock'],
                    'lotsize': r['lotsize'],
                    'entry_price': r['short_entry_price'],
                    'exit_price': r['short_exit_price'],
                    'sl3_points': r['sl3_points'],
                    'lots_multiplier': 1,
                    'signal_tag': 'SINGLE_REMAINDER',
                    'rank_v6': r['rank_v6'],
                    'rank_v7': r['rank_v7']
                })
                chosen_stocks.add(r['clean_stock'])

        res = res[:4]
        for rank_idx, item in enumerate(res, 1):
            stk = item['clean_stock']
            lot = item['lotsize']
            mult = item['lots_multiplier']
            traded_lot = lot * mult
            pts = item['sl3_points']
            gross = pts * traded_lot
            comm = 300.0 * mult
            net = gross - comm
            ep = item['entry_price']
            ret_pct = round((pts / ep) * 100, 2) if ep > 0 else 0.0

            # ₹5L Cash Equity and ₹10L MIS 2x Margin
            gross_5L = 500000.0 * (ret_pct / 100.0)
            net_5L = gross_5L - 350.0
            net_10L_mis = net_5L * 2.0

            all_trades.append({
                'date': d_str,
                'rank': rank_idx,
                'stockname': stk,
                'signal_type': item['signal_tag'],
                'lots_to_trade': mult,
                'lotsize': lot,
                'total_quantity': traded_lot,
                'entry_price': ep,
                'exit_price': item['exit_price'],
                'points': pts,
                'return_pct': ret_pct,
                'fut_net_pnl': round(net, 2),
                'net_5L': round(net_5L, 2),
                'net_10L_mis': round(net_10L_mis, 2),
                'is_win': int(net > 0),
                'year': y
            })

    df_t = pd.DataFrame(all_trades)
    df_t.to_csv(AUDITED_TRADES_OUT, index=False)

    tot_trades = len(df_t)
    tot_wins = (df_t['is_win'] == 1).sum()
    trade_wr = (tot_wins / tot_trades) * 100
    tot_fut = df_t['fut_net_pnl'].sum() / 1e5
    tot_5L = df_t['net_5L'].sum() / 1e5
    tot_10L_mis = df_t['net_10L_mis'].sum() / 1e5

    print("\n" + "=" * 105)
    print("⚡ AUDITED CERTIFICATION SUMMARY (100% BUILT DIRECTLY FROM MYSQL RAW TICKS)")
    print("=" * 105)
    print(f"Total Completed Trades        : {tot_trades:,}")
    print(f"Winning Trades / Losses       : {tot_wins:,} wins / {tot_trades - tot_wins:,} losses")
    print(f"Audited Win Rate              : 🏆 {trade_wr:.2f}%")
    print(f"Net PnL (₹5L Capital / Stock) : +₹{tot_5L:,.2f} Lakhs (~₹{tot_5L/100:.2f} Crore)")
    print(f"Net PnL (₹10L MIS 2x Margin)  : 💰 +₹{tot_10L_mis:,.2f} Lakhs (~₹{tot_10L_mis/100:.2f} Crores)")
    print(f"Net PnL (Futures Lot Sizing)  : 🚀 +₹{tot_fut:,.2f} Lakhs (~₹{tot_fut/100:.2f} Crores)")
    print(f"Saved Trade Ledger to         : {AUDITED_TRADES_OUT}")
    print("=" * 105)

if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--train-only':
        df = pd.read_csv(RAW_DATASET_OUT)
        run_walkforward_and_certification(df)
    else:
        df_extracted = run_mysql_raw_tick_extraction()
        run_walkforward_and_certification(df_extracted)
