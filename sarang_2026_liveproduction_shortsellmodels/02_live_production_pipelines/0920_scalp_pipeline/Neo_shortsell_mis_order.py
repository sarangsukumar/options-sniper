#!/usr/bin/env python3
"""
Neo_shortsell_mis_order.py
==========================
Production MIS Short Sell + Square-Off Order Placer — Kotak Neo API
Single script for both entry (SELL short) and exit (BUY cover) of MIS positions.

SELL Mode (default):
    python3 Neo_shortsell_mis_order.py 0920_SCALP
    python3 Neo_shortsell_mis_order.py 0942_HYBRID

SQUAREOFF Mode (buy cover at 09:36 or 09:40):
    python3 Neo_shortsell_mis_order.py 0920_SCALP SQUAREOFF 0936
    python3 Neo_shortsell_mis_order.py 0920_SCALP SQUAREOFF 0940

SELL Safeguards:
  1. Single-instance lock    — lockfile + psutil duplicate-process check
  2. DB state machine        — only processes isvalid='TRUE', sets '1.5' after place
  3. broker_orders JOIN      — skips stocks already executed today
  4. Open positions check    — skips if already short in open positions API
  5. Completed SELL skip     — skips if already filled SELL per Kotak order book
  6. 3-retry with backoff    — on transient Kotak API errors
  7. Telegram failure alert  — async on placement failure
  8. trading_settings.json   — kill-switch: set "place_shortsell_order": false to disable

SQUAREOFF Safeguards (additional):
  9.  DB profit check (0936) — only covers if profit_pct > PROFIT_THRESHOLD_PCT (0.05%)
  10. Already-covered check  — skips if scalp_trade_log already shows EXIT_PLACED_* for stock today
  11. Open BUY order check   — skips if a pending/open BUY order already in Kotak order book
  12. Completed BUY skip     — skips if a completed BUY order already in Kotak order book
  13. kill-switch            — set "place_squareoff_order": false in trading_settings.json
"""

import os
import sys
import json
import time as sys_time
import base64
import logging
import traceback
import subprocess
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta
import pytz

import psutil
import pyotp
import pymysql
import pandas as pd
from neo_api_client import NeoAPI
import warnings

warnings.filterwarnings('ignore')

IST = pytz.timezone('Asia/Kolkata')

def get_ist_now():
    return datetime.now(IST)

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────
SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
LOG_DIR      = os.path.join(SCRIPT_DIR, 'logs')
LOG_FILE     = os.path.join(LOG_DIR, 'shortsell_mis_orders.txt')
AUTH_CSV     = os.path.join(SCRIPT_DIR, 'kotak_auth_userid.csv')
USER_TABLE   = os.path.join(SCRIPT_DIR, 'User_table.csv')
SETTINGS_JSON = os.path.join(SCRIPT_DIR, 'trading_settings.json')
BOT_SCRIPT   = '/home/ubuntu/KotakCodes1/status_Info_bot.js'

# ── SQUAREOFF CONFIG ──────────────────────────────────────────────────────────
# At 09:36: only exit if unrealised profit > this threshold (in Rupees)
PROFIT_THRESHOLD_RS = 500.0   # Flat ₹500 unrealized PnL threshold for early profit exit

os.makedirs(LOG_DIR, exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────────────────────────────────────
logger = logging.getLogger('shortsell_mis')
logger.setLevel(logging.INFO)
if not logger.handlers:
    fh = logging.FileHandler(LOG_FILE)
    fh.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%d-%b-%y %H:%M:%S'))
    logger.addHandler(fh)

def log_print(msg):
    logger.info(str(msg))
    print(msg)

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────
@contextmanager
def suppress_stdout():
    if os.name != 'posix':
        yield; return
    old_fd = os.dup(1)
    with open(os.devnull, 'w') as dn:
        os.dup2(dn.fileno(), 1)
        try: yield
        finally:
            os.dup2(old_fd, 1)
            os.close(old_fd)

def get_trading_setting(key, default=True):
    try:
        with open(SETTINGS_JSON) as f:
            return json.load(f).get(key, default)
    except Exception:
        return default

def is_another_instance_running(name):
    current_pid = os.getpid()
    for proc in psutil.process_iter(['pid', 'cmdline']):
        try:
            if proc.pid == current_pid:
                continue
            cmdline = proc.info['cmdline'] or []
            # Must be a python process running this specific script
            is_python = any('python' in str(c).lower() for c in cmdline)
            has_script = any(name in os.path.basename(str(c)) for c in cmdline)
            if is_python and has_script:
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return False

def send_telegram_alert(msg):
    def _send():
        try:
            subprocess.run(['node', BOT_SCRIPT, msg], timeout=15)
        except Exception:
            pass
    threading.Thread(target=_send, daemon=True).start()

_STOCK_TICK_CACHE = {}

def get_tick_size(price, stockname=None, client=None):
    if stockname:
        raw_sym = str(stockname).strip().upper()
        clean_sym = SYMBOL_ALIASES.get(raw_sym, raw_sym) if 'SYMBOL_ALIASES' in globals() else raw_sym
        if clean_sym in _STOCK_TICK_CACHE:
            return _STOCK_TICK_CACHE[clean_sym]
        if client is not None:
            try:
                with suppress_stdout():
                    res = client.search_scrip(exchange_segment='nse_cm', symbol=clean_sym)
                data = res if isinstance(res, list) else (res.get('data', []) if isinstance(res, dict) else [])
                for d in data:
                    if str(d.get('pTrdSymbol', '')).strip().upper() == f"{clean_sym}-EQ":
                        dtick = float(d.get('dTickSize', 0) or 0)
                        if dtick > 0:
                            tick_rs = round(dtick / 100.0, 2)
                            _STOCK_TICK_CACHE[clean_sym] = tick_rs
                            _STOCK_TICK_CACHE[raw_sym] = tick_rs
                            return tick_rs
            except Exception:
                pass
    if price <= 250:   return 0.01
    if price <= 1000:  return 0.05
    if price <= 5000:  return 0.10
    if price <= 10000: return 0.50
    if price <= 20000: return 1.00
    return 5.00

def round_to_tick(price, stockname=None, client=None):
    tick = get_tick_size(price, stockname=stockname, client=client)
    return round(round(price / tick) * tick, 2)

import glob

# Symbol Aliases for renamed / demerged / split tickers
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
}

def get_latest_scripmaster():
    # Primary: daily updated ICICImaster_EQ.csv generated at 6:45 AM
    primary = '/home/ubuntu/KotakCodes1/masterfile/ICICImaster_EQ.csv'
    if os.path.exists(primary):
        return primary
    # Secondary fallback: config backup
    backup = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/config/ICICImaster_EQ.csv'
    if os.path.exists(backup):
        return backup
    return primary

def find_eq_numeric_token(stockname):
    """
    Look up NSE EQ (cash market) numeric token from daily ICICImaster_EQ.csv.
    Needed for the client.quotes() API to fetch live LTP.
    """
    if not stockname:
        return None
    raw_sym = str(stockname).strip().upper()
    clean_sym = SYMBOL_ALIASES.get(raw_sym, raw_sym)

    try:
        master_file = get_latest_scripmaster()
        if not os.path.exists(master_file):
            return None
        df = pd.read_csv(master_file, low_memory=False)
        # In ICICImaster_EQ.csv, columns are: token, scripcode, series, lotsize, ticksize, stockcodes
        sc_col = 'stockcodes' if 'stockcodes' in df.columns else ('stockCodes' if 'stockCodes' in df.columns else df.columns[5])
        ser_col = 'series' if 'series' in df.columns else df.columns[2]
        tok_col = 'token' if 'token' in df.columns else ('Token' if 'Token' in df.columns else df.columns[0])

        rows = df[(df[sc_col].astype(str).str.strip().str.upper().isin([clean_sym, raw_sym])) & 
                  (df[ser_col].astype(str).str.strip().str.upper()=='EQ')]
        if not rows.empty:
            return str(rows.iloc[0][tok_col])
    except Exception as e:
        log_print(f"  ⚠️  find_eq_numeric_token error for {stockname}: {e}")
    return None

# Compatibility alias for exit scripts
get_instrument_token = find_eq_numeric_token

class _TokenToSymbolMap(dict):
    def get(self, token, default=None):
        return self[token] if token in self else default
    def __getitem__(self, token):
        # Return trading symbol if token found
        return str(token)
    def __contains__(self, token):
        return False

TOKEN_TO_SYMBOL = _TokenToSymbolMap()

def fetch_live_ltp(client, stockname):
    """
    Fetches exact real-time LTP using Kotak Neo client.quotes() API.
    """
    token = find_eq_numeric_token(stockname)
    if not token:
        log_print(f"  ⚠️  Could not find numeric token for {stockname}, unable to fetch live LTP.")
        return None
    try:
        resp = client.quotes([{"instrument_token": token, "exchange_segment": "nse_cm"}], quote_type="ltp")
        if isinstance(resp, list) and len(resp) > 0 and 'ltp' in resp[0]:
            return float(resp[0]['ltp'])
        else:
            log_print(f"  ⚠️  Quotes API returned unexpected format for {stockname}: {resp}")
    except Exception as e:
        log_print(f"  ⚠️  Quotes API failed for {stockname}: {e}")
    return None


def adjust_qty_for_kotak_margin(client, stockname, price, db_qty, db_price, model_name, db_id=None, today=None):
    """
    Queries Kotak Neo client.margin_required() before placing an MIS SELL order.
    - 0920_SCALP: ₹5.00L notional @ 5x -> max actual cash margin = ₹1,00,000 per stock.
    - 0942_HYBRID: ₹6.25L notional (4 stocks) @ 5x -> max actual cash margin = ₹1,25,000 per stock.
    If a stock has lower leverage in Kotak (e.g., 3x / 33.33% margin like UBL instead of 5x / 20%),
    caps quantity so actual cash margin required (ordMrgn) stays within max_actual_margin.
    Normal 5x leverage stocks are 100% untouched. Wrapped in full try/except fallback.
    """
    try:
        if not db_qty or int(db_qty) <= 0 or not price or float(price) <= 0:
            return int(db_qty)
        db_qty = int(db_qty)
        price_f = float(price)
        ref_price = float(db_price) if (db_price and float(db_price) > 0) else price_f
        planned_notional = db_qty * ref_price

        if model_name == '0920_SCALP':
            # Map intended capital tier:
            # 7.5L input tier (6.0L - 8.0L)  -> ₹1.25 Lakhs actual margin (₹6.25L base notional @ 5x)
            # 10.0L input tier (9.0L - 12.0L) -> ₹2.00 Lakhs actual margin (₹10.0L base notional @ 5x)
            # 20.0L input tier (18.0L - 22.0L) -> ₹4.00 Lakhs actual margin (₹20.0L base notional @ 5x)
            if 600000.0 <= planned_notional <= 800000.0:
                max_actual_margin = 125000.0
            elif 900000.0 <= planned_notional <= 1200000.0:
                max_actual_margin = 200000.0
            elif 1800000.0 <= planned_notional <= 2200000.0:
                max_actual_margin = 400000.0
            else:
                max_actual_margin = max(100000.0, round(planned_notional / 5.0, 2))
        elif model_name == '0942_HYBRID':
            # ₹1.25 Lakh actual margin per stock (₹6.25L notional @ 5x)
            max_actual_margin = 125000.0
        else:
            max_actual_margin = max(100000.0, round(planned_notional / 5.0, 2))

        token = find_eq_numeric_token(stockname)
        if not token:
            log_print(f"  ⚠️  [MARGIN CHECK] No numeric token for {stockname} — keeping Qty={db_qty}")
            return db_qty

        with suppress_stdout():
            m_resp = client.margin_required(
                exchange_segment='nse_cm',
                price=str(round_to_tick(price_f)),
                order_type='L',
                product='MIS',
                quantity=str(db_qty),
                instrument_token=str(token),
                transaction_type='S'
            )

        if not isinstance(m_resp, dict):
            log_print(f"  ⚠️  [MARGIN CHECK] Unexpected margin_required response for {stockname}: {m_resp} — keeping Qty={db_qty}")
            return db_qty

        data = m_resp.get('data') if isinstance(m_resp.get('data'), dict) else m_resp
        stat_val = str(data.get('stat') or m_resp.get('stat') or '').strip().lower()
        if stat_val != 'ok' or ('ordMrgn' not in data and 'reqdMrgn' not in data):
            log_print(f"  ⚠️  [MARGIN CHECK] Unexpected margin_required response for {stockname}: {m_resp} — keeping Qty={db_qty}")
            return db_qty

        ord_mrgn = float(data.get('ordMrgn') or data.get('reqdMrgn') or 0.0)
        if ord_mrgn <= 0:
            return db_qty

        order_notional = price_f * db_qty
        margin_pct = (ord_mrgn / order_notional) * 100.0 if order_notional > 0 else 20.0
        eff_leverage = (100.0 / margin_pct) if margin_pct > 0 else 5.0
        margin_per_share = ord_mrgn / float(db_qty)

        # Cap quantity if Kotak requires >2% above target actual cash margin (ensures actual cash margin strictly <= max_actual_margin)
        if ord_mrgn > (max_actual_margin * 1.02) and margin_per_share > 0:
            new_qty = max(1, int(max_actual_margin // margin_per_share))
            if new_qty < db_qty:
                new_margin = new_qty * margin_per_share
                log_print(
                    f"  🛡️  [KOTAK MARGIN CAP] {stockname}: Kotak Margin={margin_pct:.2f}% ({eff_leverage:.2f}x leverage, ₹{margin_per_share:.2f}/sh) | "
                    f"Uncapped Margin=₹{ord_mrgn:,.0f} > Cap=₹{max_actual_margin:,.0f} → "
                    f"Adjusting Qty: {db_qty} → {new_qty} (Actual Margin: ₹{new_margin:,.0f})"
                )
                # Sync updated quantity to shortsell_orders in MySQL so confirm_*_fills.py & trade logs match
                if db_id:
                    try:
                        conn = get_db_connection()
                        with conn.cursor() as c:
                            c.execute(
                                "UPDATE shortsell_orders SET quantity=%s, modtime=NOW() WHERE id=%s",
                                (new_qty, db_id)
                            )
                        conn.commit()
                        conn.close()
                        log_print(f"    DB quantity synced: id={db_id} ({stockname}) → quantity={new_qty}")
                    except Exception as dbe:
                        log_print(f"    ⚠️ DB quantity sync warning for {stockname}: {dbe}")

                # Also sync daily_0940_live_ledger.csv and audited_0940_hybrid_trades.csv if 0942_HYBRID
                if model_name == '0942_HYBRID' and today:
                    try:
                        ledger_paths = [
                            '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_shortsell_t1_2026/02_0942_Hybrid_Model/live_production/daily_0940_live_ledger.csv',
                            '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_shortsell_t1_2026/02_0942_Hybrid_Model/live_production/audited_0940_hybrid_trades.csv',
                            '/home/ubuntu/sarang_shortsell_t1_2026/02_0942_Hybrid_Model/audited_0940_hybrid_trades.csv',
                            '/home/ubuntu/live_production0940_model/daily_0940_live_ledger.csv'
                        ]
                        for lp in ledger_paths:
                            if os.path.exists(lp):
                                ldf = pd.read_csv(lp, low_memory=False)
                                mask = (ldf['date'].astype(str) == str(today)) & (
                                    (ldf['stockname'].astype(str).str.upper() == stockname.upper()) |
                                    (ldf.get('clean_stock', pd.Series('', index=ldf.index)).astype(str).str.upper() == stockname.upper())
                                )
                                if mask.any():
                                    ldf.loc[mask, 'total_quantity'] = new_qty
                                    ldf.to_csv(lp, index=False)
                    except Exception as le:
                        log_print(f"    ⚠️ Ledger quantity sync warning for {stockname}: {le}")

                return new_qty

        log_print(
            f"  ✅ [KOTAK MARGIN OK] {stockname}: Kotak Margin={margin_pct:.2f}% ({eff_leverage:.2f}x leverage) | "
            f"Actual Margin=₹{ord_mrgn:,.0f} (Cap: ₹{max_actual_margin:,.0f}) | Qty={db_qty} unchanged"
        )
        return db_qty
    except Exception as e:
        log_print(f"  ⚠️  [MARGIN CHECK FALLBACK] Error checking margin for {stockname}: {e} — keeping Qty={db_qty}")
        return int(db_qty)

def find_eq_scripcode(stockname):
    """
    For Kotak Neo nse_cm (cash market) segment, the trading_symbol format is:
    STOCKNAME-EQ  (e.g. 'INFY-EQ', 'ULTRACEMCO-EQ', 'TMPV-EQ')
    """
    if not stockname:
        return None
    raw_sym = str(stockname).strip().upper()
    clean_sym = SYMBOL_ALIASES.get(raw_sym, raw_sym)
    return f"{clean_sym}-EQ"


def get_db_connection():
    return pymysql.connect(
        host='localhost', user='root', password='root',
        database='markets', cursorclass=pymysql.cursors.DictCursor
    )

# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
def main():
    if len(sys.argv) < 2:
        print("Usage: python3 Neo_shortsell_mis_order.py <MODEL_NAME> [SQUAREOFF|SQUAREOFF_CHASE|REENTRY] [WINDOW|STOCK] [QTY] [PRICE]")
        print("  SELL mode:      python3 Neo_shortsell_mis_order.py 0920_SCALP")
        print("  Squareoff mode: python3 Neo_shortsell_mis_order.py 0920_SCALP SQUAREOFF 0936")
        print("  Chaser mode:    python3 Neo_shortsell_mis_order.py 0920_SCALP SQUAREOFF_CHASE 0940")
        print("  Re-entry mode:  python3 Neo_shortsell_mis_order.py 0942_HYBRID REENTRY [STOCK] [QTY] [PRICE]")
        sys.exit(1)

    model_name  = sys.argv[1].upper()
    mode        = sys.argv[2].upper() if len(sys.argv) > 2 else 'SELL'
    exit_window = sys.argv[3] if len(sys.argv) > 3 else '0940'
    today       = get_ist_now().strftime('%Y-%m-%d')

    target_stock = sys.argv[3].upper() if len(sys.argv) > 3 and mode == 'REENTRY' else None
    target_qty   = int(sys.argv[4]) if len(sys.argv) > 4 and mode == 'REENTRY' and str(sys.argv[4]).isdigit() else None
    target_price = float(sys.argv[5]) if len(sys.argv) > 5 and mode == 'REENTRY' else None

    log_print("=" * 75)
    if mode in ('SQUAREOFF', 'SQUAREOFF_CHASE'):
        log_print(f"🔲 MIS SQUAREOFF ORDER PLACER — {model_name} | Mode={mode} | Window={exit_window} | {today}")
    elif mode == 'REENTRY':
        log_print(f"🔄 MIS SHORT SELL RE-ENTRY — {model_name} | Stock={target_stock or 'ALL'} | {today}")
    else:
        log_print(f"🚀 MIS SHORT SELL ORDER PLACER — {model_name} | {today}")
    log_print("=" * 75)

    # ── Kill-switch ───────────────────────────────────────────────────────────
    if mode in ('SQUAREOFF', 'SQUAREOFF_CHASE'):
        if not get_trading_setting('place_squareoff_order', True):
            log_print("⛔ Kill-switch active (place_squareoff_order=false). Exiting.")
            sys.exit(0)
    else:
        if not get_trading_setting('place_shortsell_order', True):
            log_print("⛔ Kill-switch active (place_shortsell_order=false). Exiting.")
            sys.exit(0)

    # ── Single-instance lock ─────────────────────────────────────────────────
    lock_tag = f"{target_stock or 'all'}" if mode == 'REENTRY' else exit_window
    lock_file = f'/tmp/shortsell_mis_{model_name}_{mode}_{lock_tag}.lock'
    if os.path.exists(lock_file):
        try:
            with open(lock_file) as lf:
                old_pid = int(lf.read().strip())
            if psutil.pid_exists(old_pid):
                log_print(f"⚠️  Another instance (PID {old_pid}) already running for {model_name} {mode} {lock_tag}. Exiting.")
                sys.exit(1)
            else:
                os.remove(lock_file)
        except Exception:
            os.remove(lock_file)

    with open(lock_file, 'w') as lf:
        lf.write(str(os.getpid()))

    try:
        if mode in ('SQUAREOFF', 'SQUAREOFF_CHASE'):
            _run_position_based_squareoff(model_name, today, exit_window)
        elif mode == 'REENTRY':
            _run_reentry_orders(model_name, today, target_stock, target_qty, target_price)
        else:
            _run_orders(model_name, today)
    finally:
        if os.path.exists(lock_file):
            os.remove(lock_file)

    log_print(f"\n🎉 Neo_shortsell_mis_order.py [{mode}] completed.")


def _run_orders(model_name, today):
    # ── Read pending orders from DB ───────────────────────────────────────────
    conn = get_db_connection()
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT s.*
            FROM shortsell_orders s
            LEFT JOIN broker_orders b
                ON b.stockname    = s.stockname
                AND b.type        = 'SELL'
                AND b.orderexecutiondate = %s
            WHERE s.trade_date = %s
              AND s.model_name  = %s
              AND s.isvalid     = 'TRUE'
              AND b.id IS NULL
            ORDER BY s.order_rank ASC
        """, (today, today, model_name))
        orders = cursor.fetchall()
    conn.close()

    if not orders:
        log_print(f"ℹ️  No pending orders found for {model_name} on {today}. Nothing to place.")
        sys.exit(0)

    log_print(f"📋 Found {len(orders)} pending order(s) to place:")
    for o in orders:
        log_print(f"   Rank {o['order_rank']}: {o['stockname']} | Qty={o['quantity']} | ₹{o['limit_price']:.2f} | SL=₹{o['stop_loss_price']:.2f}")

    # ── Read users ────────────────────────────────────────────────────────────
    user_ids = []
    try:
        with open(USER_TABLE) as f:
            next(f)  # skip header
            for line in f:
                u = line.strip()
                if u:
                    user_ids.append(u)
    except Exception as e:
        log_print(f"❌ Could not read User_table.csv: {e}")
        sys.exit(1)

    # ── Per-user order placement ──────────────────────────────────────────────
    for userid in user_ids:
        log_print(f"\n{'='*25} USER: {userid} {'='*25}")

        # Load auth credentials
        try:
            auth_df = pd.read_csv(AUTH_CSV)
            auth    = auth_df[auth_df['userid'] == userid]
            if auth.empty:
                log_print(f"⚠️  User {userid} not found in auth CSV. Skipping.")
                continue
            row           = auth.iloc[0]
            consumer_key  = row['consumer_key']
            consumer_secret = row['consumer_secret']
            MPIN          = str(int(row['MPIN']))
            mobile_number = str(row.get('mobile_number', '')).strip()
            totp_secret   = str(row.get('totp_secret', '')).strip()
            user_from_api = row['user_from_API']
        except Exception as e:
            log_print(f"❌ Auth load failed for {userid}: {e}")
            continue

        # Kotak TOTP login
        login_ok = False
        client   = None
        with suppress_stdout():
            try:
                client    = NeoAPI(consumer_key=consumer_key, environment='prod', neo_fin_key='neotradeapi')
                totp_code = pyotp.TOTP(totp_secret).now()
                formatted_mobile = mobile_number if mobile_number.startswith('+') else f'+91{mobile_number}'
                lr = client.totp_login(mobile_number=formatted_mobile, ucc=userid, totp=totp_code)
                if lr and 'error' in lr:
                    raise Exception(f"TOTP login error: {lr['error']}")
                vr = client.totp_validate(mpin=MPIN)
                if vr and 'error' in vr:
                    raise Exception(f"MPIN error: {vr['error']}")
                login_ok = True
            except Exception as e:
                log_print(f"❌ Login failed for {userid}: {e}")

        if not login_ok:
            log_print(f"❌ Skipping {userid} — login failed.")
            continue
        log_print(f"✔ Kotak session established for {userid} ({user_from_api})")

        # Fetch open positions to avoid double-entry
        open_short_stocks = set()
        try:
            with suppress_stdout():
                positions_resp = client.positions()
            if positions_resp and isinstance(positions_resp.get('data'), list):
                for pos in positions_resp['data']:
                    sym    = pos.get('trdSym', '') or pos.get('sym', '')
                    net_qty = int(pos.get('netQty', 0) or 0)
                    seg    = pos.get('exSeg', '')
                    if seg == 'nse_cm' and net_qty < 0:
                        # net_qty < 0 means short position
                        clean = sym.replace('-EQ', '').replace('_EQ', '').strip().upper()
                        open_short_stocks.add(clean)
                        log_print(f"  Already short: {clean} (qty={net_qty})")
        except Exception as e:
            log_print(f"  ⚠️  Could not fetch positions: {e} — proceeding without position check")

        # Fetch today's completed SELL orders from API (to skip already filled)
        # We filter by time so 09:42 model doesn't skip a stock traded by 09:20 model
        completed_sells = set()
        try:
            with suppress_stdout():
                order_book = client.order_report()
            if order_book and isinstance(order_book.get('data'), list):
                for o in order_book['data']:
                    seg    = o.get('exSeg', '')
                    status = o.get('ordSt', '')
                    ttype  = o.get('trnsTp', '')
                    sym    = o.get('trdSym', '') or o.get('sym', '')
                    ord_dt = o.get('ordDtTm', '') # e.g. "27-Sep-2026 09:25:01"
                    
                    if seg == 'nse_cm' and ttype == 'S' and status == 'complete':
                        # Parse time to determine which model placed this SELL
                        # Format is typically "DD-MMM-YYYY HH:MM:SS"
                        try:
                            time_str = ord_dt.split(' ')[1] # "HH:MM:SS"
                            hr_min = time_str[:5] # "HH:MM"
                        except:
                            hr_min = "00:00"

                        # 0920_SCALP orders are placed ~09:25
                        # 0942_HYBRID orders are placed ~09:42
                        # Require fill_qty >= 25 so manual 1-share test orders do not skip automated model trades
                        fill_qty = float(o.get('qty', 0) or o.get('fldQty', 0) or 0)
                        if fill_qty >= 25:
                            if model_name == '0920_SCALP' and hr_min < "09:30":
                                clean = sym.replace('-EQ', '').replace('_EQ', '').strip().upper()
                                completed_sells.add(clean)
                            elif model_name == '0942_HYBRID' and hr_min >= "09:40":
                                clean = sym.replace('-EQ', '').replace('_EQ', '').strip().upper()
                                completed_sells.add(clean)
                        
        except Exception as e:
            log_print(f"  ⚠️  Could not fetch order book: {e} — proceeding without fill check")
            
        if completed_sells:
            log_print(f"  Already filled SELLs for {model_name}: {completed_sells}")

        # ── Place each order ─────────────────────────────────────────────────
        success_list = []
        failed_list  = []

        for o in orders:
            db_id     = o['id']
            stockname = o['stockname']
            quantity  = o['quantity']
            db_price  = o['limit_price']
            
            # Order pricing
            order_type_val = 'L'
            live_ltp = fetch_live_ltp(client, stockname)

            if model_name == '0920_SCALP':
                # ── MODEL B: REALISTIC ADAPTIVE LIMIT PRICING (09:20 SCALP ONLY) ──
                if live_ltp and live_ltp > 0:
                    open_0920 = o.get('open_0920')
                    if not open_0920 or open_0920 <= 0:
                        open_0920 = o.get('limit_price_original') or db_price

                    # Movement % from 09:20 Open to 09:24 Close (live_ltp)
                    pct_move = ((live_ltp - open_0920) / open_0920) * 100.0
                    tick_val = get_tick_size(live_ltp)

                    # Model B Regimes:
                    if pct_move <= -0.25:
                        regime = 'CRASHING'
                        price = live_ltp - (2 * tick_val)   # -₹0.10 buffer
                    elif pct_move <= -0.05:
                        regime = 'GOING_DOWN'
                        price = live_ltp - (1 * tick_val)   # -₹0.05 buffer
                    elif pct_move < 0.05:
                        regime = 'NEUTRAL'
                        price = live_ltp                    # Base price (no buffer)
                    elif pct_move < 0.25:
                        regime = 'GOING_UP'
                        price = live_ltp                    # Base price (Model B: no buffer)
                    else:
                        regime = 'CLIMBING'
                        price = live_ltp                    # Base price (Model B: no buffer)

                    log_print(f"  ⚡ [0920_SCALP MODEL B] Live LTP (09:24 Close): ₹{live_ltp:.2f} | Open 09:20: ₹{open_0920:.2f} | Move: {pct_move:+.2f}% | Regime: {regime} → Limit Price: ₹{price:.2f}")
                else:
                    price = db_price
                    log_print(f"  ⚠️ Live LTP fetch failed for {stockname} — falling back to DB limit price: ₹{db_price:.2f}")
            else:
                # ── ORIGINAL UNTOUCHED LOGIC FOR 0942_HYBRID & OTHER MODELS ──
                if live_ltp and live_ltp > 0:
                    tick_val = get_tick_size(live_ltp)
                    price = live_ltp - (2 * tick_val)
                    log_print(f"  ⚡ [{model_name} ENTRY] Live LTP: ₹{live_ltp:.2f} | Applying 2 Ticks Entry Buffer (-₹{2*tick_val:.2f}) → Limit Price: ₹{price:.2f} (DB price: ₹{db_price:.2f})")
                else:
                    price = db_price
                    log_print(f"  ⚠️ Live LTP fetch failed — falling back to DB limit price: ₹{db_price:.2f}")

            limit_price_fmt = str(round_to_tick(price))
            price_to_send = limit_price_fmt

            # Scripcode for nse_cm — Kotak accepts plain symbol for cash market
            scripcode = find_eq_scripcode(stockname)
            if not scripcode:
                log_print(f"  ⚠️  No scripcode found for {stockname}, using symbol directly")
                scripcode = stockname

            # Skip guards
            if stockname in open_short_stocks:
                log_print(f"\n  ── {stockname} | Qty={quantity} | Price={limit_price_fmt} | OrderType={order_type_val} | Scripcode={scripcode}")
                log_print(f"  ⏭️  Already in short position → skipping {stockname}")
                _update_isvalid(db_id, '4')
                continue

            if stockname in completed_sells:
                log_print(f"\n  ── {stockname} | Qty={quantity} | Price={limit_price_fmt} | OrderType={order_type_val} | Scripcode={scripcode}")
                log_print(f"  ⏭️  Already filled SELL today → skipping {stockname}")
                _update_isvalid(db_id, '2')
                continue

            # Kotak Neo Live Margin Check & Safe Cap (0920_SCALP: ₹1.0L actual margin | 0942_HYBRID: ₹1.5L/₹2.0L actual margin)
            quantity = adjust_qty_for_kotak_margin(
                client=client,
                stockname=stockname,
                price=price,
                db_qty=quantity,
                db_price=db_price,
                model_name=model_name,
                db_id=db_id,
                today=today
            )
            o['quantity'] = quantity

            log_print(f"\n  ── {stockname} | Qty={quantity} | Price={limit_price_fmt} | OrderType={order_type_val} | Scripcode={scripcode}")

            # Place with 3 retries
            placed = False
            last_resp = None
            for attempt in range(1, 4):
                if attempt > 1:
                    sys_time.sleep(1)
                try:
                    if get_trading_setting('place_shortsell_order', True):
                        with suppress_stdout():
                            resp = client.place_order(
                                exchange_segment='nse_cm',
                                product='MIS',
                                price=price_to_send,
                                order_type=order_type_val,
                                quantity=str(quantity),
                                validity='DAY',
                                trading_symbol=scripcode,
                                transaction_type='S',
                                amo='NO',
                                disclosed_quantity='0',
                                trigger_price='0',
                            )
                    else:
                        resp = {'stat': 'Ok', 'stCode': 200, 'message': 'MOCK SUCCESS (shortsell OFF)'}
                    last_resp = resp
                    log_print(f"    Attempt {attempt}: {resp}")

                    if resp and (resp.get('stat') == 'Ok' or resp.get('stCode') == 200):
                        broker_order_id = resp.get('nOrdNo') or resp.get('message', '')
                        _update_isvalid(db_id, '1.5', broker_order_id=broker_order_id)
                        placed = True
                        break
                except Exception as e:
                    log_print(f"    Attempt {attempt} exception: {e}")
                    last_resp = {'stat': 'Not_Ok', 'errMsg': str(e)}

            if placed:
                log_print(f"  ✅ {stockname} order placed successfully")
                success_list.append(stockname)
            else:
                log_print(f"  ❌ {stockname} order FAILED after 3 attempts")
                failed_list.append(stockname)
                _update_isvalid(db_id, '3')
                err = last_resp.get('errMsg', 'Unknown') if isinstance(last_resp, dict) else str(last_resp)
                send_telegram_alert(
                    f"⚠️ <b>SHORT SELL ORDER FAILED</b>\n"
                    f"• <b>Model:</b> {model_name}\n"
                    f"• <b>Stock:</b> {stockname}\n"
                    f"• <b>Price:</b> ₹{price:.2f} | Qty: {quantity}\n"
                    f"• <b>Error:</b> {err}"
                )

        # ── Summary Telegram ─────────────────────────────────────────────────
        if success_list:
            day_name = pd.Timestamp(today).strftime('%A')
            msg = (
                f"✅ <b>MIS SHORT SELL ORDERS PLACED — {model_name}</b>\n"
                f"📅 {today} ({day_name})\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            )
            for o in orders:
                if o['stockname'] in success_list:
                    msg += (f"<b>#{o['order_rank']}. {o['stockname']}</b>\n"
                            f"  • Qty: {o['quantity']} | Limit: ₹{o['limit_price']:.2f} | SL: ₹{o['stop_loss_price']:.2f}\n"
                            f"  • Status: ✅ Order Sent\n"
                            f"------------------------------------\n")
            if failed_list:
                msg += f"⚠️ Failed: {', '.join(failed_list)}\n"
            msg += f"⚡ <i>Kotak Neo MIS | Product: MIS | Seg: nse_cm</i>"
            send_telegram_alert(msg)

        log_print(f"\n  Summary [{userid}]: ✅ Placed={success_list} | ❌ Failed={failed_list}")

        # ── 0920_SCALP 100% Single-Leg Trailing Strategy: Orders rest until 09:27:00 IST cutoff ──
        if model_name == '0920_SCALP' and success_list:
            log_print(f"\n⏳ [0920_SCALP] Initial SELL limit orders placed on book (100% Single-Leg Trailing Strategy).")
            log_print(f"   Resting until 09:27:00 IST cutoff. At 09:27:00 AM, confirm_0925_fills.py will cancel unfilled SELLs & arm 5s Trailing Protection (-₹5,000 SL | +₹2,000->+₹1,000 Floor | +₹4,000+->Peak-₹750 Trail).")


def _place_0920_leg1_resting_tp(client, orders, success_list, today, tp_target_rs=2000.0):
    """
    50/50 Split Strategy: Leg 1 Resting Limit Take-Profit Placement for 0920_SCALP.
    Places passive Limit BUY order on the book for 50% quantity at (Sell Fill - Target Drop).
    Target Drop = ₹2,000 / total_qty.
    """
    log_print(f"\n🎯 [0920_SCALP] 50/50 Execution: Checking for filled SELL orders to place Leg 1 Resting Limit TP (Target: ₹{tp_target_rs:,.0f})...")
    sys_time.sleep(5)  # Wait 5s for Kotak exchange fill confirmation

    open_buy_orders = get_open_buy_orders(client) or {}
    active_shorts = get_active_mis_short_positions(client) or {}

    order_map = {o['stockname']: o for o in orders if o.get('stockname') in success_list}

    # Fetch order book to inspect fill price
    kotak_order_report = []
    try:
        with suppress_stdout():
            ob = client.order_report()
            kotak_order_report = ob.get('data', []) if isinstance(ob, dict) else ob
    except Exception as e:
        log_print(f"  ⚠️ Could not fetch order report: {e}")

    for stockname, o in order_map.items():
        total_qty = int(o.get('quantity', 0))
        if total_qty <= 0:
            continue
        leg1_qty = total_qty // 2
        if leg1_qty <= 0:
            leg1_qty = 1

        # Check if open BUY order already exists for this stock
        if stockname in open_buy_orders:
            log_print(f"  ⏭️ Open BUY order already resting for {stockname} → skipping duplicate Leg 1 placement.")
            continue

        # Determine filled sell price
        filled_sp = None
        # Check order report first
        if isinstance(kotak_order_report, list):
            for ko in kotak_order_report:
                sym = ko.get('trdSym', '') or ko.get('sym', '')
                clean = sym.replace('-EQ', '').replace('_EQ', '').strip().upper()
                if clean == stockname.upper() and ko.get('exSeg') == 'nse_cm' and ko.get('trnsTp') == 'S':
                    st = str(ko.get('ordSt', '')).lower()
                    avg_prc = ko.get('avgPrc') or ko.get('avgprc') or ko.get('flPrc') or 0
                    try:
                        avg_prc = float(avg_prc)
                    except:
                        avg_prc = 0.0
                    if st == 'complete' and avg_prc > 0:
                        filled_sp = avg_prc
                        break

        # Fallback to active short positions
        if not filled_sp and stockname in active_shorts:
            filled_sp = active_shorts[stockname].get('avg_sell_price')

        if not filled_sp or filled_sp <= 0:
            log_print(f"  ⏳ SELL order for {stockname} not confirmed filled yet. Failsafe confirm_0925_fills.py will place Leg 1 TP upon fill.")
            continue

        # Calculate Leg 1 Limit TP price
        tp_drop = tp_target_rs / float(total_qty)
        tp_price = round_to_tick(filled_sp - tp_drop)
        if tp_price <= 0:
            log_print(f"  ⚠️ Calculated TP price <= 0 ({tp_price}) for {stockname}. Skipping.")
            continue

        tp_price_fmt = str(tp_price)
        scripcode = find_eq_scripcode(stockname) or stockname
        log_print(f"  → Placing Leg 1 Resting Limit TP for {stockname}: {leg1_qty}/{total_qty} qty @ ₹{tp_price_fmt} (Sell Fill: ₹{filled_sp:.2f}, Drop: -₹{tp_drop:.2f})")

        if get_trading_setting('place_squareoff_order', True):
            try:
                with suppress_stdout():
                    resp = client.place_order(
                        exchange_segment='nse_cm',
                        product='MIS',
                        price=tp_price_fmt,
                        order_type='L',
                        quantity=str(leg1_qty),
                        validity='DAY',
                        trading_symbol=scripcode,
                        transaction_type='B',
                        amo='NO',
                        disclosed_quantity='0',
                        trigger_price='0'
                    )
                log_print(f"    Kotak Response: {resp}")
                if resp and (resp.get('stat') == 'Ok' or resp.get('stCode') == 200):
                    tp_oid = resp.get('nOrdNo') or resp.get('orderId', '')
                    log_print(f"    ✅ Leg 1 Resting Limit TP placed successfully (Kotak OID: {tp_oid})")
                    send_telegram_alert(
                        f"🎯 <b>[09:20 SCALP - 50% LEG 1 RESTING LIMIT TP PLACED]</b>\n"
                        f"📅 {today} | ⏱️ {get_ist_now().strftime('%H:%M:%S IST')}\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"<b>• Stock:</b> <b>{stockname}</b>\n"
                        f"<b>• Action:</b> <b>Passive Limit BUY TP</b>\n"
                        f"<b>• Sell Fill Price:</b> ₹{filled_sp:.2f}\n"
                        f"<b>• Target Exit Limit:</b> <b>₹{tp_price_fmt}</b> (-₹{tp_drop:.2f})\n"
                        f"<b>• Quantity:</b> {leg1_qty} / {total_qty} (50%)\n"
                        f"<b>• Target Profit:</b> <b>₹{tp_target_rs:,.0f}</b>\n"
                        f"<b>• Kotak Order ID:</b> <code>{tp_oid}</code>\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"⚡ <i>Rests on NSE book. Fills passively at zero slippage. Leg 2 (50%) managed from 09:36.</i>"
                    )
                else:
                    log_print(f"    ⚠️ Leg 1 TP placement returned non-OK status: {resp}")
            except Exception as e:
                log_print(f"    ⚠️ Leg 1 TP placement failed: {e}")
        else:
            log_print(f"    (Mock Success - ordering disabled)")


def _update_isvalid(db_id, isvalid, broker_order_id=None):
    try:
        conn = get_db_connection()
        with conn.cursor() as c:
            if broker_order_id:
                c.execute("UPDATE shortsell_orders SET isvalid=%s, broker_order_id=%s, modtime=NOW() WHERE id=%s",
                          (isvalid, broker_order_id, db_id))
            else:
                c.execute("UPDATE shortsell_orders SET isvalid=%s, modtime=NOW() WHERE id=%s",
                          (isvalid, db_id))
        conn.commit()
        conn.close()
        log_print(f"    DB updated: id={db_id} → isvalid='{isvalid}'")
    except Exception as e:
        log_print(f"    ⚠️  DB update failed: {e}")

def _run_reentry_orders(model_name, today, target_stock=None, target_qty=None, target_price=None):
    """
    Leg 2 Re-entry Order Placer for 09:40 Short-Sell Model.
    Bypasses completed_sells check while ensuring the symbol is not currently in an open short.
    Updates sl_alert_state.json with exact re-entry price and Leg 2 parameters.
    """
    log_print("=" * 75)
    log_print(f"🔄 MIS SHORT SELL RE-ENTRY ORDER PLACER — {model_name} | Stock: {target_stock or 'ALL'} | {today}")
    log_print("=" * 75)

    user_ids = []
    try:
        with open(USER_TABLE) as f:
            next(f)
            for line in f:
                u = line.strip()
                if u:
                    user_ids.append(u)
    except Exception as e:
        log_print(f"❌ Could not read User_table.csv: {e}")
        sys.exit(1)

    state_file = '/home/ubuntu/KotakCodes1/logs/sl_alert_state.json'
    stocks_to_reenter = []

    if target_stock:
        if not target_qty:
            try:
                conn = get_db_connection()
                with conn.cursor() as c:
                    c.execute("""
                        SELECT quantity, limit_price 
                        FROM shortsell_orders 
                        WHERE trade_date=%s AND stockname=%s AND model_name LIKE %s 
                        ORDER BY id DESC LIMIT 1
                    """, (today, target_stock, f"%{model_name}%"))
                    row = c.fetchone()
                    if row:
                        target_qty = row['quantity']
                conn.close()
            except Exception as e:
                log_print(f"⚠️ Could not look up quantity from DB: {e}")
        stocks_to_reenter.append({
            'stockname': target_stock,
            'quantity': target_qty,
            'limit_price': target_price
        })
    else:
        if os.path.exists(state_file):
            try:
                with open(state_file, 'r') as sf:
                    st_data = json.load(sf)
                for stk, st_val in st_data.items():
                    if st_val.get('reentry_status') == 'AWAITING_REENTRY':
                        stocks_to_reenter.append({
                            'stockname': stk,
                            'quantity': st_val.get('leg1_qty'),
                            'limit_price': st_val.get('reentry_trigger_price')
                        })
            except Exception as e:
                log_print(f"⚠️ Error reading state file: {e}")

    if not stocks_to_reenter:
        log_print("ℹ️ No eligible re-entry orders found. Exiting.")
        return

    for userid in user_ids:
        log_print(f"\n{'='*25} USER: {userid} {'='*25}")
        try:
            auth_df = pd.read_csv(AUTH_CSV)
            auth = auth_df[auth_df['userid'] == userid]
            if auth.empty:
                log_print(f"⚠️ User {userid} not found in auth CSV. Skipping.")
                continue
            row = auth.iloc[0]
            consumer_key = row['consumer_key']
            MPIN = str(int(row['MPIN']))
            mobile_number = str(row.get('mobile_number', '')).strip()
            totp_secret = str(row.get('totp_secret', '')).strip()
            user_from_api = row['user_from_API']
        except Exception as e:
            log_print(f"❌ Auth load failed for {userid}: {e}")
            continue

        login_ok = False
        client = None
        with suppress_stdout():
            try:
                client = NeoAPI(consumer_key=consumer_key, environment='prod', neo_fin_key='neotradeapi')
                totp_code = pyotp.TOTP(totp_secret).now()
                formatted_mobile = mobile_number if mobile_number.startswith('+') else f'+91{mobile_number}'
                lr = client.totp_login(mobile_number=formatted_mobile, ucc=userid, totp=totp_code)
                if lr and 'error' in lr:
                    raise Exception(f"TOTP login error: {lr['error']}")
                vr = client.totp_validate(mpin=MPIN)
                if vr and 'error' in vr:
                    raise Exception(f"MPIN error: {vr['error']}")
                login_ok = True
            except Exception as e:
                log_print(f"❌ Login failed for {userid}: {e}")

        if not login_ok:
            log_print(f"❌ Skipping {userid} — login failed.")
            continue
        log_print(f"✔ Kotak session established for {userid} ({user_from_api})")

        # Fetch open positions to avoid double-entry
        open_short_stocks = set()
        try:
            with suppress_stdout():
                positions_resp = client.positions()
            if positions_resp and isinstance(positions_resp.get('data'), list):
                for pos in positions_resp['data']:
                    sym = pos.get('trdSym', '') or pos.get('sym', '')
                    net_qty = int(pos.get('netQty', 0) or 0)
                    seg = pos.get('exSeg', '')
                    if seg == 'nse_cm' and net_qty < 0:
                        clean = sym.replace('-EQ', '').replace('_EQ', '').strip().upper()
                        open_short_stocks.add(clean)
        except Exception as e:
            log_print(f"  ⚠️ Could not fetch positions: {e}")

        success_list = []
        failed_list = []

        for item in stocks_to_reenter:
            stockname = item['stockname']
            quantity = item.get('quantity')
            limit_price = item.get('limit_price')

            # Skip guard: If already short, do not double enter!
            if stockname in open_short_stocks:
                log_print(f"  ⏭️ Already in open short position → skipping re-entry for {stockname}")
                continue

            live_ltp = fetch_live_ltp(client, stockname)
            if live_ltp and live_ltp > 0:
                price = round_to_tick(live_ltp)
                log_print(f"  ⚡ [RE-ENTRY] Live LTP: ₹{price:.2f} (Placing at exact LTP, no buffer)")
            elif limit_price and limit_price > 0:
                price = round_to_tick(limit_price)
                log_print(f"  ⚠️ Live LTP fetch failed — using target price: ₹{price:.2f}")
            else:
                log_print(f"  ❌ Cannot determine entry price for {stockname}. Skipping.")
                failed_list.append(stockname)
                continue

            if not quantity or quantity <= 0:
                quantity = int(625000 // price) if '094' in str(model_filter) or 'HYBRID' in str(model_filter) else int(500000 // price) # ₹6.25L (₹1.25L margin) for 0942_HYBRID, ₹5L for 0920_SCALP

            limit_price_fmt = str(round_to_tick(price))
            scripcode = find_eq_scripcode(stockname) or stockname

            log_print(f"\n  ── RE-ENTRY: {stockname} | Qty={quantity} | Price={limit_price_fmt} | Scripcode={scripcode}")

            placed = False
            last_resp = None
            broker_order_id = ''
            for attempt in range(1, 4):
                if attempt > 1:
                    sys_time.sleep(1)
                try:
                    if get_trading_setting('place_shortsell_order', True):
                        with suppress_stdout():
                            resp = client.place_order(
                                exchange_segment='nse_cm',
                                product='MIS',
                                price=limit_price_fmt,
                                order_type='L',
                                quantity=str(quantity),
                                validity='DAY',
                                trading_symbol=scripcode,
                                transaction_type='S',
                                amo='NO',
                                disclosed_quantity='0',
                                trigger_price='0',
                            )
                    else:
                        resp = {'stat': 'Ok', 'stCode': 200, 'message': 'MOCK SUCCESS (shortsell OFF)'}
                    last_resp = resp
                    log_print(f"    Attempt {attempt}: {resp}")
                    if resp and (resp.get('stat') == 'Ok' or resp.get('stCode') == 200):
                        broker_order_id = resp.get('nOrdNo') or resp.get('message', '')
                        placed = True
                        break
                except Exception as e:
                    log_print(f"    Attempt {attempt} exception: {e}")
                    last_resp = {'stat': 'Not_Ok', 'errMsg': str(e)}

            if placed:
                log_print(f"  ✅ {stockname} RE-ENTRY order placed successfully (ID: {broker_order_id})")
                success_list.append(stockname)

                # Persist re-entry execution state
                try:
                    state_dict = {}
                    if os.path.exists(state_file):
                        with open(state_file, 'r') as sf:
                            state_dict = json.load(sf)
                    stk_st = state_dict.get(stockname, {})
                    orig_ep = stk_st.get('leg1_entry_price', price)
                    leg2_sl_price = round_to_tick(price * 1.015)
                    leg2_tp2_price = round_to_tick(price * 0.985)
                    stk_st['reentry_status'] = 'REENTRY_ACTIVE'
                    stk_st['reentry_price'] = round_to_tick(price)
                    stk_st['reentry_qty'] = quantity
                    stk_st['reentry_time'] = sys_time.time()
                    stk_st['reentry_order_id'] = broker_order_id
                    stk_st['reentry_sl'] = leg2_sl_price  # Tight 1.50% SL above Leg 2 re-entry
                    stk_st['reentry_tp2'] = leg2_tp2_price # 1.50% profit trailing activation
                    state_dict[stockname] = stk_st
                    with open(state_file, 'w') as sf:
                        json.dump(state_dict, sf, indent=2)
                    log_print(f"  💾 State persisted for {stockname}: ReEntry Price=₹{price:.2f}, SL(1.50%)=₹{leg2_sl_price:.2f}, TrailAct(1.50%)=₹{leg2_tp2_price:.2f}")
                except Exception as e:
                    log_print(f"  ⚠️ Failed to update state file for {stockname}: {e}")

                # Update MySQL notes
                try:
                    conn = get_db_connection()
                    with conn.cursor() as c:
                        c.execute("""
                            UPDATE shortsell_orders
                            SET notes = CONCAT(IFNULL(notes, ''), ' | REENTRY_PLACED_₹', %s), modtime = NOW()
                            WHERE trade_date = %s AND stockname = %s AND model_name LIKE %s
                        """, (f"{price:.2f}", today, stockname, f"%{model_name}%"))
                    conn.commit()
                    conn.close()
                except Exception as e:
                    log_print(f"  ⚠️ DB update notes failed for {stockname}: {e}")

                # Telegram alert
                leg2_sl_price = round_to_tick(price * 1.015)
                tp2_price = round_to_tick(price * 0.985)
                send_telegram_alert(
                    f"🚀 <b>[{model_name} - LEG 2 RE-ENTRY EXECUTED]</b>\n"
                    f"📅 {today} | ⏱️ {get_ist_now().strftime('%H:%M:%S IST')}\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"<b>• Stock:</b> <b>{stockname}</b>\n"
                    f"<b>• Action:</b> <b>SELL Limit (MIS)</b>\n"
                    f"<b>• Re-Entry Price:</b> <b>₹{price:.2f}</b> (Leg 1 Entry: ₹{orig_ep:.2f})\n"
                    f"<b>• Quantity:</b> {quantity}\n"
                    f"<b>• Kotak Order ID:</b> <code>{broker_order_id}</code>\n"
                    f"<b>• Leg 2 Tight SL (+1.50%):</b> <b>₹{leg2_sl_price:.2f}</b>\n"
                    f"<b>• Leg 2 Trailing TP Activation (-1.50%):</b> <b>₹{tp2_price:.2f}</b> (Trails 0.75% behind peak)\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"⚡ <i>Stage 4 Re-Entry Protection Active</i>"
                )
            else:
                log_print(f"  ❌ {stockname} RE-ENTRY order FAILED after 3 attempts")
                failed_list.append(stockname)
                err = last_resp.get('errMsg', 'Unknown') if isinstance(last_resp, dict) else str(last_resp)
                send_telegram_alert(
                    f"⚠️ <b>LEG 2 RE-ENTRY ORDER FAILED</b>\n"
                    f"• <b>Model:</b> {model_name}\n"
                    f"• <b>Stock:</b> {stockname}\n"
                    f"• <b>Price:</b> ₹{price:.2f} | Qty: {quantity}\n"
                    f"• <b>Error:</b> {err}"
                )

        log_print(f"\n  Re-entry Summary [{userid}]: ✅ Placed={success_list} | ❌ Failed={failed_list}")


def get_active_mis_short_positions(client):
    """Fetches MIS short positions from Kotak."""
    short_positions = {}
    try:
        with suppress_stdout():
            pos_resp = client.positions()
        raw_pos = pos_resp.get('data', []) if isinstance(pos_resp, dict) else pos_resp
        
        for p in raw_pos:
            if p.get('prod', '') != 'MIS': continue
            sym = p.get('sym', '') or p.get('trdSym', '')
            clean_sym = sym.replace('-EQ', '').replace('_EQ', '').strip().upper()
            if clean_sym == "GMRP&UI":
                clean_sym = "GMRINFRA"
            
            fl_sell, cf_sell = int(p.get('flSellQty', 0) or 0), int(p.get('cfSellQty', 0) or 0)
            fl_buy, cf_buy   = int(p.get('flBuyQty', 0) or 0), int(p.get('cfBuyQty', 0) or 0)
            
            total_sell_qty = fl_sell + cf_sell
            net_short = total_sell_qty - (fl_buy + cf_buy)
            
            if net_short > 0:
                sell_amt = float(p.get('sellAmt', 0.0) or 0.0)
                avg_sell_price = sell_amt / total_sell_qty if total_sell_qty > 0 else 0.0
                short_positions[clean_sym] = {'net_short_qty': net_short, 'avg_sell_price': avg_sell_price}
    except Exception as e:
        log_print(f"⚠️ Positions API fetch failed: {e}")
        return None
    return short_positions

class OpenOrderItem(dict):
    """
    Subclass of dict representing an open order.
    Converting to str() returns the string order_id for backwards compatibility.
    """
    def __str__(self):
        return str(self.get('order_id', ''))
    def __int__(self):
        return int(self.get('order_id', 0))

def get_open_buy_orders(client):
    """Fetches open/pending BUY orders from Kotak."""
    open_orders = {}
    try:
        with suppress_stdout():
            order_book = client.order_report()
        raw_orders = order_book.get('data', []) if isinstance(order_book, dict) else order_book
        for o in raw_orders:
            if o.get('exSeg') == 'nse_cm' and o.get('trnsTp') in ('B', 'BUY'):
                status = str(o.get('ordSt', '')).lower()
                if status in ('open', 'pending', 'trigger pending', 'put order req received'):
                    sym = o.get('trdSym', '') or o.get('sym', '')
                    clean_sym = sym.replace('-EQ', '').replace('_EQ', '').strip().upper()
                    oid = str(o.get('nOrdNo') or o.get('orderId') or '')
                    prc = float(o.get('prc') or o.get('price') or 0.0)
                    qty = int(o.get('qty') or o.get('quantity') or 0)
                    open_orders[clean_sym] = OpenOrderItem({'order_id': oid, 'price': prc, 'qty': qty})
    except Exception as e:
        log_print(f"⚠️ Order book fetch failed: {e}")
        return None
    return open_orders

def _run_position_based_squareoff(model_name, today, exit_window):
    """
    Unified, State-Based Square-Off Logic.
    Relies on Kotak Positions API as the single source of truth.
    Handles:
      1. 0920_SCALP 30s Cadence Profit Square-Off (09:36:00 to 09:39:30, every 30s).
      2. Looping chaser (0940, 1445).
      3. Single-pass squareoff (1400, 1430).
    """
    is_chaser = (exit_window in ('0940', '1445'))
    is_0920_trailing = (model_name == '0920_SCALP' and exit_window == '0936')
    mode_name = "SQUAREOFF_CHASE" if is_chaser else ("SQUAREOFF_30S_CADENCE" if is_0920_trailing else "SQUAREOFF")
    log_print(f"\n🔲 POSITION-FIRST {mode_name} — {model_name} | Window={exit_window} | {today}")

    # Determine loop duration / cadence targets
    end_time = get_ist_now()
    trailing_targets = []
    if is_chaser:
        try:
            ew_hr, ew_min = int(exit_window[:2]), int(exit_window[2:]) + 2
            if ew_min >= 60: ew_hr += 1; ew_min -= 60
            end_time = get_ist_now().replace(hour=ew_hr, minute=ew_min, second=0, microsecond=0)
        except:
            end_time = get_ist_now() + timedelta(minutes=2)
        log_print(f"  Chaser will run until {end_time.strftime('%H:%M:%S')}")
    elif is_0920_trailing:
        now_dt = get_ist_now()
        trailing_targets = [
            now_dt.replace(hour=9, minute=36, second=0, microsecond=0),
            now_dt.replace(hour=9, minute=36, second=30, microsecond=0),
            now_dt.replace(hour=9, minute=37, second=0, microsecond=0),
            now_dt.replace(hour=9, minute=37, second=30, microsecond=0),
            now_dt.replace(hour=9, minute=38, second=0, microsecond=0),
            now_dt.replace(hour=9, minute=38, second=30, microsecond=0),
            now_dt.replace(hour=9, minute=39, second=0, microsecond=0),
            now_dt.replace(hour=9, minute=39, second=30, microsecond=0),
        ]
        if now_dt > trailing_targets[-1] + timedelta(minutes=1):
            log_print("  ⚠️ Executing outside 09:36–09:39:30 window (Manual/Off-market Test Mode) → 1 immediate pass")
            trailing_targets = [now_dt]
        else:
            log_print(f"  09:20 Scalp 30s cadence active: 8 checks scheduled from 09:36:00 to 09:39:30")

    # Read users
    user_ids = []
    try:
        with open(USER_TABLE) as f:
            next(f)
            for line in f:
                u = line.strip()
                if u: user_ids.append(u)
    except Exception as e:
        log_print(f"❌ Could not read User_table: {e}")
        return

    if not user_ids: return
    userid = user_ids[0] # Assuming single user for these models

    # Auth & Login
    auth_df = pd.read_csv(AUTH_CSV)
    if userid not in auth_df['userid'].values:
        log_print(f"❌ User {userid} not found in auth CSV.")
        return
    auth = auth_df[auth_df['userid'] == userid].iloc[0]

    client = None
    with suppress_stdout():
        try:
            client = NeoAPI(consumer_key=auth['consumer_key'], environment='prod', neo_fin_key='neotradeapi')
            totp_code = pyotp.TOTP(str(auth.get('totp_secret', '')).strip()).now()
            mobile = str(auth.get('mobile_number', '')).strip()
            formatted_mobile = mobile if mobile.startswith('+') else f'+91{mobile}'
            client.totp_login(mobile_number=formatted_mobile, ucc=userid, totp=totp_code)
            client.totp_validate(mpin=str(int(auth['MPIN'])))
        except Exception as e:
            log_print(f"❌ Login failed for {userid}: {e}")
            return
    log_print(f"✔ Kotak session established for {userid}")

    # ── CORE LOOP ─────────────────────────────────────────────────────────
    loop_count = 0
    while True:
        loop_count += 1
        target_time = None

        if is_0920_trailing:
            if loop_count > len(trailing_targets):
                log_print("⏳ All 30s cadence checks (09:36:00–09:39:30) completed. Exiting for 09:40 limit chaser.")
                break
            target_time = trailing_targets[loop_count - 1]
            now_cur = get_ist_now()
            wait_sec = (target_time - now_cur).total_seconds()
            if wait_sec > 0:
                log_print(f"\n⏳ Waiting {wait_sec:.1f}s until exact cadence target {target_time.strftime('%H:%M:%S')}...")
                sys_time.sleep(wait_sec)
            elif (now_cur - target_time).total_seconds() > 20:
                log_print(f"\n⏭️ Target {target_time.strftime('%H:%M:%S')} expired ({int((now_cur - target_time).total_seconds())}s ago) — skipping.")
                continue
            log_print(f"\n⏰ === 09:20 Scalp 30s Check [{target_time.strftime('%H:%M:%S')}] at {get_ist_now().strftime('%H:%M:%S')} (Pass {loop_count}/{len(trailing_targets)}) ===")
        elif is_chaser:
            log_print(f"\n⏰ --- Chaser Loop {loop_count} at {get_ist_now().strftime('%H:%M:%S')} ---")

        # 1. Get Model Ownership from DB (What are we allowed to touch?)
        conn = get_db_connection()
        db_model_stocks = {}
        with conn.cursor() as c:
            c.execute("""
                SELECT id, stockname, sell_price 
                FROM scalp_trade_log 
                WHERE trade_date = %s AND model_name = %s
            """, (today, model_name))
            for row in c.fetchall():
                db_model_stocks[row['stockname']] = row
        conn.close()

        if not db_model_stocks:
            # Fallback: check shortsell_orders directly
            conn = get_db_connection()
            with conn.cursor() as c:
                c.execute("""
                    SELECT id, stockname, IFNULL(filled_price, limit_price) as sell_price 
                    FROM shortsell_orders 
                    WHERE trade_date = %s AND model_name = %s AND isvalid IN ('1.5', '2', 'TRUE')
                """, (today, model_name))
                for row in c.fetchall():
                    db_model_stocks[row['stockname']] = row
            conn.close()
            if db_model_stocks:
                log_print(f"  ℹ️ Found {len(db_model_stocks)} trades for {model_name} in shortsell_orders (fallback).")
            else:
                log_print(f"ℹ️  DB shows no trades for {model_name} today. Nothing to manage.")
                break

        # 2. Get Live Kotak State
        active_shorts = get_active_mis_short_positions(client)
        if active_shorts is None:
            if not is_chaser and not is_0920_trailing: break
            sys_time.sleep(2); continue
            
        open_buy_orders = get_open_buy_orders(client)
        if open_buy_orders is None:
            if not is_chaser and not is_0920_trailing: break
            sys_time.sleep(2); continue

        # 3. Filter: Which active shorts belong to THIS model?
        candidates = []
        for stock, pos_data in active_shorts.items():
            if stock in db_model_stocks:
                candidates.append((stock, pos_data, db_model_stocks[stock]))

        if not candidates:
            log_print("🎉 All MIS positions for this model are completely FLAT in Kotak!")
            if is_chaser or is_0920_trailing:
                for stock, db_row in db_model_stocks.items():
                    if open_buy_orders and stock in open_buy_orders:
                        try:
                            with suppress_stdout():
                                client.cancel_order(order_id=str(open_buy_orders[stock]))
                        except Exception: pass
                    _mark_squareoff_db(db_row['id'], exit_window, None, None, f'EXIT_DONE_{exit_window}', notes='Confirmed flat via Positions API')
            break

        # 4. Process Candidates
        for stockname, pos_data, db_row in candidates:
            net_qty = pos_data['net_short_qty']
            avg_sell = pos_data['avg_sell_price']
            row_id = db_row['id']

            log_print(f"  ── {stockname} | Kotak Net Short: {net_qty} | Avg Sell: ₹{avg_sell:.2f}")

            live_ltp = fetch_live_ltp(client, stockname)
            if not live_ltp or live_ltp <= 0:
                log_print(f"  ⚠️ Could not fetch LTP. Skipping.")
                continue

            # Profit Check (0936 or 1400 or 1430)
            if not is_chaser:
                unrealized_pnl = (avg_sell - live_ltp) * net_qty
                profit_pct = ((avg_sell - live_ltp) / avg_sell) * 100.0
                cadence_tag = f" [{target_time.strftime('%H:%M:%S')}]" if target_time else ""
                log_print(f"   {cadence_tag} LTP=₹{live_ltp} | PnL=₹{unrealized_pnl:.2f} ({profit_pct:.2f}%)")
                if exit_window == '1400':
                    if unrealized_pnl <= 0.0:
                        log_print(f"    ⏳ HOLD: Position not in profit at 14:00 (holding 100% to 14:45).")
                        continue
                    cover_qty = max(1, int(net_qty / 2))
                    log_print(f"    🎯 14:00 50/50 PROFIT BOOKING: Closing 50% ({cover_qty}/{net_qty} qty) in profit (₹{unrealized_pnl:.2f})")
                elif exit_window == '1430':
                    if '0942' not in model_name:
                        log_print(f"    ⛔ 14:30 exit window is strictly reserved for 0940 (0942_HYBRID). Skipping.")
                        continue
                    cover_qty = net_qty
                    log_print(f"    🎯 14:30 PRE-CLOSE DISCOUNT EXIT: Covering {cover_qty} qty at LTP - 0.20% discount (LTP: ₹{live_ltp:.2f})")
                else:
                    # 09:20 Scalp (0936) Profit Check
                    if unrealized_pnl < PROFIT_THRESHOLD_RS:
                        if stockname in open_buy_orders:
                            order_info = open_buy_orders[stockname]
                            order_price = order_info.get('price', 0.0) if isinstance(order_info, dict) else 0.0
                            old_order_id = str(order_info)

                            # Preserve any active SL / Floor / Trailing cover order placed by sl_near_alert_monitor.py
                            # (only cancel if it was a stale cadence cover order placed when PnL >= ₹500, i.e., order_price <= avg_sell - 500/net_qty)
                            cadence_cutoff_price = avg_sell - (PROFIT_THRESHOLD_RS / max(net_qty, 1))
                            if order_price > cadence_cutoff_price:
                                log_print(f"    🛡️ HOLD: PnL ₹{unrealized_pnl:.2f} < ₹{PROFIT_THRESHOLD_RS:.2f}. Preserving active SL/Trailing cover order in book @ ₹{order_price:.2f} (ID: {old_order_id}).")
                            else:
                                log_print(f"    ❌ Cancelling stale cadence cover order (ID: {old_order_id} @ ₹{order_price:.2f}) as PnL ₹{unrealized_pnl:.2f} < ₹{PROFIT_THRESHOLD_RS:.2f}")
                                try:
                                    with suppress_stdout():
                                        client.cancel_order(order_id=old_order_id)
                                    sys_time.sleep(1)
                                except Exception as e:
                                    log_print(f"      ⚠️ Cancel stale order failed: {e}")
                        else:
                            log_print(f"    ⏳ HOLD: PnL ₹{unrealized_pnl:.2f} < ₹{PROFIT_THRESHOLD_RS:.2f} threshold.")
                        continue
                    cover_qty = net_qty
                    log_print(f"    🎯 09:36 PROFIT BOOKING: PnL ₹{unrealized_pnl:.2f} >= ₹{PROFIT_THRESHOLD_RS:.2f} threshold.")
            else:
                cover_qty = net_qty

            # Cancel existing open order if any before placing new limit order
            if stockname in open_buy_orders:
                old_order_id = str(open_buy_orders[stockname])
                log_print(f"    ❌ Cancelling existing open order (ID: {old_order_id}) before placing new limit order")
                try:
                    with suppress_stdout():
                        cancel_resp = client.cancel_order(order_id=old_order_id)
                    log_print(f"      Cancel sent. Waiting 1s for Kotak to process...")
                    sys_time.sleep(1) # Give Kotak a moment to clear it from the book
                    # Re-fetch fresh live LTP after cancelling
                    fresh_ltp = fetch_live_ltp(client, stockname)
                    if fresh_ltp and fresh_ltp > 0:
                        live_ltp = fresh_ltp
                except Exception as e:
                    log_print(f"      ⚠️ Cancel failed: {e}. Skipping placement to avoid duplicates.")
                    continue

            # Place New Limit Order
            scripcode = find_eq_scripcode(stockname)
            if exit_window == '1430':
                limit_price = round_to_tick(live_ltp * 0.998, stockname=stockname, client=client)
                limit_price_fmt = str(limit_price)
                log_print(f"    → Placing 14:30 DISCOUNT BUY cover for {cover_qty} qty at ₹{limit_price_fmt} (LTP ₹{live_ltp:.2f} - 0.20%)")
            else:
                stk_tick = get_tick_size(live_ltp, stockname=stockname, client=client)
                limit_price = round_to_tick(live_ltp + stk_tick, stockname=stockname, client=client)
                limit_price_fmt = str(limit_price)
                cadence_label = f" [{target_time.strftime('%H:%M:%S')}]" if target_time else ""
                log_print(f"    → Placing BUY cover{cadence_label} for {cover_qty} qty at ₹{limit_price_fmt} (LTP: ₹{live_ltp:.2f})")
            
            if get_trading_setting('place_squareoff_order', True):
                try:
                    with suppress_stdout():
                        resp = client.place_order(
                            exchange_segment='nse_cm', product='MIS', price=limit_price_fmt,
                            order_type='L', quantity=str(cover_qty), validity='DAY',
                            trading_symbol=scripcode, transaction_type='B', amo='NO',
                            disclosed_quantity='0', trigger_price='0'
                        )
                    log_print(f"      Response: {resp}")
                    if resp and (resp.get('stat') == 'Ok' or resp.get('stCode') == 200):
                        broker_buy_id = resp.get('nOrdNo', '')
                        cadence_note = f"30s target {target_time.strftime('%H:%M:%S')}" if target_time else ""
                        _mark_squareoff_db(row_id, exit_window, live_ltp, broker_buy_id, f'EXIT_PLACED_{exit_window}', notes=cadence_note)
                        
                        if exit_window == '1430':
                            send_telegram_alert(
                                f"🎯 <b>[{model_name} - 14:30 PRE-CLOSE DISCOUNT LIMIT EXIT PLACED]</b>\n"
                                f"📅 {today} | ⏱️ {get_ist_now().strftime('%H:%M:%S IST')}\n"
                                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                                f"<b>• Stock:</b> <b>{stockname}</b>\n"
                                f"<b>• Action:</b> <b>BUY Cover Limit</b>\n"
                                f"<b>• Live LTP:</b> ₹{live_ltp:.2f}\n"
                                f"<b>• Target Exit Price:</b> <b>₹{limit_price_fmt}</b> (-0.20% Discount)\n"
                                f"<b>• Quantity:</b> {cover_qty}\n"
                                f"<b>• Kotak Order ID:</b> <code>{broker_buy_id}</code>\n"
                                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                                f"⚡ <i>Rests in book until 14:45. Limit Chaser will auto-cancel and chase if unfilled.</i>"
                            )
                        elif is_0920_trailing:
                            target_str = target_time.strftime('%H:%M:%S') if target_time else get_ist_now().strftime('%H:%M:%S')
                            send_telegram_alert(
                                f"🎯 <b>[09:20 SCALP - ₹500+ PROFIT LIMIT COVER PLACED]</b>\n"
                                f"📅 {today} | ⏱️ {get_ist_now().strftime('%H:%M:%S IST')} (Cadence: {target_str})\n"
                                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                                f"<b>• Stock:</b> <b>{stockname}</b>\n"
                                f"<b>• Action:</b> <b>BUY Cover Limit</b>\n"
                                f"<b>• Live LTP:</b> ₹{live_ltp:.2f}\n"
                                f"<b>• Target Exit Limit:</b> <b>₹{limit_price_fmt}</b>\n"
                                f"<b>• Quantity:</b> {cover_qty}\n"
                                f"<b>• Unrealized PnL:</b> <b>₹{unrealized_pnl:+,.2f}</b> ({profit_pct:.2f}%)\n"
                                f"<b>• Kotak Order ID:</b> <code>{broker_buy_id}</code>\n"
                                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                                f"⚡ <i>Evaluated every 30s until 09:39:30. Limit chaser takes over at 09:40.</i>"
                            )
                except Exception as e:
                    log_print(f"      ⚠️ Order placement failed: {e}")
            else:
                log_print("      (Mock Success - ordering disabled)")

        # 5. Loop control
        if is_0920_trailing:
            continue

        if not is_chaser:
            break # Exit after one pass
            
        if get_ist_now() >= end_time:
            log_print("⏳ Chaser time window expired.")
            break
            
        log_print("  ⏳ Sleeping 20 seconds before next check...")
        sys_time.sleep(20)



def _mark_squareoff_db(row_id, exit_window, buy_ltp, broker_buy_id, status, notes=''):
    """Update scalp_trade_log after a squareoff attempt."""
    try:
        conn = get_db_connection()
        with conn.cursor() as c:
            c.execute("""
                UPDATE scalp_trade_log
                SET buy_ltp_used        = %s,
                    broker_buy_order_id = %s,
                    exit_trigger        = %s,
                    status              = IFNULL(%s, status),
                    notes               = CONCAT(IFNULL(notes,''), ' | ', %s),
                    modtime             = NOW()
                WHERE id = %s
            """, (buy_ltp, broker_buy_id, exit_window, status, notes, row_id))
        conn.commit()
        conn.close()
        log_print(f"    DB updated: scalp_trade_log id={row_id} → {status}")
    except Exception as e:
        log_print(f"    ⚠️  DB update failed: {e}")



if __name__ == '__main__':
    main()
