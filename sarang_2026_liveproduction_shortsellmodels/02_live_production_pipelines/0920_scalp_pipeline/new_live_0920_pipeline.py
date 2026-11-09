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

 Capital: ₹5,00,000 per stock  →  qty = int(500000 / sell_price)
========================================================================================
"""

import os
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import time
import json, pickle
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
DATASET_FILE = os.path.join(SCRIPT_DIR, 'data', 'scalp_0920_ml_dataset.csv.gz')
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

# ─── 13 Features (matches 02_train_and_audit_0920.py / lgb_0920_scalp_model.txt exactly) ──
FEATURES_920 = [
    'morn_range_pct',
    'prev_intraday_vwap_gap',
    'prev_intraday_roc_last_hour',
    'prev_intraday_return',
    'positive_arc_ratio',
    'Gap_Pct',
    'gap_0907_pct',
    'rejection_wick',
    'nifty_gap',
    'sp500_overnight_ret',
    'nikkei_gap',
    'nifty_vs_sp500_gap',
    'nifty_vs_nikkei_gap'
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

    # Today morning ticks (09:07 - 09:20)
    cur.execute(f"""
        SELECT stockname, time, price FROM scrapdata
        WHERE date = '{today_str}'
          AND TIME(time) >= '09:07:00' AND TIME(time) <= '09:20:59'
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
    VALID_STOCKS = sorted(today_morn.keys())  # [UPDATE] Extract all dynamic morning F&O stocks (filtered by active_futs in select_top4)
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
        morn_15_19   = [x for x in mticks if '09:15:00' <= str(x['time']).split()[-1] <= '09:19:59']
        ticks_0920   = [float(x['price']) for x in mticks if str(x['time']).split()[-1] >= '09:20:00']
        if not morn_15_19:
            continue

        p_0915_ticks = [float(x['price']) for x in morn_15_19]
        open_0915  = p_0915_ticks[0]
        close_0919 = p_0915_ticks[-1]
        open_0920  = ticks_0920[0] if ticks_0920 else close_0919
        high_0919  = max(p_0915_ticks)
        low_0919   = min(p_0915_ticks)

        Gap_Pct      = ((open_0915 - p_close) / p_close) * 100.0
        gap_0907_pct = ((p_0907_ticks[0] - p_close) / p_close) * 100.0 if p_0907_ticks else Gap_Pct

        morn_range_pct = (high_0919 - low_0919) / (open_0915 + 1e-9)
        rejection_wick = (high_0919 - close_0919) / (high_0919 - low_0919 + 1e-9)
        pos_arc_ratio  = calc_arc_features(p_0915_ticks)

        records.append({
            'clean_stock'                : stock,
            'morn_range_pct'             : round(morn_range_pct, 8),
            'rejection_wick'             : round(rejection_wick, 8),
            'positive_arc_ratio'         : round(pos_arc_ratio, 6),
            'Gap_Pct'                    : round(Gap_Pct, 6),
            'gap_0907_pct'               : round(gap_0907_pct, 6),
            'prev_intraday_vwap_gap'     : round(prev_intraday_vwap_gap, 6),
            'prev_intraday_roc_last_hour': round(prev_intraday_roc_last_hour, 6),
            'prev_intraday_return'       : round(prev_intraday_return, 6),
            'entry_price'                : open_0915,   # approximate; replaced by 09:25 fill price live
            'open_0920'                  : open_0920,
        })

    df = pd.DataFrame(records)
    print(f"   ✅ Extracted {len(df)} stocks with valid features.")
    return df


# ─── Step 2: Fetch macro features from yfinance + MySQL ───────────────────────────
def fetch_macro_for_date(today_str, prev_date_str=None):
    """
    Fetch overnight macro features (Nifty, S&P 500, Nikkei 225) matching 02_train_and_audit_0920.py.
    Calculates:
      - nifty_gap: (nifty_open / nifty_close_prev) - 1
      - sp500_overnight_ret: (sp500_close_yesterday / sp500_close_day_before) - 1
      - nikkei_gap: (nikkei_open / nikkei_close_prev) - 1
      - nifty_vs_sp500_gap: nifty_gap - sp500_overnight_ret
      - nifty_vs_nikkei_gap: nifty_gap - nikkei_gap
    """
    print(f"📡 Fetching overnight global macro features for {today_str}...")
    macro = {
        'nifty_gap': 0.0,
        'sp500_overnight_ret': 0.0,
        'nikkei_gap': 0.0,
        'nifty_vs_sp500_gap': 0.0,
        'nifty_vs_nikkei_gap': 0.0
    }
    try:
        tickers = {'NIFTY': '^NSEI', 'SP500': '^GSPC', 'NIKKEI': '^N225'}
        data = yf.download(list(tickers.values()), period='15d', progress=False)
        if isinstance(data.columns, pd.MultiIndex):
            df_close = data['Close']
            df_open = data['Open']
        else:
            df_close = data[['^NSEI']]
            df_open = data[['^NSEI']]

        # 1. SP500 overnight return: (close[t-1] / close[t-2]) - 1
        df_close, df_open = df_close.reindex(pd.date_range(end=today_str, periods=15, freq='B')), df_open.reindex(pd.date_range(end=today_str, periods=15, freq='B'))
        sp_close = df_close['^GSPC'].iloc[:-1]
        if len(sp_close) >= 2:
            macro['sp500_overnight_ret'] = float((sp_close.iloc[-1] / sp_close.iloc[-2]) - 1)

        # 2. Nikkei gap: (open[t] / close[t-1]) - 1
        nikkei_open = df_open['^N225']
        nikkei_close = df_close['^N225']
        if len(nikkei_open) > 0 and len(nikkei_close) >= 2:
            macro['nikkei_gap'] = float((nikkei_open.iloc[-1] / nikkei_close.iloc[-2]) - 1)

        # 3. NIFTY gap: (open[t] / close[t-1]) - 1
        nifty_open_val = None
        nifty_prev_close = None

        date_strs = df_open.index.strftime('%Y-%m-%d').tolist()
        if today_str in date_strs:
            idx = date_strs.index(today_str)
            nifty_open_val = df_open['^NSEI'].iloc[idx]
            if idx > 0:
                nifty_prev_close = df_close['^NSEI'].iloc[idx - 1]

        # If today's open is not yet populated in yfinance, query MySQL scrapdata
        if pd.isna(nifty_open_val) or pd.isna(nifty_prev_close) or nifty_open_val is None:
            conn = get_conn()
            with conn.cursor() as cur:
                cur.execute(f"SELECT price FROM scrapdata WHERE stockname='NIFTY 50' AND date='{today_str}' AND TIME(time)>='09:07:00' ORDER BY time ASC LIMIT 1;")
                r_o = cur.fetchone()
                if r_o:
                    nifty_open_val = float(r_o['price'])
                p_date = prev_date_str
                if not p_date:
                    cur.execute(f"SELECT MAX(date) as pd FROM scrapdata WHERE date < '{today_str}'")
                    p_row = cur.fetchone()
                    if p_row and p_row['pd']:
                        p_date = str(p_row['pd'])
                if p_date:
                    cur.execute(f"SELECT price FROM scrapdata WHERE stockname='NIFTY 50' AND date='{p_date}' AND TIME(time)>='15:25:00' ORDER BY time DESC LIMIT 1;")
                    r_c = cur.fetchone()
                    if r_c:
                        nifty_prev_close = float(r_c['price'])
            conn.close()

        if nifty_open_val and nifty_prev_close and nifty_prev_close > 0 and not np.isnan(nifty_open_val):
            macro['nifty_gap'] = float((nifty_open_val / nifty_prev_close) - 1)
        else:
            macro['nifty_gap'] = 0.0

        for k in macro:
            if np.isnan(macro[k]):
                macro[k] = 0.0

        macro['nifty_vs_sp500_gap'] = macro['nifty_gap'] - macro['sp500_overnight_ret']
        macro['nifty_vs_nikkei_gap'] = macro['nifty_gap'] - macro['nikkei_gap']

        print(f"   ✅ Global Macro Features: {macro}")
    except Exception as e:
        print(f"   ⚠️ Warning: Macro fetch failed ({e}). Defaulting to 0.0.")

    return macro


# ─── Step 3: Load Pre-Trained Model & Score → Top 2 ─────────────────────────────
def select_top4(df_features, macro, today_str, dry_run=False, notional=750000.0):
    """
    Load pre-trained production model weights (lgb_0920_scalp_model.txt)
    and score candidate stocks using the exact 13 features.
    Sizing: int(notional / entry_price), defaulting to ₹7.5L (₹1.5L margin @ 5x MIS).
    """
    if not os.path.exists(MODEL_FILE):
        print(f"   ❌ Pre-trained model file not found: {MODEL_FILE}")
        sys.exit(1)

    print(f"\n🧠 Loading Pre-Trained 09:20 Production Model Weights:\n   • {MODEL_FILE}")
    model = lgb.Booster(model_file=MODEL_FILE)

    # Attach macro features to df_features
    for col in ['nifty_gap', 'sp500_overnight_ret', 'nikkei_gap', 'nifty_vs_sp500_gap', 'nifty_vs_nikkei_gap']:
        df_features[col] = float(macro.get(col, 0.0))

    df_features[FEATURES_920] = df_features[FEATURES_920].fillna(0.0)

    # [UPDATE] Filter to Point-in-Time Active F&O universe & score with 4-Checkpoint Trimmed Ensemble
    df_lots = pd.read_csv(os.path.join(SCRIPT_DIR, 'data', 'historical_lotsize_new.csv'), low_memory=False)
    df_lots['ym'], ym = pd.to_datetime(df_lots['expdate'], format='%d/%m/%Y', errors='coerce').dt.to_period('M'), pd.to_datetime(today_str).to_period('M')
    active_futs = set(df_lots[(df_lots['ym'] >= ym) & (df_lots['ym'] <= ym + 2)]['stockname'].str.strip().str.upper()) or set(df_lots[df_lots['ym'] >= df_lots['ym'].max() - 1]['stockname'].str.strip().str.upper())
    df_features, ens_mods = df_features[df_features['clean_stock'].isin(active_futs) & (df_features['entry_price'] >= 50)].copy().reset_index(drop=True), pickle.load(open(os.path.join(MODEL_DIR, 'lgb_0920_ens_checkpoints.pkl'), 'rb'))
    s_probs = np.sort(np.vstack([ens_mods[k].predict(df_features[FEATURES_920]) for k in ['day', 'week', 'month', 'year']]).T, axis=1)
    df_features['prob'] = 0.50 * pd.Series(model.predict(df_features[FEATURES_920])).rank(pct=True) + 0.50 * pd.Series((s_probs[:, 1] + s_probs[:, 2]) / 2.0).rank(pct=True)
    df_features = df_features.sort_values('prob', ascending=False).reset_index(drop=True)

    # Map input notional tier to intended actual margin & base notional (5x leverage)
    # 7.5L input -> ₹1.25L actual margin (₹6.25L base notional @ 5x)
    # 10L input  -> ₹2.00L actual margin (₹10.0L base notional @ 5x)
    # 20L input  -> ₹4.00L actual margin (₹20.0L base notional @ 5x)
    if 700000.0 <= notional <= 800000.0:
        target_margin = 125000.0
    elif 950000.0 <= notional <= 1050000.0:
        target_margin = 200000.0
    elif 1900000.0 <= notional <= 2100000.0:
        target_margin = 400000.0
    else:
        target_margin = round(notional / 5.0, 2)
    effective_notional = target_margin * 5.0

    # Select Top 2 Ranks Only (Rank 1 & Rank 2)
    top2 = df_features.head(2).copy()
    top2['quantity'] = top2['entry_price'].apply(lambda p: int(effective_notional / p) if pd.notna(p) and p > 0 else 0)

    print(f"\n🏆 TOP 2 PICKS (09:20 Scalp Verified Rolling 4-Freq Model | Input=₹{notional/100000.0:g}L -> Margin=₹{target_margin/100000.0:g}L @ 5x):")
    print(f"{'Rank':<6} {'Stock':<16} {'Prob':<10} {'Entry~':<12} {f'Qty (₹{target_margin/100000.0:g}L Mrgn)':<18}")
    print("-" * 64)
    for i, row in top2.iterrows():
        rank = i + 1
        print(f"  {rank:<5} {row['clean_stock']:<16} {row['prob']:<10.4f} ₹{row.get('entry_price', 0):<11.2f} {row.get('quantity', 0):<14}")

    return top2


# ─── Step 4: Live intraday exit monitor ──────────────────────────────────────────
def monitor_exits(top4, today_str, dry_run=False):
    """
    Tick-by-tick exit monitor (100% Single-Leg 3-Stage Trailing Strategy on ₹5L per stock).
    Entry: 09:25:00 market open price (first tick at/after 09:25)
    Exit rules:
      1. Stage 1 Initial SL (Peak PnL < +₹2,000): -₹5,000 (1.00% above entry)
      2. Stage 2 Profit Floor (+₹2,000 <= Peak PnL < +₹4,000): Lock +₹1,000 (+0.20%)
      3. Stage 3 Dynamic Profit Trail (Peak PnL >= +₹4,000): Lock (Peak PnL - ₹750)
      4. 09:36–09:39:30 Cadence: Exit if Net PnL >= +₹500
      5. 09:40:00 sharp: Hard exit
    """
    if dry_run:
        print("\n[DRY RUN] Skipping live intraday monitoring.")
        return {}

    print(f"\n⏱️  Starting intraday exit monitoring for {today_str}...")
    conn = get_conn()
    cur  = conn.cursor()

    # Fetch all intraday ticks for top4 stocks from 09:25 to 09:41
    stocks_str = "', '".join(top4['clean_stock'].tolist())
    cur.execute(f"""
        SELECT stockname, time, price FROM scrapdata
        WHERE date = '{today_str}'
          AND TIME(time) >= '09:25:00' AND TIME(time) <= '09:41:00'
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
        qty         = int(500000 / entry_price)
        sl_price    = min(entry_price + (5000.0 / max(qty, 1)), entry_price * 1.0100)

        trail_low    = entry_price
        max_pnl_rs   = 0.0
        exit_price   = None
        exit_time    = None
        exit_reason  = 'HARD_EXIT_0940'

        print(f"   📌 {stock}: entry={entry_price:.2f}, initial_sl={sl_price:.2f} (-₹5,000), qty={qty}")

        for tick in entry_ticks[1:]:
            t_str = str(tick['time']).split()[-1]
            p     = float(tick['price'])
            cur_pnl = (entry_price - p) * qty

            # Determine active protection from prior peak before updating peak on this tick, or after peak update
            if p < trail_low:
                trail_low = p
            max_pnl_rs = max(max_pnl_rs, (entry_price - trail_low) * qty)

            if max_pnl_rs >= 4000.0:
                locked_pnl = max_pnl_rs - 750.0
                active_stop_price = entry_price - (locked_pnl / max(qty, 1))
                stage_lbl = f"TRAIL_LOCK_+{int(locked_pnl)}"
            elif max_pnl_rs >= 2000.0:
                locked_pnl = 1000.0
                active_stop_price = entry_price - (1000.0 / max(qty, 1))
                stage_lbl = "FLOOR_LOCK_+1000"
            else:
                locked_pnl = -5000.0
                active_stop_price = sl_price
                stage_lbl = "INITIAL_SL_-5000"

            if p >= active_stop_price or cur_pnl <= locked_pnl:
                exit_price  = p
                exit_time   = t_str
                exit_reason = stage_lbl
                break

            if '09:36:00' <= t_str < '09:40:00':
                chg_est = get_kotak_charges(qty, entry_price, p)
                if (cur_pnl - chg_est) >= 500.0:
                    exit_price  = p
                    exit_time   = t_str
                    exit_reason = 'CADENCE_0936_500'
                    break

            if t_str >= '09:40:00':
                exit_price  = p
                exit_time   = t_str
                exit_reason = 'HARD_EXIT_0940'
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
def save_predictions(top4, today_str, dry_run=False):
    top4_save = top4[['clean_stock', 'prob']].copy()
    top4_save.insert(0, 'short_date', today_str)
    if not dry_run:
        top4_save.to_csv(PRED_TODAY, index=False)
        print(f"\n💾 Predictions saved to {PRED_TODAY}")
    else:
        print(f"\n[DRY RUN] Skipping overwrite of {PRED_TODAY}")
    
    return top4_save

def append_to_pending_ledger(top4, today_str):
    import pytz
    now_str = datetime.now(pytz.timezone('Asia/Kolkata')).strftime('%Y-%m-%d %H:%M:%S')
    new_rows = []
    for idx, row in top4.reset_index(drop=True).iterrows():
        new_rows.append({
            'date': today_str,
            'rank': idx + 1,
            'stockname': str(row['clean_stock']).strip().upper(),
            'short_prob': round(float(row['prob']), 4),
            'close_0919': round(float(row['entry_price']), 2),
            'lotsize': int(row['quantity']),
            'entry_time': '09:25:00',
            'entry_price': np.nan,
            'exit_time': '09:40:00',
            'exit_price': np.nan,
            'gross_pnl': np.nan,
            'charges': 300.0,
            'net_pnl': np.nan,
            'return_pct': np.nan,
            'status': 'PENDING',
            'predicted_at': now_str,
            'reconciled_at': np.nan,
            'qty': int(row['quantity']),
            'prob': round(float(row['prob']), 4)
        })
    df_new = pd.DataFrame(new_rows)
    if os.path.exists(LEDGER_FILE):
        try:
            df_ledger = pd.read_csv(LEDGER_FILE)
            already_done = ((df_ledger['date'] == today_str) & (df_ledger.get('status', '') == 'COMPLETED')).any()
            if not already_done:
                df_ledger = df_ledger[df_ledger['date'] != today_str]
                df_ledger = pd.concat([df_ledger, df_new], ignore_index=True)
                df_ledger.to_csv(LEDGER_FILE, index=False)
                print(f"📓 Ledger updated for {today_str} (Status: PENDING)")
            else:
                print(f"ℹ️ Date {today_str} already COMPLETED in ledger; skipped overwriting.")
        except Exception as e:
            print(f"⚠️ Error updating ledger: {e}")
    else:
        df_new.to_csv(LEDGER_FILE, index=False)
        print(f"📓 Created ledger with today's PENDING records.")

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
def notify_predictions(top4, today_str, dry_run=False, notional=750000.0):
    from datetime import datetime
    import pytz
    target_margin = 125000.0 if (700000.0 <= notional <= 800000.0) else (200000.0 if (950000.0 <= notional <= 1050000.0) else (400000.0 if (1900000.0 <= notional <= 2100000.0) else round(notional / 5.0, 2)))
    now_str = datetime.now(pytz.timezone('Asia/Kolkata')).strftime('%Y-%m-%d %H:%M:%S IST')
    lines = [
        f"⚡ <b>[09:20 SCALP ENGINE: ROLLING 4-FREQ TOP-2 SELECTION]</b>",
        f"📅 <b>Date:</b> {today_str} | ⏱️ <b>Generated:</b> {now_str}",
        f"🎯 <b>Execution Architecture:</b> 100% Single-Leg (₹{target_margin/100000.0:g}L Margin / ₹{target_margin*5.0/100000.0:g}L Notional @ 5x) | Option 2 (1.50% SL + 09:36 Cadence Exit)",
        f"📊 <b>Model Edge:</b> 80.64% Historical Win Rate | +₹1.71 Cr Net PnL (₹20L Notional)",
        "",
        f"<b>🔻 TARGET {len(top4)} SHORT-SELL ORDERS:</b>"
    ]

    for i, (_, row) in enumerate(top4.iterrows(), 1):
        stk = row['clean_stock']
        prob = row['prob'] * 100
        cmp_p = row['entry_price']
        lots = row['quantity']
        lines.append(f"  <b>{i}. {stk}</b>: Short Prob = <code>{prob:.1f}%</code> | CMP: ₹{cmp_p:.2f} | Lot: <b>{lots}</b>")

    lines.extend([
        "",
        "⏱️ <b>100% Single-Leg Execution & Protective Rules:</b>",
        f"• <b>09:25:00:</b> Initial Limit Sell (₹{target_margin/100000.0:g}L Actual Margin / ₹{target_margin*5.0/100000.0:g}L Notional @ 5x) placed on book",
        "• <b>09:27:00:</b> Cancel unfilled SELLs & arm 5s Kotak Quotes Trailing Engine",
        "• <b>Stage 1 Initial SL (Peak &lt; +₹2,000):</b> <b>-₹5,000 (1.00%)</b>",
        "• <b>Stage 2 Profit Floor (Peak +₹2,000 to +₹3,999):</b> Locks <b>+₹1,000 (+0.20%)</b>",
        "• <b>Stage 3 Dynamic Trail (Peak ≥ +₹4,000):</b> Trails <b>Peak - ₹750</b> (₹3,250, ₹4,250, ...)",
        "• <b>09:36:00–09:39:30:</b> 30s Cadence check (Lock profit if Net PnL ≥ ₹500)",
        "• <b>09:40:00:</b> Hard Square-Off cover for any remaining open short quantity"
    ])

    msg = "\n".join(lines)
    print(f"\n📣 Telegram:\n{msg}")
    if not dry_run:
        send_telegram(msg)

def notify_reconcile(df_today, today_str, dry_run=False):
    total_pnl = df_today['pnl_net'].sum() if 'pnl_net' in df_today else 0.0
    wins       = (df_today['is_win'] == 1).sum() if 'is_win' in df_today else 0
    lines = [f"📊 <b>09:20 SCALP RECONCILE | {today_str}</b>"]
    for _, row in df_today.iterrows():
        is_win_val = row.get('is_win', 0)
        pnl_val = row.get('pnl_net', 0.0)
        pnl_str = f"₹{pnl_val:,.0f}" if pnl_val is not None and not pd.isna(pnl_val) else "N/A"
        reason = row.get('exit_reason', 'PENDING')
        emoji = "✅" if is_win_val == 1 else "❌"
        lines.append(f"  {emoji} {row['stockname']}: {pnl_str} [{reason}]")
    tot_pnl_str = f"₹{total_pnl:,.0f}" if total_pnl is not None and not pd.isna(total_pnl) else "N/A"
    lines.append(f"\n<b>Total PnL: {tot_pnl_str} | Wins: {wins}/{len(df_today)}</b>")
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
    parser.add_argument('--notional',   type=float, default=750000.0, help='Notional capital per trade in ₹ (default 750000 = ₹7.5L, use 2000000 for ₹20L)')
    args = parser.parse_args()

    import pytz
    today_str = args.date or datetime.now(pytz.timezone('Asia/Kolkata')).strftime('%Y-%m-%d')
    print("=" * 80)
    print(f"🚀 NEW 0920 SCALP PIPELINE | {today_str} | Notional=₹{args.notional/100000.0:g}L | dry_run={args.dry_run}")
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
    macro = fetch_macro_for_date(today_str, prev_date_str)

    # 3. Score and select Top 2
    top4 = select_top4(df_features, macro, today_str, dry_run=args.dry_run, notional=args.notional)
    if top4.empty:
        print("❌ No stocks scored. Check model and features.")
        sys.exit(1)

    # 4. Save predictions CSV
    save_predictions(top4, today_str, dry_run=args.dry_run)

    # 4.5 Insert into shortsell_orders DB table for Kotak Neo MIS Execution
    if not args.dry_run:
        try:
            sys.path.append('/home/ubuntu/KotakCodes1')
            from insert_shortsell_orders import insert_shortsell_orders
            
            # 0920 needs 'close_0919' mapped to price and 'lotsize' or 'quantity'
            top4_for_insert = top4.copy()
            top4_for_insert['close_0919'] = top4_for_insert['entry_price']
            insert_shortsell_orders(top4_for_insert, model_name='0920_SCALP', trade_date=today_str)
        except Exception as e:
            print(f"⚠️ Could not insert into shortsell_orders table: {e}")
            
        # Append to live ledger with status PENDING for evening reconciliation
        try:
            append_to_pending_ledger(top4, today_str)
        except Exception as e:
            print(f"⚠️ Could not update ledger: {e}")
    else:
        print("\n[DRY RUN] Skipping insertion into shortsell_orders table and ledger.")

    # 5. Telegram alert — predictions
    notify_predictions(top4, today_str, dry_run=args.dry_run, notional=args.notional)

    print("\n✅ Morning prediction phase complete. Shortsell orders ready for Kotak Neo execution at 09:24:56 AM.")
    print("   Run with --reconcile after market close to reconcile PnL.")


if __name__ == '__main__':
    main()
