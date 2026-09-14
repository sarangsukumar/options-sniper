#!/usr/bin/env python3
"""
live_0940_hybrid_pipeline.py
----------------------------
Production 09:40 AM IST Live Short-Sell Prediction & Telegram Bot Alert Engine.
Architecture: Model V6 (Overextended Reversion) + Model V7 (Premarket Fader Sniper).

Execution Timeline:
  - 09:40:30 AM: Script runs (via daily_schedules.txt / thescheduler.js).
  - 09:41:00 AM: Computes morning features, trains walk-forward models, generates rankings.
  - 09:41:15 AM: Identifies Dual Confirmed signals (V6 <= 4 AND V7 <= 4) and formats 4-order daily plan.
  - 09:41:30 AM: Dispatches rich HTML alert to Telegram via status_Info_bot.js.
  - 09:42:00 AM: Trader / API executes the 4 short sell orders with 3.0% Stop Loss.
  - 14:45:00 PM: Square-off all open intraday positions.
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
BASE_DIR = '/home/ubuntu/sarang_2026_shortsell_algos/02_Best_Longer_Window_0942_1445'
HIST_DATASET = '/home/ubuntu/v5_from_scratch/data/short_sell_ml_dataset_v5_scratch.csv'
LOTS_FILE = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/config/historical_lotsize_new.csv'
BOT_SCRIPT = '/home/ubuntu/KotakCodes1/status_Info_bot.js'
OUTPUT_CSV = os.path.join(BASE_DIR, 'live_predictions_today.csv')

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

def fetch_live_data(target_date_str, prev_date_str, candidate_filter=None):
    """Fetch previous day indicators and today's morning ticks from MySQL markets DB."""
    cand_clause = ""
    if candidate_filter and len(candidate_filter) > 0:
        cands_formatted = ", ".join([f"'{s.strip().upper()}'" for s in candidate_filter])
        cand_clause = f" AND TRIM(BOTH '\"' FROM TRIM(BOTH \"'\" FROM TRIM(stockname))) IN ({cands_formatted}) "

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
          {cand_clause}
        ORDER BY time ASC
        """
        cursor.execute(q_prev)
        prev_ticks = cursor.fetchall()
        df_prev_ticks = pd.DataFrame(prev_ticks)

        # 3. Fetch today's 09:07 pre-market prices
        q_0907 = f"""
        SELECT TRIM(BOTH '\"' FROM TRIM(BOTH \"'\" FROM TRIM(stockname))) as clean_stock,
               CAST(price AS DECIMAL(10,2)) as price_0907
        FROM scrapdata_F1
        WHERE date = '{target_date_str}' AND time = '{target_date_str} 09:07:00' AND isvalid = 'TRUE'
          {cand_clause}
        """
        cursor.execute(q_0907)
        rows_0907 = cursor.fetchall()
        df_0907 = pd.DataFrame(rows_0907)
        if len(df_0907) == 0:
            # Fallback to cash equity scrapdata for 09:07 pre-market open
            q_0907_eq = f"""
            SELECT TRIM(BOTH '\"' FROM TRIM(BOTH \"'\" FROM TRIM(stockname))) as clean_stock,
                   CAST(price AS DECIMAL(10,2)) as price_0907
            FROM scrapdata
            WHERE date = '{target_date_str}' AND time = '{target_date_str} 09:07:00' AND isvalid = 'TRUE'
              {cand_clause}
            """
            cursor.execute(q_0907_eq)
            df_0907 = pd.DataFrame(cursor.fetchall())

        # 4. Fetch today's morning ticks up to 09:40:00 AM
        q_morn = f"""
        SELECT TRIM(BOTH '\"' FROM TRIM(BOTH \"'\" FROM TRIM(stockname))) as clean_stock,
               time, CAST(price AS DECIMAL(10,2)) as price
        FROM scrapdata_F1
        WHERE date = '{target_date_str}' AND TIME(time) >= '09:15:00' AND TIME(time) <= '09:40:00'
          AND isvalid = 'TRUE'
          AND stockname NOT IN ('NIFTY 50', 'NIFTY BANK', 'NIFTY', 'BANKNIFTY', 'FINNIFTY')
          {cand_clause}
        ORDER BY time ASC
        """
        cursor.execute(q_morn)
        morn_ticks = cursor.fetchall()
        df_morn_ticks = pd.DataFrame(morn_ticks)

    conn.close()
    return df_prev_ticks, df_0907, df_morn_ticks

def compute_features(df_prev_ticks, df_0907, df_morn_ticks, target_date_str):
    """Compute the 7 pure DB features for all candidates."""
    # 1. Prior day metrics
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

    # 2. Pre-market map
    map_0907 = dict(zip(df_0907['clean_stock'], df_0907['price_0907'].astype(float))) if len(df_0907) > 0 else {}

    # 3. Morning ticks metrics
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

            # 09:07 price
            p_0907 = map_0907.get(stock, p_open)

            pm = prev_metrics.get(stock, {})
            p_prev_close = pm.get('prev_close', p_open)

            # Features
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
                'rejection_wick': rejection
            })

    return pd.DataFrame(records)

def train_and_predict(df_today):
    """Train Model V6 and Model V7 on historical dataset and rank today's candidate stocks."""
    print("\n2. Training LightGBM Model V6 and Model V7 on historical pure database walkover...")
    df_hist = pd.read_csv(HIST_DATASET, low_memory=False)
    for f in PURE_DB_FEATURES:
        df_hist[f] = pd.to_numeric(df_hist[f], errors='coerce').fillna(0.0)
        df_today[f] = pd.to_numeric(df_today[f], errors='coerce').fillna(0.0)

    # Model V6: Broad Universe Reversion
    lgb_v6 = lgb.LGBMRegressor(n_estimators=100, learning_rate=0.05, max_depth=5, random_state=42, verbose=-1)
    lgb_v6.fit(df_hist[PURE_DB_FEATURES], df_hist['short_pct_return'])
    df_today['pred_v6'] = lgb_v6.predict(df_today[PURE_DB_FEATURES])
    df_today['rank_v6'] = df_today['pred_v6'].rank(ascending=False, method='first').astype(int)

    # Model V7: Premarket Fade Momentum Sniper
    hist_v7 = df_hist[df_hist['gap_fade_0907_to_940_pct'] < 0.0].copy()
    lgb_v7 = lgb.LGBMRegressor(n_estimators=100, learning_rate=0.05, max_depth=5, random_state=42, verbose=-1)
    lgb_v7.fit(hist_v7[PURE_DB_FEATURES], hist_v7['short_pct_return'])

    # Predict V7 for today's faders
    faders_mask = df_today['gap_fade_0907_to_940_pct'] < 0.0
    df_today['pred_v7'] = np.nan
    df_today['rank_v7'] = 999

    if faders_mask.sum() > 0:
        df_today.loc[faders_mask, 'pred_v7'] = lgb_v7.predict(df_today.loc[faders_mask, PURE_DB_FEATURES])
        df_today.loc[faders_mask, 'rank_v7'] = df_today.loc[faders_mask, 'pred_v7'].rank(ascending=False, method='first').astype(int)

    # Flag Dual Confirmed: ranked <= 4 in both V6 and V7
    df_today['is_dual'] = (df_today['rank_v6'] <= 4) & (df_today['rank_v7'] <= 4)
    return df_today

def construct_4_order_plan(df_ranked, lot_map, target_dt):
    """
    Construct optimal 4-order daily execution plan:
    - 4 total orders/lots per day.
    - If 2 Duals: 2 lots to Dual 1, 2 lots to Dual 2 (Total: 4 lots).
    - If 1 Dual: 2 lots to Dual 1, 1 lot each to top 2 single picks (Total: 4 lots).
    - If 0 Duals: 1 lot each to Top 4 single picks (Total: 4 lots).
    """
    duals = df_ranked[df_ranked['is_dual']].sort_values('rank_v6').copy()
    singles = df_ranked[~df_ranked['is_dual']].sort_values('rank_v6').copy()

    plan = []
    if len(duals) >= 2:
        for i in range(2):
            row = duals.iloc[i].to_dict()
            row['lots_to_trade'] = 2
            row['signal_type'] = 'DUAL CONFIRMED 🎯'
            row['confidence'] = 'VERY HIGH (72.3% WR | 6.27 PF)'
            plan.append(row)
    elif len(duals) == 1:
        row = duals.iloc[0].to_dict()
        row['lots_to_trade'] = 2
        row['signal_type'] = 'DUAL CONFIRMED 🎯'
        row['confidence'] = 'VERY HIGH (72.3% WR | 6.27 PF)'
        plan.append(row)
        for i in range(min(2, len(singles))):
            s_row = singles.iloc[i].to_dict()
            s_row['lots_to_trade'] = 1
            s_row['signal_type'] = 'SINGLE ENGINE 📊'
            s_row['confidence'] = 'HIGH (62.4% WR)'
            plan.append(s_row)
    else:
        for i in range(min(4, len(singles))):
            s_row = singles.iloc[i].to_dict()
            s_row['lots_to_trade'] = 1
            s_row['signal_type'] = 'SINGLE ENGINE 📊'
            s_row['confidence'] = 'HIGH (62.4% WR)'
            plan.append(s_row)

    df_plan = pd.DataFrame(plan)
    if len(df_plan) > 0:
        df_plan['lotsize'] = [get_exact_lot(s, target_dt, lot_map) for s in df_plan['clean_stock']]
        df_plan['total_quantity'] = df_plan['lotsize'] * df_plan['lots_to_trade']
        df_plan['stop_loss_3pct'] = (df_plan['entry_price_0940'] * 1.03).round(2)
    return df_plan

def format_telegram_alert(df_plan, target_date_str, has_duals):
    """Format rich Telegram HTML notification."""
    day_name = pd.to_datetime(target_date_str).strftime('%A')
    msg = f"📉 <b>HYBRID SHORT SELL ORDERS ({target_date_str} - {day_name})</b>\n"
    if day_name == 'Monday':
        msg += "⚠️ <b>MONDAYS NOT RECOMMENDED FOR 09:40 SHORT</b> ⚠️\n"
        msg += "<i>Historical audit shows Monday full-day shorts face chop & lower edge (48.2% WR vs 64% Tue-Thu). Stock suggestions provided below for tracking / paper trading.</i>\n"
        msg += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    msg += f"⏰ <b>Entry:</b> 09:42:00 AM IST | <b>Exit:</b> 14:45:00 PM IST\n"
    msg += f"🛡️ <b>Stop Loss:</b> 3.0% (Tick-by-Tick) | <b>Max Slots:</b> 4 Orders\n"
    msg += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"

    if has_duals:
        msg += "🎯 <b>DUAL CONFIRMED SIGNALS DETECTED!</b>\n"
        msg += "<i>Both Model V6 & V7 agree (72.3% Win Rate | 6.27 PF)</i>\n"
        msg += "⭐ <b>2X Lot Sizing Allocated to Dual Signals</b>\n"
        msg += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    else:
        msg += "ℹ️ <i>Standard Regime: 4 Single Engine Picks (1 Lot each)</i>\n"
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

        msg += f"<b>#{idx+1}. {stock}</b> — <b>{signal}</b>\n"
        msg += f"  • <b>Action:</b> SHORT SELL {lots} LOT(S) ({qty:,} qty)\n"
        msg += f"  • <b>Est. Entry (09:42):</b> ₹{p_entry:,.2f}\n"
        msg += f"  • <b>Stop Loss (3.0%):</b> ₹{sl_price:,.2f}\n"
        msg += f"  • <b>Ranks:</b> V6: #{r_v6} | V7: #{r_v7}\n"
        msg += "------------------------------------\n"

    msg += "⚡ <i>Automated from sarang_2026_shortsell_algos (scrapdata_F1)</i>"
    return msg

def main():
    parser = argparse.ArgumentParser(description="Live 09:40 AM Hybrid Prediction Engine")
    parser.add_argument('--date', type=str, default=None, help="Target date YYYY-MM-DD")
    parser.add_argument('--force-monday', action='store_true', help="Force execution even on Monday")
    parser.add_argument('--whole-universe', action='store_true', help="Force scanning entire F&O universe instead of Custom Limit fills")
    args = parser.parse_args()

    print("===================================================================================")
    print("🚀 LIVE 09:40 AM SHORT SELL HYBRID ENGINE (MODEL V6 + MODEL V7)")
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

    # Check candidate filtering mode:
    # CRITICAL: The simulation pipeline records trades in markets_pnl0325.csv under the BUY date (prev_date_str).
    # Those positions exit on today's morning (09:15-09:40 AM) via Custom Limit Fill!
    # Therefore, we match simulationdate in markets_pnl0325.csv with prev_date_str from scrapdata_F1!
    cand_filter = None
    pnl_path = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/data/markets_pnl0325.csv'
    if not args.whole_universe and os.path.exists(pnl_path) and prev_date_str:
        pnl_df = pd.read_csv(pnl_path)
        pnl_df['parsed_dt'] = pd.to_datetime(pnl_df['simulationdate'], format='mixed', dayfirst=True, errors='coerce').dt.strftime('%Y-%m-%d')
        
        # Exact match with previous trading day from DB:
        prev_pnl = pnl_df[pnl_df['parsed_dt'] == prev_date_str]
        cl_df = prev_pnl[prev_pnl['sell_exec_type'].astype(str).str.contains('Custom Limit')]
        
        if len(cl_df) > 0:
            cand_filter = cl_df['stockname'].astype(str).str.strip().str.upper().unique().tolist()
            print(f"\n⚙️ CANDIDATE MODE: CUSTOM LIMIT MET ORDERS ({len(cand_filter)} stocks matched on prev trading day {prev_date_str} in markets_pnl0325.csv)")
        else:
            print(f"\n⚙️ CANDIDATE MODE: WHOLE UNIVERSE (No Custom Limit fills found in markets_pnl0325 for {prev_date_str})")
    else:
        print("\n⚙️ CANDIDATE MODE: WHOLE UNIVERSE (All Active F&O Contracts)")

    # 2. Fetch live data
    print(f"1. Fetching live MySQL data for {target_date_str} ({day_name})...")
    df_prev_ticks, df_0907, df_morn_ticks = fetch_live_data(target_date_str, prev_date_str, candidate_filter=cand_filter)

    if len(df_morn_ticks) == 0:
        print(f"❌ Error: No morning ticks found for date {target_date_str} in scrapdata_F1.")
        return

    # 3. Compute features
    df_features = compute_features(df_prev_ticks, df_0907, df_morn_ticks, target_date_str)
    print(f"   • Candidate stocks evaluated: {len(df_features)}")

    # 4. Train models & predict
    df_ranked = train_and_predict(df_features)

    # 5. Formulate 4-order plan
    lot_map = load_verified_lot_sizes()
    df_plan = construct_4_order_plan(df_ranked, lot_map, target_dt)

    if len(df_plan) == 0:
        print("❌ Error: No orders could be formulated.")
        return

    has_duals = df_plan['is_dual'].any()

    print("\n===================================================================================")
    print(f"🏆 4-ORDER LIVE SHORT SELL PLAN FOR {target_date_str} (ENTRY EXACT 09:42 AM)")
    print("===================================================================================")
    cols_show = ['clean_stock', 'signal_type', 'lots_to_trade', 'total_quantity', 'entry_price_0940', 'stop_loss_3pct', 'rank_v6', 'rank_v7']
    print(df_plan[cols_show].to_string(index=False))

    # 6. Save CSV
    df_plan.to_csv(OUTPUT_CSV, index=False)
    print(f"\n✅ Saved live prediction orders to: {OUTPUT_CSV}")

    # 7. Format & Dispatch Telegram Alert
    print("\n3. Formatting and sending Telegram Bot Alert...")
    tg_msg = format_telegram_alert(df_plan, target_date_str, has_duals)
    print(tg_msg)
    send_telegram_msg(tg_msg)
    print("\n🎉 Live 09:40 Hybrid Pipeline Completed Successfully!")

if __name__ == '__main__':
    main()
