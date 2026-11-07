#!/usr/bin/env python3
"""
live_0940_hybrid_pipeline.py
----------------------------
Production 09:40 AM IST Live Short-Sell Pipeline (Certified 1-Lot Setup).
Architecture: Single Model 09:42 Prediction.
Portfolio Allocation: 4 Orders, 1 Lot Each.

Key Operational Rules:
  - 4 Total Lots Daily Hard Budget.
  - Entry: Exact 09:42:00 AM IST.
  - Stop Loss: 3.0% Tick-by-Tick intraday SL.
  - Exit: 14:45:00 PM IST intraday square-off.
"""

import os
import sys
import time
import argparse
from datetime import datetime
import pandas as pd
import numpy as np
import pymysql
import subprocess
import lightgbm as lgb
import warnings

# Insert short-sell orders into DB for automated Kotak MIS placement
sys.path.insert(0, '/home/ubuntu/KotakCodes1')
try:
    from insert_shortsell_orders import insert_shortsell_orders as _insert_ss_orders
except ImportError:
    _insert_ss_orders = None

warnings.filterwarnings('ignore')

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = '/home/ubuntu/sarang_shortsell_t1_2026/02_0942_Hybrid_Model'
HIST_DATASET = '/home/ubuntu/sarang_verified_shorsellalgo_0940/data/0940_hybrid_dataset_from_scrapdata.csv'
MODEL_FILE = os.path.join(SCRIPT_DIR, 'lgb_0940_rebound_aware_audited_model.txt')
LOT_SIZE_FILE = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/config/historical_lotsize_new.csv'
PRED_CSV = os.path.join(SCRIPT_DIR, 'live_predictions_today.csv')
LEDGER_CSV = os.path.join(SCRIPT_DIR, 'daily_0940_live_ledger.csv')
AUDIT_CSV = os.path.join(BASE_DIR, 'audited_0940_hybrid_trades.csv')
LOCAL_AUDIT_CSV = os.path.join(SCRIPT_DIR, 'audited_0940_hybrid_trades.csv')
SARANG_DIR = BASE_DIR
CAPITAL_PER_TRADE = 1000000.0  # ₹10.0 Lakhs per trade notional (₹2.0L actual margin @ 5x MIS, Blueprint Frozen Invariant)

# 15 Upgraded Rebound-Aware & Cross-Sectional Alpha Features (M2_Exp3_Fixed_Pruned Blueprint):
# Pruned: dormant dip_zone_flag (0.05% gain) and skewed tail bear_mom_acceleration (-16.8 skew).
# Added: prev_candle_filling, sector_gap_dispersion, sector_return_dispersion, cross_sectional_gap_rank, stock_sortino.
PURE_DB_FEATURES = [
    'gap_0907_pct', 'gap_fade_0907_to_940_pct',
    'prev_intraday_vwap_gap', 'prev_intraday_return', 'prev_intraday_roc_last_hour',
    'morn_range_pct', 'rejection_wick',
    'ret_0940_vs_prev_close', 'crash_dip_bounce_risk', 'rebound_interaction',
    'prev_candle_filling', 'sector_gap_dispersion', 'sector_return_dispersion',
    'cross_sectional_gap_rank', 'stock_sortino'
]

# Legacy features still computed from live DB (kept for compatibility)
LEGACY_DB_FEATURES = [
    'gap_0907_pct', 'gap_fade_0907_to_940_pct', 'prev_intraday_vwap_gap',
    'prev_intraday_return', 'prev_intraday_roc_last_hour', 'morn_range_pct',
    'rejection_wick', 'prev_1450_to_1519_pct', 'Gap_Pct',
    'nifty_gap', 'sp500_overnight_ret', 'nikkei_gap',
    'nifty_vs_sp500_gap', 'nifty_vs_nikkei_gap'
]

def get_db_connection():
    return pymysql.connect(
        host='localhost',
        user='root',
        password='root',
        database='markets',
        cursorclass=pymysql.cursors.DictCursor
    )

def load_verified_lot_sizes():
    """Load verified contract lot sizes mapping."""
    if not os.path.exists(LOT_SIZE_FILE):
        return {}
    df_lots = pd.read_csv(LOT_SIZE_FILE)
    df_lots['stockname'] = df_lots['stockname'].astype(str).str.strip().str.upper()
    return dict(zip(df_lots['stockname'], df_lots['lotsize'].astype(int)))

def fetch_live_data(target_date_str, prev_date_str):
    """Fetch previous day indicators and today's morning ticks from MySQL markets DB."""
    conn = get_db_connection()

    # FIX: Blueprint Step 1 — Stripped foreign yfinance download to prevent network freeze/timeouts
    print("   • Using Pure Domestic Features (Zero Foreign API Dependency)...")
    macro = {
        'nifty_gap': 0.0, 'sp500_overnight_ret': 0.0,
        'nikkei_gap': 0.0, 'nifty_vs_sp500_gap': 0.0,
        'nifty_vs_nikkei_gap': 0.0
    }

    with conn.cursor() as cursor:
        print(f"   • Target Trading Date:    {target_date_str}")
        print(f"   • Prior Trading Date:     {prev_date_str}")

        q_prev = f"""
        SELECT TRIM(BOTH '\"' FROM TRIM(BOTH \"'\" FROM TRIM(stockname))) as clean_stock,
               time, CAST(price AS DECIMAL(10,2)) as price
        FROM scrapdata
        WHERE date = '{prev_date_str}' AND isvalid = 'TRUE'
          AND stockname NOT IN ('NIFTY 50', 'NIFTY BANK', 'NIFTY', 'BANKNIFTY', 'FINNIFTY')
        ORDER BY time ASC
        """
        cursor.execute(q_prev)
        df_prev_ticks = pd.DataFrame(cursor.fetchall())

        q_0907 = f"""
        SELECT TRIM(BOTH '\"' FROM TRIM(BOTH \"'\" FROM TRIM(stockname))) as clean_stock,
               CAST(price AS DECIMAL(10,2)) as price_0907
        FROM scrapdata
        WHERE date = '{target_date_str}' AND TIME(time) < '09:15:00' AND isvalid = 'TRUE'
        """
        cursor.execute(q_0907)
        df_0907 = pd.DataFrame(cursor.fetchall())

        q_morn = f"""
        SELECT TRIM(BOTH '\"' FROM TRIM(BOTH \"'\" FROM TRIM(stockname))) as clean_stock,
               time, CAST(price AS DECIMAL(10,2)) as price
        FROM scrapdata
        WHERE date = '{target_date_str}' AND TIME(time) >= '09:15:00' AND TIME(time) <= '09:40:00'
          AND isvalid = 'TRUE'
          AND stockname NOT IN ('NIFTY 50', 'NIFTY BANK', 'NIFTY', 'BANKNIFTY', 'FINNIFTY')
        ORDER BY time ASC
        """
        cursor.execute(q_morn)
        df_morn_ticks = pd.DataFrame(cursor.fetchall())

    conn.close()
    return df_prev_ticks, df_0907, df_morn_ticks, macro

def compute_features(df_prev_ticks, df_0907, df_morn_ticks, target_date_str, cl_stocks, macro):
    """Compute all required DB features."""
    prev_metrics = {}
    if len(df_prev_ticks) > 0:
        for stock, grp in df_prev_ticks.groupby('clean_stock'):
            prices = grp['price'].astype(float).values
            times = pd.to_datetime(grp['time'])
            if len(prices) < 5: continue
            open_p = prices[0]
            close_p = prices[-1]
            vwap = float(np.mean(prices))
            ret = (close_p - open_p) / open_p * 100.0 if open_p > 0 else 0.0
            vwap_gap = (close_p - vwap) / vwap * 100.0 if vwap > 0 else 0.0
            lh_mask = times.dt.time >= datetime.strptime('14:30:00', '%H:%M:%S').time()
            lh_prices = prices[lh_mask]
            roc_lh = ((lh_prices[-1] - lh_prices[0]) / lh_prices[0] * 100.0) if len(lh_prices) >= 2 and lh_prices[0] > 0 else 0.0
            t1450_mask = times.dt.time >= datetime.strptime('14:50:00', '%H:%M:%S').time()
            prices_1450_end = prices[t1450_mask]
            p_1450 = prices_1450_end[0] if len(prices_1450_end) > 0 else close_p
            prev_1450_ret = ((close_p - p_1450) / p_1450 * 100.0) if p_1450 > 0 else 0.0

            p_prev_high = float(np.max(prices))
            p_prev_low = float(np.min(prices))
            prev_candle_filling = float(np.clip((close_p - p_prev_low) / (p_prev_high - p_prev_low + 1e-9), 0.0, 1.0))

            prev_metrics[stock] = {
                'prev_close': close_p,
                'prev_intraday_return': ret,
                'prev_intraday_vwap_gap': vwap_gap,
                'prev_intraday_roc_last_hour': roc_lh,
                'prev_1450_to_1519_pct': prev_1450_ret,
                'prev_candle_filling': prev_candle_filling
            }

    map_0907 = dict(zip(df_0907['clean_stock'], df_0907['price_0907'].astype(float))) if len(df_0907) > 0 else {}

    records = []
    if len(df_morn_ticks) > 0:
        for stock, grp in df_morn_ticks.groupby('clean_stock'):
            prices = grp['price'].astype(float).values
            if len(prices) < 2: continue
            p_open = prices[0]
            p_940 = prices[-1]
            p_high = float(np.max(prices))
            p_low = float(np.min(prices))
            p_0907 = map_0907.get(stock, p_open)

            pm = prev_metrics.get(stock, {})
            p_prev_close = pm.get('prev_close', p_open)
            gap_0907_pct = ((p_0907 - p_prev_close) / p_prev_close * 100.0) if p_prev_close > 0 else 0.0
            gap_pct = ((p_open - p_prev_close) / p_prev_close * 100.0) if p_prev_close > 0 else 0.0
            
            # Match Historical Backtest Exactly: If pure 09:07 pre-market is missing, gap_fade is 0.0
            if stock in map_0907 and p_0907 > 0:
                gap_fade = ((p_940 - p_0907) / p_0907 * 100.0)
            else:
                gap_fade = 0.0
            morn_range = ((p_high - p_low) / p_open * 100.0) if p_open > 0 else 0.0
            rejection = ((p_high - p_940) / p_open * 100.0) if p_open > 0 else 0.0
            actual_stock_pct_940 = ((p_940 - p_prev_close) / p_prev_close * 100.0) if p_prev_close > 0 else 0.0

            records.append({
                'date_str': target_date_str,
                'clean_stock': stock,
                'prev_close': p_prev_close,
                'entry_price_0940': p_940,
                'actual_stock_pct_940': actual_stock_pct_940,
                'gap_0907_pct': gap_0907_pct,
                'gap_fade_0907_to_940_pct': gap_fade,
                'prev_intraday_vwap_gap': pm.get('prev_intraday_vwap_gap', 0.0),
                'prev_intraday_return': pm.get('prev_intraday_return', 0.0),
                'prev_intraday_roc_last_hour': pm.get('prev_intraday_roc_last_hour', 0.0),
                'morn_range_pct': morn_range,
                'rejection_wick': rejection,
                'prev_candle_filling': pm.get('prev_candle_filling', 0.5),
                'prev_1450_to_1519_pct': pm.get('prev_1450_to_1519_pct', 0.0),
                'Gap_Pct': gap_pct,
                'nifty_gap': macro.get('nifty_gap', 0.0),
                'sp500_overnight_ret': macro.get('sp500_overnight_ret', 0.0),
                'nikkei_gap': macro.get('nikkei_gap', 0.0),
                'nifty_vs_sp500_gap': macro.get('nifty_vs_sp500_gap', 0.0),
                'nifty_vs_nikkei_gap': macro.get('nifty_vs_nikkei_gap', 0.0),
                'is_in_cl': stock in cl_stocks
            })
    df_res = pd.DataFrame(records)
    if not df_res.empty:
        # Rebound-Aware & Momentum Acceleration Feature Engineering
        df_res['gap_0907_pct'] = pd.to_numeric(df_res['gap_0907_pct'], errors='coerce').fillna(0.0)
        df_res['gap_fade_0907_to_940_pct'] = pd.to_numeric(df_res['gap_fade_0907_to_940_pct'], errors='coerce').fillna(0.0)
        df_res['prev_intraday_return'] = pd.to_numeric(df_res['prev_intraday_return'], errors='coerce').fillna(0.0)
        df_res['morn_range_pct'] = pd.to_numeric(df_res['morn_range_pct'], errors='coerce').fillna(0.0)

        df_res['ret_0940_vs_prev_close'] = ((1.0 + df_res['gap_0907_pct']/100.0) * (1.0 + df_res['gap_fade_0907_to_940_pct']/100.0) - 1.0) * 100.0
        df_res['crash_dip_bounce_risk'] = np.where((df_res['prev_intraday_return'] < -2.5) & (df_res['ret_0940_vs_prev_close'] < 0.0), 1.0, 0.0)
        df_res['rebound_interaction'] = np.clip(df_res['prev_intraday_return'] * df_res['ret_0940_vs_prev_close'], -30.0, 30.0)

        # Cross-Sectional Alpha Dispersion & Clamped Sortino (M2_Exp3_Fixed_Pruned Blueprint):
        gap_mean = float(df_res['Gap_Pct'].mean()) if len(df_res) else 0.0
        ret_mean = float(df_res['ret_0940_vs_prev_close'].mean()) if len(df_res) else 0.0
        df_res['sector_gap_dispersion'] = df_res['Gap_Pct'] - gap_mean
        df_res['sector_return_dispersion'] = df_res['ret_0940_vs_prev_close'] - ret_mean
        df_res['cross_sectional_gap_rank'] = df_res['Gap_Pct'].rank(ascending=True, pct=True)
        df_res['stock_sortino'] = np.clip(df_res['prev_intraday_return'] / (df_res['morn_range_pct'] + 0.1), -10.0, 10.0)

    for f in PURE_DB_FEATURES:
        if f not in df_res.columns: df_res[f] = 0.0
        df_res[f] = pd.to_numeric(df_res[f], errors='coerce').fillna(0.0)
    return df_res

def load_historical_dataset_with_macro(dataset_path):
    print("   • Loading Historical Base Features and fetching historical macro data...")
    import yfinance as yf
    tickers = {'^NSEI': 'nifty', '^GSPC': 'sp500', '^N225': 'nikkei'}
    data = yf.download(list(tickers.keys()), start='2018-01-01', end='2026-12-31', progress=False, auto_adjust=True)
    df_close = data['Close'].reset_index(); df_open = data['Open'].reset_index()
    dates = pd.date_range(start='2018-01-01', end='2026-12-31', freq='B')
    features = pd.DataFrame({'date': dates})
    features['date_str'] = features['date'].dt.strftime('%Y-%m-%d')
    nifty_c = df_close[['Date', '^NSEI']].rename(columns={'Date': 'date', '^NSEI': 'nifty_close'})
    nifty_o = df_open[['Date', '^NSEI']].rename(columns={'Date': 'date', '^NSEI': 'nifty_open'})
    features = features.merge(nifty_c, on='date', how='left').merge(nifty_o, on='date', how='left')
    features['nifty_gap'] = (features['nifty_open'] / features['nifty_close'].shift(1)) - 1
    sp_c = df_close[['Date', '^GSPC']].rename(columns={'Date': 'date', '^GSPC': 'sp500_close'})
    features = features.merge(sp_c, on='date', how='left')
    features['sp500_overnight_ret'] = (features['sp500_close'].shift(1) / features['sp500_close'].shift(2)) - 1
    nikkei_c = df_close[['Date', '^N225']].rename(columns={'Date': 'date', '^N225': 'nikkei_close'})
    nikkei_o = df_open[['Date', '^N225']].rename(columns={'Date': 'date', '^N225': 'nikkei_open'})
    features = features.merge(nikkei_c, on='date', how='left').merge(nikkei_o, on='date', how='left')
    features['nikkei_gap'] = (features['nikkei_open'] / features['nikkei_close'].shift(1)) - 1
    for c in ['sp500_overnight_ret', 'nikkei_gap', 'nifty_gap']: 
        features[c] = features[c].fillna(0)
    features['nifty_vs_sp500_gap'] = features['nifty_gap'] - features['sp500_overnight_ret']
    features['nifty_vs_nikkei_gap'] = features['nifty_gap'] - features['nikkei_gap']
    global_macro = features[['date_str', 'nifty_gap', 'sp500_overnight_ret', 'nikkei_gap', 'nifty_vs_sp500_gap', 'nifty_vs_nikkei_gap']]
    df_hist = pd.read_csv(dataset_path, low_memory=False)
    
    # =========================================================================
    # CRITICAL FIX: PURGE F1 DATA FROM HISTORICAL DATASET
    # The raw dataset mixed F1 prices into `price_0907_unified`. We must recalculate 
    # the premarket features using ONLY pure EQ (`price_0907_eq`) and `Gap_Pct`.
    # =========================================================================
    if 'price_0907_eq' in df_hist.columns and 'prev_close' in df_hist.columns:
        df_hist['price_0907_eq'] = pd.to_numeric(df_hist['price_0907_eq'], errors='coerce')
        df_hist['prev_close'] = pd.to_numeric(df_hist['prev_close'], errors='coerce')
        df_hist['morning_close'] = pd.to_numeric(df_hist['morning_close'], errors='coerce')
        df_hist['Gap_Pct'] = pd.to_numeric(df_hist.get('Gap_Pct', 0), errors='coerce').fillna(0.0)

        df_hist['gap_0907_pct'] = np.where(
            df_hist['price_0907_eq'].notna() & df_hist['prev_close'].notna() & (df_hist['prev_close'] > 0),
            ((df_hist['price_0907_eq'] - df_hist['prev_close']) / df_hist['prev_close']) * 100.0,
            df_hist['Gap_Pct']
        )
        df_hist['gap_fade_0907_to_940_pct'] = np.where(
            df_hist['price_0907_eq'].notna() & (df_hist['price_0907_eq'] > 0) & df_hist['morning_close'].notna(),
            ((df_hist['morning_close'] - df_hist['price_0907_eq']) / df_hist['price_0907_eq']) * 100.0,
            0.0
        )
    # =========================================================================

    date_col = 'short_date' if 'short_date' in df_hist.columns else ('buy_day' if 'buy_day' in df_hist.columns else 'date_str')
    df_hist = df_hist.drop_duplicates(subset=[date_col, 'clean_stock'])
    if 'short_pct_return' in df_hist.columns:
        df_hist['short_pct_return'] = df_hist['short_pct_return'].clip(-15, 15)
    if 'short_entry_price' in df_hist.columns:
        df_hist = df_hist[df_hist['short_entry_price'] >= 50].reset_index(drop=True)
    df_hist = df_hist.merge(global_macro, left_on=date_col, right_on='date_str', how='left')
    return df_hist

def retrain_and_save_model():
    """
    Retrain the Audited Rebound-Aware LightGBM Model on the full verified historical 
    dataset (excluding Mondays, price >= 30) and save model booster to disk.
    """
    print("\n🔁 RETRAINING: 09:40 Audited Rebound-Aware LightGBM Model (Excl. Mondays | Top 4 Selection)...")
    if not os.path.exists(HIST_DATASET):
        raise FileNotFoundError(f"Audited historical dataset not found at {HIST_DATASET}")

    df_hist = pd.read_csv(HIST_DATASET, low_memory=False)
    df_hist['clean_stock'] = df_hist['clean_stock'].astype(str).str.strip().str.upper()
    df_hist['date_dt'] = pd.to_datetime(df_hist.get('date_str', df_hist.get('date', '')))

    # Strict Strategy Rule: Exclude Mondays (empirically destroys ₹19.23L net PnL)
    df_hist = df_hist[df_hist['date_dt'].dt.dayofweek != 0].copy()

    # Universal Penny Stock Liquidity & Circuit Trap Filter (entry price >= ₹30)
    df_hist['short_entry_price'] = pd.to_numeric(df_hist['short_entry_price'], errors='coerce').fillna(0.0)
    df_hist = df_hist[df_hist['short_entry_price'] >= 30.0].copy()

    # Purge any F1 contamination from historical pre-market features using pure EQ (price_0907_eq)
    if 'price_0907_eq' in df_hist.columns and 'prev_close' in df_hist.columns:
        df_hist['price_0907_eq'] = pd.to_numeric(df_hist['price_0907_eq'], errors='coerce')
        df_hist['prev_close'] = pd.to_numeric(df_hist['prev_close'], errors='coerce')
        df_hist['morning_close'] = pd.to_numeric(df_hist.get('morning_close', df_hist.get('short_entry_price')), errors='coerce')
        df_hist['Gap_Pct'] = pd.to_numeric(df_hist.get('Gap_Pct', 0), errors='coerce').fillna(0.0)

        df_hist['gap_0907_pct'] = np.where(
            df_hist['price_0907_eq'].notna() & df_hist['prev_close'].notna() & (df_hist['prev_close'] > 0),
            ((df_hist['price_0907_eq'] - df_hist['prev_close']) / df_hist['prev_close']) * 100.0,
            df_hist['Gap_Pct']
        )
        df_hist['gap_fade_0907_to_940_pct'] = np.where(
            df_hist['price_0907_eq'].notna() & (df_hist['price_0907_eq'] > 0) & df_hist['morning_close'].notna(),
            ((df_hist['morning_close'] - df_hist['price_0907_eq']) / df_hist['price_0907_eq']) * 100.0,
            0.0
        )

    # Engineer Rebound Propensity Features & Bear Momentum Acceleration
    df_hist['gap_0907_pct'] = pd.to_numeric(df_hist['gap_0907_pct'], errors='coerce').fillna(0.0)
    df_hist['gap_fade_0907_to_940_pct'] = pd.to_numeric(df_hist['gap_fade_0907_to_940_pct'], errors='coerce').fillna(0.0)
    df_hist['prev_intraday_return'] = pd.to_numeric(df_hist['prev_intraday_return'], errors='coerce').fillna(0.0)

    df_hist['ret_0940_vs_prev_close'] = ((1.0 + df_hist['gap_0907_pct']/100.0) * (1.0 + df_hist['gap_fade_0907_to_940_pct']/100.0) - 1.0) * 100.0
    df_hist['crash_dip_bounce_risk'] = np.where((df_hist['prev_intraday_return'] < -2.5) & (df_hist['ret_0940_vs_prev_close'] < 0.0), 1.0, 0.0)
    df_hist['rebound_interaction'] = np.clip(df_hist['prev_intraday_return'] * df_hist['ret_0940_vs_prev_close'], -30.0, 30.0)
    df_hist['prev_candle_filling'] = np.clip(df_hist['rejection_wick'], 0.0, 1.0)
    df_hist['sector_gap_dispersion'] = df_hist['gap_0907_pct'] - df_hist.groupby('date_str')['gap_0907_pct'].transform('mean')
    df_hist['sector_return_dispersion'] = df_hist['ret_0940_vs_prev_close'] - df_hist.groupby('date_str')['ret_0940_vs_prev_close'].transform('mean')
    df_hist['cross_sectional_gap_rank'] = df_hist.groupby('date_str')['gap_0907_pct'].rank(pct=True)
    df_hist['stock_sortino'] = np.clip(df_hist['prev_intraday_return'] / (df_hist['morn_range_pct'] + 0.1), -10.0, 10.0)

    for f in PURE_DB_FEATURES:
        if f not in df_hist.columns: df_hist[f] = 0.0
        df_hist[f] = pd.to_numeric(df_hist[f], errors='coerce').fillna(0.0)

    df_hist['short_target'] = pd.to_numeric(df_hist.get('short_pct_return', 0.0), errors='coerce').fillna(0.0)

    # Half-Yearly Expanding Window Cutoff (Jan 1 for H1, Jul 1 for H2)
    today_date = pd.Timestamp.today().normalize()
    cutoff_month = 7 if today_date.month >= 7 else 1
    cutoff_date = pd.Timestamp(year=today_date.year, month=cutoff_month, day=1)
    tr = df_hist[df_hist['date_dt'] < cutoff_date].copy()

    y_tr = tr['short_target'].values
    weights = np.where(y_tr < 0, 1.8, 1.0)
    trn_data = lgb.Dataset(tr[PURE_DB_FEATURES], label=y_tr, weight=weights)

    params = dict(
        objective='huber',
        alpha=1.0,
        metric='rmse',
        boosting_type='gbdt',
        learning_rate=0.05,
        max_depth=5,
        num_leaves=31,
        random_state=42,
        verbose=-1
    )
    mod = lgb.train(params, trn_data, num_boost_round=100)
    mod.save_model(MODEL_FILE)
    print(f"   ✅ Audited Rebound-Aware Huber (1.8x Downside Weight) Model saved → {MODEL_FILE}")
    print(f"      (Half-Yearly Cutoff < {cutoff_date.strftime('%Y-%m-%d')} | Trained on {len(tr):,} historical rows | {len(PURE_DB_FEATURES)} features)")
    return mod

def train_and_predict_single(df_today):
    # 1. Check if today is Monday
    import datetime as dt_module
    today_str = df_today['date_str'].iloc[0] if 'date_str' in df_today.columns else dt_module.date.today().strftime('%Y-%m-%d')
    today_dow = pd.Timestamp(today_str).dayofweek  # 0=Mon

    if today_dow == 0:
        print(f"\n📅 [MONDAY EXCLUSION] Today ({today_str}) is Monday.")
        print("   🚫 Audited model strictly excludes Monday trading (-₹19.23L net historical penalty on Mondays).")
        print("   ✅ Skipping all trades for today per audited specification.")
        return pd.DataFrame(), [], "📅 MONDAY (TRADING STRICTLY EXCLUDED PER AUDIT)"

    # 2. Load or Train Audited Model
    if os.path.exists(MODEL_FILE):
        print(f"\n2. Loading Pre-Trained Audited Rebound-Aware Model...")
        mod = lgb.Booster(model_file=MODEL_FILE)
        print(f"   ✔ Audited model loaded: {MODEL_FILE} ({len(mod.feature_name())} features)")
    else:
        print(f"\n2. ⚠️  Audited model not found — Training Rebound-Aware model now...")
        mod = retrain_and_save_model()

    print("   • Scoring today's candidates with 12 Rebound-Aware Features...")
    for f in PURE_DB_FEATURES:
        if f not in df_today.columns:
            df_today[f] = 0.0
        df_today[f] = pd.to_numeric(df_today[f], errors='coerce').fillna(0.0)
    df_today['pred_return'] = mod.predict(df_today[PURE_DB_FEATURES])
    df_ranked = df_today.sort_values('pred_return', ascending=False).reset_index(drop=True)


    # =========================================================
    # APPROVED FILTER RULES (Zero Look-Ahead, Proven on 7 Years)
    # =========================================================
    import datetime as dt_module
    today_str = df_ranked['date_str'].iloc[0] if 'date_str' in df_ranked.columns else dt_module.date.today().strftime('%Y-%m-%d')
    today_dow = pd.Timestamp(today_str).dayofweek  # 0=Mon

    # Fetch Nifty's live 09:40 price and prev close from DB
    try:
        import pymysql
        _conn = pymysql.connect(host='localhost', user='root', password='root', database='markets')
        _cur = _conn.cursor()
        
        # =========================================================================
        # CRITICAL NOTE: We explicitly use `scrapdata` (Equity Cash) here for the 
        # Nifty 50 Index. Using `scrapdata_F1` (Futures) causes false crash triggers 
        # on the Friday morning after expiry due to contract rollover premiums.
        # =========================================================================
        _cur.execute(f"""
            SELECT
              (SELECT price FROM scrapdata WHERE stockname='NIFTY 50' AND DATE(time) < '{today_str}' ORDER BY time DESC LIMIT 1) AS nifty_prev_close,
              (SELECT price FROM scrapdata WHERE stockname='NIFTY 50' AND DATE(time) = '{today_str}' AND TIME(time) >= '09:40:00' ORDER BY time ASC LIMIT 1) AS nifty_940_price
        """)
        _row = _cur.fetchone()
        _conn.close()
        nifty_prev_close = float(_row[0]) if _row and _row[0] else 0.0
        nifty_940_price  = float(_row[1]) if _row and _row[1] else 0.0
        nifty_pct = ((nifty_940_price - nifty_prev_close) / nifty_prev_close * 100.0) if (nifty_prev_close > 0 and nifty_940_price > 0) else 0.0
        print(f"\n   📊 FILTER INPUTS:")
        print(f"      Nifty Prev Close : {nifty_prev_close:.2f}")
        print(f"      Nifty @ 09:40    : {nifty_940_price:.2f}")
        print(f"      Nifty % Change   : {nifty_pct:+.2f}%")
        print(f"      Day of Week      : {'Monday' if today_dow==0 else ['Tue','Wed','Thu','Fri'][today_dow-1]}")

        print("   🔍 Checking 09:20-09:40 Market Breadth (Oversold Filter)...")
        breadth_win_rate = 50.0
        try:
            _bconn = pymysql.connect(host='localhost', user='root', password='root', database='markets')
            _bcur = _bconn.cursor()
            _bcur.execute(f"""
                SELECT stockname, TIME(time) as tm, close 
                FROM scrapdata 
                WHERE date = '{today_str}'
                AND TIME(time) IN ('09:20:00', '09:40:00')
            """)
            cur = _bcur
            rows = cur.fetchall()
            bdf = pd.DataFrame(rows, columns=['stockname', 'tm', 'close'])
            if not bdf.empty:
                pivot = bdf.pivot_table(index='stockname', columns='tm', values='close', aggfunc='last')
                if '09:20:00' in pivot.columns and '09:40:00' in pivot.columns:
                    pivot['ret'] = (pivot['09:40:00'] - pivot['09:20:00']) / pivot['09:20:00'] * 100
                    pivot = pivot.dropna()
                    if len(pivot) > 10:
                        breadth_win_rate = (pivot['ret'] > 0).mean() * 100
            print(f"      09:20-09:40 Win Rate: {breadth_win_rate:.1f}%")
            _bconn.close()
        except Exception as e:
            print(f"      ⚠️ Could not fetch market breadth: {e}")

    except Exception as e:
        print(f"   ⚠️ Could not fetch Nifty live data: {e}. Filters defaulting to Rule 1 only.")
        nifty_pct = 0.0

    # Compute exact stock % change from prev_close to 09:40
    if 'actual_stock_pct_940' in df_ranked.columns:
        df_ranked['stock_pct_940'] = pd.to_numeric(df_ranked['actual_stock_pct_940'], errors='coerce').fillna(0.0)
    elif 'entry_price_0940' in df_ranked.columns and 'prev_close' in df_ranked.columns:
        df_ranked['stock_pct_940'] = np.where(
            df_ranked['prev_close'] > 0,
            ((df_ranked['entry_price_0940'] - df_ranked['prev_close']) / df_ranked['prev_close']) * 100.0,
            0.0
        )
    elif 'entry_price_0940' in df_ranked.columns and 'Gap_Pct' in df_ranked.columns:
        df_ranked['stock_pct_940'] = ((1.0 + df_ranked['gap_0907_pct']/100.0) * (1.0 + df_ranked['gap_fade_0907_to_940_pct']/100.0) - 1.0) * 100.0
    else:
        df_ranked['stock_pct_940'] = 0.0

    def apply_rules(row):
        spct = row['stock_pct_940']

        # RULE 1: Skip if stock is down more than -1.5% (avoids severe rebound traps while allowing mild dips)
        if spct < -1.5:
            return False, "RULE1: Stock dropped > 1.5%"

        # RULE 2: Crash Day Protector
        # If Nifty is down more than -0.5%, be stricter on the stock
        if nifty_pct < -0.5 and spct < -0.5:
            return False, f"RULE2: Nifty({nifty_pct:+.2f}%) crash & Stock({spct:+.2f}%)"

        # RULE 3: Monday Danger Rule
        # Monday mornings have max buy-the-dip pressure, be stricter
        if today_dow == 0 and spct < -0.5:
            return False, f"RULE3: Monday & Stock({spct:+.2f}%)"

        # RULE 4: Extreme Oversold Protector
        # If fewer than 10% of stocks went up between 09:20 and 09:40, the market is severely crashed and bouncing.
        if breadth_win_rate < 10.0:
            return False, f"RULE4: Market Crashed! (Breadth Win% = {breadth_win_rate:.1f}%)"

        # RULE 5: VWAP Exhaustion Filter — DISABLED for Huber Model
        # The Huber Loss + Time-Decay model is inherently robust to VWAP-exhausted outlier setups
        # via its Huber objective. Backtesting (2020-2026) showed this filter reduces performance
        # with the Huber model:  2025: -2L, 2026: -1.5L vs keeping all trades.
        # ⟶ Re-enable if switching back to RMSE objective model.
        # prev_vwap_gap = row.get('prev_intraday_vwap_gap', 0.0)
        # if prev_vwap_gap < -0.52:
        #     return False, f"RULE5: VWAP Exhausted (Prev VWAP Gap = {prev_vwap_gap:+.2f}%)"

        return True, None



    # ===================================================================
    # AUDITED SELECTION & QUALIFIED REPLACEMENTS (Option A)
    # 1. Evaluate original Top 4 with Cutoff -1.5% (Rule 1) and Crash Protector (Rule 2).
    # 2. OPTION A CONSTRAINT: Replacements from Rank 5 and Rank 6 are ONLY
    #    permitted to replace stocks dropped by Rule 1 (stock_pct_940 < -1.5%).
    #    Stocks dropped by Rule 2 (Nifty crash), Rule 3, or Rule 4 remain EMPTY.
    # 3. Maximum replacements allowed = r1_dropped_count (capped by available slots).
    # 4. Replacement candidates must meet Quality Gate: stock_pct_940 >= -0.5%
    #    (and pass Crash/Breadth filters). If not met, slot remains empty.
    # ===================================================================
    # [UPDATE] Point-in-Time Non-Future Priority + Futures Backfill in Top-5
    lot_path = LOT_SIZE_FILE if os.path.exists(LOT_SIZE_FILE) else os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'historical_lotsize_new.csv')
    if not os.path.exists(lot_path):
        fallback_cfg = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'config', 'historical_lotsize_new.csv')
        if os.path.exists(fallback_cfg):
            lot_path = fallback_cfg
    if os.path.exists(lot_path):
        df_lots = pd.read_csv(lot_path, low_memory=False)
        df_lots['ym'], ym = pd.to_datetime(df_lots['expdate'], format='%d/%m/%Y', errors='coerce').dt.to_period('M'), pd.to_datetime(today_str).to_period('M')
        active_futs = set(df_lots[(df_lots['ym'] >= ym) & (df_lots['ym'] <= ym + 2)]['stockname'].str.strip().str.upper()) or set(df_lots[df_lots['ym'] >= df_lots['ym'].max() - 1]['stockname'].str.strip().str.upper())
    else:
        active_futs = set()
    df_ranked['in_pit_futures'] = df_ranked['clean_stock'].isin(active_futs)
    original_top4 = pd.concat([df_ranked.iloc[:5][~df_ranked.iloc[:5]['in_pit_futures']], df_ranked.iloc[:5][df_ranked.iloc[:5]['in_pit_futures']], df_ranked.iloc[5:]], ignore_index=True).head(4).copy()

    print(f"\n   🛡️ APPLYING FILTER RULES TO ORIGINAL TOP 4 CANDIDATES:")
    passed = []
    blocked_list = []
    r1_dropped_count = 0

    # Determine active market rule label
    if nifty_pct < -0.5:
        active_rule_msg = f"🔴 CRASH DAY (Nifty {nifty_pct:+.2f}%). Strict filters active."
    elif today_dow == 0:
        active_rule_msg = f"📅 MONDAY. Max buy-the-dip pressure. Strict filters active."
    else:
        active_rule_msg = f"🟢 NORMAL DAY (Nifty {nifty_pct:+.2f}%). Standard filters active."

    for idx, row in original_top4.iterrows():
        ok, reason = apply_rules(row)
        if ok:
            row_dict = row.to_dict()
            row_dict['model_rank'] = idx + 1
            row_dict['signal_type'] = f"TOP 4 (RANK {idx + 1})"
            passed.append(row_dict)
            print(f"      ✅ TRADING  Rank {idx + 1}: {row['clean_stock']:12} | stock%: {row['stock_pct_940']:+.2f}%")
        else:
            if "RULE1" in reason:
                r1_dropped_count += 1
            blocked_list.append({
                'stock': row['clean_stock'],
                'model_rank': idx + 1,
                'entry': float(row['entry_price_0940']),
                'qty': int(CAPITAL_PER_TRADE / float(row['entry_price_0940'])),
                'reason': reason
            })
            print(f"      ⛔ SKIPPED  Rank {idx + 1}: {row['clean_stock']:12} | stock%: {row['stock_pct_940']:+.2f}% | Reason: {reason}")

    # OPTION A: Qualified Replacements (Ranks 5 & 6) ONLY for Rule 1 drops
    reps_allowed = min(4 - len(passed), r1_dropped_count)
    if reps_allowed > 0 and len(df_ranked) > 4:
        print(f"\n   🔄 EVALUATING OPTION A REPLACEMENTS (Rule 1 drops: {r1_dropped_count}, Max Reps Allowed: {reps_allowed}):")
        reps_taken = 0
        for r_idx in range(4, min(6, len(df_ranked))):
            cand = df_ranked.iloc[r_idx]
            spct = cand['stock_pct_940']
            rank_num = r_idx + 1
            
            # Condition 1: Must be >= -0.5% (avoids chasing down moves / rebound trap)
            if spct < -0.5:
                print(f"      ⛔ REPLACEMENT SKIP Rank {rank_num}: {cand['clean_stock']:12} | stock%: {spct:+.2f}% < -0.5% (Rebound Trap Guard)")
                continue
                
            # Condition 2: Nifty crash protector
            if nifty_pct < -0.5 and spct < -0.5:
                print(f"      ⛔ REPLACEMENT SKIP Rank {rank_num}: {cand['clean_stock']:12} | Nifty Crash Filter")
                continue
                
            # Condition 3: Extreme oversold breadth protector
            if breadth_win_rate < 10.0:
                print(f"      ⛔ REPLACEMENT SKIP Rank {rank_num}: {cand['clean_stock']:12} | Market Crashed Breadth < 10%")
                continue
                
            cand_dict = cand.to_dict()
            cand_dict['model_rank'] = rank_num
            cand_dict['signal_type'] = f"REPLACEMENT (RANK {rank_num})"
            passed.append(cand_dict)
            reps_taken += 1
            print(f"      ✅ REPLACEMENT ACCEPTED Rank {rank_num}: {cand['clean_stock']:12} | stock%: {spct:+.2f}% (Rule 1 Replacement)")
            
            if reps_taken == reps_allowed or len(passed) == 4:
                break

    if not passed:
        print("   ⚠️ All candidates blocked. 0 trades today.")
        return pd.DataFrame(), blocked_list, active_rule_msg

    df_plan = pd.DataFrame(passed).reset_index(drop=True)
    df_plan['lots_to_trade'] = 1
    print(f"   ✅ Total {len(df_plan)} orders confirmed for execution.")
    return df_plan, blocked_list, active_rule_msg


def append_to_daily_ledger(target_date_str, df_plan):
    for f_path in [LEDGER_CSV, AUDIT_CSV, LOCAL_AUDIT_CSV]:
        try:
            if not os.path.exists(f_path):
                df_plan.to_csv(f_path, index=False)
                print(f"✔ Created new ledger: {f_path} with {len(df_plan)} order(s)")
            else:
                existing_df = pd.read_csv(f_path)
                if 'date_str' in existing_df.columns:
                    today_existing = existing_df[existing_df['date_str'] == target_date_str]
                    if len(today_existing) > 0 and 'pnl_net' in today_existing.columns and today_existing['pnl_net'].notna().any():
                        print(f"ℹ️ Ledger already contains COMPLETED trades for {target_date_str}; keeping reconciled entries.")
                        continue
                    existing_df = existing_df[existing_df['date_str'] != target_date_str]
                new_ledger = pd.concat([existing_df, df_plan], ignore_index=True)
                new_ledger.to_csv(f_path, index=False)
                print(f"✔ Appended {len(df_plan)} order(s) to ledger: {f_path} (Status: PENDING)")
        except Exception as e:
            print(f"⚠️ Could not append to {f_path}: {e}")

def format_telegram_alert(df_plan, target_date_str, blocked_stocks=None, active_rule_msg=None):
    day_name = pd.to_datetime(target_date_str).strftime('%A')
    n_traded  = len(df_plan)
    n_blocked = len(blocked_stocks) if blocked_stocks else 0
    lines = [
        f"📉 <b>HYBRID SHORT SELL ORDERS ({target_date_str} - {day_name})</b>",
        f"⏰ <b>Entry:</b> 09:42:00 AM IST | <b>Exit:</b> 4-Stage Dynamic Engine (14:45 PM)",
        f"🛡️ <b>Stop Loss:</b> 3.00% ➔ 1.50% ➔ 1.00% (3-Min Time-Decay) | <b>Budget:</b> Fixed ₹10.0L/Trade (₹2.0L Margin)",
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]

    if active_rule_msg:
        lines.append(f"📊 <b>Market Status:</b> {active_rule_msg}")
        lines.append(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    lines.append(f"🎯 <b>MODEL TOP 4 PREDICTIONS</b>  |  ✅ {n_traded} Trading  ⛔ {n_blocked} Skipped")
    lines.append(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    # Traded stocks
    for idx, row in df_plan.iterrows():
        stock = row['clean_stock']
        entry = float(row['entry_price_0940'])
        sl    = entry * 1.0300
        qty   = int(row.get('total_quantity', int(CAPITAL_PER_TRADE / entry)))
        sig   = row.get('signal_type', 'TOP 4')
        lines.append(f"✅ <b>{stock}</b>  <i>({sig})</i>")
        lines.append(f"  • <b>Action:</b> SHORT SELL {qty} QTY (₹10.0L Notional / ₹2.0L Margin)")
        lines.append(f"  • <b>Entry:</b> ₹{entry:,.2f}  |  <b>Initial SL (3.0%):</b> ₹{sl:,.2f}")
        lines.append(f"------------------------------------")

    # Skipped stocks — same card style, just marked ⛔
    if blocked_stocks:
        for b in blocked_stocks:
            entry = b.get('entry', 0)
            qty   = b.get('qty', 0)
            sl    = entry * 1.0300 if entry else 0
            lines.append(f"⛔ <b>{b['stock']}</b>  <i>(SKIPPED)</i>")
            lines.append(f"  • <b>Would have been:</b> SHORT SELL {qty} QTY (₹10.0L Notional / ₹2.0L Margin)")
            lines.append(f"  • <b>Price:</b> ₹{entry:,.2f}  |  <b>SL:</b> ₹{sl:,.2f}")
            lines.append(f"  • <b>Reason:</b> {b['reason']}")
            lines.append(f"------------------------------------")

    lines.append(f"")
    lines.append(f"⚡ <i>Automated — sarang_shortsell_t1_2026 09:42 Hybrid</i>")
    return "\n".join(lines)

def send_telegram_alert(message):
    bot_path = '/home/ubuntu/telegram_bot/New_OrderInfoBot.js'
    if not os.path.exists(bot_path):
        print("⚠️ Telegram bot script not found.")
        return
    escaped_msg = message.replace('"', '\\"')
    try:
        subprocess.run(['node', bot_path, escaped_msg], check=True)
    except Exception as e:
        print(f"⚠️ Failed to send Telegram alert: {e}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--date', type=str, help='Target date YYYY-MM-DD')
    parser.add_argument('--force-monday', action='store_true', help='Force execution on Monday (overrides Monday Lockout)')
    parser.add_argument('--retrain', action='store_true', help='Retrain Huber model and save (run on Fridays)')
    parser.add_argument('--no-telegram', action='store_true', help='Skip telegram alerts')
    args = parser.parse_args()

    # Weekly retrain mode — retrain and save model, then exit
    if args.retrain:
        retrain_and_save_model()
        print("\n✅ Retrain complete. Model saved. Exiting.")
        return

    import pytz
    target_date_str = args.date if args.date else datetime.now(pytz.timezone('Asia/Kolkata')).strftime('%Y-%m-%d')
    day_name = pd.to_datetime(target_date_str).strftime('%A')
    target_dt = pd.to_datetime(target_date_str)

    # Strict Monday Lockout (Rule 5: Monday buy-the-dip drag elimination)
    if target_dt.dayofweek == 0 and not args.force_monday:
        print(f"\n🚫 [MONDAY LOCKOUT ACTIVE] Date: {target_date_str} ({day_name})")
        print("   Model 2 strictly excludes Monday trading (-₹19.23L historical penalty). Exiting safely.")
        return

    print("="*83)
    print("🚀 LIVE 09:40 AM SHORT SELL MODEL (CERTIFIED 1-LOT TOP 4 SELECTION)")
    print("="*83)

    print(f"1. Fetching live MySQL data for {target_date_str} ({day_name})...")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(f"SELECT MAX(date) as dt FROM scrapdata WHERE date < '{target_date_str}'")
    prev_row = cursor.fetchone()
    prev_date_str = str(prev_row['dt']) if prev_row and prev_row['dt'] else None
    conn.close()

    if not prev_date_str:
        print("❌ Error: Unable to determine prior trading date.")
        return

    df_prev, df_0907, df_morn, macro = fetch_live_data(target_date_str, prev_date_str)
    if len(df_morn) == 0:
        print("❌ Error: No morning ticks found for today.")
        return

    print("3. Computing Features for active universe...")
    df_features = compute_features(df_prev, df_0907, df_morn, target_date_str, set(), macro)
    df_features = df_features[df_features['entry_price_0940'] >= 50].reset_index(drop=True)
    print(f"   • Total candidate stocks scored (Price >= ₹50): {len(df_features)}")

    df_plan, blocked_stocks, active_rule_msg = train_and_predict_single(df_features)

    if len(df_plan) == 0:
        print("⚠️ No trades selected for today (all blocked).")
        msg = format_telegram_alert(df_plan, target_date_str, blocked_stocks, active_rule_msg)
        print(msg)
        if not args.no_telegram:
            send_telegram_alert(msg)
        else:
            print("ℹ️ Telegram alert skipped (--no-telegram specified).")
        return

    print("\n" + "="*83)
    print(f"🏆 4-LOT LIVE SHORT SELL PLAN FOR {target_date_str} (TOTAL LOTS: 4 | ENTRY 09:42 AM)")
    print("="*83)

    df_plan['total_quantity'] = df_plan.apply(lambda x: int(CAPITAL_PER_TRADE / x['entry_price_0940']), axis=1)
    df_plan['stop_loss_2_25pct'] = df_plan['entry_price_0940'] * 1.0300

    print(df_plan[['clean_stock', 'signal_type', 'lots_to_trade', 'total_quantity', 'entry_price_0940', 'stop_loss_2_25pct']])

    df_plan['stockname'] = df_plan['clean_stock']
    df_plan['date'] = target_date_str
    df_plan['status'] = 'PENDING'
    df_plan['date_str'] = target_date_str
    df_plan.to_csv(PRED_CSV, index=False)
    print(f"\n✅ Saved live prediction orders to: {PRED_CSV}")
    append_to_daily_ledger(target_date_str, df_plan)

    # Insert into shortsell_orders table for automated Kotak MIS order placement
    print(f"\n📋 Inserting into shortsell_orders for Kotak MIS automation...")
    if _insert_ss_orders:
        _insert_ss_orders(df_plan, model_name='0942_HYBRID', trade_date=target_date_str, blocked_stocks=blocked_stocks)
    else:
        print("  ⚠️  insert_shortsell_orders not available — skipping DB insert")

    print("\n3. Formatting and sending Telegram Bot Alert...")
    msg = format_telegram_alert(df_plan, target_date_str, blocked_stocks, active_rule_msg)
    print(msg)
    if not args.no_telegram:
        send_telegram_alert(msg)
    else:
        print("ℹ️ Telegram alert skipped (--no-telegram specified).")
    print("\n🎉 Live 09:40 Certified Model Pipeline Completed Successfully!")

if __name__ == '__main__':
    main()
