#!/usr/bin/env python3
"""
reconcile_0940_live_mimic_pnl.py
---------------------------------
Post-Trade / Evening Reconciler that EXACTLY mimics our live 09:42 Hybrid Engine execution:
  1. Entry at 09:42:00 AM IST.
  2. Leg 1:
     - 2.0% Take Profit (TP1) -> exits instantly.
     - 2.25% Stop Loss (SL) -> exits instantly.
     - If neither hits by 14:30:00 -> exits at 14:30:00 (with 0.20% discount limit / market fill).
  3. Rebound & Leg 2 (if Leg 1 took profit):
     - After Leg 1 TP, watches for +0.50% rebound bounce from TP price before 14:30:00.
     - If bounce >= +0.50%, re-enters Leg 2 at rebound trigger price.
     - Leg 2 TP: 1.75% profit target (rebound_price * 0.9825).
     - Leg 2 SL: Anchored at original Leg 1 Entry price (Zero Capital Risk).
     - If neither hits by 14:30:00 -> exits at 14:30:00.
  4. Calculates complete trade accounting (Leg 1 + Leg 2 Gross PnL, Statutory Zerodha Taxes, Net PnL).
  5. Updates `daily_0940_live_mimic_ledger.csv` and broadcasts the Reconciled PnL report to Telegram.
"""

import os
import sys
import argparse
import subprocess
import requests
from datetime import datetime
import pytz
import numpy as np
import pandas as pd
import pymysql

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SOURCE_LEDGER_CSV = os.path.join(SCRIPT_DIR, 'daily_0940_live_ledger.csv')
MIMIC_LEDGER_CSV = os.path.join(SCRIPT_DIR, 'daily_0940_live_mimic_ledger.csv')
AUDITED_MIMIC_CSV = os.path.join(SCRIPT_DIR, 'audited_0940_live_mimic_trades.csv')
SARANG_DIR = '/home/ubuntu/sarang_2026_shortsell_algos/02_Best_Longer_Window_0942_1445'
BOT_SCRIPT = '/home/ubuntu/KotakCodes1/status_Info_bot.js'

# Telegram routing
CRITICAL_BOT_TOKEN = "5350311365:AAFkTUBR4IGvgS5Z9mJngz-mgk7-HkhFEYE"
CRITICAL_CHAT_ID = "-627025839"

def get_taxes(qty, sell_price, buy_price):
    turnover = (qty * sell_price) + (qty * buy_price)
    stt = round(qty * sell_price * 0.00025)
    txn = turnover * 0.0000322
    sebi = turnover * 0.000001
    stamp = round(qty * buy_price * 0.00003)
    gst = (40.0 + txn + sebi) * 0.18
    return round(40.0 + stt + txn + sebi + stamp + gst, 2)

def get_db_connection():
    return pymysql.connect(
        host='localhost',
        user='root',
        password='root',
        database='markets',
        cursorclass=pymysql.cursors.DictCursor
    )

def send_telegram_alert(msg):
    # 1. Send via status_Info_bot.js to Status and Warnings (-1002365534285)
    if os.path.exists(BOT_SCRIPT):
        try:
            res = subprocess.run(['node', BOT_SCRIPT, msg], capture_output=True, text=True, timeout=20)
            print(f"[Telegram Bot Response - Status & Warnings]: {res.stdout.strip()[:100]}")
        except Exception as e:
            print(f"⚠️ Telegram notification error (Status & Warnings): {e}")
    else:
        print("ℹ️ Telegram bot script not found; Status & Warnings notification skipped.")

    # 2. Also send directly to Critical Alerts (-627025839)
    try:
        url = f"https://api.telegram.org/bot{CRITICAL_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": CRITICAL_CHAT_ID,
            "text": msg,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        resp = requests.post(url, json=payload, timeout=10)
        print(f"[Telegram Bot Response - Critical Alerts ({CRITICAL_CHAT_ID})]: {resp.status_code}")
    except Exception as e:
        print(f"⚠️ Telegram notification error (Critical Alerts): {e}")

def simulate_trade_live_mimic(ticks, total_qty):
    """
    Simulates a stock's tick-by-tick trajectory mirroring KotakCodes1 live engine:
      1. Leg 1: Entry at 09:42:00, 2.0% TP, 2.25% SL, 14:30 discount exit.
      2. Leg 2 (if TP1 hit): +0.50% Rebound re-entry, Zero Capital Risk SL (Leg 1 Entry), 1.75% TP2, 14:30 exit.
    """
    if not ticks:
        return None

    # Filter ticks with valid numeric price
    valid_ticks = [
        t for t in ticks
        if t.get('price') is not None and str(t.get('price')).strip() != '' and float(t.get('price') or 0) > 0
    ]
    if not valid_ticks:
        return None

    try:
        ep = float(valid_ticks[0]['price'])
    except Exception:
        return None

    entry_time = str(valid_ticks[0]['time']).split()[-1]
    tp1 = round(ep * 0.98, 2)            # 2.0% Take Profit
    sl1 = round(ep * 1.0225, 2)          # 2.25% Stop Loss

    leg1_exit_p = None
    leg1_exit_t = None
    leg1_reason = None
    rebound_trigger = None

    leg2_entry_p = None
    leg2_entry_t = None
    leg2_tp = None
    leg2_sl = None
    leg2_exit_p = None
    leg2_exit_t = None
    leg2_reason = None

    for t in valid_ticks:
        tm = str(t['time']).split()[-1]
        try:
            p = float(t['price'])
            l = float(t.get('low') if t.get('low') is not None and str(t.get('low')).strip() != '' else p)
            h = float(t.get('high') if t.get('high') is not None and str(t.get('high')).strip() != '' else p)
        except Exception:
            continue

        # --- LEG 1 ---
        if leg1_exit_p is None:
            # 1. 2.25% SL
            if h >= sl1:
                leg1_exit_p = sl1
                leg1_exit_t = tm
                leg1_reason = 'STOP_LOSS_2.25%'
                break
            # 2. 2.0% TP
            if l <= tp1:
                leg1_exit_p = tp1
                leg1_exit_t = tm
                leg1_reason = 'TAKE_PROFIT_2.0%'
                rebound_trigger = round(tp1 * 1.005, 2) # +0.50% Rebound
                continue
            # 3. 14:30 Pre-Close Exit (0.20% discount limit or market close)
            if tm >= '14:30:00':
                disc_p = round(p * 0.998, 2)
                leg1_exit_p = disc_p
                leg1_exit_t = tm
                leg1_reason = '14:30_DISCOUNT_EXIT'
                break
        else:
            # Leg 1 TP achieved -> watch for Leg 2 Re-entry bounce before 14:30
            if leg2_entry_p is None:
                if tm >= '14:30:00':
                    # Window closed
                    break
                if h >= rebound_trigger:
                    leg2_entry_p = rebound_trigger
                    leg2_entry_t = tm
                    leg2_tp = round(leg2_entry_p * 0.9825, 2) # 1.75% TP
                    leg2_sl = ep                              # Anchored at Leg 1 Entry (Zero Risk)
                    continue
            else:
                # Leg 2 Active
                # 1. Zero Capital Risk SL (Leg 1 Entry)
                if h >= leg2_sl:
                    leg2_exit_p = leg2_sl
                    leg2_exit_t = tm
                    leg2_reason = 'LEG2_SL_ZERO_RISK'
                    break
                # 2. 1.75% TP
                if l <= leg2_tp:
                    leg2_exit_p = leg2_tp
                    leg2_exit_t = tm
                    leg2_reason = 'LEG2_TP_1.75%'
                    break
                # 3. 14:30 Pre-Close Exit
                if tm >= '14:30:00':
                    disc_p = round(p * 0.998, 2)
                    leg2_exit_p = disc_p
                    leg2_exit_t = tm
                    leg2_reason = 'LEG2_1430_DISCOUNT_EXIT'
                    break

    if leg1_exit_p is None:
        try:
            leg1_exit_p = float(valid_ticks[-1]['price'])
            leg1_exit_t = str(valid_ticks[-1]['time']).split()[-1]
            leg1_reason = 'TIME_EXIT_1445'
        except Exception:
            return None

    # Compute Accounting
    leg1_gross = round((ep - leg1_exit_p) * total_qty, 2)
    leg1_tax = get_taxes(total_qty, ep, leg1_exit_p)
    leg1_net = round(leg1_gross - leg1_tax, 2)
    leg1_ret = round(((ep - leg1_exit_p) / ep) * 100.0, 2) if ep > 0 else 0.0

    has_leg2 = (leg2_entry_p is not None and leg2_exit_p is not None)
    if has_leg2:
        leg2_gross = round((leg2_entry_p - leg2_exit_p) * total_qty, 2)
        leg2_tax = get_taxes(total_qty, leg2_entry_p, leg2_exit_p)
        leg2_net = round(leg2_gross - leg2_tax, 2)
        leg2_ret = round(((leg2_entry_p - leg2_exit_p) / leg2_entry_p) * 100.0, 2) if leg2_entry_p > 0 else 0.0
    else:
        leg2_gross, leg2_tax, leg2_net, leg2_ret = 0.0, 0.0, 0.0, 0.0

    total_gross = round(leg1_gross + leg2_gross, 2)
    total_tax = round(leg1_tax + leg2_tax, 2)
    total_net = round(total_gross - total_tax, 2)
    overall_ret = round(((total_gross / (ep * total_qty)) * 100.0), 2) if ep > 0 else 0.0

    return {
        'entry_price': ep,
        'entry_time': entry_time,
        'leg1_exit_price': leg1_exit_p,
        'leg1_exit_time': leg1_exit_t,
        'leg1_exit_reason': leg1_reason,
        'leg1_net_pnl': leg1_net,
        'leg1_return_pct': leg1_ret,
        'has_leg2': has_leg2,
        'rebound_trigger': rebound_trigger,
        'leg2_entry_price': leg2_entry_p,
        'leg2_entry_time': leg2_entry_t,
        'leg2_exit_price': leg2_exit_p,
        'leg2_exit_time': leg2_exit_t,
        'leg2_exit_reason': leg2_reason,
        'leg2_net_pnl': leg2_net,
        'leg2_return_pct': leg2_ret,
        'gross_pnl': total_gross,
        'charges': total_tax,
        'net_pnl': total_net,
        'return_pct': overall_ret
    }

def simulate_simple_1445_no_tp(ticks, total_qty):
    """
    Strategy 1: Entry 09:42:00, Exit 14:45:00, SL 2.25%, No TP (Simple Hold).
    """
    valid_ticks = [
        t for t in ticks
        if t.get('price') is not None and str(t.get('price')).strip() != '' and float(t.get('price') or 0) > 0
    ]
    if not valid_ticks:
        return None
    try:
        ep = float(valid_ticks[0]['price'])
    except Exception:
        return None

    entry_time = str(valid_ticks[0]['time']).split()[-1]
    sl_price = round(ep * 1.0225, 2)

    exit_p = None
    exit_t = None
    exit_reason = None

    for t in valid_ticks:
        tm = str(t['time']).split()[-1]
        try:
            p = float(t['price'])
            h = float(t.get('high') if t.get('high') is not None and str(t.get('high')).strip() != '' else p)
        except Exception:
            continue

        if h >= sl_price:
            exit_p = sl_price
            exit_t = tm
            exit_reason = 'STOP_LOSS_2.25%'
            break

        if tm >= '14:45:00':
            exit_p = p
            exit_t = tm
            exit_reason = 'TIME_EXIT_1445'
            break

    if exit_p is None:
        exit_p = float(valid_ticks[-1]['price'])
        exit_t = str(valid_ticks[-1]['time']).split()[-1]
        exit_reason = 'TIME_EXIT_1445'

    gross = round((ep - exit_p) * total_qty, 2)
    tax = get_taxes(total_qty, ep, exit_p)
    net = round(gross - tax, 2)
    ret = round(((ep - exit_p) / ep) * 100.0, 2) if ep > 0 else 0.0

    return {
        'entry_price': ep,
        'entry_time': entry_time,
        'exit_price': exit_p,
        'exit_time': exit_t,
        'exit_reason': exit_reason,
        'gross_pnl': gross,
        'charges': tax,
        'net_pnl': net,
        'return_pct': ret
    }

def simulate_tp2_1445(ticks, total_qty):
    """
    Strategy 2: Entry 09:42:00, Exit 14:45:00, SL 2.25%, TP 2.0% (Single Leg).
    """
    valid_ticks = [
        t for t in ticks
        if t.get('price') is not None and str(t.get('price')).strip() != '' and float(t.get('price') or 0) > 0
    ]
    if not valid_ticks:
        return None
    try:
        ep = float(valid_ticks[0]['price'])
    except Exception:
        return None

    entry_time = str(valid_ticks[0]['time']).split()[-1]
    tp_price = round(ep * 0.98, 2)
    sl_price = round(ep * 1.0225, 2)

    exit_p = None
    exit_t = None
    exit_reason = None

    for t in valid_ticks:
        tm = str(t['time']).split()[-1]
        try:
            p = float(t['price'])
            h = float(t.get('high') if t.get('high') is not None and str(t.get('high')).strip() != '' else p)
            l = float(t.get('low') if t.get('low') is not None and str(t.get('low')).strip() != '' else p)
        except Exception:
            continue

        if h >= sl_price:
            exit_p = sl_price
            exit_t = tm
            exit_reason = 'STOP_LOSS_2.25%'
            break

        if l <= tp_price:
            exit_p = tp_price
            exit_t = tm
            exit_reason = 'TAKE_PROFIT_2.0%'
            break

        if tm >= '14:45:00':
            exit_p = p
            exit_t = tm
            exit_reason = 'TIME_EXIT_1445'
            break

    if exit_p is None:
        exit_p = float(valid_ticks[-1]['price'])
        exit_t = str(valid_ticks[-1]['time']).split()[-1]
        exit_reason = 'TIME_EXIT_1445'

    gross = round((ep - exit_p) * total_qty, 2)
    tax = get_taxes(total_qty, ep, exit_p)
    net = round(gross - tax, 2)
    ret = round(((ep - exit_p) / ep) * 100.0, 2) if ep > 0 else 0.0

    return {
        'entry_price': ep,
        'entry_time': entry_time,
        'exit_price': exit_p,
        'exit_time': exit_t,
        'exit_reason': exit_reason,
        'gross_pnl': gross,
        'charges': tax,
        'net_pnl': net,
        'return_pct': ret
    }

def reconcile_live_mimic(target_date=None, force_all=False, no_telegram=False, all_pending=False):
    if not os.path.exists(SOURCE_LEDGER_CSV):
        print(f"❌ Error: Source ledger file not found at {SOURCE_LEDGER_CSV}")
        return

    df_source = pd.read_csv(SOURCE_LEDGER_CSV)

    # Load existing mimic ledger if present, otherwise initialize from source ledger
    if os.path.exists(MIMIC_LEDGER_CSV):
        df_ledger = pd.read_csv(MIMIC_LEDGER_CSV)
        # Synchronize new trades from source ledger (e.g. today's date)
        existing_keys = set(zip(df_ledger['date'].astype(str), df_ledger['stockname'].astype(str)))
        new_rows = []
        for _, r in df_source.iterrows():
            if (str(r['date']), str(r['stockname'])) not in existing_keys:
                new_r = r.to_dict()
                new_r['status'] = 'PENDING'
                new_rows.append(new_r)
        if new_rows:
            print(f"📥 Synced {len(new_rows)} new trade(s) from source ledger into mimic ledger.")
            df_ledger = pd.concat([df_ledger, pd.DataFrame(new_rows)], ignore_index=True)
    else:
        df_ledger = df_source.copy()
        df_ledger['status'] = 'PENDING'

    # If no target_date is given and all_pending is False, target today's date or latest pending date
    ist = pytz.timezone('Asia/Kolkata')
    today_str = datetime.now(ist).strftime('%Y-%m-%d')

    if not target_date and not all_pending:
        today_pending = df_ledger[(df_ledger['date'] == today_str) & (df_ledger['status'] == 'PENDING')]
        if not today_pending.empty:
            target_date = today_str
        else:
            pending_dates = sorted(df_ledger[df_ledger['status'] == 'PENDING']['date'].dropna().unique().tolist())
            if pending_dates:
                target_date = pending_dates[-1]

    # Determine rows to reconcile
    if target_date:
        mask = (df_ledger['date'] == target_date)
        if not force_all:
            mask = mask & (df_ledger['status'] == 'PENDING')
    else:
        if force_all:
            mask = pd.Series(True, index=df_ledger.index)
        else:
            mask = (df_ledger['status'] == 'PENDING')

    target_indices = df_ledger[mask].index.tolist()
    if not target_indices:
        print("✔ No pending trades to reconcile for 09:42 Live Mimic Model.")
        if target_date:
            print(f"   (Trades for {target_date} are already marked COMPLETED)")
        return

    print(f"🔍 [09:42 LIVE MIMIC RECONCILER] Reconciling {len(target_indices)} trade(s) across {df_ledger.loc[target_indices, 'date'].nunique()} date(s)...")

    conn = get_db_connection()
    now_ts = datetime.now(ist).strftime('%Y-%m-%d %H:%M:%S')
    reconciled_dates = set()
    completed_count = 0

    obj_cols = [
        'leg2_entry_time', 'leg2_exit_time', 'leg2_exit_reason',
        'entry_time', 'leg1_exit_time', 'leg1_exit_reason',
        's1_exit_time', 's1_exit_reason',
        's2_exit_time', 's2_exit_reason',
        'status', 'reconciled_at'
    ]
    for c in obj_cols:
        if c in df_ledger.columns:
            df_ledger[c] = df_ledger[c].astype(object)

    with conn.cursor() as cursor:
        for idx in target_indices:
            row = df_ledger.loc[idx]
            d = str(row['date'])
            s = str(row['clean_stock'] if 'clean_stock' in row and not pd.isna(row['clean_stock']) else row['stockname']).strip().upper()
            lots_to_trade = int(row['lots_to_trade']) if 'lots_to_trade' in row and not pd.isna(row['lots_to_trade']) else 1
            lotsize = int(row['lotsize']) if 'lotsize' in row and not pd.isna(row['lotsize']) else (int(row['total_quantity']) // lots_to_trade if 'total_quantity' in row and pd.notna(row['total_quantity']) else 100)
            total_qty = int(row['total_quantity']) if 'total_quantity' in row and not pd.isna(row['total_quantity']) else lots_to_trade * lotsize

            try:
                # Query scrapdata_F1 (Futures) first
                cursor.execute(f"""
                    SELECT time, CAST(price AS DECIMAL(10,2)) as price, CAST(IFNULL(high, price) AS DECIMAL(10,2)) as high, CAST(IFNULL(low, price) AS DECIMAL(10,2)) as low
                    FROM scrapdata_F1
                    WHERE date = '{d}' AND stockname = '{s}'
                      AND TIME(time) >= '09:42:00' AND TIME(time) <= '14:45:00'
                      AND price IS NOT NULL AND price > 0
                      AND (isvalid = 'TRUE' OR isvalid IS NULL OR isvalid = '1' OR isvalid = '')
                    ORDER BY time ASC
                """)
                ticks_f1 = cursor.fetchall()

                # Query scrapdata (Cash Equity)
                cursor.execute(f"""
                    SELECT time, CAST(price AS DECIMAL(10,2)) as price, CAST(IFNULL(high, price) AS DECIMAL(10,2)) as high, CAST(IFNULL(low, price) AS DECIMAL(10,2)) as low
                    FROM scrapdata
                    WHERE date = '{d}' AND stockname = '{s}'
                      AND TIME(time) >= '09:42:00' AND TIME(time) <= '14:45:00'
                      AND price IS NOT NULL AND price > 0
                      AND (isvalid = 'TRUE' OR isvalid IS NULL OR isvalid = '1' OR isvalid = '')
                    ORDER BY time ASC
                """)
                ticks_eq = cursor.fetchall()

                res_f1 = simulate_trade_live_mimic(ticks_f1, total_qty) if ticks_f1 else None
                res_eq = simulate_trade_live_mimic(ticks_eq, total_qty) if ticks_eq else None

                if not res_f1 and not res_eq:
                    print(f"⚠️ {d} | {s}: No tick data found in scrapdata or scrapdata_F1. Remains PENDING.")
                    continue

                primary = res_f1 if res_f1 else res_eq
                ticks_primary = ticks_f1 if ticks_f1 else ticks_eq

                # Strategy 1 (Simple Hold 14:45, SL 2.25%, No TP)
                res_s1 = simulate_simple_1445_no_tp(ticks_primary, total_qty) if ticks_primary else None
                # Strategy 2 (Fixed 2.0% TP, SL 2.25%, Exit 14:45)
                res_s2 = simulate_tp2_1445(ticks_primary, total_qty) if ticks_primary else None

                # Update Strategy 3 fields in dataframe
                df_ledger.loc[idx, 'entry_price'] = primary['entry_price']
                df_ledger.loc[idx, 'entry_time'] = primary['entry_time']
                df_ledger.loc[idx, 'stop_loss_2_25pct'] = round(primary['entry_price'] * 1.0225, 2)
                df_ledger.loc[idx, 'tp1_price'] = round(primary['entry_price'] * 0.98, 2)
                df_ledger.loc[idx, 'leg1_exit_price'] = primary['leg1_exit_price']
                df_ledger.loc[idx, 'leg1_exit_time'] = primary['leg1_exit_time']
                df_ledger.loc[idx, 'leg1_exit_reason'] = primary['leg1_exit_reason']
                df_ledger.loc[idx, 'leg1_net_pnl'] = primary['leg1_net_pnl']
                df_ledger.loc[idx, 'leg1_return_pct'] = primary['leg1_return_pct']

                df_ledger.loc[idx, 'has_leg2'] = primary['has_leg2']
                df_ledger.loc[idx, 'rebound_trigger'] = primary['rebound_trigger']
                df_ledger.loc[idx, 'leg2_entry_price'] = primary['leg2_entry_price']
                df_ledger.loc[idx, 'leg2_entry_time'] = primary['leg2_entry_time']
                df_ledger.loc[idx, 'leg2_exit_price'] = primary['leg2_exit_price']
                df_ledger.loc[idx, 'leg2_exit_time'] = primary['leg2_exit_time']
                df_ledger.loc[idx, 'leg2_exit_reason'] = primary['leg2_exit_reason']
                df_ledger.loc[idx, 'leg2_net_pnl'] = primary['leg2_net_pnl']
                df_ledger.loc[idx, 'leg2_return_pct'] = primary['leg2_return_pct']

                df_ledger.loc[idx, 'gross_pnl'] = primary['gross_pnl']
                df_ledger.loc[idx, 'charges'] = primary['charges']
                df_ledger.loc[idx, 'net_pnl'] = primary['net_pnl']
                df_ledger.loc[idx, 'return_pct'] = primary['return_pct']
                df_ledger.loc[idx, 'exit_price'] = primary['leg2_exit_price'] if primary['has_leg2'] else primary['leg1_exit_price']
                df_ledger.loc[idx, 'exit_time'] = primary['leg2_exit_time'] if primary['has_leg2'] else primary['leg1_exit_time']
                df_ledger.loc[idx, 'exit_reason'] = primary['leg2_exit_reason'] if primary['has_leg2'] else primary['leg1_exit_reason']

                # Update Strategy 1 fields
                if res_s1:
                    df_ledger.loc[idx, 's1_entry_price'] = res_s1['entry_price']
                    df_ledger.loc[idx, 's1_exit_price'] = res_s1['exit_price']
                    df_ledger.loc[idx, 's1_exit_time'] = res_s1['exit_time']
                    df_ledger.loc[idx, 's1_exit_reason'] = res_s1['exit_reason']
                    df_ledger.loc[idx, 's1_gross_pnl'] = res_s1['gross_pnl']
                    df_ledger.loc[idx, 's1_charges'] = res_s1['charges']
                    df_ledger.loc[idx, 's1_net_pnl'] = res_s1['net_pnl']
                    df_ledger.loc[idx, 's1_return_pct'] = res_s1['return_pct']

                # Update Strategy 2 fields
                if res_s2:
                    df_ledger.loc[idx, 's2_entry_price'] = res_s2['entry_price']
                    df_ledger.loc[idx, 's2_exit_price'] = res_s2['exit_price']
                    df_ledger.loc[idx, 's2_exit_time'] = res_s2['exit_time']
                    df_ledger.loc[idx, 's2_exit_reason'] = res_s2['exit_reason']
                    df_ledger.loc[idx, 's2_gross_pnl'] = res_s2['gross_pnl']
                    df_ledger.loc[idx, 's2_charges'] = res_s2['charges']
                    df_ledger.loc[idx, 's2_net_pnl'] = res_s2['net_pnl']
                    df_ledger.loc[idx, 's2_return_pct'] = res_s2['return_pct']

                if res_f1:
                    df_ledger.loc[idx, 'f1_net_pnl'] = res_f1['net_pnl']
                    df_ledger.loc[idx, 'f1_return_pct'] = res_f1['return_pct']
                if res_eq:
                    df_ledger.loc[idx, 'eq_net_pnl'] = res_eq['net_pnl']
                    df_ledger.loc[idx, 'eq_return_pct'] = res_eq['return_pct']

                df_ledger.loc[idx, 'status'] = 'COMPLETED'
                df_ledger.loc[idx, 'reconciled_at'] = now_ts

                reconciled_dates.add(d)
                completed_count += 1
            except Exception as row_err:
                print(f"⚠️ Error simulating {d} | {s}: {row_err}")
                continue

    conn.close()

    if completed_count == 0:
        print("⚠️ No trades could be reconciled.")
        return

    # Save to Ledgers
    save_paths = [
        MIMIC_LEDGER_CSV,
        AUDITED_MIMIC_CSV,
        os.path.join(SARANG_DIR, 'daily_0940_live_mimic_ledger.csv'),
        os.path.join(SARANG_DIR, 'audited_0940_live_mimic_trades.csv')
    ]
    for p in save_paths:
        try:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            df_ledger.to_csv(p, index=False)
            print(f"✔ Saved Live Mimic Ledger: {p}")
        except Exception as e:
            print(f"⚠️ Error saving {p}: {e}")

    # Generate Reports & Telegram Alerts
    for d in sorted(list(reconciled_dates)):
        day_df = df_ledger[(df_ledger['date'] == d) & (df_ledger['status'] == 'COMPLETED')].sort_values('rank')
        if day_df.empty:
            continue

        # Strategy 1 Totals
        s1_net = day_df['s1_net_pnl'].sum() if 's1_net_pnl' in day_df else 0.0
        s1_gross = day_df['s1_gross_pnl'].sum() if 's1_gross_pnl' in day_df else 0.0
        s1_charges = day_df['s1_charges'].sum() if 's1_charges' in day_df else 0.0
        s1_wins = (day_df['s1_net_pnl'] > 0).sum() if 's1_net_pnl' in day_df else 0
        s1_win_rate = (s1_wins / len(day_df)) * 100.0 if len(day_df) > 0 else 0.0

        # Strategy 2 Totals
        s2_net = day_df['s2_net_pnl'].sum() if 's2_net_pnl' in day_df else 0.0
        s2_gross = day_df['s2_gross_pnl'].sum() if 's2_gross_pnl' in day_df else 0.0
        s2_charges = day_df['s2_charges'].sum() if 's2_charges' in day_df else 0.0
        s2_wins = (day_df['s2_net_pnl'] > 0).sum() if 's2_net_pnl' in day_df else 0
        s2_win_rate = (s2_wins / len(day_df)) * 100.0 if len(day_df) > 0 else 0.0

        # Strategy 3 Totals
        tot_net = day_df['net_pnl'].sum()
        tot_gross = day_df['gross_pnl'].sum()
        tot_charges = day_df['charges'].sum()
        wins = (day_df['net_pnl'] > 0).sum()
        win_rate = (wins / len(day_df)) * 100.0 if len(day_df) > 0 else 0.0

        diff_s3_s1 = tot_net - s1_net
        diff_s3_s2 = tot_net - s2_net
        pnl_color = "🟢" if tot_net >= 0 else "🔴"

        print("\n" + "=" * 125)
        print(f"📊 09:40 MODEL DAILY 3-STRATEGY RECONCILED REPORT: {d}")
        print("=" * 125)

        print("\n🔹 [STRATEGY 1: SIMPLE HOLD (NO TP, SL 2.25%, EXIT 14:45)]")
        print(f"{'#':<3} | {'Stock':<10} | {'Qty':<5} | {'Entry (09:42)':<15} | {'Exit Price':<12} | {'Exit Time':<10} | {'Reason':<16} | {'Net PnL (₹)':<12} | {'Return %':<8}")
        print("-" * 105)
        for i, (_, r) in enumerate(day_df.iterrows()):
            stk = r.get('clean_stock') if pd.notna(r.get('clean_stock')) else r.get('stockname')
            qty = int(r.get('total_quantity', 0))
            ep = f"₹{r.get('s1_entry_price', r.get('entry_price', 0.0)):,.2f}"
            xp = f"₹{r.get('s1_exit_price', 0.0):,.2f}"
            xt = str(r.get('s1_exit_time', '-'))
            xr = str(r.get('s1_exit_reason', '-'))
            npnl = r.get('s1_net_pnl', 0.0)
            ret = r.get('s1_return_pct', 0.0)
            print(f"{i+1:<3} | {stk:<10} | {qty:<5} | {ep:<15} | {xp:<12} | {xt:<10} | {xr:<16} | {npnl:>11,.2f} | {ret:>7.2f}%")
        print("-" * 105)
        print(f"Strategy 1 Total Net: ₹{s1_net:,.2f} | Gross: ₹{s1_gross:,.2f} | Charges: ₹{s1_charges:,.2f} | Win Rate: {s1_win_rate:.1f}%")

        print("\n🔹 [STRATEGY 2: FIXED 2.0% TP (SL 2.25%, EXIT 14:45)]")
        print(f"{'#':<3} | {'Stock':<10} | {'Qty':<5} | {'Entry (09:42)':<15} | {'Exit Price':<12} | {'Exit Time':<10} | {'Reason':<16} | {'Net PnL (₹)':<12} | {'Return %':<8}")
        print("-" * 105)
        for i, (_, r) in enumerate(day_df.iterrows()):
            stk = r.get('clean_stock') if pd.notna(r.get('clean_stock')) else r.get('stockname')
            qty = int(r.get('total_quantity', 0))
            ep = f"₹{r.get('s2_entry_price', r.get('entry_price', 0.0)):,.2f}"
            xp = f"₹{r.get('s2_exit_price', 0.0):,.2f}"
            xt = str(r.get('s2_exit_time', '-'))
            xr = str(r.get('s2_exit_reason', '-'))
            npnl = r.get('s2_net_pnl', 0.0)
            ret = r.get('s2_return_pct', 0.0)
            print(f"{i+1:<3} | {stk:<10} | {qty:<5} | {ep:<15} | {xp:<12} | {xt:<10} | {xr:<16} | {npnl:>11,.2f} | {ret:>7.2f}%")
        print("-" * 105)
        print(f"Strategy 2 Total Net: ₹{s2_net:,.2f} | Gross: ₹{s2_gross:,.2f} | Charges: ₹{s2_charges:,.2f} | Win Rate: {s2_win_rate:.1f}%")

        print("\n🔹 [STRATEGY 3: REBOUND RE-ENTRY MODEL (LEG 1 + LEG 2, EXIT 14:30)]")
        print(f"{'#':<3} | {'Stock':<10} | {'Leg 1 In':<17} | {'Leg 1 Out':<17} | {'L1 Net (₹)':<11} | {'Re-entry In':<17} | {'Leg 2 Out':<17} | {'Total Net (₹)':<12}")
        print("-" * 125)
        for i, (_, r) in enumerate(day_df.iterrows()):
            stk = r.get('clean_stock') if pd.notna(r.get('clean_stock')) else r.get('stockname')
            l1_in = f"₹{r.get('entry_price', 0.0):,.1f}@{str(r.get('entry_time', ''))[:5]}"
            l1_out = f"₹{r.get('leg1_exit_price', 0.0):,.1f}@{str(r.get('leg1_exit_time', ''))[:5]}"
            l1_n = r.get('leg1_net_pnl', 0.0)
            
            if r.get('has_leg2'):
                l2_in = f"₹{r.get('leg2_entry_price', 0.0):,.1f}@{str(r.get('leg2_entry_time', ''))[:5]}"
                l2_out = f"₹{r.get('leg2_exit_price', 0.0):,.1f}@{str(r.get('leg2_exit_time', ''))[:5]}"
            else:
                l2_in = "-"
                l2_out = "-"
            t_net = r.get('net_pnl', 0.0)
            print(f"{i+1:<3} | {stk:<10} | {l1_in:<17} | {l1_out:<17} | {l1_n:>10,.2f}  | {l2_in:<17} | {l2_out:<17} | {t_net:>11,.2f}")
        print("-" * 125)
        print(f"Strategy 3 Total Net: ₹{tot_net:,.2f} | Gross: ₹{tot_gross:,.2f} | Charges: ₹{tot_charges:,.2f} | Win Rate: {win_rate:.1f}%")

        print("\n" + "=" * 65)
        print("🏆 3-STRATEGY EXECUTIVE COMPARISON SUMMARY")
        print("=" * 65)
        print(f"• Strategy 1 (Hold 14:45, No TP): ₹{s1_net:+11,.2f} (Win Rate: {s1_win_rate:.1f}%)")
        print(f"• Strategy 2 (Fixed 2.0% TP):     ₹{s2_net:+11,.2f} (Win Rate: {s2_win_rate:.1f}%)")
        print(f"• Strategy 3 (Rebound Re-entry):  ₹{tot_net:+11,.2f} (Win Rate: {win_rate:.1f}%)")
        print(f"🚀 Rebound Model Alpha vs S1:     ₹{diff_s3_s1:+11,.2f}")
        print(f"🚀 Rebound Model Alpha vs S2:     ₹{diff_s3_s2:+11,.2f}")
        print("=" * 65)

        # Telegram Alert Construction
        tg_lines = [
            f"{pnl_color} <b>[09:40 DAILY 3-STRATEGY RECONCILE REPORT]</b>",
            f"📅 <b>Date:</b> {d} | ⏱️ <b>Audit Time:</b> {now_ts} IST",
            "",
            "━━━━━━━━━━━━━━━━━━━━━",
            "🔹 <b>STRATEGY 1: SIMPLE HOLD (NO TP)</b>",
            "<i>Rules: Entry 09:42 | SL 2.25% | No TP | Exit 14:45</i>"
        ]
        for i, (_, r) in enumerate(day_df.iterrows()):
            stk = r.get('clean_stock') if pd.notna(r.get('clean_stock')) else r.get('stockname')
            qty = int(r.get('total_quantity', 0))
            ep = r.get('s1_entry_price', r.get('entry_price', 0.0))
            xp = r.get('s1_exit_price', 0.0)
            xt = str(r.get('s1_exit_time', '-'))
            xr = str(r.get('s1_exit_reason', '-'))
            npnl = r.get('s1_net_pnl', 0.0)
            ret = r.get('s1_return_pct', 0.0)
            icon = "✅" if npnl > 0 else "❌"
            tg_lines.append(f"  {icon} <b>#{i+1} {stk}</b> (Qty {qty}): In ₹{ep:,.2f} ➔ Out ₹{xp:,.2f} @ {xt} [{xr}] | Net: <b>₹{npnl:+,.2f}</b> ({ret:+.2f}%)")
        tg_lines.append(f"💰 <b>S1 Net PnL:</b> <b>₹{s1_net:+,.2f}</b> (WR: {s1_win_rate:.1f}%)")

        tg_lines.extend([
            "",
            "━━━━━━━━━━━━━━━━━━━━━",
            "🔹 <b>STRATEGY 2: FIXED 2.0% TP</b>",
            "<i>Rules: Entry 09:42 | TP 2.0% | SL 2.25% | Exit 14:45</i>"
        ])
        for i, (_, r) in enumerate(day_df.iterrows()):
            stk = r.get('clean_stock') if pd.notna(r.get('clean_stock')) else r.get('stockname')
            qty = int(r.get('total_quantity', 0))
            ep = r.get('s2_entry_price', r.get('entry_price', 0.0))
            xp = r.get('s2_exit_price', 0.0)
            xt = str(r.get('s2_exit_time', '-'))
            xr = str(r.get('s2_exit_reason', '-'))
            npnl = r.get('s2_net_pnl', 0.0)
            ret = r.get('s2_return_pct', 0.0)
            icon = "✅" if npnl > 0 else "❌"
            tg_lines.append(f"  {icon} <b>#{i+1} {stk}</b> (Qty {qty}): In ₹{ep:,.2f} ➔ Out ₹{xp:,.2f} @ {xt} [{xr}] | Net: <b>₹{npnl:+,.2f}</b> ({ret:+.2f}%)")
        tg_lines.append(f"💰 <b>S2 Net PnL:</b> <b>₹{s2_net:+,.2f}</b> (WR: {s2_win_rate:.1f}%)")

        tg_lines.extend([
            "",
            "━━━━━━━━━━━━━━━━━━━━━",
            "🔹 <b>STRATEGY 3: REBOUND RE-ENTRY MODEL</b>",
            "<i>Rules: Leg 1 (2% TP / 2.25% SL / 14:30) ➔ Re-entry (+0.5% Rebound / 1.75% TP2 / Zero-risk SL / 14:30)</i>"
        ])
        for i, (_, r) in enumerate(day_df.iterrows()):
            stk_name = str(r['clean_stock']) if 'clean_stock' in r and pd.notna(r['clean_stock']) else str(r['stockname'])
            t_icon = "✅" if r['net_pnl'] > 0 else "❌"
            qty = int(r.get('total_quantity', 0))

            l1_entry_p = r.get('entry_price', 0.0)
            l1_entry_t = str(r.get('entry_time', '09:42:00'))
            l1_exit_p = r.get('leg1_exit_price', 0.0)
            l1_exit_t = str(r.get('leg1_exit_time', '-'))
            l1_reason = r.get('leg1_exit_reason', '')
            l1_net = r.get('leg1_net_pnl', 0.0)
            l1_ret = r.get('leg1_return_pct', 0.0)
            tot_n = r.get('net_pnl', 0.0)

            tg_lines.append(f"  {t_icon} <b>#{i+1} {stk_name}</b> (Qty {qty}):")
            tg_lines.append(f"      • Leg 1: In ₹{l1_entry_p:,.2f} @ {l1_entry_t} ➔ Out ₹{l1_exit_p:,.2f} @ {l1_exit_t} [{l1_reason}] | Net: <b>₹{l1_net:+,.2f}</b> ({l1_ret:+.2f}%)")
            if r.get('has_leg2'):
                l2_entry_p = r.get('leg2_entry_price', 0.0)
                l2_entry_t = str(r.get('leg2_entry_time', '-'))
                l2_exit_p = r.get('leg2_exit_price', 0.0)
                l2_exit_t = str(r.get('leg2_exit_time', '-'))
                l2_reason = r.get('leg2_exit_reason', '')
                l2_net = r.get('leg2_net_pnl', 0.0)
                l2_ret = r.get('leg2_return_pct', 0.0)
                tg_lines.append(f"      • 🔄 Leg 2: In ₹{l2_entry_p:,.2f} @ {l2_entry_t} ➔ Out ₹{l2_exit_p:,.2f} @ {l2_exit_t} [{l2_reason}] | Net: <b>₹{l2_net:+,.2f}</b> ({l2_ret:+.2f}%)")
            tg_lines.append(f"      • <b>Total Stock Net:</b> <b>₹{tot_n:+,.2f}</b>")

        tg_lines.extend([
            f"💰 <b>S3 Net PnL:</b> <b>₹{tot_net:+,.2f}</b> (WR: {win_rate:.1f}%)",
            "",
            "━━━━━━━━━━━━━━━━━━━━━",
            "🏆 <b>EXECUTIVE COMPARISON SUMMARY</b>",
            f"• <b>S1 (Hold 14:45, No TP):</b> <b>₹{s1_net:+,.2f}</b> | WR: {s1_win_rate:.1f}%",
            f"• <b>S2 (Fixed 2.0% TP):</b> <b>₹{s2_net:+,.2f}</b> | WR: {s2_win_rate:.1f}%",
            f"• <b>S3 (Rebound Re-entry):</b> <b>₹{tot_net:+,.2f}</b> | WR: {win_rate:.1f}%",
            f"🚀 <b>Alpha S3 vs S1:</b> <b>₹{diff_s3_s1:+,.2f}</b>",
            f"🚀 <b>Alpha S3 vs S2:</b> <b>₹{diff_s3_s2:+,.2f}</b>"
        ])

        if not no_telegram:
            send_telegram_alert("\n".join(tg_lines))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="09:42 Live Mimic Engine Evening Reconciler")
    parser.add_argument('--date', type=str, default=None, help="Target Date YYYY-MM-DD (defaults to today or latest pending)")
    parser.add_argument('--force-all', action='store_true', help="Re-reconcile even if already completed")
    parser.add_argument('--all-pending', action='store_true', help="Reconcile all historical pending trades")
    parser.add_argument('--no-telegram', action='store_true', help="Skip sending Telegram alert")
    args = parser.parse_args()

    reconcile_live_mimic(target_date=args.date, force_all=args.force_all, no_telegram=args.no_telegram, all_pending=args.all_pending)
