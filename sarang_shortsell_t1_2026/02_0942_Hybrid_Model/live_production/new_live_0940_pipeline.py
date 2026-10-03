#!/usr/bin/env python3
"""
========================================================================================
 NEW LIVE 0940 HYBRID PIPELINE — 100% GROUNDED IN HISTORICAL MODEL
========================================================================================
 Rewritten from scratch to exactly match the historical canonical model in:
   02_0942_Hybrid_Model/full_mysql_raw_tick_extractor_and_rebuild.py  (feature extraction)
   02_0942_Hybrid_Model/rebuild_and_verify_from_scratch.py           (Strategy 4 selection)

 Workflow (runs at 09:41:30 IST daily Mon-Fri, SKIPS MONDAY):
   1. Skip if today is Monday (Strategy 4 core rule)
   2. Fetch prev-day ticks from MySQL `scrapdata_F1` (fallback: `scrapdata`)
      + today's 09:07, 09:15-09:40 ticks (same tables)
   3. Compute 7 pure-DB features (identical formulas to full_mysql_raw_tick_extractor_and_rebuild.py)
   4. Load 4 pre-trained models: v6_cl, v7_cl, v6_full, v7_full
   5. Load CL universe from markets_pnl0325.csv.gz (sell_exec_type='Custom Limit Fill')
   6. Apply Strategy 4 selection: Quad Confirmed → Dual Confirmed → Alternating 50/50 CL/Full
   7. Write daily predictions CSV + Telegram alert
   8. Monitor tick-by-tick:
        All-time SL: 3.0% from entry price (09:42 onward)
        Hard exit:   14:45:00 sharp
   9. Reconcile and append to daily_0940_live_ledger.csv

 Capital: ₹5,00,000 per stock  →  qty = int(500000 / entry_price)
========================================================================================
"""

import os
import sys
import time
import subprocess
import argparse
import warnings
from datetime import datetime, date

import pymysql
import numpy as np
import pandas as pd
import lightgbm as lgb

warnings.filterwarnings('ignore')

# ─── Paths ──────────────────────────────────────────────────────────────────────
SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR    = SCRIPT_DIR                                       # lgb_0940_*.txt files live here
PARENT_DIR   = os.path.dirname(SCRIPT_DIR)                     # 02_0942_Hybrid_Model/
DATA_DIR     = os.path.join(PARENT_DIR, 'data')

MODEL_V6_CL   = os.path.join(MODEL_DIR, 'lgb_0940_v6_cl.txt')
MODEL_V7_CL   = os.path.join(MODEL_DIR, 'lgb_0940_v7_cl.txt')
MODEL_V6_FULL = os.path.join(MODEL_DIR, 'lgb_0940_v6_full.txt')
MODEL_V7_FULL = os.path.join(MODEL_DIR, 'lgb_0940_v7_full.txt')
PNL_FILE      = os.path.join(DATA_DIR,  'markets_pnl0325.csv.gz')
PRED_TODAY    = os.path.join(MODEL_DIR,  'live_predictions_today.csv')
LEDGER_FILE   = os.path.join(MODEL_DIR,  'daily_0940_live_ledger.csv')
TELEGRAM_BOT  = '/home/ubuntu/KotakCodes1/status_Info_bot.js'

# ─── 7 pure-DB features (must match rebuild_and_verify_from_scratch.py exactly) ─
PURE_DB_FEATURES = [
    'gap_0907_pct', 'gap_fade_0907_to_940_pct',
    'prev_intraday_vwap_gap', 'prev_intraday_return', 'prev_intraday_roc_last_hour',
    'morn_range_pct', 'rejection_wick'
]

EXCLUDED_STOCKS = ('NIFTY 50', 'NIFTY BANK', 'NIFTY', 'BANKNIFTY', 'FINNIFTY')

# ─── DB Connection ───────────────────────────────────────────────────────────────
def get_conn():
    return pymysql.connect(
        host='localhost', user='root', password='root',
        database='markets', cursorclass=pymysql.cursors.DictCursor
    )

# ─── Kotak Charges ────────────────────────────────────────────────────────────────
def get_kotak_charges(qty, sell_price, buy_price):
    """Approximate Kotak brokerage + statutory charges for short-sell."""
    turnover = (qty * sell_price) + (qty * buy_price)
    stt      = round(qty * sell_price * 0.00025)
    txn      = turnover * 0.0000322
    sebi     = turnover * 0.000001
    stamp    = round(qty * buy_price * 0.00003)
    gst      = (40.0 + txn + sebi) * 0.18
    return round(40.0 + stt + txn + sebi + stamp + gst, 2)

# ─── Telegram alert ───────────────────────────────────────────────────────────────
def send_telegram(msg):
    try:
        subprocess.Popen(['node', TELEGRAM_BOT, msg], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        print(f"   ⚠️  Telegram send failed: {e}")

# ─── Step 1: Extract today's features from MySQL ─────────────────────────────────
def extract_today_features(today_str, prev_date_str):
    """
    Extract 7 pure-DB features for all stocks for today_str.
    Formulas exactly match full_mysql_raw_tick_extractor_and_rebuild.py:extract_single_day()

    Key formula differences from 0920 model:
      - vwap = np.mean(prices)  [UNWEIGHTED — NOT volume-weighted]
      - morn_range_pct = (high_940 - low_940) / p_open * 100.0   [as %, NOT ratio]
      - rejection_wick = (high_940 - p_940) / p_open * 100.0     [NOT normalized by range]
      - Source: scrapdata_F1 with fallback to scrapdata
    """
    print(f"\n📊 Extracting 0940 features from MySQL for {today_str} (prev={prev_date_str})...")
    conn = get_conn()
    cur  = conn.cursor()

    # ── Previous day ticks: try F1 first, fallback to EQ ──────────────────────
    cur.execute(f"""
        SELECT stockname, time, price FROM scrapdata_F1
        WHERE date = '{prev_date_str}' AND isvalid = 'TRUE'
          AND stockname NOT IN {EXCLUDED_STOCKS}
        ORDER BY time ASC
    """)
    prev_rows = cur.fetchall()
    if not prev_rows:
        cur.execute(f"""
            SELECT stockname, time, close as price FROM scrapdata
            WHERE date = '{prev_date_str}' AND isvalid = 'TRUE'
              AND stockname NOT IN {EXCLUDED_STOCKS}
            ORDER BY time ASC
        """)
        prev_rows = cur.fetchall()

    # ── Today ticks: try F1 first, fallback to EQ ─────────────────────────────
    cur.execute(f"""
        SELECT stockname, time, price, high, low FROM scrapdata_F1
        WHERE date = '{today_str}' AND isvalid = 'TRUE'
          AND stockname NOT IN {EXCLUDED_STOCKS}
        ORDER BY time ASC
    """)
    today_rows = cur.fetchall()
    if not today_rows:
        cur.execute(f"""
            SELECT stockname, time, close as price, high, low FROM scrapdata
            WHERE date = '{today_str}' AND isvalid = 'TRUE'
              AND stockname NOT IN {EXCLUDED_STOCKS}
            ORDER BY time ASC
        """)
        today_rows = cur.fetchall()

    conn.close()

    if not prev_rows or not today_rows:
        print("   ❌ No data found in MySQL for this date.")
        return pd.DataFrame()

    df_prev  = pd.DataFrame(prev_rows)
    df_today = pd.DataFrame(today_rows)

    df_prev['clean_stock']  = df_prev['stockname'].astype(str).str.strip().str.upper()
    df_today['clean_stock'] = df_today['stockname'].astype(str).str.strip().str.upper()
    df_today['time_val']    = pd.to_datetime(df_today['time']).dt.time

    t_0907 = datetime.strptime('09:07:00', '%H:%M:%S').time()
    t_0915 = datetime.strptime('09:15:00', '%H:%M:%S').time()
    t_0940 = datetime.strptime('09:40:00', '%H:%M:%S').time()

    # ── Previous day metrics ──────────────────────────────────────────────────
    prev_map = {}
    for stk, grp in df_prev.groupby('clean_stock'):
        grp_valid = grp[grp['price'].notna()]
        if len(grp_valid) < 2:
            continue
        prices = grp_valid['price'].astype(float).values
        times  = pd.to_datetime(grp_valid['time'])
        p_open  = prices[0]
        p_close = prices[-1]

        # UNWEIGHTED mean VWAP — exact match to extractor
        vwap     = float(np.mean(prices))
        ret      = ((p_close - p_open) / p_open * 100.0) if p_open > 0 else 0.0
        vwap_gap = ((p_close - vwap) / vwap * 100.0) if vwap > 0 else 0.0

        lh_mask   = times.dt.time >= datetime.strptime('14:30:00', '%H:%M:%S').time()
        lh_prices = prices[lh_mask.values]
        roc_lh    = ((lh_prices[-1] - lh_prices[0]) / lh_prices[0] * 100.0) if len(lh_prices) >= 2 and lh_prices[0] > 0 else 0.0

        prev_map[stk] = {
            'prev_close': p_close, 'prev_open': p_open,
            'vwap': vwap, 'ret': ret, 'vwap_gap': vwap_gap, 'roc_lh': roc_lh
        }

    # ── Today features ────────────────────────────────────────────────────────
    records = []
    for stk, grp in df_today.groupby('clean_stock'):
        pm = prev_map.get(stk)
        if not pm:
            continue

        # Morning ticks 09:15 – 09:40
        morn = grp[(grp['time_val'] >= t_0915) & (grp['time_val'] <= t_0940) & grp['price'].notna()]
        if len(morn) < 2:
            continue

        m_prices  = morn['price'].astype(float).values
        p_open    = m_prices[0]
        p_940     = m_prices[-1]

        morn_highs = morn['high'].dropna().astype(float).values
        morn_lows  = morn['low'].dropna().astype(float).values
        if len(morn_highs) == 0 or len(morn_lows) == 0:
            continue
        high_940 = float(np.max(morn_highs))
        low_940  = float(np.min(morn_lows))

        # 09:07 price (safe fallback to open)
        row_0907 = grp[grp['time_val'] == t_0907]
        p_0907   = p_open
        if len(row_0907) > 0 and pd.notna(row_0907['price'].iloc[0]):
            try:
                p_0907 = float(row_0907['price'].iloc[0])
            except (ValueError, TypeError):
                p_0907 = p_open

        # Feature formulas — exact match to extractor
        p_prev_close        = pm['prev_close']
        gap_0907_pct        = ((p_0907 - p_prev_close) / p_prev_close * 100.0) if p_prev_close > 0 else 0.0
        gap_fade            = ((p_940 - p_0907) / p_0907 * 100.0) if p_0907 > 0 else 0.0
        morn_range_pct      = ((high_940 - low_940) / p_open * 100.0) if p_open > 0 else 0.0   # as %, NOT ratio
        rejection_wick      = ((high_940 - p_940) / p_open * 100.0) if p_open > 0 else 0.0     # NOT normalized by range

        records.append({
            'clean_stock'               : stk,
            'gap_0907_pct'              : round(gap_0907_pct, 4),
            'gap_fade_0907_to_940_pct'  : round(gap_fade, 4),
            'prev_intraday_vwap_gap'    : round(pm['vwap_gap'], 4),
            'prev_intraday_return'      : round(pm['ret'], 4),
            'prev_intraday_roc_last_hour': round(pm['roc_lh'], 4),
            'morn_range_pct'            : round(morn_range_pct, 4),
            'rejection_wick'            : round(rejection_wick, 4),
            'entry_price'               : round(p_940, 2),          # approximate; actual entry = 09:42 tick
        })

    df = pd.DataFrame(records)
    print(f"   ✅ Extracted {len(df)} stocks with valid 0940 features.")
    return df


# ─── Step 2: Load CL universe ────────────────────────────────────────────────────
def load_cl_universe(today_str):
    """
    Load the Candidate List: stocks where sell_exec_type == 'Custom Limit Fill' on today_str.
    Matches rebuild_and_verify_from_scratch.py CL logic.
    """
    try:
        pnl = pd.read_csv(PNL_FILE, usecols=['simulationdate', 'stockname', 'sell_exec_type'])
        pnl['buy_day']     = pd.to_datetime(pnl['simulationdate'], format='mixed', dayfirst=True, errors='coerce').dt.strftime('%Y-%m-%d')
        pnl['clean_stock'] = pnl['stockname'].astype(str).str.strip().str.upper()
        cl_on_date = set(pnl[(pnl['sell_exec_type'] == 'Custom Limit Fill') & (pnl['buy_day'] == today_str)]['clean_stock'])
        print(f"   ✅ CL universe for {today_str}: {len(cl_on_date)} stocks")
        return cl_on_date
    except Exception as e:
        print(f"   ⚠️  Could not load CL universe ({e}). Using empty set.")
        return set()


# ─── Step 3: Train models on-the-fly and score ───────────────────────────────────
FEATURE_FILE = os.path.join(os.path.dirname(SCRIPT_DIR), 'data', 'short_sell_ml_dataset_from_mysql_scratch.csv')

def score_and_select_top4(df_features, cl_stocks_today):
    """
    Train 4 models on-the-fly from the historical v5_continuous dataset.
    Exact logic from rebuild_and_verify_from_scratch.py walk-forward training:
      - V6 CL: trained on CL subset (buy_day, stockname) from markets_pnl0325.csv.gz
      - V7 CL: trained on CL faders (gap_fade < 0)
      - V6 Full: trained on all stocks
      - V7 Full: trained on full faders
    Training: all rows where year < current_year (expanding window last fold)
    """
    import datetime as dt_module
    current_year = dt_module.date.today().year

    print(f"\n🤖 Training 4 models on-the-fly (year < {current_year}) from historical dataset...")
    if not os.path.exists(FEATURE_FILE):
        print(f"   ❌ Dataset not found: {FEATURE_FILE}")
        sys.exit(1)

    df_hist = pd.read_csv(FEATURE_FILE, low_memory=False)
    df_hist['clean_stock'] = df_hist['clean_stock'].astype(str).str.strip().str.upper()
    df_hist['date_dt'] = pd.to_datetime(df_hist['date_str'])
    df_hist['year'] = df_hist['date_dt'].dt.year

    # Monday exclusion (matches rebuild_and_verify_from_scratch.py line 55)
    df_hist = df_hist[df_hist['date_dt'].dt.dayofweek != 0].reset_index(drop=True)

    # Map CL universe from markets_pnl0325.csv.gz
    try:
        pnl = pd.read_csv(PNL_FILE, usecols=['simulationdate', 'stockname', 'sell_exec_type'])
        pnl['buy_day']     = pd.to_datetime(pnl['simulationdate'], format='mixed', dayfirst=True, errors='coerce').dt.strftime('%Y-%m-%d')
        pnl['clean_stock'] = pnl['stockname'].astype(str).str.strip().str.upper()
        cl_only = set(zip(pnl[pnl['sell_exec_type'] == 'Custom Limit Fill']['buy_day'],
                          pnl[pnl['sell_exec_type'] == 'Custom Limit Fill']['clean_stock']))
        if 'buy_day' in df_hist.columns:
            df_hist['is_strict_cl'] = [((b, s) in cl_only) for b, s in zip(df_hist['buy_day'], df_hist['clean_stock'])]
        else:
            df_hist['is_strict_cl'] = [((d, s) in cl_only) for d, s in zip(df_hist['date_str'], df_hist['clean_stock'])]
    except Exception as e:
        print(f"   ⚠️  Could not load CL universe for training ({e}). All training rows = non-CL.")
        df_hist['is_strict_cl'] = False

    for f in PURE_DB_FEATURES:
        if f not in df_hist.columns:
            df_hist[f] = 0.0
        df_hist[f] = pd.to_numeric(df_hist[f], errors='coerce').fillna(0.0)
    if 'short_target' not in df_hist.columns:
        df_hist['short_target'] = pd.to_numeric(df_hist.get('short_pct_return', df_hist.get('stock_ret_940', 0)), errors='coerce').fillna(0.0)

    params = dict(n_estimators=100, learning_rate=0.05, max_depth=5, random_state=42, n_jobs=-1, verbose=-1)

    # Training slice: year < current_year
    tr_full = df_hist[(df_hist['year'] >= 2018) & (df_hist['year'] < current_year)].copy()
    tr_cl   = tr_full[tr_full['is_strict_cl']].copy()

    print(f"   Training V6_Full on {len(tr_full):,} rows, V6_CL on {len(tr_cl):,} rows...")

    # V6 Full
    m6_full = lgb.LGBMRegressor(**params)
    m6_full.fit(tr_full[PURE_DB_FEATURES], tr_full['short_target'])

    # V7 Full (faders)
    tr7_full = tr_full[tr_full['gap_fade_0907_to_940_pct'] < 0.0].copy()
    m7_full = lgb.LGBMRegressor(**params)
    if len(tr7_full) > 0:
        m7_full.fit(tr7_full[PURE_DB_FEATURES], tr7_full['short_target'])
    else:
        m7_full = None

    # V6 CL
    m6_cl = lgb.LGBMRegressor(**params) if len(tr_cl) > 0 else None
    if m6_cl:
        m6_cl.fit(tr_cl[PURE_DB_FEATURES], tr_cl['short_target'])

    # V7 CL (faders)
    tr7_cl = tr_cl[tr_cl['gap_fade_0907_to_940_pct'] < 0.0].copy() if len(tr_cl) > 0 else pd.DataFrame()
    m7_cl = lgb.LGBMRegressor(**params) if len(tr7_cl) > 0 else None
    if m7_cl:
        m7_cl.fit(tr7_cl[PURE_DB_FEATURES], tr7_cl['short_target'])

    print("   ✅ All 4 models trained.")

    df = df_features.copy()
    df[PURE_DB_FEATURES] = df[PURE_DB_FEATURES].fillna(0.0)

    # Mark CL membership
    df['is_strict_cl'] = df['clean_stock'].isin(cl_stocks_today)

    # ── CL sub-dataframe ──────────────────────────────────────────────────────
    df_cl   = df[df['is_strict_cl']].copy()
    df_full = df.copy()

    if len(df_cl) > 0:
        df_cl['pred_v6_cl'] = m6_cl.predict(df_cl[PURE_DB_FEATURES])
        df_cl['rank_v6_cl'] = df_cl['pred_v6_cl'].rank(ascending=False, method='first')

        # V7 CL: faders only (gap_fade < 0)
        df7_cl = df_cl[df_cl['gap_fade_0907_to_940_pct'] < 0.0].copy()
        if len(df7_cl) > 0:
            df7_cl['pred_v7_cl'] = m7_cl.predict(df7_cl[PURE_DB_FEATURES])
            df7_cl['rank_v7_cl'] = df7_cl['pred_v7_cl'].rank(ascending=False, method='first')
            df_cl = df_cl.merge(df7_cl[['clean_stock', 'rank_v7_cl']], on='clean_stock', how='left')
        else:
            df_cl['rank_v7_cl'] = 999.0
        df_cl['rank_v7_cl'] = df_cl['rank_v7_cl'].fillna(999.0)
    else:
        print("   ⚠️  No CL stocks for today — using Full model only.")
        df_cl = pd.DataFrame(columns=df.columns.tolist() + ['pred_v6_cl', 'rank_v6_cl', 'rank_v7_cl'])

    # ── Full universe ─────────────────────────────────────────────────────────
    df_full['pred_v6_full'] = m6_full.predict(df_full[PURE_DB_FEATURES])
    df_full['rank_v6_full'] = df_full['pred_v6_full'].rank(ascending=False, method='first')

    df7_full = df_full[df_full['gap_fade_0907_to_940_pct'] < 0.0].copy()
    if len(df7_full) > 0:
        df7_full['pred_v7_full'] = m7_full.predict(df7_full[PURE_DB_FEATURES])
        df7_full['rank_v7_full'] = df7_full['pred_v7_full'].rank(ascending=False, method='first')
        df_full = df_full.merge(df7_full[['clean_stock', 'rank_v7_full']], on='clean_stock', how='left')
    else:
        df_full['rank_v7_full'] = 999.0
    df_full['rank_v7_full'] = df_full['rank_v7_full'].fillna(999.0)

    # ── Strategy 4 Selection ─────────────────────────────────────────────────
    res = []
    chosen_stocks = set()

    # Step A: Quad Confirmed (in both CL+FULL top4) and Dual Confirmed (top4 in either)
    dual_cands = []
    if len(df_cl) > 0:
        for _, r in df_cl.iterrows():
            if r['rank_v6_cl'] <= 4 and r['rank_v7_cl'] <= 4:
                dual_cands.append((r['clean_stock'], r['entry_price'], 'DUAL_CL', r['rank_v6_cl'], r['rank_v7_cl']))
    for _, r in df_full.iterrows():
        if r['rank_v6_full'] <= 4 and r['rank_v7_full'] <= 4:
            dual_cands.append((r['clean_stock'], r['entry_price'], 'DUAL_FULL', r['rank_v6_full'], r['rank_v7_full']))

    dual_stock_map = {}
    for stk, ep, src, rk6, rk7 in dual_cands:
        if stk not in dual_stock_map:
            dual_stock_map[stk] = {'entry_price': ep, 'sources': [src], 'rank_v6': rk6, 'rank_v7': rk7}
        else:
            dual_stock_map[stk]['sources'].append(src)

    sorted_duals = sorted(dual_stock_map.items(), key=lambda x: (len(x[1]['sources']) > 1, -x[1]['rank_v6']), reverse=True)
    for stk, info in sorted_duals:
        if len(res) >= 4:
            break
        is_quad = len(info['sources']) > 1
        res.append({
            'clean_stock' : stk,
            'entry_price' : info['entry_price'],
            'signal_tag'  : 'QUAD_CONFIRMED' if is_quad else 'DUAL_CONFIRMED',
            'source'      : 'QUAD (CL+FULL)' if is_quad else info['sources'][0],
            'rank_v6'     : info['rank_v6'],
            'rank_v7'     : info['rank_v7'],
        })
        chosen_stocks.add(stk)

    # Step B: Alternating 50/50 CL / Full fill for remaining slots
    cl_best   = []
    full_best = []

    if len(df_cl) > 0:
        for _, r in df_cl.sort_values(['rank_v6_cl', 'rank_v7_cl']).iterrows():
            if r['clean_stock'] not in chosen_stocks:
                cl_best.append((r['clean_stock'], r['entry_price'], 'SINGLE_CL', r['rank_v6_cl'], r['rank_v7_cl']))

    for _, r in df_full.sort_values(['rank_v6_full', 'rank_v7_full']).iterrows():
        if r['clean_stock'] not in chosen_stocks:
            full_best.append((r['clean_stock'], r['entry_price'], 'SINGLE_FULL', r['rank_v6_full'], r['rank_v7_full']))

    idx_cl = 0; idx_full = 0; toggle = True
    while len(res) < 4 and (idx_cl < len(cl_best) or idx_full < len(full_best)):
        if toggle and idx_cl < len(cl_best):
            stk, ep, tag, rk6, rk7 = cl_best[idx_cl]
            if stk not in chosen_stocks:
                res.append({'clean_stock': stk, 'entry_price': ep, 'signal_tag': tag, 'source': 'CL FILL', 'rank_v6': rk6, 'rank_v7': rk7})
                chosen_stocks.add(stk)
            idx_cl += 1; toggle = False
        elif idx_full < len(full_best):
            stk, ep, tag, rk6, rk7 = full_best[idx_full]
            if stk not in chosen_stocks:
                res.append({'clean_stock': stk, 'entry_price': ep, 'signal_tag': tag, 'source': 'FULL MARKET', 'rank_v6': rk6, 'rank_v7': rk7})
                chosen_stocks.add(stk)
            idx_full += 1; toggle = True
        elif idx_cl < len(cl_best):
            stk, ep, tag, rk6, rk7 = cl_best[idx_cl]
            if stk not in chosen_stocks:
                res.append({'clean_stock': stk, 'entry_price': ep, 'signal_tag': tag, 'source': 'CL FILL', 'rank_v6': rk6, 'rank_v7': rk7})
                chosen_stocks.add(stk)
            idx_cl += 1
        else:
            break

    top4 = pd.DataFrame(res[:4])

    print("\n🏆 TOP 4 PICKS (09:40 Hybrid):")
    print(f"{'Rank':<6} {'Stock':<16} {'Signal':<18} {'Source':<16} {'V6':<6} {'V7':<6}")
    print("-" * 70)
    for i, row in top4.iterrows():
        print(f"  {i+1:<5} {row['clean_stock']:<16} {row['signal_tag']:<18} {row['source']:<16} {row['rank_v6']:<6.0f} {row['rank_v7']:<6.0f}")

    return top4


# ─── Step 4: Intraday exit monitor ────────────────────────────────────────────────
def monitor_exits(top4, today_str, dry_run=False):
    """
    Tick-by-tick exit monitor for 0940 model.
    Entry: first tick at/after 09:42:00
    Exit rules:
      1. All-time SL: price goes UP 3.0% above entry → exit at sl_price
      2. Hard exit at 14:45:00 (take first available tick)
    """
    if dry_run:
        print("\n[DRY RUN] Skipping live intraday monitoring.")
        return {}

    print(f"\n⏱️  Starting 0940 intraday exit monitoring for {today_str}...")
    conn = get_conn()
    cur  = conn.cursor()

    stocks_str = "', '".join(top4['clean_stock'].tolist())

    # Try F1 first
    cur.execute(f"""
        SELECT stockname, time, price FROM scrapdata_F1
        WHERE date = '{today_str}'
          AND TIME(time) >= '09:42:00' AND TIME(time) <= '14:46:00'
          AND stockname IN ('{stocks_str}')
        ORDER BY stockname, time ASC
    """)
    rows = cur.fetchall()
    if not rows:
        cur.execute(f"""
            SELECT stockname, time, close as price FROM scrapdata
            WHERE date = '{today_str}'
              AND TIME(time) >= '09:42:00' AND TIME(time) <= '14:46:00'
              AND stockname IN ('{stocks_str}')
            ORDER BY stockname, time ASC
        """)
        rows = cur.fetchall()
    conn.close()

    tick_map = {}
    for r in rows:
        stk = r['stockname'].strip().upper()
        tick_map.setdefault(stk, []).append(r)

    results = {}
    for _, pred_row in top4.iterrows():
        stock = pred_row['clean_stock']
        ticks = tick_map.get(stock, [])

        if not ticks:
            print(f"   ⚠️  No intraday ticks for {stock}")
            results[stock] = {'exit_price': None, 'exit_time': None, 'exit_reason': 'NO_DATA'}
            continue

        entry_price = float(ticks[0]['price'])
        qty         = int(500000 / entry_price)
        sl_price    = entry_price * 1.03   # 3.0% stop loss

        exit_price  = None
        exit_time   = None
        exit_reason = 'HARD_EXIT_1445'

        print(f"   📌 {stock}: entry={entry_price:.2f}, sl={sl_price:.2f}, qty={qty}")

        for tick in ticks:
            t_str = str(tick['time']).split()[-1]
            p     = float(tick['price'])

            # 3.0% SL
            if p >= sl_price:
                exit_price  = sl_price
                exit_time   = t_str
                exit_reason = 'SL_3PCT'
                break

            # Hard exit at 14:45
            if t_str >= '14:45:00':
                exit_price  = p
                exit_time   = t_str
                exit_reason = 'HARD_EXIT_1445'
                break

        # Fallback: last tick
        if exit_price is None:
            last_tick   = ticks[-1]
            exit_price  = float(last_tick['price'])
            exit_time   = str(last_tick['time']).split()[-1]
            exit_reason = 'HARD_EXIT_LAST'

        charges = get_kotak_charges(qty, entry_price, exit_price)
        pnl_net = ((entry_price - exit_price) * qty) - charges
        ret_pct = ((entry_price - exit_price) / entry_price) * 100.0

        results[stock] = {
            'entry_price' : entry_price,
            'exit_price'  : exit_price,
            'exit_time'   : exit_time,
            'exit_reason' : exit_reason,
            'qty'         : qty,
            'pnl_net'     : round(pnl_net, 2),
            'ret_pct'     : round(ret_pct, 4),
            'is_win'      : int(pnl_net > 0),
        }
        emoji = "✅" if pnl_net > 0 else "❌"
        print(f"   {emoji} {stock}: exit={exit_price:.2f} @ {exit_time} [{exit_reason}] PnL=₹{pnl_net:,.0f}")

    return results


# ─── Step 5: Save predictions + reconcile ─────────────────────────────────────────
def save_predictions(top4, today_str):
    top4_save = top4.copy()
    top4_save.insert(0, 'short_date', today_str)
    top4_save.to_csv(PRED_TODAY, index=False)
    print(f"\n💾 Predictions saved to {PRED_TODAY}")

def reconcile_to_ledger(top4, exit_results, today_str):
    rows = []
    for _, pred_row in top4.iterrows():
        stock = pred_row['clean_stock']
        res   = exit_results.get(stock, {})
        rows.append({
            'date'        : today_str,
            'stockname'   : stock,
            'signal_tag'  : pred_row.get('signal_tag', ''),
            'source'      : pred_row.get('source', ''),
            'rank_v6'     : pred_row.get('rank_v6', None),
            'rank_v7'     : pred_row.get('rank_v7', None),
            'entry_price' : res.get('entry_price', None),
            'exit_price'  : res.get('exit_price', None),
            'exit_time'   : res.get('exit_time', None),
            'exit_reason' : res.get('exit_reason', None),
            'qty'         : res.get('qty', None),
            'pnl_net'     : res.get('pnl_net', None),
            'ret_pct'     : res.get('ret_pct', None),
            'is_win'      : res.get('is_win', None),
        })

    df_today = pd.DataFrame(rows)

    if os.path.exists(LEDGER_FILE):
        df_ledger = pd.read_csv(LEDGER_FILE)
        df_ledger = df_ledger[df_ledger['date'] != today_str]
        df_ledger = pd.concat([df_ledger, df_today], ignore_index=True)
    else:
        df_ledger = df_today

    df_ledger.to_csv(LEDGER_FILE, index=False)
    print(f"📓 Ledger updated: {LEDGER_FILE} ({len(df_ledger)} total rows)")
    return df_today


# ─── Step 6: Telegram notification ────────────────────────────────────────────────
def notify_predictions(top4, today_str, dry_run=False):
    lines = [f"🎯 <b>09:40 HYBRID | {today_str}</b>"]
    lines.append("Top 4 Short-Sell Picks:")
    for i, (_, row) in enumerate(top4.iterrows(), 1):
        lines.append(f"  {i}. <b>{row['clean_stock']}</b> [{row['signal_tag']}] via {row['source']}")
    msg = "\n".join(lines)
    print(f"\n📣 Telegram:\n{msg}")
    if not dry_run:
        send_telegram(msg)

def notify_reconcile(df_today, today_str, dry_run=False):
    total_pnl = df_today['pnl_net'].sum()
    wins       = (df_today['is_win'] == 1).sum()
    lines = [f"📊 <b>09:40 HYBRID RECONCILE | {today_str}</b>"]
    for _, row in df_today.iterrows():
        emoji = "✅" if row['is_win'] == 1 else "❌"
        lines.append(f"  {emoji} {row['stockname']}: ₹{row['pnl_net']:,.0f} [{row['exit_reason']}]")
    lines.append(f"\n<b>Total PnL: ₹{total_pnl:,.0f} | Wins: {wins}/{len(df_today)}</b>")
    msg = "\n".join(lines)
    print(f"\n📣 Reconcile Telegram:\n{msg}")
    if not dry_run:
        send_telegram(msg)


# ─── Main ─────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description='New 0940 Hybrid Live Pipeline')
    parser.add_argument('--date',      default=None, help='Override today date YYYY-MM-DD')
    parser.add_argument('--dry-run',   action='store_true', help='Predict only, no live monitoring')
    parser.add_argument('--reconcile', action='store_true', help='Run reconcile phase only (post-market)')
    args = parser.parse_args()

    today_str = args.date or date.today().strftime('%Y-%m-%d')
    today_dt  = datetime.strptime(today_str, '%Y-%m-%d')

    print("=" * 80)
    print(f"🎯 NEW 0940 HYBRID PIPELINE | {today_str} | dry_run={args.dry_run}")
    print("=" * 80)

    # ── Monday exclusion (core Strategy 4 rule) ────────────────────────────────
    if today_dt.weekday() == 0:  # 0 = Monday
        msg = f"⚠️  0940 HYBRID: Skipping Monday {today_str} (Strategy 4 Monday exclusion rule)."
        print(msg)
        send_telegram(f"⏸️ <b>09:40 HYBRID | {today_str}</b>\n{msg}")
        sys.exit(0)

    # ── Find previous trading day ──────────────────────────────────────────────
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute(f"SELECT MAX(date) as pd FROM scrapdata WHERE date < '{today_str}'")
    row = cur.fetchone()
    conn.close()
    if not row or not row['pd']:
        print("❌ Cannot find previous trading day in MySQL. Exiting.")
        sys.exit(1)
    prev_date_str = str(row['pd'])
    print(f"   Previous trading day: {prev_date_str}")

    if args.reconcile:
        if not os.path.exists(PRED_TODAY):
            print("❌ No predictions file found. Run prediction phase first.")
            sys.exit(1)
        top4 = pd.read_csv(PRED_TODAY)
        exit_results = monitor_exits(top4, today_str, dry_run=args.dry_run)
        df_today = reconcile_to_ledger(top4, exit_results, today_str)
        notify_reconcile(df_today, today_str, dry_run=args.dry_run)
        return

    # ── PREDICTION PHASE ──────────────────────────────────────────────────────

    # 1. Extract DB features
    df_features = extract_today_features(today_str, prev_date_str)
    if df_features.empty:
        print("❌ No features extracted. Check MySQL for today's data.")
        sys.exit(1)

    # 2. Load CL universe for today
    cl_stocks_today = load_cl_universe(today_str)

    # 3. Score and select Top 4 via Strategy 4
    top4 = score_and_select_top4(df_features, cl_stocks_today)
    if top4.empty:
        print("❌ No stocks selected. Check models and features.")
        sys.exit(1)

    # 4. Save predictions
    save_predictions(top4, today_str)

    # 5. Telegram — predictions
    notify_predictions(top4, today_str, dry_run=args.dry_run)

    # 6. Live monitoring
    if not args.dry_run:
        print(f"\n⏳ Waiting briefly before starting exit monitor...")
        time.sleep(10)
        exit_results = monitor_exits(top4, today_str, dry_run=False)
        df_today = reconcile_to_ledger(top4, exit_results, today_str)
        notify_reconcile(df_today, today_str, dry_run=False)
    else:
        print("\n[DRY RUN] Prediction phase complete. Skipping live monitoring.")


if __name__ == '__main__':
    main()
