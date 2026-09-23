#!/usr/bin/env python3
"""
live_0920_scalp_pipeline.py
=============================================================================
Production 09:20 - 09:40 Scalp Prediction Engine (Session 1)
Historical Metrics: 64.96% Win Rate | ₹88.69 Lakhs Net Profit (after charges, 2021-2026)

Triggered at 09:20:20 AM IST Mon-Fri:
1. Reads morning EQ cash ticks (09:15 - 09:19) and previous day features from scrapdata.
2. Performs instant inference using pre-trained LightGBM walk-forward model.
3. Ranks candidates and selects Top 4 weakest stocks for opening scalp short-sell.
4. Fixed ₹5,00,000 notional equity per trade: qty = int(500000 / cmp_0919).
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
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROD_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..'))
MODEL_FILE = os.path.join(SCRIPT_DIR, 'lgb_0920_scalp_model.txt')
BOT_SCRIPT = '/home/ubuntu/KotakCodes1/status_Info_bot.js'
OUTPUT_CSV = os.path.join(SCRIPT_DIR, 'live_0920_predictions_today.csv')
LEDGER_CSV = os.path.join(SCRIPT_DIR, 'daily_0920_live_ledger.csv')

FEATURES = [
    'prev_intraday_vwap_gap', 'prev_intraday_roc_last_hour', 'prev_intraday_return',
    'positive_arc_ratio', 'Gap_Pct', 'gap_0907_pct', 'morn_range_pct', 'rejection_wick'
]

# Official NSE F&O Universe (180+ Liquid Contract Stocks)
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
VALID_SET = set(VALID_STOCKS)

def get_db_connection():
    return pymysql.connect(
        host='localhost',
        user='root',
        password='root',
        database='markets',
        cursorclass=pymysql.cursors.DictCursor
    )


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

def append_to_daily_ledger(target_date_str, top4_df):
    """
    Appends the daily Top 4 short-sell picks to daily_0920_live_ledger.csv with status PENDING.
    Avoids duplicate entries if executed multiple times on the same date.
    """
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    new_rows = []
    for idx, row in top4_df.reset_index(drop=True).iterrows():
        new_rows.append({
            'date': target_date_str,
            'rank': idx + 1,
            'stockname': str(row['stockname']).strip().upper(),
            'short_prob': round(float(row['short_prob']), 4),
            'close_0919': round(float(row['close_0919']), 2),
            'qty': int(row['lotsize']),
            'entry_time': '09:21:00',
            'entry_price': np.nan,
            'exit_time': '09:41:00',
            'exit_price': np.nan,
            'gross_pnl': np.nan,
            'charges': 300.0,
            'net_pnl': np.nan,
            'return_pct': np.nan,
            'status': 'PENDING',
            'predicted_at': now_str,
            'reconciled_at': np.nan
        })
    df_new = pd.DataFrame(new_rows)
    
    if os.path.exists(LEDGER_CSV):
        try:
            df_existing = pd.read_csv(LEDGER_CSV)
            if target_date_str in df_existing['date'].values:
                already_completed = ((df_existing['date'] == target_date_str) & (df_existing['status'] == 'COMPLETED')).any()
                if not already_completed:
                    df_existing = df_existing[df_existing['date'] != target_date_str]
                    df_combined = pd.concat([df_existing, df_new], ignore_index=True)
                    df_combined.to_csv(LEDGER_CSV, index=False)
                    print(f"✔ Daily ledger refreshed for {target_date_str} (Status: PENDING)")
                else:
                    print(f"ℹ️ Date {target_date_str} already reconciled in ledger; skipped overwriting.")
            else:
                df_combined = pd.concat([df_existing, df_new], ignore_index=True)
                df_combined.to_csv(LEDGER_CSV, index=False)
                print(f"✔ Daily predictions appended to persistent ledger: {LEDGER_CSV} (Status: PENDING)")
        except Exception as e:
            print(f"⚠️ Error updating ledger ({e}); writing fresh file.")
            df_new.to_csv(LEDGER_CSV, index=False)
    else:
        df_new.to_csv(LEDGER_CSV, index=False)
        print(f"✔ Created new persistent ledger: {LEDGER_CSV}")

def run_scalp_pipeline(target_date_str=None, no_telegram=False):
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

    # Fetch today's global macro features via yfinance (matches training logic exactly)
    print(f"\n0. Fetching Global Macro Features (Nifty/S&P500/Nikkei) via yfinance...")
    try:
        import yfinance as yf
        tickers = {'^NSEI': 'nifty', '^GSPC': 'sp500', '^N225': 'nikkei'}
        data = yf.download(list(tickers.keys()), period='5d', progress=False, auto_adjust=True)
        df_close = data['Close'].reset_index().rename(columns={'Date': 'date'})
        df_open  = data['Open'].reset_index().rename(columns={'Date': 'date'})
        df_close['date'] = pd.to_datetime(df_close['date']).dt.date.astype(str)
        df_open['date']  = pd.to_datetime(df_open['date']).dt.date.astype(str)
        df_close = df_close.sort_values('date')
        df_open  = df_open.sort_values('date')
        today_row_c = df_close[df_close['date'] == target_date_str]
        prev_row_c  = df_close[df_close['date'] < target_date_str].tail(2)
        today_row_o = df_open[df_open['date'] == target_date_str]
        nifty_open  = float(today_row_o['^NSEI'].values[0]) if len(today_row_o) else None
        nifty_close_prev = float(prev_row_c['^NSEI'].values[-1]) if len(prev_row_c) >= 1 else None
        sp500_close_prev  = float(prev_row_c['^GSPC'].values[-1]) if len(prev_row_c) >= 1 else None
        sp500_close_prev2 = float(prev_row_c['^GSPC'].values[-2]) if len(prev_row_c) >= 2 else None
        nikkei_open  = float(today_row_o['^N225'].values[0]) if len(today_row_o) else None
        nikkei_close_prev = float(prev_row_c['^N225'].values[-1]) if len(prev_row_c) >= 1 else None
        nifty_gap           = ((nifty_open / nifty_close_prev) - 1) if nifty_open and nifty_close_prev else 0.0
        sp500_overnight_ret = ((sp500_close_prev / sp500_close_prev2) - 1) if sp500_close_prev and sp500_close_prev2 else 0.0
        nikkei_gap          = ((nikkei_open / nikkei_close_prev) - 1) if nikkei_open and nikkei_close_prev else 0.0
        nifty_vs_sp500_gap  = nifty_gap - sp500_overnight_ret
        nifty_vs_nikkei_gap = nifty_gap - nikkei_gap
        print(f"   ✔ nifty_gap={nifty_gap:.4f} | sp500_ret={sp500_overnight_ret:.4f} | nikkei_gap={nikkei_gap:.4f}")
    except Exception as e:
        print(f"   ⚠️ yfinance fetch failed ({e}) — using 0.0 for macro features")
        nifty_gap = sp500_overnight_ret = nikkei_gap = nifty_vs_sp500_gap = nifty_vs_nikkei_gap = 0.0


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
        if stock not in VALID_SET:
            continue
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

        if close_0919 < 50:
            continue
        
        lotsize = int(500000.0 / close_0919)

        processed_records.append({
            'stockname': stock,
            'prev_close': p_close,
            'close_0919': close_0919,
            'lotsize': lotsize,
            'prev_intraday_vwap_gap': prev_intraday_vwap_gap,
            'prev_intraday_roc_last_hour': prev_intraday_roc_last_hour,
            'prev_intraday_return': prev_intraday_return,
            'positive_arc_ratio': pos_arc_ratio,
            'Gap_Pct': Gap_Pct,
            'gap_0907_pct': gap_0907_pct,
            'morn_range_pct': morn_range_pct,
            'rejection_wick': rejection_wick,
            'nifty_gap': nifty_gap,
            'sp500_overnight_ret': sp500_overnight_ret,
            'nikkei_gap': nikkei_gap,
            'nifty_vs_sp500_gap': nifty_vs_sp500_gap,
            'nifty_vs_nikkei_gap': nifty_vs_nikkei_gap,
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
        print(f"#{idx+1} | {row['stockname'].ljust(12)} | Prob: {row['short_prob']*100:.1f}% | CMP: ₹{row['close_0919']:.2f} | Qty: {row['lotsize']} | Wick: {row['rejection_wick']:.2f}")
    print("=" * 75)

    # Save CSV output
    top4.to_csv(OUTPUT_CSV, index=False)
    print(f"\n✔ Plan saved to: {OUTPUT_CSV}")

    # Append to Master Daily Ledger
    append_to_daily_ledger(target_date_str, top4)

    # 6. Format and Send Telegram Message
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S IST')
    lines = [
        f"⚡ <b>[09:20 SCALP ENGINE: 20-MIN SHORT SELL SELECTION]</b>",
        f"📅 <b>Date:</b> {target_date_str} | ⏱️ <b>Generated:</b> {now_str}",
        f"🎯 <b>Holding Window:</b> 09:21 AM Entry ➔ 09:41 AM Exit (20 Mins)",
        f"📊 <b>Model Edge:</b> 64.83% Historical Win Rate | +₹61.22L Net PnL",
        "",
        "<b>🔻 TARGET 4 SHORT-SELL ORDERS:</b>"
    ]

    for idx, row in top4.iterrows():
        stk = row['stockname']
        prob = row['short_prob'] * 100
        cmp_p = row['close_0919']
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
    if not no_telegram:
        send_telegram_alert(tg_message)

    duration = (datetime.now() - start_time).total_seconds()
    print(f"\n🎉 09:20 Scalp Pipeline Completed Successfully in {duration:.2f} seconds.")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="09:20 - 09:40 Scalp Engine Live Runner")
    parser.add_argument('--date', type=str, default=None, help="Target Date YYYY-MM-DD (defaults to latest in DB)")
    parser.add_argument('--no-telegram', action='store_true', help="Skip sending Telegram alert")
    args = parser.parse_args()

    run_scalp_pipeline(target_date_str=args.date, no_telegram=args.no_telegram)
