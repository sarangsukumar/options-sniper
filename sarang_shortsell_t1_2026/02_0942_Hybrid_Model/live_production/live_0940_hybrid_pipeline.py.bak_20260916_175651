#!/usr/bin/env python3
"""
live_0940_hybrid_pipeline.py
----------------------------
Production 09:40 AM IST Live Short-Sell Master Ensemble & Telegram Bot Alert Engine.
Architecture: Model V6 (Overextended Reversion) + Model V7 (Premarket Fader Sniper).
Portfolio Allocation: OPTION 2 DYNAMIC 4-LOTS BUDGET (Strict Total 4 Lots Max / Day).

Key Operational Rules:
  - 4 Total Lots Daily Hard Budget (never exceeds 4 lots across the entire portfolio).
  - High Conviction Dual/Quad Confirmed signals receive 2 Lots each (up to 4 lots total).
  - If 1 Dual Confirmed: 1 Dual (2 lots) + Top 1 CL Single (1 lot) + Top 1 Full Single (1 lot) = 4 lots total.
  - If 0 Dual Confirmed: Top 2 CL Singles (1 lot each) + Top 2 Full Singles (1 lot each) = 4 lots total.
  - Entry: Exact 09:42:00 AM IST.
  - Stop Loss: 3.0% Tick-by-Tick intraday SL.
  - Exit: 14:45:00 PM IST intraday square-off.
"""

import os
import sys
import argparse
import subprocess
import pymysql
import pandas as pd
import numpy as np
import lightgbm as lgb
from datetime import datetime, date
import warnings

warnings.filterwarnings('ignore')

# Base paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = '/home/ubuntu/sarang_2026_shortsell_algos/02_Best_Longer_Window_0942_1445'
HIST_DATASET = '/home/ubuntu/v5_from_scratch/data/short_sell_ml_dataset_v5_scratch.csv'
PNL_FILE = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/data/markets_pnl0325.csv'
LOTS_FILE = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/config/historical_lotsize_new.csv'
BOT_SCRIPT = '/home/ubuntu/KotakCodes1/status_Info_bot.js'
OUTPUT_CSV = os.path.join(SCRIPT_DIR, 'live_predictions_today.csv')
LEDGER_CSV = os.path.join(SCRIPT_DIR, 'daily_0940_live_ledger.csv')
SARANG_DIR = BASE_DIR

PURE_DB_FEATURES = [
    'gap_0907_pct',
    'gap_fade_0907_to_940_pct',
    'prev_intraday_vwap_gap',
    'prev_intraday_return',
    'prev_intraday_roc_last_hour',
    'morn_range_pct',
    'rejection_wick'
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
    if not os.path.exists(LOTS_FILE):
        return {}
    df_lots = pd.read_csv(LOTS_FILE)
    df_lots['exp_dt'] = pd.to_datetime(df_lots['expdate'], format='%d/%m/%Y', errors='coerce')
    df_lots['clean_stock'] = df_lots['stockname'].astype(str).str.strip().str.upper()
    lot_map = {}
    for stock, grp in df_lots.groupby('clean_stock'):
        lot_map[stock] = grp.sort_values('exp_dt')
    return lot_map

def get_exact_lot(stock, dt, lot_map, fallback=1000):
    stk = str(stock).strip().upper()
    if stk not in lot_map:
        return fallback
    sub = lot_map[stk]
    f = sub[sub['exp_dt'] >= dt]
    if len(f) > 0:
        return int(f.iloc[0]['lotsize'])
    return int(sub.iloc[-1]['lotsize'])

def send_telegram_msg(msg):
    """Dispatch formatted message through the live Telegram bot."""
    if os.path.exists(BOT_SCRIPT):
        try:
            res = subprocess.run(['node', BOT_SCRIPT, msg], capture_output=True, text=True, timeout=20)
            print("Telegram Bot Response:", res.stdout.strip())
        except Exception as e:
            print(f"Error calling Telegram Bot script: {e}")
    else:
        print(f"Warning: Bot script {BOT_SCRIPT} not found.")

def fetch_live_data(target_date_str, prev_date_str):
    """Fetch previous day indicators and today's morning ticks from MySQL markets DB for all active contracts."""
    conn = get_db_connection()
    with conn.cursor() as cursor:
        print(f"   • Target Trading Date:    {target_date_str}")
        print(f"   • Prior Trading Date:     {prev_date_str}")

        # 1. Fetch prior day ticks to compute VWAP gap, return, and last-hour ROC
        q_prev = f"""
        SELECT TRIM(BOTH '\"' FROM TRIM(BOTH \"'\" FROM TRIM(stockname))) as clean_stock,
               time, CAST(price AS DECIMAL(10,2)) as price
        FROM scrapdata_F1
        WHERE date = '{prev_date_str}' AND isvalid = 'TRUE'
          AND stockname NOT IN ('NIFTY 50', 'NIFTY BANK', 'NIFTY', 'BANKNIFTY', 'FINNIFTY')
        ORDER BY time ASC
        """
        cursor.execute(q_prev)
        df_prev_ticks = pd.DataFrame(cursor.fetchall())

        # 2. Fetch today's 09:07 pre-market prices
        q_0907 = f"""
        SELECT TRIM(BOTH '\"' FROM TRIM(BOTH \"'\" FROM TRIM(stockname))) as clean_stock,
               CAST(price AS DECIMAL(10,2)) as price_0907
        FROM scrapdata_F1
        WHERE date = '{target_date_str}' AND time = '{target_date_str} 09:07:00' AND isvalid = 'TRUE'
        """
        cursor.execute(q_0907)
        rows_0907 = cursor.fetchall()
        df_0907 = pd.DataFrame(rows_0907)
        if len(df_0907) == 0:
            q_0907_eq = f"""
            SELECT TRIM(BOTH '\"' FROM TRIM(BOTH \"'\" FROM TRIM(stockname))) as clean_stock,
                   CAST(price AS DECIMAL(10,2)) as price_0907
            FROM scrapdata
            WHERE date = '{target_date_str}' AND time = '{target_date_str} 09:07:00' AND isvalid = 'TRUE'
            """
            cursor.execute(q_0907_eq)
            df_0907 = pd.DataFrame(cursor.fetchall())

        # 3. Fetch today's morning ticks up to 09:40:00 AM
        q_morn = f"""
        SELECT TRIM(BOTH '\"' FROM TRIM(BOTH \"'\" FROM TRIM(stockname))) as clean_stock,
               time, CAST(price AS DECIMAL(10,2)) as price
        FROM scrapdata_F1
        WHERE date = '{target_date_str}' AND TIME(time) >= '09:15:00' AND TIME(time) <= '09:40:00'
          AND isvalid = 'TRUE'
          AND stockname NOT IN ('NIFTY 50', 'NIFTY BANK', 'NIFTY', 'BANKNIFTY', 'FINNIFTY')
        ORDER BY time ASC
        """
        cursor.execute(q_morn)
        df_morn_ticks = pd.DataFrame(cursor.fetchall())

    conn.close()
    return df_prev_ticks, df_0907, df_morn_ticks

def compute_features(df_prev_ticks, df_0907, df_morn_ticks, target_date_str, cl_stocks):
    """Compute the 7 pure DB features and tag Custom Limit candidate membership."""
    prev_metrics = {}
    if len(df_prev_ticks) > 0:
        for stock, grp in df_prev_ticks.groupby('clean_stock'):
            prices = grp['price'].astype(float).values
            times = pd.to_datetime(grp['time'])
            if len(prices) < 5:
                continue
            open_p = prices[0]
            close_p = prices[-1]
            vwap = float(np.mean(prices))
            ret = (close_p - open_p) / open_p * 100.0 if open_p > 0 else 0.0
            vwap_gap = (close_p - vwap) / vwap * 100.0 if vwap > 0 else 0.0

            # Last hour ROC (after 14:30)
            lh_mask = times.dt.time >= datetime.strptime('14:30:00', '%H:%M:%S').time()
            lh_prices = prices[lh_mask]
            roc_lh = ((lh_prices[-1] - lh_prices[0]) / lh_prices[0] * 100.0) if len(lh_prices) >= 2 and lh_prices[0] > 0 else 0.0

            prev_metrics[stock] = {
                'prev_close': close_p,
                'prev_intraday_return': ret,
                'prev_intraday_vwap_gap': vwap_gap,
                'prev_intraday_roc_last_hour': roc_lh
            }

    map_0907 = dict(zip(df_0907['clean_stock'], df_0907['price_0907'].astype(float))) if len(df_0907) > 0 else {}

    records = []
    if len(df_morn_ticks) > 0:
        for stock, grp in df_morn_ticks.groupby('clean_stock'):
            prices = grp['price'].astype(float).values
            if len(prices) < 2:
                continue
            p_open = prices[0]
            p_940 = prices[-1]
            p_high = float(np.max(prices))
            p_low = float(np.min(prices))
            p_0907 = map_0907.get(stock, p_open)

            pm = prev_metrics.get(stock, {})
            p_prev_close = pm.get('prev_close', p_open)

            gap_0907_pct = ((p_0907 - p_prev_close) / p_prev_close * 100.0) if p_prev_close > 0 else 0.0
            gap_fade = ((p_940 - p_0907) / p_0907 * 100.0) if p_0907 > 0 else 0.0
            morn_range = ((p_high - p_low) / p_open * 100.0) if p_open > 0 else 0.0
            rejection = ((p_high - p_940) / p_open * 100.0) if p_open > 0 else 0.0

            records.append({
                'date_str': target_date_str,
                'clean_stock': stock,
                'entry_price_0940': p_940,
                'gap_0907_pct': gap_0907_pct,
                'gap_fade_0907_to_940_pct': gap_fade,
                'prev_intraday_vwap_gap': pm.get('prev_intraday_vwap_gap', 0.0),
                'prev_intraday_return': pm.get('prev_intraday_return', 0.0),
                'prev_intraday_roc_last_hour': pm.get('prev_intraday_roc_last_hour', 0.0),
                'morn_range_pct': morn_range,
                'rejection_wick': rejection,
                'is_in_cl': stock in cl_stocks
            })

    df_res = pd.DataFrame(records)
    for f in PURE_DB_FEATURES:
        df_res[f] = pd.to_numeric(df_res[f], errors='coerce').fillna(0.0)
    return df_res

def train_and_predict_ensemble(df_today):
    """
    Train Model V6 & V7 on BOTH Custom Limit historical subset and Full Universe dataset.
    Generates dual rankings and detects Quad Confirmed and Dual Confirmed setups.
    """
    print("\n2. Training LightGBM Models on Historical Database (Custom Limit & Full Universe)...")
    df_hist = pd.read_csv(HIST_DATASET, low_memory=False)
    for f in PURE_DB_FEATURES:
        df_hist[f] = pd.to_numeric(df_hist[f], errors='coerce').fillna(0.0)

    # 1. Prepare Custom Limit historical subset
    pnl = pd.read_csv(PNL_FILE, usecols=['simulationdate', 'stockname', 'sell_exec_type'])
    pnl['buy_day'] = pd.to_datetime(pnl['simulationdate'], format='mixed', dayfirst=True, errors='coerce').dt.strftime('%Y-%m-%d')
    pnl['clean_stock'] = pnl['stockname'].astype(str).str.strip().str.upper()
    cl_only = set(zip(pnl[pnl['sell_exec_type'] == 'Custom Limit Fill']['buy_day'], pnl[pnl['sell_exec_type'] == 'Custom Limit Fill']['clean_stock']))
    df_hist['is_strict_cl'] = [ (b, s) in cl_only for b, s in zip(df_hist['buy_day'], df_hist['clean_stock']) ]
    hist_cl = df_hist[df_hist['is_strict_cl']].copy()

    # Train Custom Limit Models
    m6_cl = lgb.LGBMRegressor(n_estimators=100, learning_rate=0.05, max_depth=5, random_state=42, verbose=-1)
    m6_cl.fit(hist_cl[PURE_DB_FEATURES], hist_cl['short_pct_return'])

    hist_cl_v7 = hist_cl[hist_cl['gap_fade_0907_to_940_pct'] < 0.0].copy()
    m7_cl = lgb.LGBMRegressor(n_estimators=100, learning_rate=0.05, max_depth=5, random_state=42, verbose=-1)
    m7_cl.fit(hist_cl_v7[PURE_DB_FEATURES], hist_cl_v7['short_pct_return'])

    # Train Full Universe Models
    m6_full = lgb.LGBMRegressor(n_estimators=100, learning_rate=0.05, max_depth=5, random_state=42, verbose=-1)
    m6_full.fit(df_hist[PURE_DB_FEATURES], df_hist['short_pct_return'])

    hist_full_v7 = df_hist[df_hist['gap_fade_0907_to_940_pct'] < 0.0].copy()
    m7_full = lgb.LGBMRegressor(n_estimators=100, learning_rate=0.05, max_depth=5, random_state=42, verbose=-1)
    m7_full.fit(hist_full_v7[PURE_DB_FEATURES], hist_full_v7['short_pct_return'])

    # 2. Score Full Universe candidates
    df_today['pred_v6_full'] = m6_full.predict(df_today[PURE_DB_FEATURES])
    df_today['rank_v6_full'] = df_today['pred_v6_full'].rank(ascending=False, method='first').astype(int)

    faders_full = df_today['gap_fade_0907_to_940_pct'] < 0.0
    df_today['pred_v7_full'] = np.nan
    df_today['rank_v7_full'] = 999
    if faders_full.sum() > 0:
        df_today.loc[faders_full, 'pred_v7_full'] = m7_full.predict(df_today.loc[faders_full, PURE_DB_FEATURES])
        df_today.loc[faders_full, 'rank_v7_full'] = df_today.loc[faders_full, 'pred_v7_full'].rank(ascending=False, method='first').astype(int)

    # 3. Score Custom Limit candidates
    df_today['pred_v6_cl'] = np.nan
    df_today['rank_v6_cl'] = 999
    df_today['pred_v7_cl'] = np.nan
    df_today['rank_v7_cl'] = 999

    cl_mask = df_today['is_in_cl']
    if cl_mask.sum() > 0:
        df_today.loc[cl_mask, 'pred_v6_cl'] = m6_cl.predict(df_today.loc[cl_mask, PURE_DB_FEATURES])
        df_today.loc[cl_mask, 'rank_v6_cl'] = df_today.loc[cl_mask, 'pred_v6_cl'].rank(ascending=False, method='first').astype(int)

        cl_faders = cl_mask & (df_today['gap_fade_0907_to_940_pct'] < 0.0)
        if cl_faders.sum() > 0:
            df_today.loc[cl_faders, 'pred_v7_cl'] = m7_cl.predict(df_today.loc[cl_faders, PURE_DB_FEATURES])
            df_today.loc[cl_faders, 'rank_v7_cl'] = df_today.loc[cl_faders, 'pred_v7_cl'].rank(ascending=False, method='first').astype(int)

    # 4. Signal Classification
    df_today['is_dual_cl'] = (df_today['rank_v6_cl'] <= 4) & (df_today['rank_v7_cl'] <= 4)
    df_today['is_dual_full'] = (df_today['rank_v6_full'] <= 4) & (df_today['rank_v7_full'] <= 4)
    df_today['is_quad'] = df_today['is_dual_cl'] & df_today['is_dual_full']
    df_today['is_any_dual'] = df_today['is_dual_cl'] | df_today['is_dual_full']

    return df_today

def construct_dynamic_4lot_plan(df_ranked, lot_map, target_dt):
    """
    Construct Option 2: Dynamic 4-Lots Budget (Strict Ceiling: Total 4 Lots Max / Day).
    - Step A: Quad / Dual Confirmed stocks get 2 lots each (max 2 stocks = 4 lots).
    - Step B: If lots remain (< 4 lots): fill with 1-lot Singles (alternating Top 1 CL, Top 1 Full).
    - Guaranteed: Total lots traded across the portfolio is ALWAYS <= 4 lots!
    """
    plan = []
    chosen = set()
    current_lots = 0

    # Step A: High Conviction Duals/Quads (2 lots each)
    duals = df_ranked[df_ranked['is_any_dual']].copy()
    if len(duals) > 0:
        duals['sort_key'] = np.where(duals['is_quad'], 0, np.minimum(duals['rank_v6_full'], duals['rank_v6_cl']))
        duals = duals.sort_values('sort_key')
        for idx, r in duals.iterrows():
            if current_lots + 2 <= 4:
                is_q = r['is_quad']
                r_v6 = int(r['rank_v6_full'] if r['rank_v6_full'] <= r['rank_v6_cl'] else r['rank_v6_cl'])
                r_v7 = int(r['rank_v7_full'] if r['rank_v7_full'] <= r['rank_v7_cl'] else r['rank_v7_cl'])
                source_tag = 'BOTH (QUAD)' if is_q else ('CL FILL' if r['is_dual_cl'] else 'FULL MARKET')

                plan.append({
                    'clean_stock': r['clean_stock'],
                    'lots_to_trade': 2,
                    'signal_type': 'QUAD CONFIRMED 🎯🎯' if is_q else 'DUAL CONFIRMED 🎯',
                    'confidence': 'EXTREME (77.1% WR | 5.89 PF)' if is_q else 'VERY HIGH (75.5% WR | 6.31 PF)',
                    'entry_price_0940': r['entry_price_0940'],
                    'rank_v6': r_v6,
                    'rank_v7': r_v7,
                    'source': source_tag,
                    'is_dual': True,
                    'is_quad': is_q
                })
                chosen.add(r['clean_stock'])
                current_lots += 2

    # Step B: Remainder Singles (1 lot each, alternating CL and Full)
    cl_mask = df_ranked['is_in_cl']
    cl_best = []
    if cl_mask.sum() > 0:
        cl_sorted = df_ranked[cl_mask].sort_values(by=['rank_v6_cl', 'rank_v7_cl'])
        for idx, r in cl_sorted.iterrows():
            if r['clean_stock'] not in chosen:
                cl_best.append(r)

    full_best = []
    full_sorted = df_ranked.sort_values(by=['rank_v6_full', 'rank_v7_full'])
    for idx, r in full_sorted.iterrows():
        if r['clean_stock'] not in chosen:
            full_best.append(r)

    idx_cl, idx_full = 0, 0
    toggle = True
    while current_lots < 4 and (idx_cl < len(cl_best) or idx_full < len(full_best)):
        if toggle and idx_cl < len(cl_best):
            r = cl_best[idx_cl]
            if r['clean_stock'] not in chosen:
                plan.append({
                    'clean_stock': r['clean_stock'],
                    'lots_to_trade': 1,
                    'signal_type': 'SINGLE ENGINE (CL) 📊',
                    'confidence': 'HIGH (56.0% WR | 2.3 PF)',
                    'entry_price_0940': r['entry_price_0940'],
                    'rank_v6': int(r['rank_v6_cl']),
                    'rank_v7': int(r['rank_v7_cl']) if r['rank_v7_cl'] != 999 else 999,
                    'source': 'CL FILL',
                    'is_dual': False,
                    'is_quad': False
                })
                chosen.add(r['clean_stock'])
                current_lots += 1
            idx_cl += 1
            toggle = False
        elif idx_full < len(full_best):
            r = full_best[idx_full]
            if r['clean_stock'] not in chosen:
                plan.append({
                    'clean_stock': r['clean_stock'],
                    'lots_to_trade': 1,
                    'signal_type': 'SINGLE ENGINE (FULL) 📊',
                    'confidence': 'HIGH (57.1% WR | 2.4 PF)',
                    'entry_price_0940': r['entry_price_0940'],
                    'rank_v6': int(r['rank_v6_full']),
                    'rank_v7': int(r['rank_v7_full']) if r['rank_v7_full'] != 999 else 999,
                    'source': 'FULL MARKET',
                    'is_dual': False,
                    'is_quad': False
                })
                chosen.add(r['clean_stock'])
                current_lots += 1
            idx_full += 1
            toggle = True
        elif idx_cl < len(cl_best):
            r = cl_best[idx_cl]
            if r['clean_stock'] not in chosen:
                plan.append({
                    'clean_stock': r['clean_stock'],
                    'lots_to_trade': 1,
                    'signal_type': 'SINGLE ENGINE (CL) 📊',
                    'confidence': 'HIGH (56.0% WR | 2.3 PF)',
                    'entry_price_0940': r['entry_price_0940'],
                    'rank_v6': int(r['rank_v6_cl']),
                    'rank_v7': int(r['rank_v7_cl']) if r['rank_v7_cl'] != 999 else 999,
                    'source': 'CL FILL',
                    'is_dual': False,
                    'is_quad': False
                })
                chosen.add(r['clean_stock'])
                current_lots += 1
            idx_cl += 1
        else:
            break

    df_plan = pd.DataFrame(plan)
    if len(df_plan) > 0:
        df_plan['lotsize'] = [get_exact_lot(s, target_dt, lot_map) for s in df_plan['clean_stock']]
        df_plan['total_quantity'] = df_plan['lotsize'] * df_plan['lots_to_trade']
        df_plan['stop_loss_3pct'] = (df_plan['entry_price_0940'] * 1.03).round(2)
    return df_plan

def append_to_daily_ledger(target_date_str, df_plan):
    """
    Appends the daily short-sell picks to daily_0940_live_ledger.csv with status PENDING.
    Avoids overwriting already COMPLETED historical/reconciled trades.
    """
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    new_rows = []
    for idx, row in df_plan.reset_index(drop=True).iterrows():
        new_rows.append({
            'date': target_date_str,
            'rank': idx + 1,
            'stockname': str(row['clean_stock']).strip().upper(),
            'signal_type': row['signal_type'],
            'source': row['source'],
            'lots_to_trade': int(row['lots_to_trade']),
            'lotsize': int(row['lotsize']),
            'total_quantity': int(row['total_quantity']),
            'entry_time': '09:42:00',
            'entry_price': round(float(row['entry_price_0940']), 2),
            'stop_loss_3pct': round(float(row['stop_loss_3pct']), 2),
            'exit_time': np.nan,
            'exit_price': np.nan,
            'exit_reason': np.nan,
            'points': np.nan,
            'gross_pnl': np.nan,
            'charges': round(300.0 * int(row['lots_to_trade']), 2),
            'net_pnl': np.nan,
            'return_pct': np.nan,
            'rank_v6': int(row['rank_v6']),
            'rank_v7': int(row['rank_v7']) if row['rank_v7'] != 999 else 999,
            'status': 'PENDING',
            'predicted_at': now_str,
            'reconciled_at': np.nan
        })
    df_new = pd.DataFrame(new_rows)
    
    ledger_targets = [
        LEDGER_CSV,
        os.path.join(SCRIPT_DIR, 'audited_0940_hybrid_trades.csv'),
        os.path.join(SARANG_DIR, 'daily_0940_live_ledger.csv'),
        os.path.join(SARANG_DIR, 'audited_0940_hybrid_trades.csv'),
        '/home/ubuntu/940-1445_model/audited_0940_hybrid_trades.csv'
    ]
    
    for l_path in ledger_targets:
        if os.path.exists(l_path):
            try:
                df_existing = pd.read_csv(l_path)
                if target_date_str in df_existing['date'].astype(str).values:
                    completed = df_existing[(df_existing['date'].astype(str) == target_date_str) & (df_existing['status'] == 'COMPLETED')]
                    if len(completed) > 0:
                        print(f"ℹ️ Ledger already contains COMPLETED trades for {target_date_str}; keeping reconciled entries.")
                        continue
                    else:
                        df_existing = df_existing[df_existing['date'].astype(str) != target_date_str]
                df_updated = pd.concat([df_existing, df_new], ignore_index=True)
                df_updated.to_csv(l_path, index=False)
                print(f"✔ Appended {len(df_new)} order(s) to ledger: {l_path} (Status: PENDING)")
            except Exception as e:
                print(f"⚠️ Error appending to {l_path}: {e}")
        else:
            try:
                os.makedirs(os.path.dirname(l_path), exist_ok=True)
                df_new.to_csv(l_path, index=False)
                print(f"✔ Created new ledger: {l_path} with {len(df_new)} order(s)")
            except Exception as e:
                print(f"⚠️ Error creating {l_path}: {e}")

def format_telegram_alert(df_plan, target_date_str):
    """Format rich Telegram HTML notification with dynamic 4-lots budget telemetry."""
    day_name = pd.to_datetime(target_date_str).strftime('%A')
    tot_lots = int(df_plan['lots_to_trade'].sum())
    has_quad = df_plan['is_quad'].any()
    has_duals = df_plan['is_dual'].any()

    msg = f"📉 <b>HYBRID SHORT SELL ORDERS ({target_date_str} - {day_name})</b>\n"
    if day_name == 'Monday':
        msg += "⚠️ <b>MONDAYS NOT RECOMMENDED FOR 09:40 SHORT</b> ⚠️\n"
        msg += "<i>Historical audit shows Monday full-day shorts face chop & lower edge (48.2% WR vs 64% Tue-Thu). Stock suggestions provided below for tracking / paper trading.</i>\n"
        msg += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"

    msg += f"⏰ <b>Entry:</b> 09:42:00 AM IST | <b>Exit:</b> 14:45:00 PM IST\n"
    msg += f"🛡️ <b>Stop Loss:</b> 3.0% (Tick-by-Tick) | <b>Total Lots:</b> {tot_lots} Lots (Hard Budget)\n"
    msg += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"

    if has_quad:
        msg += "🎯🎯 <b>QUAD CONFIRMED SIGNALS DETECTED!</b>\n"
        msg += "<i>Both Models agree across BOTH Custom Limit & Full Universe (77.1% WR | 5.89 PF)</i>\n"
        msg += "⭐ <b>2X Lot Sizing Allocated (Hard 4-Lots Budget)</b>\n"
        msg += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    elif has_duals:
        msg += "🎯 <b>DUAL CONFIRMED SIGNALS DETECTED!</b>\n"
        msg += "<i>Both Model V6 & V7 agree (75.5% WR | 6.31 PF)</i>\n"
        msg += "⭐ <b>2X Lot Sizing Allocated (Hard 4-Lots Budget)</b>\n"
        msg += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    else:
        msg += "ℹ️ <i>Standard Regime: 4 Single Engine Picks (1 Lot each, 50/50 Balanced)</i>\n"
        msg += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"

    for idx, row in df_plan.iterrows():
        stock = row['clean_stock']
        signal = row['signal_type']
        lots = int(row['lots_to_trade'])
        qty = int(row['total_quantity'])
        p_entry = float(row['entry_price_0940'])
        sl_price = float(row['stop_loss_3pct'])
        r_v6 = int(row['rank_v6'])
        r_v7 = str(int(row['rank_v7'])) if row['rank_v7'] != 999 else "N/A"
        src = row['source']

        msg += f"<b>#{idx+1}. {stock}</b> — <b>{signal}</b>\n"
        msg += f"  • <b>Action:</b> SHORT SELL {lots} LOT(S) ({qty:,} qty)\n"
        msg += f"  • <b>Est. Entry (09:42):</b> ₹{p_entry:,.2f}\n"
        msg += f"  • <b>Stop Loss (3.0%):</b> ₹{sl_price:,.2f}\n"
        msg += f"  • <b>Engine Ranks:</b> V6: #{r_v6} | V7: #{r_v7} ({src})\n"
        msg += "------------------------------------\n"

    msg += "⚡ <i>Automated from sarang_2026_shortsell_algos (Option 2 Dynamic Budget)</i>"
    return msg

def main():
    parser = argparse.ArgumentParser(description="Live 09:40 AM Hybrid Prediction Engine (Option 2 Dynamic Budget)")
    parser.add_argument('--date', type=str, default=None, help="Target date YYYY-MM-DD")
    parser.add_argument('--force-monday', action='store_true', help="Force execution even on Monday")
    args = parser.parse_args()

    print("===================================================================================")
    print("🚀 LIVE 09:40 AM SHORT SELL MASTER ENSEMBLE (OPTION 2: DYNAMIC 4-LOTS BUDGET)")
    print("===================================================================================")

    # 1. Determine target date and previous trading date from MySQL scrapdata_F1
    conn = get_db_connection()
    with conn.cursor() as cursor:
        if args.date:
            target_date_str = args.date
        else:
            cursor.execute("SELECT MAX(date) as max_dt FROM scrapdata_F1")
            target_date_str = str(cursor.fetchone()['max_dt'])

        cursor.execute(f"SELECT MAX(date) as prev_date FROM scrapdata_F1 WHERE date < '{target_date_str}'")
        row = cursor.fetchone()
        prev_date_str = str(row['prev_date']) if row and row['prev_date'] else None
    conn.close()

    target_dt = pd.to_datetime(target_date_str)
    day_name = target_dt.strftime('%A')

    # Monday Filter notice
    if day_name == 'Monday':
        print(f"\n⚠️ Today is {day_name} ({target_date_str}).")
        print("   Proceeding with stock suggestions calculation as requested.")
        print("   Notice: 'Mondays not recommended for 09:40 short' caution will be included in the Telegram alert.")

    # 2. Identify Custom Limit candidate stocks from prior trading day
    cl_stocks = set()
    if os.path.exists(PNL_FILE) and prev_date_str:
        pnl_df = pd.read_csv(PNL_FILE)
        pnl_df['parsed_dt'] = pd.to_datetime(pnl_df['simulationdate'], format='mixed', dayfirst=True, errors='coerce').dt.strftime('%Y-%m-%d')
        prev_pnl = pnl_df[pnl_df['parsed_dt'] == prev_date_str]
        cl_df = prev_pnl[prev_pnl['sell_exec_type'].astype(str).str.contains('Custom Limit')]
        if len(cl_df) > 0:
            cl_stocks = set(cl_df['stockname'].astype(str).str.strip().str.upper().unique())
            print(f"⚙️ CUSTOM LIMIT SET: {len(cl_stocks)} stocks matched on prev trading day {prev_date_str} in markets_pnl0325.csv")

    # 3. Fetch live data for whole F&O universe
    print(f"1. Fetching live MySQL data for {target_date_str} ({day_name})...")
    df_prev_ticks, df_0907, df_morn_ticks = fetch_live_data(target_date_str, prev_date_str)

    if len(df_morn_ticks) == 0:
        print(f"❌ Error: No morning ticks found for date {target_date_str} in scrapdata_F1.")
        return

    # 4. Compute features
    df_features = compute_features(df_prev_ticks, df_0907, df_morn_ticks, target_date_str, cl_stocks)
    print(f"   • Total candidate stocks scored: {len(df_features)} (CL candidates: {df_features['is_in_cl'].sum()})")

    # 5. Train ensemble models & rank
    df_ranked = train_and_predict_ensemble(df_features)

    # 6. Formulate Option 2 Dynamic 4-Lots Plan
    lot_map = load_verified_lot_sizes()
    df_plan = construct_dynamic_4lot_plan(df_ranked, lot_map, target_dt)

    if len(df_plan) == 0:
        print("❌ Error: No orders could be formulated.")
        return

    tot_lots = int(df_plan['lots_to_trade'].sum())

    print("\n===================================================================================")
    print(f"🏆 4-LOT LIVE SHORT SELL PLAN FOR {target_date_str} (TOTAL LOTS: {tot_lots} | ENTRY 09:42 AM)")
    print("===================================================================================")
    cols_show = ['clean_stock', 'signal_type', 'lots_to_trade', 'total_quantity', 'entry_price_0940', 'stop_loss_3pct', 'rank_v6', 'rank_v7', 'source']
    print(df_plan[cols_show].to_string(index=False))

    # 7. Save CSV & Append to Daily Ledger
    df_plan.to_csv(OUTPUT_CSV, index=False)
    print(f"\n✅ Saved live prediction orders to: {OUTPUT_CSV}")
    append_to_daily_ledger(target_date_str, df_plan)

    # 8. Format & Dispatch Telegram Alert
    print("\n3. Formatting and sending Telegram Bot Alert...")
    tg_msg = format_telegram_alert(df_plan, target_date_str)
    print(tg_msg)
    send_telegram_msg(tg_msg)
    print("\n🎉 Live 09:40 Master Ensemble (Option 2) Completed Successfully!")

if __name__ == '__main__':
    main()
