#!/usr/bin/env python3
"""
live_0920_scalp_pipeline.py
=============================================================================
Production 09:20 - 09:40 Scalp Prediction Engine (Session 1)
Historical Metrics: 64.91% Win Rate | ₹55.20 Lakhs Net Profit (after charges)

Triggered at 09:20:20 AM IST Mon-Fri:
1. Reads morning EQ cash ticks (09:15 - 09:19) and previous day features from scrapdata.
2. Performs instant inference using pre-trained LightGBM walk-forward model.
3. Ranks candidates and selects Top 4 weakest stocks for opening scalp short-sell.
4. Matches dynamic contract lot sizes from historical_lotsize_new.csv.
5. Formulates 09:21:00 Entry -> 09:41:00 Exit order plan and alerts Telegram bot.
=============================================================================
"""

import os
import sys
import argparse
import subprocess
import pymysql
import numpy as np
import pandas as pd
import lightgbm as lgb
from datetime import datetime, date
import warnings

warnings.filterwarnings('ignore')

# Configuration & Paths
BASE_DIR = '/home/ubuntu/sarang_2026_shortsell_algos/01_Best_Shorter_Window_0920_0940'
MODEL_FILE = os.path.join(BASE_DIR, 'lgb_0920_scalp_model.txt')
LOTS_FILE = '/home/ubuntu/KotakCodes1/historical_lotsize_new.csv'
BOT_SCRIPT = '/home/ubuntu/KotakCodes1/status_Info_bot.js'
OUTPUT_CSV = os.path.join(BASE_DIR, 'live_0920_predictions_today.csv')

FEATURES = [
    'prev_intraday_vwap_gap', 
    'prev_intraday_roc_last_hour', 
    'prev_intraday_return', 
    'positive_arc_ratio', 
    'Gap_Pct', 
    'gap_0907_pct', 
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

def load_lot_sizes():
    if not os.path.exists(LOTS_FILE):
        return {}
    df = pd.read_csv(LOTS_FILE)
    df['clean_stock'] = df['stockname'].astype(str).str.strip().str.upper()
    df['exp_dt'] = pd.to_datetime(df['expdate'], format='%d/%m/%Y', errors='coerce')
    lot_map = {}
    for stock, grp in df.groupby('clean_stock'):
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

def send_telegram_alert(msg):
    if os.path.exists(BOT_SCRIPT):
        try:
            res = subprocess.run(['node', BOT_SCRIPT, msg], capture_output=True, text=True, timeout=20)
            print("[Telegram Bot Response]:", res.stdout.strip())
        except Exception as e:
            print(f"[Telegram Bot Error]: {e}")
    else:
        print(f"[Warning]: Bot script {BOT_SCRIPT} not found.")

def calc_arc_features(prices):
    if len(prices) < 3:
        return 0.0
    p = np.array(prices)
    norm_p = (p - p[0]) / (p[0] + 1e-9)
    changes = np.diff(norm_p)
    pos_arcs = np.sum(changes > 0)
    total_arcs = len(changes)
    return float(pos_arcs / total_arcs) if total_arcs > 0 else 0.0

def run_scalp_pipeline(target_date_str=None):
    start_time = datetime.now()
    print("=" * 75)
    print("⚡ 09:20 - 09:40 SCALP PREDICTION ENGINE (SESSION 1)")
    print("=" * 75)

    conn = get_db_connection()
    with conn.cursor() as cursor:
        if not target_date_str:
            cursor.execute("SELECT MAX(date) as dt FROM scrapdata")
            latest_row = cursor.fetchone()
            target_date_str = str(latest_row['dt']) if latest_row and latest_row['dt'] else datetime.now().strftime('%Y-%m-%d')
        
        # Determine previous trading date
        cursor.execute(f"SELECT MAX(date) as prev_dt FROM scrapdata WHERE date < '{target_date_str}'")
        prev_row = cursor.fetchone()
        prev_date_str = str(prev_row['prev_dt']) if prev_row and prev_row['prev_dt'] else None

    print(f"• Target Trading Date   : {target_date_str}")
    print(f"• Prior Trading Date    : {prev_date_str}")

    if not prev_date_str:
        print("❌ Error: Unable to determine prior trading date from MySQL scrapdata.")
        return

    # Load pre-trained LightGBM model
    if not os.path.exists(MODEL_FILE):
        print(f"❌ Error: Model file not found at {MODEL_FILE}")
        return
    model = lgb.Booster(model_file=MODEL_FILE)
    lot_map = load_lot_sizes()

    # 1. Fetch Previous Day Cash Ticks for universe
    print(f"\n1. Fetching Prior Day ({prev_date_str}) Intraday Ticks from scrapdata...")
    with conn.cursor() as cursor:
        cursor.execute(f"""
            SELECT stockname, time, price, volume FROM scrapdata
            WHERE date = '{prev_date_str}'
              AND TIME(time) >= '09:15:00' AND TIME(time) <= '15:30:00'
            ORDER BY stockname, time ASC
        """)
        prev_rows = cursor.fetchall()

    prev_dict = {}
    for r in prev_rows:
        s = r['stockname'].replace('"', '').replace("'", "").strip().upper()
        if s not in prev_dict:
            prev_dict[s] = []
        prev_dict[s].append(r)

    # 2. Fetch Today's Morning Cash Ticks (09:07 premarket and 09:15 to 09:19:59)
    print(f"2. Fetching Today's Morning ({target_date_str}) Ticks (09:07 - 09:19:59)...")
    with conn.cursor() as cursor:
        cursor.execute(f"""
            SELECT stockname, time, price FROM scrapdata
            WHERE date = '{target_date_str}'
              AND TIME(time) >= '09:07:00' AND TIME(time) <= '09:19:59'
            ORDER BY stockname, time ASC
        """)
        morn_rows = cursor.fetchall()
    conn.close()

    morn_dict = {}
    for r in morn_rows:
        s = r['stockname'].replace('"', '').replace("'", "").strip().upper()
        if s not in morn_dict:
            morn_dict[s] = []
        morn_dict[s].append(r)

    # 3. Compute Features for all active stocks
    print("3. Computing Feature Vectors across Active Universe...")
    processed_records = []
    target_dt = pd.to_datetime(target_date_str)

    for stock, mticks in morn_dict.items():
        if stock not in prev_dict or len(prev_dict[stock]) < 10:
            continue
        
        pticks = prev_dict[stock]
        p_prices = [float(x['price']) for x in pticks]
        p_vols = [float(x['volume']) if x.get('volume') is not None else 1.0 for x in pticks]
        p_times = [str(x['time']).split()[-1] for x in pticks]

        p_open = p_prices[0]
        p_close = p_prices[-1]
        p_high = max(p_prices)
        p_low = min(p_prices)

        # VWAP
        cum_pv = sum(p * v for p, v in zip(p_prices, p_vols))
        cum_v = sum(p_vols)
        vwap = cum_pv / cum_v if cum_v > 0 else p_close
        prev_intraday_vwap_gap = ((p_close - vwap) / vwap) * 100.0

        # ROC Last Hour (14:30 to 15:30)
        lh_prices = [p for t, p in zip(p_times, p_prices) if t >= '14:30:00']
        p_1430 = lh_prices[0] if lh_prices else p_close
        prev_intraday_roc_last_hour = ((p_close - p_1430) / p_1430) * 100.0

        # Prev Intraday Return
        prev_intraday_return = ((p_close - p_open) / p_open) * 100.0

        # Today's Morning Ticks
        p_0907_ticks = [float(x['price']) for x in mticks if str(x['time']).split()[-1] < '09:15:00']
        p_0915_ticks = [float(x['price']) for x in mticks if str(x['time']).split()[-1] >= '09:15:00']

        if not p_0915_ticks:
            continue

        open_0915 = p_0915_ticks[0]
        close_0919 = p_0915_ticks[-1]
        high_0919 = max(p_0915_ticks)
        low_0919 = min(p_0915_ticks)

        Gap_Pct = ((open_0915 - p_close) / p_close) * 100.0

        if p_0907_ticks:
            p_0907 = p_0907_ticks[0]
            gap_0907_pct = ((p_0907 - p_close) / p_close) * 100.0
        else:
            gap_0907_pct = Gap_Pct

        morn_range_pct = (high_0919 - low_0919) / (open_0915 + 1e-9)
        rejection_wick = (high_0919 - close_0919) / (high_0919 - low_0919 + 1e-9)
        pos_arc_ratio = calc_arc_features(p_0915_ticks)

        lotsize = get_exact_lot(stock, target_dt, lot_map, fallback=1000)

        processed_records.append({
            'stockname': stock,
            'prev_close': p_close,
            'cmp_0919': close_0919,
            'lotsize': lotsize,
            'prev_intraday_vwap_gap': prev_intraday_vwap_gap,
            'prev_intraday_roc_last_hour': prev_intraday_roc_last_hour,
            'prev_intraday_return': prev_intraday_return,
            'positive_arc_ratio': pos_arc_ratio,
            'Gap_Pct': Gap_Pct,
            'gap_0907_pct': gap_0907_pct,
            'morn_range_pct': morn_range_pct,
            'rejection_wick': rejection_wick
        })

    if not processed_records:
        print("⚠️ No valid stocks qualified with full morning and prior day data.")
        return

    df_candidates = pd.DataFrame(processed_records)
    print(f"   • Qualified Universe Candidates: {len(df_candidates)} stocks")

    # 4. Run Model Inference
    X = df_candidates[FEATURES]
    df_candidates['short_prob'] = model.predict(X)

    # 5. Select Top 4 Candidates
    df_candidates = df_candidates.sort_values('short_prob', ascending=False).reset_index(drop=True)
    top4 = df_candidates.head(4).copy()

    print("\n" + "=" * 75)
    print("🎯 TOP 4 09:20 SCALP CANDIDATES (09:21 ENTRY -> 09:41 EXIT):")
    print("=" * 75)
    for idx, row in top4.iterrows():
        print(f"#{idx+1} | {row['stockname'].ljust(12)} | Prob: {row['short_prob']*100:.1f}% | CMP: ₹{row['cmp_0919']:.2f} | Lot Size: {row['lotsize']} | Wick: {row['rejection_wick']:.2f}")
    print("=" * 75)

    # Save CSV output
    top4.to_csv(OUTPUT_CSV, index=False)
    print(f"\n✔ Plan saved to: {OUTPUT_CSV}")

    # 6. Format and Send Telegram Message
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S IST')
    lines = [
        f"⚡ <b>[09:20 SCALP ENGINE: 20-MIN SHORT SELL SELECTION]</b>",
        f"📅 <b>Date:</b> {target_date_str} | ⏱️ <b>Generated:</b> {now_str}",
        f"🎯 <b>Holding Window:</b> 09:21 AM Entry ➔ 09:41 AM Exit (20 Mins)",
        f"📊 <b>Model Edge:</b> 64.91% Historical Win Rate | +₹55.20L Net PnL",
        "",
        "<b>🔻 TARGET 4 SHORT-SELL ORDERS:</b>"
    ]

    for idx, row in top4.iterrows():
        stk = row['stockname']
        prob = row['short_prob'] * 100
        cmp_p = row['cmp_0919']
        lots = row['lotsize']
        lines.append(f"  <b>{idx+1}. {stk}</b>: Short Prob = <code>{prob:.1f}%</code> | CMP: ₹{cmp_p:.2f} | Lot: <b>{lots}</b>")

    lines.extend([
        "",
        "⏱️ <b>Execution Rules:</b>",
        "• <b>Entry:</b> Sell at Market at 09:21:00 AM IST",
        "• <b>Exit:</b> Unconditional Square-Off at 09:41:00 AM IST (Strict 20-min Hold)",
        "• <b>Risk:</b> Zero midday exposure, zero afternoon chop risk."
    ])

    tg_message = "\n".join(lines)
    send_telegram_alert(tg_message)

    duration = (datetime.now() - start_time).total_seconds()
    print(f"\n🎉 09:20 Scalp Pipeline Completed Successfully in {duration:.2f} seconds.")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="09:20 - 09:40 Scalp Engine Live Runner")
    parser.add_argument('--date', type=str, default=None, help="Target Date YYYY-MM-DD (defaults to latest in DB)")
    args = parser.parse_args()

    run_scalp_pipeline(target_date_str=args.date)
