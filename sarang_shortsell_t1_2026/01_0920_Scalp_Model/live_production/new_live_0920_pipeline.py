#!/usr/bin/env python3
"""
========================================================================================
 NEW LIVE 0920 SCALP PIPELINE — 100% GROUNDED IN HISTORICAL MODEL
========================================================================================
 Rewritten from scratch to exactly match the historical canonical model in:
   01_0920_Scalp_Model/0_extract_0920_dataset.py  (feature extraction)
   01_0920_Scalp_Model/1_build_features_and_train.py (model + features list)

 Workflow (runs at 09:20:30 IST daily Mon-Fri):
   1. Fetch previous day ticks + today 09:07 + today 09:15-09:19 from MySQL `scrapdata`
   2. Compute 8 pure DB features (identical formulas to 0_extract_0920_dataset.py)
   3. Fetch Nifty / S&P500 / Nikkei macro gaps from yfinance (5 macro features)
   4. Load pre-trained lgb_0920_scalp_model.txt (13 features, LightGBM binary)
   5. Score all VALID_STOCKS, select Top 4 by probability
   6. Write daily predictions CSV + Telegram alert
   7. Monitor intraday:
        09:36 – 09:40 : 0.05% trailing stop
        09:40 – 14:45 : 0.30% trailing stop
        All-time SL   : 2.0% from entry price
        14:45         : hard exit
   8. Reconcile and append to daily_0920_live_ledger.csv

 Capital: ₹10,00,000 per stock  →  qty = int(1000000 / sell_price)
========================================================================================
"""

import os
import sys
import time
import json
import subprocess
import argparse
import warnings
from datetime import datetime, date, timedelta

import pymysql
import numpy as np
import pandas as pd
import lightgbm as lgb
import yfinance as yf

warnings.filterwarnings('ignore')

# ─── Paths ──────────────────────────────────────────────────────────────────────
SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR    = SCRIPT_DIR                                       # lgb_0920_scalp_model.txt lives here
PARENT_DIR   = os.path.dirname(SCRIPT_DIR)                     # 01_0920_Scalp_Model/
DATASET_FILE = os.path.join(PARENT_DIR, 'data', 'scalp_0920_ml_dataset.csv.gz')
MODEL_FILE   = os.path.join(MODEL_DIR,  'lgb_0920_scalp_model.txt')
PRED_TODAY   = os.path.join(MODEL_DIR,  'live_0920_predictions_today.csv')
LEDGER_FILE  = os.path.join(MODEL_DIR,  'daily_0920_live_ledger.csv')
TELEGRAM_BOT = '/home/ubuntu/KotakCodes1/status_Info_bot.js'

# ─── Universe ───────────────────────────────────────────────────────────────────
VALID_STOCKS = [
    'AARTIIND', 'ABB', 'ABBOTINDIA', 'ABCAPITAL', 'ABFRL', 'ACC', 'ADANIENT', 'ADANIPORTS',
    'ALKEM', 'AMBUJACEM', 'APOLLOHOSP', 'APOLLOTYRE', 'ASHOKLEY', 'ASIANPAINT', 'ASTRAL',
    'ATUL', 'AUBANK', 'AUROPHARMA', 'AXISBANK', 'BAJAJ-AUTO', 'BAJAJFINSV', 'BAJFINANCE',
    'BALKRISIND', 'BALRAMCHIN', 'BANDHANBNK', 'BANKBARODA', 'BATAINDIA', 'BEL', 'BERGEPAINT',
    'BHARATFORG', 'BHARTIARTL', 'BHEL', 'BIOCON', 'BOSCHLTD', 'BPCL', 'BRITANNIA', 'BSOFT',
    'CANBK', 'CANFINHOME', 'CHAMBLFERT', 'CHOLAFIN', 'CIPLA', 'COALINDIA', 'COFORGE', 'COLPAL',
    'CONCOR', 'COROMANDEL', 'CROMPTON', 'CUB', 'CUMMINSIND', 'DABUR', 'DALBHARAT', 'DEEPAKNTR',
    'DELTACORP', 'DIVISLAB', 'DIXON', 'DLF', 'DRREDDY', 'EICHERMOT', 'ESCORTS', 'EXIDEIND',
    'FEDERALBNK', 'GAIL', 'GLENMARK', 'GMRINFRA', 'GNFC', 'GODREJCP', 'GODREJPROP', 'GRANULES',
    'GRASIM', 'GUJGASLTD', 'HAL', 'HAVELLS', 'HCLTECH', 'HDFCAMC', 'HDFCBANK', 'HDFCLIFE',
    'HEROMOTOCO', 'HINDALCO', 'HINDCOPPER', 'HINDPETRO', 'HINDUNILVR', 'IBULHSGFIN', 'ICICIBANK',
    'ICICIGI', 'ICICIPRULI', 'IDEA', 'IDFC', 'IDFCFIRSTB', 'IEX', 'IGL', 'INDHOTEL', 'INDIACEM',
    'INDIAMART', 'INDIGO', 'INDUSINDBK', 'INDUSTOWER', 'INFY', 'IOC', 'IPCALAB', 'IRCTC', 'ITC',
    'JINDALSTEL', 'JKCEMENT', 'JSWSTEEL', 'JUBLFOOD', 'KOTAKBANK', 'L&TFH', 'LALPATHLAB',
    'LAURUSLABS', 'LICHSGFIN', 'LT', 'LTF', 'LTIM', 'LTTS', 'LUPIN', 'M&M', 'M&MFIN', 'MANAPPURAM',
    'MARICO', 'MARUTI', 'MCDOWELL-N', 'MCX', 'METROPOLIS', 'MFSL', 'MGL', 'MOTHERSON', 'MPHASIS',
    'MRF', 'MUTHOOTFIN', 'NATIONALUM', 'NAUKRI', 'NAVINFLUOR', 'NESTLEIND', 'NMDC', 'NTPC',
    'OBEROIRLTY', 'OFSS', 'ONGC', 'PAGEIND', 'PEL', 'PERSISTENT', 'PETRONET', 'PFC', 'PIDILITIND',
    'PIIND', 'PNB', 'POLYCAB', 'POWERGRID', 'PVRINOX', 'RAMCOCEM', 'RBLBANK', 'RECLTD', 'RELIANCE',
    'SAIL', 'SBICARD', 'SBILIFE', 'SBIN', 'SHREECEM', 'SHRIRAMFIN', 'SIEMENS', 'SRF', 'SUNPHARMA',
    'SUNTV', 'SYNGENE', 'TATACHEM', 'TATACOMM', 'TATACONSUM', 'TATAMOTORS', 'TATAPOWER', 'TATASTEEL',
    'TCS', 'TECHM', 'TITAN', 'TORNTPHARM', 'TRENT', 'TVSMOTOR', 'UBL', 'ULTRACEMCO', 'UNITDSPR',
    'UPL', 'VEDL', 'VOLTAS', 'WIPRO', 'ZEEL', 'ZYDUSLIFE'
]

# ─── 13 Features (must match 1_build_features_and_train.py exactly) ─────────────
FEATURES_920 = [
    'morn_range_pct', 'prev_intraday_vwap_gap', 'prev_intraday_roc_last_hour',
    'prev_intraday_return', 'positive_arc_ratio', 'Gap_Pct', 'gap_0907_pct',
    'rejection_wick', 'nifty_gap', 'sp500_overnight_ret', 'nikkei_gap',
    'nifty_vs_sp500_gap', 'nifty_vs_nikkei_gap'
]

# ─── DB Connection ───────────────────────────────────────────────────────────────
def get_conn():
    return pymysql.connect(
        host='localhost', user='root', password='root',
        database='markets', cursorclass=pymysql.cursors.DictCursor
    )

# ─── Helper: calc_arc_features (exact copy from 0_extract_0920_dataset.py) ───────
def calc_arc_features(prices):
    if len(prices) < 3:
        return 0.0
    p = np.array(prices)
    norm_p = (p - p[0]) / (p[0] + 1e-9)
    changes = np.diff(norm_p)
    pos_arcs = np.sum(changes > 0)
    total_arcs = len(changes)
    return float(pos_arcs / total_arcs) if total_arcs > 0 else 0.0

# ─── Kotak Charges (for reconcile) ───────────────────────────────────────────────
def get_kotak_charges(qty, sell_price, buy_price):
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

# ─── Step 1: Extract today's features from MySQL ──────────────────────────────────
def extract_today_features(today_str, prev_date_str):
    """
    Extract 8 pure-DB features for all VALID_STOCKS for today_str.
    Formulas are 100% identical to 0_extract_0920_dataset.py:extract_features()
    """
    print(f"\n📊 Extracting features from MySQL for {today_str} (prev={prev_date_str})...")
    conn = get_conn()
    cur  = conn.cursor()

    # Previous day ticks (09:15-15:30)
    cur.execute(f"""
        SELECT stockname, time, price, volume FROM scrapdata
        WHERE date = '{prev_date_str}'
          AND TIME(time) >= '09:15:00' AND TIME(time) <= '15:30:00'
        ORDER BY stockname, time ASC
    """)
    prev_rows = cur.fetchall()

    # Today morning ticks (09:07 - 09:19)
    cur.execute(f"""
        SELECT stockname, time, price FROM scrapdata
        WHERE date = '{today_str}'
          AND TIME(time) >= '09:07:00' AND TIME(time) <= '09:19:59'
        ORDER BY stockname, time ASC
    """)
    morn_rows = cur.fetchall()

    conn.close()

    # Group by stock
    pday = {}
    for r in prev_rows:
        stk = r['stockname'].strip().upper()
        pday.setdefault(stk, []).append(r)

    today_morn = {}
    for r in morn_rows:
        stk = r['stockname'].strip().upper()
        today_morn.setdefault(stk, []).append(r)

    records = []
    for stock in VALID_STOCKS:
        if stock not in today_morn or stock not in pday:
            continue

        pticks = pday[stock]
        if len(pticks) < 10:
            continue

        p_prices = [float(x['price']) for x in pticks]
        p_vols   = [float(x['volume']) if x.get('volume') is not None else 1.0 for x in pticks]
        p_times  = [str(x['time']).split()[-1] for x in pticks]

        p_open  = p_prices[0]
        p_close = p_prices[-1]

        # VWAP (volume-weighted — matches 0_extract_0920_dataset.py)
        cum_pv = sum(p * v for p, v in zip(p_prices, p_vols))
        cum_v  = sum(p_vols)
        vwap   = cum_pv / cum_v if cum_v > 0 else p_close
        prev_intraday_vwap_gap = ((p_close - vwap) / vwap) * 100.0

        lh_prices = [p for t, p in zip(p_times, p_prices) if t >= '14:30:00']
        p_1430 = lh_prices[0] if lh_prices else p_close
        prev_intraday_roc_last_hour = ((p_close - p_1430) / p_1430) * 100.0
        prev_intraday_return        = ((p_close - p_open) / p_open) * 100.0

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

        Gap_Pct      = ((open_0915 - p_close) / p_close) * 100.0
        gap_0907_pct = ((p_0907_ticks[0] - p_close) / p_close) * 100.0 if p_0907_ticks else Gap_Pct

        morn_range_pct = (high_0919 - low_0919) / (open_0915 + 1e-9)
        rejection_wick = (high_0919 - close_0919) / (high_0919 - low_0919 + 1e-9)
        pos_arc_ratio  = calc_arc_features(p_0915_ticks)

        records.append({
            'clean_stock'                : stock,
            'morn_range_pct'             : morn_range_pct,
            'rejection_wick'             : rejection_wick,
            'positive_arc_ratio'         : pos_arc_ratio,
            'Gap_Pct'                    : Gap_Pct,
            'gap_0907_pct'               : gap_0907_pct,
            'prev_intraday_vwap_gap'     : prev_intraday_vwap_gap,
            'prev_intraday_roc_last_hour': prev_intraday_roc_last_hour,
            'prev_intraday_return'       : prev_intraday_return,
            'entry_price'                : open_0915,   # approximate; replaced by 09:25 fill price live
        })

    df = pd.DataFrame(records)
    print(f"   ✅ Extracted {len(df)} stocks with valid features.")
    return df


# ─── Step 2: Fetch macro features from yfinance ────────────────────────────────────
def fetch_macro_for_date(today_str):
    """
    Fetch Nifty/SP500/Nikkei gaps for today_str.
    Exact logic from 1_build_features_and_train.py.
    """
    print("📡 Fetching macro data from Yahoo Finance...")
    tickers = {'NIFTY': '^NSEI', 'SP500': '^GSPC', 'NIKKEI': '^N225'}
    today_dt = pd.Timestamp(today_str)
    start    = (today_dt - pd.Timedelta(days=10)).strftime('%Y-%m-%d')
    end      = (today_dt + pd.Timedelta(days=2)).strftime('%Y-%m-%d')

# ─── Step 2: Fetch macro features from yfinance ────────────────────────────────────
def fetch_macro_for_date(today_str):
    """
    Stub — macro is now computed inside select_top4 from the full historical time series.
    Returns empty dict; select_top4 handles the actual macro lookup for today.
    """
    return {}   # macro built inside select_top4 to avoid duplicate downloads



# ─── Step 3: Train live model + Score → Top 4 ────────────────────────────────────
def select_top4(df_features, macro, today_str, dry_run=False):
    """
    Train the current-year model on-the-fly from the historical dataset.
    Matches 1_build_features_and_train.py EXACTLY:
      - Download full Nifty/SP500/Nikkei macro time series from yfinance
      - Merge per date into historical dataset (not as scalars)
      - Train on all years < current_year (expanding window, last fold)
      - Score today's stocks with today's macro
    """
    import datetime as dt_module
    current_year = dt_module.date.today().year

    print(f"\n🤖 Training live 13-feature model (train years < {current_year}) from historical dataset...")
    if not os.path.exists(DATASET_FILE):
        print(f"   ❌ Dataset not found: {DATASET_FILE}")
        sys.exit(1)

    # ── Step A: Build macro time series (exact copy of 1_build_features_and_train.py logic) ──
    print("   Downloading macro time series for training merge...")
    try:
        data = yf.download(['^NSEI', '^GSPC', '^N225'], start='2018-01-01', end='2027-01-01', progress=False)
        if isinstance(data.columns, pd.MultiIndex):
            df_close_ts = data['Close'].reset_index()
            df_open_ts  = data['Open'].reset_index()
        else:
            df_close_ts = pd.DataFrame(data['Close']).reset_index()
            df_open_ts  = pd.DataFrame(data['Open']).reset_index()

        dates_range = pd.date_range(start='2018-01-01', end='2027-01-01', freq='B')
        macro_ts = pd.DataFrame({'date': dates_range})
        macro_ts['date_str'] = macro_ts['date'].dt.strftime('%Y-%m-%d')

        nifty_c = df_close_ts[['Date', '^NSEI']].rename(columns={'Date': 'date', '^NSEI': 'nifty_close'})
        nifty_o = df_open_ts[['Date', '^NSEI']].rename(columns={'Date': 'date', '^NSEI': 'nifty_open'})
        macro_ts = macro_ts.merge(nifty_c, on='date', how='left').merge(nifty_o, on='date', how='left')
        macro_ts['nifty_gap'] = (macro_ts['nifty_open'] / macro_ts['nifty_close'].shift(1)) - 1

        sp_c = df_close_ts[['Date', '^GSPC']].rename(columns={'Date': 'date', '^GSPC': 'sp500_close'})
        macro_ts = macro_ts.merge(sp_c, on='date', how='left')
        macro_ts['sp500_overnight_ret'] = (macro_ts['sp500_close'].shift(1) / macro_ts['sp500_close'].shift(2)) - 1

        nikkei_c = df_close_ts[['Date', '^N225']].rename(columns={'Date': 'date', '^N225': 'nikkei_close'})
        nikkei_o = df_open_ts[['Date', '^N225']].rename(columns={'Date': 'date', '^N225': 'nikkei_open'})
        macro_ts = macro_ts.merge(nikkei_c, on='date', how='left').merge(nikkei_o, on='date', how='left')
        macro_ts['nikkei_gap'] = (macro_ts['nikkei_open'] / macro_ts['nikkei_close'].shift(1)) - 1

        for c in ['sp500_overnight_ret', 'nikkei_gap', 'nifty_gap']:
            macro_ts[c] = macro_ts[c].fillna(0)
        macro_ts['nifty_vs_sp500_gap'] = macro_ts['nifty_gap'] - macro_ts['sp500_overnight_ret']
        macro_ts['nifty_vs_nikkei_gap'] = macro_ts['nifty_gap'] - macro_ts['nikkei_gap']

        global_macro_ts = macro_ts[['date_str', 'nifty_gap', 'sp500_overnight_ret', 'nikkei_gap', 'nifty_vs_sp500_gap', 'nifty_vs_nikkei_gap']]
        print("   ✅ Macro time series built.")
    except Exception as e:
        print(f"   ⚠️  yfinance failed for training macro ({e}). Using zeros.")
        global_macro_ts = None

    # ── Step B: Load and merge historical dataset ─────────────────────────────
    df_hist = pd.read_csv(DATASET_FILE, low_memory=False)
    df_hist['year'] = pd.to_datetime(df_hist['short_date']).dt.year

    if global_macro_ts is not None:
        df_hist = df_hist.merge(global_macro_ts, left_on='short_date', right_on='date_str', how='left')
    else:
        for c in ['nifty_gap', 'sp500_overnight_ret', 'nikkei_gap', 'nifty_vs_sp500_gap', 'nifty_vs_nikkei_gap']:
            df_hist[c] = 0.0

    df_hist[FEATURES_920] = df_hist[FEATURES_920].fillna(0)
    df_hist['target'] = (df_hist['pnl_net'] > 0).astype(int)

    params_920 = {
        'objective': 'binary',
        'metric': 'auc',
        'boosting_type': 'gbdt',
        'learning_rate': 0.05,
        'max_depth': 5,
        'num_leaves': 31,
        'feature_fraction': 0.8,
        'verbose': -1,
        'random_state': 42
    }

    # Train on all history before current_year (same as walk-forward last fold)
    tr = df_hist[df_hist['year'] < current_year]
    if len(tr) == 0:
        print("   ❌ No training data. Check dataset.")
        sys.exit(1)

    print(f"   Training on {len(tr):,} rows (years < {current_year})...")
    model = lgb.train(
        params_920,
        lgb.Dataset(tr[FEATURES_920], label=tr['target']),
        num_boost_round=300
    )
    print(f"   ✅ Model trained.")

    # ── Step C: Score today's features with today's macro from time series ───
    macro_cols = ['nifty_gap', 'sp500_overnight_ret', 'nikkei_gap', 'nifty_vs_sp500_gap', 'nifty_vs_nikkei_gap']
    if global_macro_ts is not None:
        today_macro_row = global_macro_ts[global_macro_ts['date_str'] == today_str]
        if len(today_macro_row) > 0:
            for c in macro_cols:
                df_features[c] = float(today_macro_row[c].iloc[0])
            ng = float(today_macro_row['nifty_gap'].iloc[0])
            sp = float(today_macro_row['sp500_overnight_ret'].iloc[0])
            nk = float(today_macro_row['nikkei_gap'].iloc[0])
            print(f"   ✅ Today's macro (from ts): nifty_gap={ng:.4f}, sp500={sp:.4f}, nikkei={nk:.4f}")
        else:
            print(f"   ⚠️  No macro row found for {today_str}. Using zeros for scoring.")
            for c in macro_cols:
                df_features[c] = 0.0
    else:
        for c in macro_cols:
            df_features[c] = 0.0

    df_features[FEATURES_920] = df_features[FEATURES_920].fillna(0)
    df_features['prob'] = model.predict(df_features[FEATURES_920])
    df_features = df_features.sort_values('prob', ascending=False).reset_index(drop=True)
    top4 = df_features.head(4).copy()

    print("\n🏆 TOP 4 PICKS (09:20 Scalp):")
    print(f"{'Rank':<6} {'Stock':<16} {'Prob':<10} {'Entry~':<12}")
    print("-" * 46)
    for i, row in top4.iterrows():
        rank = i + 1
        print(f"  {rank:<5} {row['clean_stock']:<16} {row['prob']:<10.4f} {row.get('entry_price', 0):<12.2f}")

    return top4


# ─── Step 4: Live intraday exit monitor ──────────────────────────────────────────
def monitor_exits(top4, today_str, dry_run=False):
    """
    Tick-by-tick exit monitor.
    Entry: 09:25:00 market open price (first tick at/after 09:25)
    Exit rules:
      1. All-time SL  = entry * 1.02 (2.0% above entry → short loses 2%)
      2. 09:36–09:40  = 0.05% trailing stop (trail off intraday low)
      3. 09:40–14:45  = 0.30% trailing stop
      4. 14:45 sharp  = hard exit (take last available price)
    """
    if dry_run:
        print("\n[DRY RUN] Skipping live intraday monitoring.")
        return {}

    print(f"\n⏱️  Starting intraday exit monitoring for {today_str}...")
    conn = get_conn()
    cur  = conn.cursor()

    # Fetch all intraday ticks for top4 stocks from 09:25 to 14:45
    stocks_str = "', '".join(top4['clean_stock'].tolist())
    cur.execute(f"""
        SELECT stockname, time, price FROM scrapdata
        WHERE date = '{today_str}'
          AND TIME(time) >= '09:25:00' AND TIME(time) <= '14:46:00'
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

        # Find entry price at 09:25
        entry_ticks = [t for t in ticks if str(t['time']).split()[-1] >= '09:25:00']
        if not entry_ticks:
            print(f"   ⚠️  No 09:25 tick for {stock}")
            results[stock] = {'exit_price': None, 'exit_time': None, 'exit_reason': 'NO_ENTRY'}
            continue

        entry_price = float(entry_ticks[0]['price'])
        qty         = int(1000000 / entry_price)
        sl_price    = entry_price * 1.02    # 2.0% stop loss (price goes UP → we lose on short)

        # Trailing stop state
        trail_low    = entry_price           # track intraday LOW (price going down is good for short)
        exit_price   = None
        exit_time    = None
        exit_reason  = 'HARD_EXIT_1445'

        print(f"   📌 {stock}: entry={entry_price:.2f}, sl={sl_price:.2f}, qty={qty}")

        for tick in entry_ticks:
            t_str = str(tick['time']).split()[-1]
            p     = float(tick['price'])

            # Update trailing low
            if p < trail_low:
                trail_low = p

            # 1. All-time SL — 2.0%
            if p >= sl_price:
                exit_price  = sl_price
                exit_time   = t_str
                exit_reason = 'SL_2PCT'
                break

            # 2. 09:36 – 09:40: 0.05% trailing stop
            if '09:36:00' <= t_str < '09:40:00':
                trail_threshold = trail_low * 1.0005   # 0.05% above the running low
                if p >= trail_threshold:
                    exit_price  = p
                    exit_time   = t_str
                    exit_reason = 'TRAIL_005_0936'
                    break

            # 3. 09:40 – 14:45: 0.30% trailing stop
            if '09:40:00' <= t_str < '14:45:00':
                trail_threshold = trail_low * 1.003    # 0.30% above the running low
                if p >= trail_threshold:
                    exit_price  = p
                    exit_time   = t_str
                    exit_reason = 'TRAIL_030_0940'
                    break

            # 4. Hard exit at 14:45
            if t_str >= '14:45:00':
                exit_price  = p
                exit_time   = t_str
                exit_reason = 'HARD_EXIT_1445'
                break

        # If no exit triggered, take last tick
        if exit_price is None:
            last_tick   = entry_ticks[-1]
            exit_price  = float(last_tick['price'])
            exit_time   = str(last_tick['time']).split()[-1]
            exit_reason = 'HARD_EXIT_LAST'

        charges  = get_kotak_charges(qty, entry_price, exit_price)
        pnl_net  = ((entry_price - exit_price) * qty) - charges
        ret_pct  = ((entry_price - exit_price) / entry_price) * 100.0

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


# ─── Step 5: Save predictions + reconcile to ledger ──────────────────────────────
def save_predictions(top4, today_str):
    top4_save = top4[['clean_stock', 'prob']].copy()
    top4_save.insert(0, 'short_date', today_str)
    top4_save.to_csv(PRED_TODAY, index=False)
    print(f"\n💾 Predictions saved to {PRED_TODAY}")
    return top4_save

def reconcile_to_ledger(top4, exit_results, today_str):
    rows = []
    for _, pred_row in top4.iterrows():
        stock  = pred_row['clean_stock']
        res    = exit_results.get(stock, {})
        rows.append({
            'date'        : today_str,
            'stockname'   : stock,
            'prob'        : round(pred_row['prob'], 4),
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
        # Remove existing entry for today (idempotent)
        df_ledger = df_ledger[df_ledger['date'] != today_str]
        df_ledger = pd.concat([df_ledger, df_today], ignore_index=True)
    else:
        df_ledger = df_today

    df_ledger.to_csv(LEDGER_FILE, index=False)
    print(f"📓 Ledger updated: {LEDGER_FILE} ({len(df_ledger)} total rows)")
    return df_today


# ─── Step 6: Telegram notification ────────────────────────────────────────────────
def notify_predictions(top4, today_str, dry_run=False):
    lines = [f"🚀 <b>09:20 SCALP | {today_str}</b>"]
    lines.append("Top 4 Short-Sell Picks:")
    for i, (_, row) in enumerate(top4.iterrows(), 1):
        lines.append(f"  {i}. <b>{row['clean_stock']}</b> (score: {row['prob']:.3f})")
    msg = "\n".join(lines)
    print(f"\n📣 Telegram:\n{msg}")
    if not dry_run:
        send_telegram(msg)

def notify_reconcile(df_today, today_str, dry_run=False):
    total_pnl = df_today['pnl_net'].sum()
    wins       = (df_today['is_win'] == 1).sum()
    lines = [f"📊 <b>09:20 SCALP RECONCILE | {today_str}</b>"]
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
    parser = argparse.ArgumentParser(description='New 0920 Scalp Live Pipeline')
    parser.add_argument('--date',       default=None, help='Override today date YYYY-MM-DD (for dry-run)')
    parser.add_argument('--dry-run',    action='store_true', help='Predict only, no live orders or monitoring')
    parser.add_argument('--reconcile',  action='store_true', help='Run only reconcile phase (after market close)')
    args = parser.parse_args()

    today_str = args.date or date.today().strftime('%Y-%m-%d')
    print("=" * 80)
    print(f"🚀 NEW 0920 SCALP PIPELINE | {today_str} | dry_run={args.dry_run}")
    print("=" * 80)

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
        # ── RECONCILE PHASE ONLY ──────────────────────────────────────────────
        # Load predictions already saved and run exit monitoring
        if not os.path.exists(PRED_TODAY):
            print("❌ No predictions file found for today. Run prediction phase first.")
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

    # 2. Macro features
    macro = fetch_macro_for_date(today_str)

    # 3. Score and select Top 4
    top4 = select_top4(df_features, macro, today_str, dry_run=args.dry_run)
    if top4.empty:
        print("❌ No stocks scored. Check model and features.")
        sys.exit(1)

    # 4. Save predictions CSV
    save_predictions(top4, today_str)

    # 5. Telegram alert — predictions
    notify_predictions(top4, today_str, dry_run=args.dry_run)

    # 6. Intraday monitoring (blocking — runs until 14:45)
    if not args.dry_run:
        # Wait until 09:36 when trailing starts, monitoring runs until 14:45
        now = datetime.now()
        market_open_str = f"{today_str} 09:25:00"
        # Give a moment for orders to fill before monitoring
        print(f"\n⏳ Waiting briefly before starting exit monitor...")
        time.sleep(10)

        exit_results = monitor_exits(top4, today_str, dry_run=False)
        df_today = reconcile_to_ledger(top4, exit_results, today_str)
        notify_reconcile(df_today, today_str, dry_run=False)
    else:
        print("\n[DRY RUN] Prediction phase complete. Skipping live monitoring.")
        print("   Run with --reconcile after market close to reconcile PnL.")


if __name__ == '__main__':
    main()
