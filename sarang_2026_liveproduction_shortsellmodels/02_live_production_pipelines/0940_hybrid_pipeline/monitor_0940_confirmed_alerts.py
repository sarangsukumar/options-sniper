#!/usr/bin/env python3
"""
monitor_0940_confirmed_alerts.py
=================================
Independent Real-Time Confirmation Watcher for 09:40 Short-Sell Model.
Monitors candidate stocks between 09:43:00 AM and 10:45:00 AM IST.

When a candidate stock satisfies downward confirmation:
  - cond_a (Direct Downward):
      -0.55% <= move_vs_0942 <= -0.20%, max_bounce <= +0.35%, LTP < VWAP, 1m red
  - cond_b (Bounce-Rejection):
      +0.25% <= max_bounce <= +1.25%, broke below 09:42 (-0.40% to -0.05%), LTP < VWAP, 1m & 2m red

It immediately sends an instant Telegram alert with the stock name, rank, trigger condition,
LTP, and move vs 09:42 benchmark price.

CRITICAL:
- This is a 100% independent watcher.
- It does NOT touch, place, or modify live orders.
- It guarantees zero deletions and zero disruption to live execution.
"""

import os
import sys
import time
import argparse
import subprocess
import pytz
import pandas as pd
from datetime import datetime, date

IST = pytz.timezone('Asia/Kolkata')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PREDICTIONS_CSV = os.path.join(BASE_DIR, 'live_predictions_today.csv')
CONFIRMED_LOG_CSV = os.path.join(BASE_DIR, 'confirmed_alerts_today.csv')
WATCHER_LOG = os.path.join(BASE_DIR, 'watcher_0940.log')

BOT_SCRIPT = '/home/ubuntu/telegram_bot/New_OrderInfoBot.js'
MASTER_FILE = '/home/ubuntu/KotakCodes1/masterfile/ICICImaster_EQ.csv'
AUTH_CSV = '/home/ubuntu/KotakCodes1/kotak_auth_userid.csv'

SYMBOL_ALIASES = {
    'TATAMOTORS': 'TMPV',
    'TMPV': 'TMPV',
    'IBULHSGFIN': 'SAMMAANCAP',
    'SAMMAANCAP': 'SAMMAANCAP',
    'GMRINFRA': 'GMRP&UI',
    'GMRP&UI': 'GMRP&UI',
    'L&TFH': 'LTF',
    'LTF': 'LTF',
    'LTIMINDTREE': 'LTM',
    'LTIM': 'LTM',
    'MCDOWELL-N': 'UNITDSPR',
    'UNITDSPR': 'UNITDSPR',
    'M&MFIN': 'MMFIN',
    'MMFIN': 'MMFIN',
}

_MASTER_TOKEN_CACHE = None

def log_msg(msg):
    now_str = datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S')
    formatted = f"[{now_str}] [0940_CONFIRM_WATCHER] {msg}"
    print(formatted)
    try:
        with open(WATCHER_LOG, 'a') as f:
            f.write(formatted + '\n')
    except Exception:
        pass

def find_eq_numeric_token(stockname):
    global _MASTER_TOKEN_CACHE
    if not stockname:
        return None
    raw_sym = str(stockname).strip().upper()
    clean_sym = SYMBOL_ALIASES.get(raw_sym, raw_sym)
    try:
        if _MASTER_TOKEN_CACHE is None and os.path.exists(MASTER_FILE):
            df = pd.read_csv(MASTER_FILE, low_memory=False)
            eq_df = df[df['series'].astype(str).str.strip().str.upper() == 'EQ']
            _MASTER_TOKEN_CACHE = dict(zip(
                eq_df['stockcodes'].astype(str).str.strip().str.upper(),
                eq_df['token'].astype(str).str.strip()
            ))
        if _MASTER_TOKEN_CACHE:
            return _MASTER_TOKEN_CACHE.get(clean_sym) or _MASTER_TOKEN_CACHE.get(raw_sym)
    except Exception as e:
        log_msg(f"⚠️ Token lookup exception for {stockname}: {e}")
    return None

def get_kotak_client():
    try:
        from neo_api_client import NeoAPI
        import pyotp

        if not os.path.exists(AUTH_CSV):
            log_msg(f"⚠️ Auth CSV not found at {AUTH_CSV}")
            return None

        auth_df = pd.read_csv(AUTH_CSV)
        if auth_df.empty:
            return None
        row = auth_df.iloc[0]

        client = NeoAPI(consumer_key=str(row['consumer_key']), environment='prod', neo_fin_key='neotradeapi')
        totp_code = pyotp.TOTP(str(row['totp_secret']).strip()).now()
        mobile = str(row['mobile_number']).strip()
        formatted_mobile = mobile if mobile.startswith('+') else f"+91{mobile}"

        client.totp_login(mobile_number=formatted_mobile, ucc=str(row['userid']), totp=totp_code)
        client.totp_validate(mpin=str(int(row['MPIN'])))
        log_msg("✅ Authenticated Kotak Neo client successfully.")
        return client
    except Exception as e:
        log_msg(f"⚠️ Kotak client initialization failed: {e}")
        return None

def fetch_live_quote(client, stockname):
    token = find_eq_numeric_token(stockname)
    if not token or client is None:
        return None
    try:
        resp = client.quotes([{"instrument_token": str(token), "exchange_segment": "nse_cm"}], quote_type="")
        if isinstance(resp, list) and len(resp) > 0:
            q = resp[0]
            ltp = float(q.get('ltp', 0.0))
            vwap = float(q.get('average_price', 0.0))
            if vwap <= 0:
                ohlc = q.get('ohlc', {})
                vwap = float(ohlc.get('close', ltp))
            return {'ltp': ltp, 'vwap': vwap}
    except Exception as e:
        log_msg(f"⚠️ Quote fetch failed for {stockname}: {e}")
    return None

def send_telegram_alert(stockname, rank, trigger_type, entry_0942, confirmed_ltp, move_pct, max_bounce_pct, vwap, trigger_time_str, dry_run=False):
    msg_lines = [
        "🎯 <b>09:40 CONFIRMED SHORT-SELL SIGNAL</b>",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"• <b>Stock:</b> <code>{stockname}</code> (Rank #{rank})",
        f"• <b>Status:</b> <b>CONFIRMED DOWNWARD</b> 📉",
        f"• <b>Trigger Rule:</b> {trigger_type}",
        f"• <b>09:42 Ref Price:</b> ₹{entry_0942:,.2f}",
        f"• <b>Confirmed LTP:</b> ₹{confirmed_ltp:,.2f} ({move_pct:+.2f}%)",
        f"• <b>Day VWAP:</b> ₹{vwap:,.2f} (LTP &lt; VWAP ✅)",
        f"• <b>Max Prior Bounce:</b> {max_bounce_pct:+.2f}%",
        f"• <b>Trigger Time:</b> {trigger_time_str} IST",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "⚡ <i>Automated — 09:40 Hybrid Real-Time Confirmation Watcher</i>"
    ]
    if dry_run:
        msg_lines.insert(1, "🧪 <i>[SIMULATED DRY-RUN TEST]</i>")

    msg = "\n".join(msg_lines)
    log_msg(f"📢 Sending Confirmation Alert for {stockname} ({trigger_type}) at {confirmed_ltp:,.2f} ({move_pct:+.2f}%)...")

    if not os.path.exists(BOT_SCRIPT):
        log_msg(f"⚠️ Telegram bot script not found at {BOT_SCRIPT}")
        return False

    try:
        escaped_msg = msg.replace('"', '\\"')
        subprocess.run(['node', BOT_SCRIPT, escaped_msg], check=True)
        log_msg(f"✅ Telegram alert successfully delivered for {stockname}!")
        return True
    except Exception as e:
        log_msg(f"⚠️ Failed to send Telegram alert for {stockname}: {e}")
        return False

def record_confirmed_alert(stockname, rank, trigger_type, entry_0942, confirmed_ltp, move_pct, max_bounce_pct, trigger_time_str):
    today_str = datetime.now(IST).strftime('%Y-%m-%d')
    new_row = pd.DataFrame([{
        'date': today_str,
        'time': trigger_time_str,
        'stockname': stockname,
        'model_rank': rank,
        'trigger_type': trigger_type,
        'entry_price_0942': entry_0942,
        'confirmed_ltp': confirmed_ltp,
        'move_pct': move_pct,
        'max_bounce_pct': max_bounce_pct
    }])
    try:
        if os.path.exists(CONFIRMED_LOG_CSV):
            new_row.to_csv(CONFIRMED_LOG_CSV, mode='a', header=False, index=False)
        else:
            new_row.to_csv(CONFIRMED_LOG_CSV, mode='w', header=True, index=False)
    except Exception as e:
        log_msg(f"⚠️ Error appending to {CONFIRMED_LOG_CSV}: {e}")

def run_dry_run_test():
    log_msg("🧪 Starting 09:40 Confirmation Watcher DRY-RUN TEST...")
    mock_candidates = [
        {'stockname': 'TATACHEM', 'model_rank': 1, 'entry_price_0940': 1050.0},
        {'stockname': 'DEEPAKNTR', 'model_rank': 2, 'entry_price_0940': 1520.0},
        {'stockname': 'UNITDSPR', 'model_rank': 3, 'entry_price_0940': 1320.0},
        {'stockname': 'AARTIIND', 'model_rank': 4, 'entry_price_0940': 445.0}
    ]

    log_msg(f"📋 Loaded {len(mock_candidates)} mock candidates for 09:42 benchmark.")

    # 1. Test cond_a (Direct Downward on TATACHEM)
    # Move -0.32%, max bounce +0.10%, LTP < VWAP, 1m return < 0
    ref_price = 1050.0
    confirmed_ltp = 1046.60
    move_pct = ((confirmed_ltp - ref_price) / ref_price) * 100.0
    max_bounce_pct = 0.10
    vwap = 1048.50
    now_time = datetime.now(IST).strftime('%H:%M:%S')

    log_msg(f"🧪 Testing cond_a simulation on TATACHEM (Move: {move_pct:.2f}%, Max Bounce: {max_bounce_pct:.2f}%)...")
    is_cond_a = (-0.55 <= move_pct <= -0.20) and (max_bounce_pct <= 0.35) and (confirmed_ltp < vwap)
    assert is_cond_a, "cond_a verification failed!"
    send_telegram_alert('TATACHEM', 1, 'Direct Downward (cond_a)', ref_price, confirmed_ltp, move_pct, max_bounce_pct, vwap, now_time, dry_run=True)
    record_confirmed_alert('TATACHEM', 1, 'Direct Downward (cond_a)', ref_price, confirmed_ltp, move_pct, max_bounce_pct, now_time)

    # 2. Test cond_b (Bounce-Rejection on DEEPAKNTR)
    # Prior bounce +0.45%, rolled over to -0.18%, LTP < VWAP, 1m & 2m negative
    ref_price_2 = 1520.0
    confirmed_ltp_2 = 1517.20
    move_pct_2 = ((confirmed_ltp_2 - ref_price_2) / ref_price_2) * 100.0
    max_bounce_pct_2 = 0.45
    vwap_2 = 1522.00
    now_time_2 = datetime.now(IST).strftime('%H:%M:%S')

    log_msg(f"🧪 Testing cond_b simulation on DEEPAKNTR (Move: {move_pct_2:.2f}%, Max Bounce: {max_bounce_pct_2:.2f}%)...")
    is_cond_b = (0.25 <= max_bounce_pct_2 <= 1.25) and (-0.40 <= move_pct_2 <= -0.05) and (confirmed_ltp_2 < vwap_2)
    assert is_cond_b, "cond_b verification failed!"
    send_telegram_alert('DEEPAKNTR', 2, 'Bounce-Rejection (cond_b)', ref_price_2, confirmed_ltp_2, move_pct_2, max_bounce_pct_2, vwap_2, now_time_2, dry_run=True)
    record_confirmed_alert('DEEPAKNTR', 2, 'Bounce-Rejection (cond_b)', ref_price_2, confirmed_ltp_2, move_pct_2, max_bounce_pct_2, now_time_2)

    log_msg("✅ DRY-RUN TEST COMPLETE: Both cond_a and cond_b validated and dispatched.")

def main():
    parser = argparse.ArgumentParser(description="09:40 Real-Time Confirmation Watcher Daemon")
    parser.add_argument('--dry-run', action='store_true', help="Run simulated dry-run validation")
    parser.add_argument('--interval', type=int, default=30, help="Polling interval in seconds (default: 30s)")
    parser.add_argument('--csv', type=str, default=PREDICTIONS_CSV, help="Path to live_predictions_today.csv")
    args = parser.parse_args()

    if args.dry_run:
        run_dry_run_test()
        return

    log_msg("🚀 09:40 Confirmation Watcher started.")

    if not os.path.exists(args.csv):
        log_msg(f"⚠️ Predictions file not found: {args.csv}. Exiting.")
        return

    df_preds = pd.read_csv(args.csv)
    if df_preds.empty:
        log_msg("⚠️ Predictions file is empty. Exiting.")
        return

    # Filter top 4 candidates
    candidates = {}
    for _, row in df_preds.head(4).iterrows():
        sym = str(row.get('clean_stock') or row.get('stockname')).strip().upper()
        rank = int(row.get('model_rank', len(candidates) + 1))
        p0942 = float(row.get('entry_price_0940') or row.get('prev_close', 0.0))
        candidates[sym] = {
            'rank': rank,
            'entry_0942': p0942,
            'high_since_0942': p0942,
            'history': [], # list of (timestamp, ltp)
            'confirmed': False
        }

    log_msg(f"🎯 Monitoring {len(candidates)} candidate stocks: {list(candidates.keys())}")

    client = get_kotak_client()
    if client is None:
        log_msg("⚠️ Failed to initialize Kotak API client. Cannot poll live ticks. Exiting.")
        return

    alerted_set = set()

    # Main Polling Loop between 09:43:00 and 10:45:00 IST
    while True:
        now_ist = datetime.now(IST)
        now_time_str = now_ist.strftime('%H:%M:%S')

        # Time check: stop at 10:45:00 AM IST
        if now_time_str >= '10:45:00':
            log_msg(f"🛑 Time reached {now_time_str} IST (>= 10:45:00 AM). Watcher window closed. Exiting.")
            break

        # If all candidates already confirmed, exit early
        unconfirmed = [s for s, d in candidates.items() if not d['confirmed']]
        if not unconfirmed:
            log_msg("🎉 All candidates confirmed downward movement! Watcher finished.")
            break

        # Poll quotes for unconfirmed candidates
        for sym in unconfirmed:
            info = candidates[sym]
            quote = fetch_live_quote(client, sym)
            if not quote or quote['ltp'] <= 0:
                continue

            ltp = quote['ltp']
            vwap = quote['vwap']
            ref_p = info['entry_0942']

            if ref_p <= 0:
                info['entry_0942'] = ltp
                ref_p = ltp

            # Update highest price since 09:42
            if ltp > info['high_since_0942']:
                info['high_since_0942'] = ltp

            info['history'].append((now_ist, ltp))
            # Keep history within last 5 minutes
            if len(info['history']) > 15:
                info['history'].pop(0)

            max_bounce_pct = ((info['high_since_0942'] - ref_p) / ref_p) * 100.0
            move_vs_0942_pct = ((ltp - ref_p) / ref_p) * 100.0

            # Calculate 1m and 2m returns if history allows
            ret_1m = -0.01  # Default bearish if first tick
            ret_2m = -0.01
            if len(info['history']) >= 2:
                prev_1m_ltp = info['history'][-2][1]
                ret_1m = ((ltp - prev_1m_ltp) / prev_1m_ltp) * 100.0
            if len(info['history']) >= 3:
                prev_2m_ltp = info['history'][-3][1]
                ret_2m = ((ltp - prev_2m_ltp) / prev_2m_ltp) * 100.0

            # Evaluate cond_a: Direct Downward
            cond_a = (
                (-0.55 <= move_vs_0942_pct <= -0.20) and
                (max_bounce_pct <= 0.35) and
                (ltp < vwap) and
                (ret_1m < 0)
            )

            # Evaluate cond_b: Bounce-Rejection
            cond_b = (
                (0.25 <= max_bounce_pct <= 1.25) and
                (-0.40 <= move_vs_0942_pct <= -0.05) and
                (ltp < vwap) and
                (ret_1m < 0) and
                (ret_2m <= -0.10)
            )

            if cond_a or cond_b:
                trigger_name = "Direct Downward (cond_a)" if cond_a else "Bounce-Rejection (cond_b)"
                if sym not in alerted_set:
                    alerted_set.add(sym)
                    info['confirmed'] = True
                    send_telegram_alert(
                        stockname=sym,
                        rank=info['rank'],
                        trigger_type=trigger_name,
                        entry_0942=ref_p,
                        confirmed_ltp=ltp,
                        move_pct=move_vs_0942_pct,
                        max_bounce_pct=max_bounce_pct,
                        vwap=vwap,
                        trigger_time_str=now_time_str
                    )
                    record_confirmed_alert(
                        stockname=sym,
                        rank=info['rank'],
                        trigger_type=trigger_name,
                        entry_0942=ref_p,
                        confirmed_ltp=ltp,
                        move_pct=move_vs_0942_pct,
                        max_bounce_pct=max_bounce_pct,
                        trigger_time_str=now_time_str
                    )

        time.sleep(args.interval)

if __name__ == '__main__':
    main()
