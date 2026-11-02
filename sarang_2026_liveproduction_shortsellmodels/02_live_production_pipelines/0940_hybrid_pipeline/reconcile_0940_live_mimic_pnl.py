#!/usr/bin/env python3
"""
reconcile_0940_live_mimic_pnl.py
---------------------------------
Evening 3-Simulation Reconciler for the 09:40 / 09:42 Hybrid Short-Sell Model:

  • SIMULATION 1: NO TP | SL AT 2.25% (3-MINUTE CONSECUTIVE BREACH) | EXIT 14:45
      - Entry at 09:42:00 AM IST (uses live Kotak filled_price if available, else 09:42 tick).
      - No Take Profit.
      - Stop-Loss at 2.25% (ep * 1.0225) requiring 3 consecutive 1-minute breaches (resets to 0 if price drops back below SL).
      - Otherwise holds until 14:45:00 EOD Exit.

  • SIMULATION 2: 2.0% FIXED TP | SL AT 2.25% (3-MIN CONT. BREACH) | RE-ENTRY AT +0.50% BOUNCE
      - Leg 1: Fixed 2.0% TP (ep * 0.98, instant exit), 2.25% SL with 3 consecutive 1-minute breaches, 14:30 discount exit (p * 0.998).
      - Leg 2 (if Leg 1 hit 2.0% TP before 14:30): Re-enters on +0.50% bounce from Leg 1 exit price (leg1_exit_p * 1.005).
        Leg 2 TP: 1.75% (leg2_ep * 0.9825), Leg 2 SL: Zero-Risk at Leg 1 Entry (ep), 14:30 discount exit.

  • SIMULATION 3: LIVE 4-STAGE DYNAMIC ENGINE (CURRENT LIVE STRATEGY)
      - Stage 1 (Time-Decay SL, 3-Min Consecutive Breach):
          • 09:42 – 10:59: 3.00% SL (ep * 1.0300)
          • 11:00 – 12:29: 1.50% SL (ep * 1.0150)
          • 12:30 – 14:45: 1.00% SL (ep * 1.0100)
          Requires 3 consecutive 1-minute breaches (resets to 0 if price recovers below SL).
      - Stage 2 (Pre-TP Profit Lock, Immediate Exit):
          • Once peak profit reaches +1.25% (min_ltp <= ep * 0.9875), locks +0.50% minimum profit floor (ep * 0.9950).
          • Immediate exit if price rebounds to >= ep * 0.9950 before reaching 2.00% TP. Does NOT trigger Leg 2 re-entry.
      - Stage 3 (Leg 1 Trailing TP Engine, Immediate Exit):
          • Activates at +2.00% profit (ep * 0.9800).
          • Sets initial floor at +1.75% profit (ep * 0.9825) (waits until profit lowers to 1.75% instead of 1.90%),
            and trails 0.50% behind peak profit (active_sl = min(ep * 0.9825, min_ltp * 1.005)).
          • Immediate exit when price >= active_sl; arms Stage 4 Leg 2 Re-entry.
      - Stage 4 (Leg 2 Re-Entry at +0.50% Bounce):
          • After Stage 3 Trailing TP exit (before 14:30), re-enters on +0.50% bounce (leg1_exit_p * 1.005).
          • Leg 2 monitored with 1.50% Tight SL (leg2_ep * 1.015) and 1.50% Trailing TP (leg2_ep * 0.985, trailing 0.75% behind min_ltp_l2).
      - 14:30 Pre-Close Discount Exit (p * 0.998) / 14:45 EOD Exit.
"""

import os
import sys
import time
import argparse
import subprocess
import requests
import urllib3.util.connection as urllib3_cn
urllib3_cn.HAS_IPV6 = False
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
STATUS_BOT_TOKEN = "7920868588:AAE4mPlDQJWnkv9CbmHO8idiSBVnP7K0Gko"
STATUS_CHAT_ID = "-1002365534285"

TELEGRAM_GROUPS = [
    ("5350311365:AAFkTUBR4IGvgS5Z9mJngz-mgk7-HkhFEYE", "-627025839", "kotak_Critical Alerts"),
    ("5350311365:AAFkTUBR4IGvgS5Z9mJngz-mgk7-HkhFEYE", "-698073972", "Order_Information"),
    ("5350311365:AAFkTUBR4IGvgS5Z9mJngz-mgk7-HkhFEYE", "5372262877", "Admin Direct"),
]

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
    # 1. Send via status_Info_bot.js to Status and Warnings (-1002365534285) with direct IPv4 fallback
    status_sent = False
    if os.path.exists(BOT_SCRIPT):
        try:
            res = subprocess.run(['node', BOT_SCRIPT, msg], capture_output=True, text=True, timeout=35)
            out_str = res.stdout.strip()
            print(f"[Telegram Bot Response - Status & Warnings]: {out_str[:100]}")
            if res.returncode == 0 and "Message sent successfully" in out_str:
                status_sent = True
        except Exception as e:
            print(f"⚠️ Telegram notification error (Status & Warnings node): {e}")

    if not status_sent:
        url = f"https://api.telegram.org/bot{STATUS_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": STATUS_CHAT_ID, "text": msg, "parse_mode": "HTML", "disable_web_page_preview": True}
        for attempt in range(1, 5):
            try:
                resp = requests.post(url, json=payload, timeout=12)
                if resp.status_code == 200:
                    print(f"[Telegram Bot Response - Status & Warnings Direct IPv4]: 200 (attempt {attempt})")
                    status_sent = True
                    break
            except Exception as e:
                print(f"⚠️ Telegram direct fallback error (Status & Warnings attempt {attempt}/4): {e}")
            time.sleep(2 * attempt)

    # 2. Send directly to Critical Alerts, Order Information, and Admin Direct (with 4-attempt IPv4 retry)
    for token, chat_id, label in TELEGRAM_GROUPS:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": msg,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        for attempt in range(1, 5):
            try:
                resp = requests.post(url, json=payload, timeout=12)
                print(f"[Telegram Bot Response - {label} ({chat_id})]: {resp.status_code}")
                if resp.status_code == 200:
                    break
            except Exception as e:
                print(f"⚠️ Telegram notification error ({label} attempt {attempt}/4): {e}")
            time.sleep(2 * attempt)

def _filter_valid_ticks(ticks):
    if not ticks:
        return []
    seen_times = set()
    cleaned = []
    prev_p = None
    for t in ticks:
        if t.get('price') is None or str(t.get('price')).strip() == '':
            continue
        try:
            p = float(t['price'])
        except Exception:
            continue
        if p <= 0:
            continue
        tm = str(t.get('time', '')).split()[-1]
        if tm in seen_times:
            continue
        # Guard against single-tick corrupted database spikes (>12% jump in 1 min)
        if prev_p is not None and abs(p - prev_p) / prev_p > 0.12:
            continue
        seen_times.add(tm)
        prev_p = p
        cleaned.append(t)
    return cleaned

def simulate_sim1_no_tp_3min_sl(ticks, total_qty, override_ep=None):
    """
    SIMULATION 1: NO TP | SL AT 2.25% (3-MINUTE CONSECUTIVE BREACH) | EXIT 14:45
    """
    valid_ticks = _filter_valid_ticks(ticks)
    if not valid_ticks:
        return None
    try:
        ep = float(override_ep) if (override_ep is not None and float(override_ep) > 0) else float(valid_ticks[0]['price'])
    except Exception:
        return None

    entry_time = str(valid_ticks[0]['time']).split()[-1]
    sl_price = round(ep * 1.0225, 2)

    exit_p = None
    exit_t = None
    exit_reason = None
    breach_count = 0

    for t in valid_ticks:
        tm = str(t['time']).split()[-1]
        try:
            p = float(t['price'])
        except Exception:
            continue

        if p >= sl_price:
            breach_count += 1
            if breach_count >= 3:
                exit_p = p
                exit_t = tm
                exit_reason = 'SL_2.25%_3MIN'
                break
        else:
            breach_count = 0

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

def simulate_sim2_fixed_tp2_reentry_3min_sl(ticks, total_qty, override_ep=None):
    """
    SIMULATION 2: 2.0% FIXED TP | SL AT 2.25% (3-MIN CONT. BREACH) | RE-ENTRY AT +0.50% BOUNCE
      - Leg 1: Fixed 2.0% TP (ep * 0.98, instant exit), 2.25% SL (3-minute consecutive breach), 14:30 discount exit.
      - Leg 2 (if Leg 1 hit 2.0% TP before 14:30): Re-entry on +0.50% bounce from Leg 1 exit price,
        1.75% TP2 (leg2_ep * 0.9825), Zero-Risk SL at Leg 1 Entry (ep), 14:30 discount exit.
    """
    valid_ticks = _filter_valid_ticks(ticks)
    if not valid_ticks:
        return None
    try:
        ep = float(override_ep) if (override_ep is not None and float(override_ep) > 0) else float(valid_ticks[0]['price'])
    except Exception:
        return None

    entry_time = str(valid_ticks[0]['time']).split()[-1]
    tp1 = round(ep * 0.9800, 2)
    sl1 = round(ep * 1.0225, 2)

    leg1_exit_p = None
    leg1_exit_t = None
    leg1_reason = None
    rebound_trigger = None
    breach_count = 0
    discount_limit_l1 = None

    leg2_entry_p = None
    leg2_entry_t = None
    leg2_tp = None
    leg2_sl = None
    leg2_exit_p = None
    leg2_exit_t = None
    leg2_reason = None
    discount_limit_l2 = None

    for t in valid_ticks:
        tm = str(t['time']).split()[-1]
        try:
            p = float(t['price'])
        except Exception:
            continue

        if leg1_exit_p is None:
            # 1. 2.25% SL with 3-Minute Consecutive Breach
            if p >= sl1:
                breach_count += 1
                if breach_count >= 3:
                    leg1_exit_p = p
                    leg1_exit_t = tm
                    leg1_reason = 'SL_2.25%_3MIN'
                    break
            else:
                breach_count = 0

            # 2. Fixed 2.0% TP (Instant Exit)
            if p <= tp1:
                leg1_exit_p = p
                leg1_exit_t = tm
                leg1_reason = 'FIXED_TP_2.0%'
                rebound_trigger = round(leg1_exit_p * 1.005, 2)
                continue

            # 3. 14:30 Pre-Close Resting Discount Limit (-0.20%) / 14:45 Chaser Exit
            if tm >= '14:30:00':
                if discount_limit_l1 is None:
                    discount_limit_l1 = round(p * 0.998, 2)
                elif p <= discount_limit_l1:
                    leg1_exit_p = discount_limit_l1
                    leg1_exit_t = tm
                    leg1_reason = '14:30_DISCOUNT_EXIT'
                    break
            if tm >= '14:45:00':
                leg1_exit_p = p
                leg1_exit_t = tm
                leg1_reason = 'TIME_EXIT_1445'
                break
        else:
            # Watch for +0.50% bounce re-entry before 14:30
            if leg2_entry_p is None:
                if tm >= '14:30:00':
                    break
                if rebound_trigger is not None and p >= rebound_trigger:
                    leg2_entry_p = p
                    leg2_entry_t = tm
                    leg2_tp = round(leg2_entry_p * 0.9825, 2)
                    leg2_sl = ep
                    continue
            else:
                if p >= leg2_sl:
                    leg2_exit_p = p
                    leg2_exit_t = tm
                    leg2_reason = 'LEG2_SL_ZERO_RISK'
                    break
                if p <= leg2_tp:
                    leg2_exit_p = p
                    leg2_exit_t = tm
                    leg2_reason = 'LEG2_TP_1.75%'
                    break
                if tm >= '14:30:00':
                    if discount_limit_l2 is None:
                        discount_limit_l2 = round(p * 0.998, 2)
                    elif p <= discount_limit_l2:
                        leg2_exit_p = discount_limit_l2
                        leg2_exit_t = tm
                        leg2_reason = 'LEG2_1430_EXIT'
                        break
                if tm >= '14:45:00':
                    leg2_exit_p = p
                    leg2_exit_t = tm
                    leg2_reason = 'LEG2_TIME_EXIT_1445'
                    break

    if leg1_exit_p is None:
        leg1_exit_p = float(valid_ticks[-1]['price'])
        leg1_exit_t = str(valid_ticks[-1]['time']).split()[-1]
        leg1_reason = 'TIME_EXIT_1445'
    if leg2_entry_p is not None and leg2_exit_p is None:
        leg2_exit_p = float(valid_ticks[-1]['price'])
        leg2_exit_t = str(valid_ticks[-1]['time']).split()[-1]
        leg2_reason = 'LEG2_TIME_EXIT_1445'

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
        'exit_price': leg2_exit_p if has_leg2 else leg1_exit_p,
        'exit_time': leg2_exit_t if has_leg2 else leg1_exit_t,
        'exit_reason': f"{leg1_reason}+{leg2_reason}" if has_leg2 else leg1_reason,
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

def simulate_sim3_live_4stage_engine(ticks, total_qty, override_ep=None):
    """
    SIMULATION 3: LIVE 4-STAGE DYNAMIC ENGINE (CURRENT LIVE CODE)
      1. Stage 1 (Time-Decay SL, 3-Min Consecutive Breach):
           • 09:42 – 10:59: 3.00% SL
           • 11:00 – 12:29: 1.50% SL
           • 12:30 – 14:45: 1.00% SL
      2. Stage 2 (Pre-TP Profit Lock at +1.25% Peak -> Locks +0.50% Profit Floor at ep * 0.9950):
           • Immediate exit if price rebounds to >= ep * 0.9950 before reaching 2.00% TP.
           • Does NOT trigger Leg 2 re-entry.
      3. Stage 3 (Leg 1 Trailing TP Engine at +2.00% -> +1.75% Initial Floor & 0.50% Trail):
           • Activates when price <= ep * 0.9800 (+2.00% profit).
           • Initial floor set at +1.75% profit (ep * 0.9825); ratchets 0.50% behind min_ltp (min(ep * 0.9825, min_ltp * 1.005)).
           • Immediate exit when price >= active_sl; arms Stage 4 Leg 2 Re-entry.
      4. Stage 4 (Leg 2 Re-Entry at +0.50% Bounce):
           • Re-enters when price >= leg1_exit_p * 1.005 before 14:30.
           • Monitored with 1.50% Tight SL (leg2_ep * 1.015) and 1.50% Trailing TP (leg2_ep * 0.985, trailing 0.75% behind min_ltp_l2).
    """
    valid_ticks = _filter_valid_ticks(ticks)
    if not valid_ticks:
        return None
    try:
        ep = float(override_ep) if (override_ep is not None and float(override_ep) > 0) else float(valid_ticks[0]['price'])
    except Exception:
        return None

    entry_time = str(valid_ticks[0]['time']).split()[-1]
    tp_activation_price = round(ep * 0.9800, 2)  # +2.00% profit activation
    pre_tp_lock_price = round(ep * 0.9950, 2)    # +0.50% locked floor once peak >= +1.25%
    initial_trail_floor = round(ep * 0.9825, 2)  # +1.75% initial trailing floor

    min_ltp = ep
    trail_active = False
    breach_count = 0

    leg1_exit_p = None
    leg1_exit_t = None
    leg1_reason = None
    allow_reentry = False
    rebound_trigger = None
    discount_limit_l1 = None

    leg2_entry_p = None
    leg2_entry_t = None
    min_ltp_l2 = None
    trail_active_l2 = False
    leg2_exit_p = None
    leg2_exit_t = None
    leg2_reason = None
    discount_limit_l2 = None

    for t in valid_ticks:
        tm = str(t['time']).split()[-1]
        try:
            p = float(t['price'])
        except Exception:
            continue

        if leg1_exit_p is None:
            # Determine Stage 1 Time-Decay SL tier
            t_int = int(tm.replace(':', '')[:4]) if len(tm) >= 4 else 942
            if t_int < 1100:
                decay_sl_pct = 3.00
            elif t_int < 1230:
                decay_sl_pct = 1.50
            else:
                decay_sl_pct = 1.00
            base_sl = round(ep * (1.0 + decay_sl_pct / 100.0), 2)

            # Track peak profit
            min_ltp = min(min_ltp, p)
            max_profit_pct = ((ep - min_ltp) / ep) * 100.0

            active_sl = base_sl

            # Stage 2: Pre-TP Profit Lock (+1.25% peak -> locks +0.50% profit)
            if max_profit_pct >= 1.25 and not trail_active:
                active_sl = min(active_sl, pre_tp_lock_price)

            # Stage 3: Trailing TP Activation (+2.00%) & Ratchet (+1.75% initial floor, 0.50% trail)
            if not trail_active and p <= tp_activation_price:
                trail_active = True

            if trail_active:
                active_sl = min(initial_trail_floor, round(min_ltp * 1.005, 2))

            is_profit_protection = bool(trail_active or (max_profit_pct >= 1.25 and active_sl == pre_tp_lock_price))

            if p >= active_sl:
                if is_profit_protection:
                    # Immediate execution on Stage 2 Pre-TP Lock or Stage 3 Trailing TP
                    breach_count = 0
                    leg1_exit_p = p
                    leg1_exit_t = tm
                    if trail_active:
                        leg1_reason = 'STAGE3_TRAIL_TP'
                        allow_reentry = True
                        rebound_trigger = round(leg1_exit_p * 1.005, 2)
                        continue
                    else:
                        leg1_reason = 'STAGE2_LOCK_+0.50%'
                        allow_reentry = False
                        break
                else:
                    # Stage 1 Time-Decay SL: 3-Minute Consecutive Breach Check
                    breach_count += 1
                    if breach_count >= 3:
                        leg1_exit_p = p
                        leg1_exit_t = tm
                        leg1_reason = f'STAGE1_SL_{decay_sl_pct:.2f}%_3MIN'
                        allow_reentry = False
                        break
            else:
                breach_count = 0

            # 14:30 Pre-Close Resting Discount Limit (-0.20%) / 14:45 Chaser Exit
            if tm >= '14:30:00':
                if discount_limit_l1 is None:
                    discount_limit_l1 = round(p * 0.998, 2)
                elif p <= discount_limit_l1:
                    leg1_exit_p = discount_limit_l1
                    leg1_exit_t = tm
                    leg1_reason = '14:30_DISCOUNT_EXIT'
                    allow_reentry = False
                    break
            if tm >= '14:45:00':
                leg1_exit_p = p
                leg1_exit_t = tm
                leg1_reason = 'TIME_EXIT_1445'
                allow_reentry = False
                break
        else:
            # Stage 4: Leg 2 Re-Entry (only if Stage 3 Trailing TP exited before 14:30)
            if not allow_reentry:
                break
            if leg2_entry_p is None:
                if tm >= '14:30:00':
                    break
                if rebound_trigger is not None and p >= rebound_trigger:
                    leg2_entry_p = p
                    leg2_entry_t = tm
                    min_ltp_l2 = p
                    trail_active_l2 = False
                    continue
            else:
                min_ltp_l2 = min(min_ltp_l2, p)
                leg2_sl = round(leg2_entry_p * 1.015, 2)          # 1.50% Tight SL
                leg2_tp_act = round(leg2_entry_p * 0.985, 2)      # 1.50% Trailing TP activation

                if not trail_active_l2 and p <= leg2_tp_act:
                    trail_active_l2 = True

                if trail_active_l2:
                    leg2_active_sl = min(leg2_tp_act, round(min_ltp_l2 * 1.0075, 2))
                else:
                    leg2_active_sl = leg2_sl

                if p >= leg2_active_sl:
                    leg2_exit_p = p
                    leg2_exit_t = tm
                    leg2_reason = 'LEG2_TRAIL_TP' if trail_active_l2 else 'LEG2_SL_1.50%'
                    break

                if tm >= '14:30:00':
                    if discount_limit_l2 is None:
                        discount_limit_l2 = round(p * 0.998, 2)
                    elif p <= discount_limit_l2:
                        leg2_exit_p = discount_limit_l2
                        leg2_exit_t = tm
                        leg2_reason = 'LEG2_1430_EXIT'
                        break
                if tm >= '14:45:00':
                    leg2_exit_p = p
                    leg2_exit_t = tm
                    leg2_reason = 'LEG2_TIME_EXIT_1445'
                    break

    if leg1_exit_p is None:
        leg1_exit_p = float(valid_ticks[-1]['price'])
        leg1_exit_t = str(valid_ticks[-1]['time']).split()[-1]
        leg1_reason = 'TIME_EXIT_1445'
    if leg2_entry_p is not None and leg2_exit_p is None:
        leg2_exit_p = float(valid_ticks[-1]['price'])
        leg2_exit_t = str(valid_ticks[-1]['time']).split()[-1]
        leg2_reason = 'LEG2_TIME_EXIT_1445'

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

def reconcile_live_mimic(target_date=None, force_all=False, no_telegram=False, all_pending=False):
    if not os.path.exists(SOURCE_LEDGER_CSV):
        print(f"❌ Error: Source ledger file not found at {SOURCE_LEDGER_CSV}")
        return

    df_source = pd.read_csv(SOURCE_LEDGER_CSV)

    if os.path.exists(MIMIC_LEDGER_CSV):
        df_ledger = pd.read_csv(MIMIC_LEDGER_CSV)
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
        print("✔ No pending trades to reconcile for 09:40 3-Simulation Reconciler.")
        if target_date:
            print(f"   (Trades for {target_date} are already marked COMPLETED)")
        return

    print(f"🔍 [09:40 3-SIMULATION RECONCILER] Reconciling {len(target_indices)} trade(s) across {df_ledger.loc[target_indices, 'date'].nunique()} date(s)...")

    conn = get_db_connection()
    now_ts = datetime.now(ist).strftime('%Y-%m-%d %H:%M:%S')
    reconciled_dates = set()
    completed_count = 0

    obj_cols = [
        'leg2_entry_time', 'leg2_exit_time', 'leg2_exit_reason',
        'entry_time', 'leg1_exit_time', 'leg1_exit_reason',
        's1_exit_time', 's1_exit_reason',
        's2_exit_time', 's2_exit_reason',
        's2_leg1_exit_time', 's2_leg1_exit_reason',
        's2_leg2_entry_time', 's2_leg2_exit_time', 's2_leg2_exit_reason',
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
                # Check if live Kotak filled_price and margin-adjusted quantity exist in shortsell_orders
                cursor.execute(f"""
                    SELECT filled_price, quantity
                    FROM shortsell_orders
                    WHERE trade_date = '{d}' AND stockname = '{s}'
                      AND model_name LIKE '%0942%'
                      AND isvalid NOT IN ('FALSE', 'REJECTED')
                    ORDER BY id DESC LIMIT 1
                """)
                ord_row = cursor.fetchone()
                live_filled_ep = float(ord_row['filled_price']) if (ord_row and ord_row.get('filled_price') and float(ord_row['filled_price']) > 0) else None
                if ord_row and ord_row.get('quantity') and int(ord_row['quantity']) > 0:
                    total_qty = int(ord_row['quantity'])
                    df_ledger.loc[idx, 'total_quantity'] = total_qty

                # Query scrapdata_F1 (Futures) first
                cursor.execute(f"""
                    SELECT time, CAST(price AS DECIMAL(10,2)) as price, CAST(IFNULL(high, price) AS DECIMAL(10,2)) as high, CAST(IFNULL(low, price) AS DECIMAL(10,2)) as low
                    FROM scrapdata_F1
                    WHERE date = '{d}' AND stockname = '{s}'
                      AND TIME(time) >= '09:42:00' AND TIME(time) <= '14:45:00'
                      AND price IS NOT NULL AND price > 0
                      AND (isvalid = 'TRUE' OR isvalid IS NULL OR isvalid = '1' OR isvalid = '')
                      AND (is_future = 'F1' OR is_future IS NULL OR is_future = '')
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

                res_f1 = simulate_sim3_live_4stage_engine(ticks_f1, total_qty, override_ep=live_filled_ep) if ticks_f1 else None
                res_eq = simulate_sim3_live_4stage_engine(ticks_eq, total_qty, override_ep=live_filled_ep) if ticks_eq else None

                if not res_f1 and not res_eq:
                    print(f"⚠️ {d} | {s}: No tick data found in scrapdata or scrapdata_F1. Remains PENDING.")
                    continue

                # Prioritize Cash Equity (scrapdata) since live execution is on NSE EQ
                primary = res_eq if res_eq else res_f1
                ticks_primary = ticks_eq if ticks_eq else ticks_f1

                # Simulation 1: No TP, SL at 2.25% (3-Min Cont. Breach), Exit 14:45
                res_s1 = simulate_sim1_no_tp_3min_sl(ticks_primary, total_qty, override_ep=live_filled_ep)
                # Simulation 2: 2.0% Fixed TP, SL at 2.25% (3-Min Cont. Breach), Re-Entry at +0.50% Bounce
                res_s2 = simulate_sim2_fixed_tp2_reentry_3min_sl(ticks_primary, total_qty, override_ep=live_filled_ep)

                # Update Simulation 3 (Live 4-Stage Dynamic Engine) fields
                df_ledger.loc[idx, 'entry_price'] = primary['entry_price']
                df_ledger.loc[idx, 'entry_time'] = primary['entry_time']
                df_ledger.loc[idx, 'stop_loss_2_25pct'] = round(primary['entry_price'] * 1.0300, 2)
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

                # Update Simulation 1 fields
                if res_s1:
                    df_ledger.loc[idx, 's1_entry_price'] = res_s1['entry_price']
                    df_ledger.loc[idx, 's1_exit_price'] = res_s1['exit_price']
                    df_ledger.loc[idx, 's1_exit_time'] = res_s1['exit_time']
                    df_ledger.loc[idx, 's1_exit_reason'] = res_s1['exit_reason']
                    df_ledger.loc[idx, 's1_gross_pnl'] = res_s1['gross_pnl']
                    df_ledger.loc[idx, 's1_charges'] = res_s1['charges']
                    df_ledger.loc[idx, 's1_net_pnl'] = res_s1['net_pnl']
                    df_ledger.loc[idx, 's1_return_pct'] = res_s1['return_pct']

                # Update Simulation 2 fields
                if res_s2:
                    df_ledger.loc[idx, 's2_entry_price'] = res_s2['entry_price']
                    df_ledger.loc[idx, 's2_exit_price'] = res_s2['exit_price']
                    df_ledger.loc[idx, 's2_exit_time'] = res_s2['exit_time']
                    df_ledger.loc[idx, 's2_exit_reason'] = res_s2['exit_reason']
                    df_ledger.loc[idx, 's2_leg1_exit_price'] = res_s2['leg1_exit_price']
                    df_ledger.loc[idx, 's2_leg1_exit_time'] = res_s2['leg1_exit_time']
                    df_ledger.loc[idx, 's2_leg1_exit_reason'] = res_s2['leg1_exit_reason']
                    df_ledger.loc[idx, 's2_leg1_net_pnl'] = res_s2['leg1_net_pnl']
                    df_ledger.loc[idx, 's2_leg1_return_pct'] = res_s2['leg1_return_pct']
                    df_ledger.loc[idx, 's2_has_leg2'] = res_s2['has_leg2']
                    df_ledger.loc[idx, 's2_leg2_entry_price'] = res_s2['leg2_entry_price']
                    df_ledger.loc[idx, 's2_leg2_entry_time'] = res_s2['leg2_entry_time']
                    df_ledger.loc[idx, 's2_leg2_exit_price'] = res_s2['leg2_exit_price']
                    df_ledger.loc[idx, 's2_leg2_exit_time'] = res_s2['leg2_exit_time']
                    df_ledger.loc[idx, 's2_leg2_exit_reason'] = res_s2['leg2_exit_reason']
                    df_ledger.loc[idx, 's2_leg2_net_pnl'] = res_s2['leg2_net_pnl']
                    df_ledger.loc[idx, 's2_leg2_return_pct'] = res_s2['leg2_return_pct']
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
            print(f"✔ Saved 3-Simulation Ledger: {p}")
        except Exception as e:
            print(f"⚠️ Error saving {p}: {e}")

    for d in sorted(list(reconciled_dates)):
        day_df = df_ledger[(df_ledger['date'] == d) & (df_ledger['status'] == 'COMPLETED')].sort_values('model_rank' if 'model_rank' in df_ledger.columns else 'rank')
        if day_df.empty:
            continue

        # Simulation 1 Totals
        s1_net = day_df['s1_net_pnl'].sum() if 's1_net_pnl' in day_df else 0.0
        s1_gross = day_df['s1_gross_pnl'].sum() if 's1_gross_pnl' in day_df else 0.0
        s1_charges = day_df['s1_charges'].sum() if 's1_charges' in day_df else 0.0
        s1_wins = (day_df['s1_net_pnl'] > 0).sum() if 's1_net_pnl' in day_df else 0
        s1_win_rate = (s1_wins / len(day_df)) * 100.0 if len(day_df) > 0 else 0.0

        # Simulation 2 Totals
        s2_net = day_df['s2_net_pnl'].sum() if 's2_net_pnl' in day_df else 0.0
        s2_gross = day_df['s2_gross_pnl'].sum() if 's2_gross_pnl' in day_df else 0.0
        s2_charges = day_df['s2_charges'].sum() if 's2_charges' in day_df else 0.0
        s2_wins = (day_df['s2_net_pnl'] > 0).sum() if 's2_net_pnl' in day_df else 0
        s2_win_rate = (s2_wins / len(day_df)) * 100.0 if len(day_df) > 0 else 0.0

        # Simulation 3 Totals (Live 4-Stage Dynamic Engine)
        tot_net = day_df['net_pnl'].sum()
        tot_gross = day_df['gross_pnl'].sum()
        tot_charges = day_df['charges'].sum()
        wins = (day_df['net_pnl'] > 0).sum()
        win_rate = (wins / len(day_df)) * 100.0 if len(day_df) > 0 else 0.0

        diff_s3_s1 = tot_net - s1_net
        diff_s3_s2 = tot_net - s2_net
        pnl_color = "🟢" if tot_net >= 0 else "🔴"

        print("\n" + "=" * 130)
        print(f"📊 09:40 MODEL — EVENING 3-SIMULATION RECONCILIATION REPORT: {d}")
        print("=" * 130)

        print("\n🔹 [SIMULATION 1: NO TP | SL AT 2.25% (3-MINUTE CONSECUTIVE BREACH) | EXIT 14:45]")
        print(f"{'#':<3} | {'Stock':<10} | {'Qty':<5} | {'Entry (09:42)':<15} | {'Exit Price':<12} | {'Exit Time':<10} | {'Reason':<18} | {'Net PnL (₹)':<12} | {'Return %':<8}")
        print("-" * 110)
        for i, (_, r) in enumerate(day_df.iterrows()):
            stk = r.get('clean_stock') if pd.notna(r.get('clean_stock')) else r.get('stockname')
            qty = int(r.get('total_quantity', 0))
            ep = f"₹{r.get('s1_entry_price', r.get('entry_price', 0.0)):,.2f}"
            xp = f"₹{r.get('s1_exit_price', 0.0):,.2f}"
            xt = str(r.get('s1_exit_time', '-'))
            xr = str(r.get('s1_exit_reason', '-'))
            npnl = r.get('s1_net_pnl', 0.0)
            ret = r.get('s1_return_pct', 0.0)
            print(f"{i+1:<3} | {stk:<10} | {qty:<5} | {ep:<15} | {xp:<12} | {xt:<10} | {xr:<18} | {npnl:>11,.2f} | {ret:>7.2f}%")
        print("-" * 110)
        print(f"Simulation 1 Total Net: ₹{s1_net:,.2f} | Gross: ₹{s1_gross:,.2f} | Charges: ₹{s1_charges:,.2f} | Win Rate: {s1_win_rate:.1f}%")

        print("\n🔹 [SIMULATION 2: 2.0% FIXED TP | SL AT 2.25% (3-MIN CONT. BREACH) | RE-ENTRY AT +0.50% BOUNCE]")
        print(f"{'#':<3} | {'Stock':<10} | {'Leg 1 In':<17} | {'Leg 1 Out':<17} | {'L1 Reason':<16} | {'Re-Entry In':<15} | {'Leg 2 Out':<15} | {'Total Net (₹)':<12}")
        print("-" * 130)
        for i, (_, r) in enumerate(day_df.iterrows()):
            stk = r.get('clean_stock') if pd.notna(r.get('clean_stock')) else r.get('stockname')
            l1_in = f"₹{r.get('s2_entry_price', r.get('entry_price', 0.0)):,.2f}@{str(r.get('entry_time', '09:42'))[:5]}"
            l1_out = f"₹{r.get('s2_leg1_exit_price', r.get('s2_exit_price', 0.0)):,.2f}@{str(r.get('s2_leg1_exit_time', r.get('s2_exit_time', '')))[:5]}"
            l1_r = str(r.get('s2_leg1_exit_reason', r.get('s2_exit_reason', '-')))[:16]
            if r.get('s2_has_leg2'):
                l2_in = f"₹{r.get('s2_leg2_entry_price', 0.0):,.2f}@{str(r.get('s2_leg2_entry_time', ''))[:5]}"
                l2_out = f"₹{r.get('s2_leg2_exit_price', 0.0):,.2f}@{str(r.get('s2_leg2_exit_time', ''))[:5]}"
            else:
                l2_in = "-"
                l2_out = "-"
            npnl = r.get('s2_net_pnl', 0.0)
            print(f"{i+1:<3} | {stk:<10} | {l1_in:<17} | {l1_out:<17} | {l1_r:<16} | {l2_in:<15} | {l2_out:<15} | {npnl:>11,.2f}")
        print("-" * 130)
        print(f"Simulation 2 Total Net: ₹{s2_net:,.2f} | Gross: ₹{s2_gross:,.2f} | Charges: ₹{s2_charges:,.2f} | Win Rate: {s2_win_rate:.1f}%")

        print("\n🔹 [SIMULATION 3: LIVE 4-STAGE DYNAMIC ENGINE (STAGE-2 @ +1.25% | TRAIL FLOOR @ +1.75% | TIME-DECAY 3-MIN SL)]")
        print(f"{'#':<3} | {'Stock':<10} | {'Leg 1 In':<17} | {'Leg 1 Out':<17} | {'L1 Reason':<22} | {'Re-Entry In':<15} | {'Leg 2 Out':<15} | {'Total Net (₹)':<12}")
        print("-" * 130)
        for i, (_, r) in enumerate(day_df.iterrows()):
            stk = r.get('clean_stock') if pd.notna(r.get('clean_stock')) else r.get('stockname')
            l1_in = f"₹{r.get('entry_price', 0.0):,.2f}@{str(r.get('entry_time', '09:42'))[:5]}"
            l1_out = f"₹{r.get('leg1_exit_price', 0.0):,.2f}@{str(r.get('leg1_exit_time', ''))[:5]}"
            l1_r = str(r.get('leg1_exit_reason', '-'))[:22]
            if r.get('has_leg2'):
                l2_in = f"₹{r.get('leg2_entry_price', 0.0):,.2f}@{str(r.get('leg2_entry_time', ''))[:5]}"
                l2_out = f"₹{r.get('leg2_exit_price', 0.0):,.2f}@{str(r.get('leg2_exit_time', ''))[:5]}"
            else:
                l2_in = "-"
                l2_out = "-"
            t_net = r.get('net_pnl', 0.0)
            print(f"{i+1:<3} | {stk:<10} | {l1_in:<17} | {l1_out:<17} | {l1_r:<22} | {l2_in:<15} | {l2_out:<15} | {t_net:>11,.2f}")
        print("-" * 130)
        print(f"Simulation 3 Total Net: ₹{tot_net:,.2f} | Gross: ₹{tot_gross:,.2f} | Charges: ₹{tot_charges:,.2f} | Win Rate: {win_rate:.1f}%")

        print("\n" + "=" * 80)
        print("🏆 09:40 MODEL — 3-SIMULATION EXECUTIVE COMPARISON SUMMARY")
        print("=" * 80)
        print(f"• SIM 1 (No TP | 2.25% 3-Min SL | Exit 14:45):             ₹{s1_net:+11,.2f} (WR: {s1_win_rate:.1f}%)")
        print(f"• SIM 2 (2.0% TP | 2.25% 3-Min SL | +0.50% Re-Entry):      ₹{s2_net:+11,.2f} (WR: {s2_win_rate:.1f}%)")
        print(f"• SIM 3 (LIVE 4-STAGE ENGINE: 1.25% Lock | 1.75% Floor):   ₹{tot_net:+11,.2f} (WR: {win_rate:.1f}%)")
        print(f"🚀 Live Engine (SIM 3) Alpha vs SIM 1:                      ₹{diff_s3_s1:+11,.2f}")
        print(f"🚀 Live Engine (SIM 3) Alpha vs SIM 2:                      ₹{diff_s3_s2:+11,.2f}")
        print("=" * 80)

        # Telegram Alert Construction with Crystal-Clear Headings
        tg_lines = [
            f"{pnl_color} <b>[09:40 MODEL — EVENING 3-SIMULATION RECONCILIATION REPORT]</b>",
            f"📅 <b>Date:</b> {d} | ⏱️ <b>Audit Time:</b> {now_ts} IST",
            "",
            "━━━━━━━━━━━━━━━━━━━━━",
            "1️⃣ <b>SIMULATION 1: NO TP | SL AT 2.25% (3-MIN CONT. BREACH)</b>",
            "<i>Rules: Entry 09:42 | No TP | 2.25% SL (3 Consecutive Min Breach) | Exit 14:45</i>"
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
            tg_lines.append(
                f"  {icon} <b>#{i+1} {stk}</b> (Qty {qty}): In ₹{ep:,.2f} ➔ Out ₹{xp:,.2f} @ {xt} [{xr}] | Net: <b>₹{npnl:+,.2f}</b> ({ret:+.2f}%)"
            )
        tg_lines.append(f"💰 <b>SIM 1 Total Net PnL:</b> <b>₹{s1_net:+,.2f}</b> (WR: {s1_win_rate:.1f}%)")

        tg_lines.extend([
            "",
            "━━━━━━━━━━━━━━━━━━━━━",
            "2️⃣ <b>SIMULATION 2: 2.0% FIXED TP | 2.25% SL (3-MIN) | +0.50% RE-ENTRY</b>",
            "<i>Rules: Leg 1 (2.0% Fixed TP / 2.25% 3-Min SL / 14:30) ➔ Leg 2 (+0.50% Bounce Re-Entry / 1.75% TP2 / Zero-Risk SL)</i>"
        ])
        for i, (_, r) in enumerate(day_df.iterrows()):
            stk = r.get('clean_stock') if pd.notna(r.get('clean_stock')) else r.get('stockname')
            qty = int(r.get('total_quantity', 0))
            ep = r.get('s2_entry_price', r.get('entry_price', 0.0))
            l1_xp = r.get('s2_leg1_exit_price', r.get('s2_exit_price', 0.0))
            l1_xt = str(r.get('s2_leg1_exit_time', r.get('s2_exit_time', '-')))
            l1_xr = str(r.get('s2_leg1_exit_reason', r.get('s2_exit_reason', '-')))
            l1_net = r.get('s2_leg1_net_pnl', r.get('s2_net_pnl', 0.0))
            l1_ret = r.get('s2_leg1_return_pct', r.get('s2_return_pct', 0.0))
            tot_s2 = r.get('s2_net_pnl', 0.0)
            icon = "✅" if tot_s2 > 0 else "❌"
            if r.get('s2_has_leg2'):
                l2_ep = r.get('s2_leg2_entry_price', 0.0)
                l2_et = str(r.get('s2_leg2_entry_time', '-'))
                l2_xp = r.get('s2_leg2_exit_price', 0.0)
                l2_xt = str(r.get('s2_leg2_exit_time', '-'))
                l2_xr = str(r.get('s2_leg2_exit_reason', '-'))
                l2_net = r.get('s2_leg2_net_pnl', 0.0)
                l2_ret = r.get('s2_leg2_return_pct', 0.0)
                tg_lines.append(f"  {icon} <b>#{i+1} {stk}</b> (Qty {qty}):")
                tg_lines.append(f"      • Leg 1: In ₹{ep:,.2f} ➔ Out ₹{l1_xp:,.2f} @ {l1_xt} [{l1_xr}] | Net: <b>₹{l1_net:+,.2f}</b> ({l1_ret:+.2f}%)")
                tg_lines.append(f"      • 🔄 Leg 2: In ₹{l2_ep:,.2f} @ {l2_et} ➔ Out ₹{l2_xp:,.2f} @ {l2_xt} [{l2_xr}] | Net: <b>₹{l2_net:+,.2f}</b> ({l2_ret:+.2f}%)")
                tg_lines.append(f"      • <b>Total Stock Net:</b> <b>₹{tot_s2:+,.2f}</b>")
            else:
                tg_lines.append(
                    f"  {icon} <b>#{i+1} {stk}</b> (Qty {qty}): In ₹{ep:,.2f} ➔ Out ₹{l1_xp:,.2f} @ {l1_xt} [{l1_xr}] | Net: <b>₹{tot_s2:+,.2f}</b> ({l1_ret:+.2f}%)"
                )
        tg_lines.append(f"💰 <b>SIM 2 Total Net PnL:</b> <b>₹{s2_net:+,.2f}</b> (WR: {s2_win_rate:.1f}%)")

        tg_lines.extend([
            "",
            "━━━━━━━━━━━━━━━━━━━━━",
            "3️⃣ <b>SIMULATION 3: LIVE 4-STAGE DYNAMIC ENGINE (CURRENT LIVE CODE)</b>",
            "<i>Rules: Stage 1 Time-Decay 3-Min SL (3.00% ➔ 1.50% @ 11:00 ➔ 1.00% @ 12:30) | Stage 2 Pre-TP Lock (+1.25% Peak ➔ Locks +0.50%) | Stage 3 Trail TP (2.00% Act ➔ 1.75% Floor & 0.50% Trail) | Stage 4 Re-Entry (+0.50% Bounce)</i>"
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

            if r.get('has_leg2'):
                l2_entry_p = r.get('leg2_entry_price', 0.0)
                l2_entry_t = str(r.get('leg2_entry_time', '-'))
                l2_exit_p = r.get('leg2_exit_price', 0.0)
                l2_exit_t = str(r.get('leg2_exit_time', '-'))
                l2_reason = r.get('leg2_exit_reason', '')
                l2_net = r.get('leg2_net_pnl', 0.0)
                l2_ret = r.get('leg2_return_pct', 0.0)
                tg_lines.append(f"  {t_icon} <b>#{i+1} {stk_name}</b> (Qty {qty}):")
                tg_lines.append(f"      • Leg 1: In ₹{l1_entry_p:,.2f} @ {l1_entry_t} ➔ Out ₹{l1_exit_p:,.2f} @ {l1_exit_t} [{l1_reason}] | Net: <b>₹{l1_net:+,.2f}</b> ({l1_ret:+.2f}%)")
                tg_lines.append(f"      • 🔄 Leg 2: In ₹{l2_entry_p:,.2f} @ {l2_entry_t} ➔ Out ₹{l2_exit_p:,.2f} @ {l2_exit_t} [{l2_reason}] | Net: <b>₹{l2_net:+,.2f}</b> ({l2_ret:+.2f}%)")
                tg_lines.append(f"      • <b>Total Stock Net:</b> <b>₹{tot_n:+,.2f}</b>")
            else:
                tg_lines.append(
                    f"  {t_icon} <b>#{i+1} {stk_name}</b> (Qty {qty}): In ₹{l1_entry_p:,.2f} ➔ Out ₹{l1_exit_p:,.2f} @ {l1_exit_t} [{l1_reason}] | Net: <b>₹{tot_n:+,.2f}</b> ({l1_ret:+.2f}%)"
                )

        tg_lines.extend([
            f"💰 <b>SIM 3 Total Net PnL:</b> <b>₹{tot_net:+,.2f}</b> (WR: {win_rate:.1f}%)",
            "",
            "━━━━━━━━━━━━━━━━━━━━━",
            "🏆 <b>3-SIMULATION EXECUTIVE SUMMARY</b>",
            f"1️⃣ <b>SIM 1 (No TP | 2.25% 3-Min SL):</b> <b>₹{s1_net:+,.2f}</b> | WR: {s1_win_rate:.1f}%",
            f"2️⃣ <b>SIM 2 (2.0% TP | 2.25% SL | +0.5% Re-Entry):</b> <b>₹{s2_net:+,.2f}</b> | WR: {s2_win_rate:.1f}%",
            f"3️⃣ <b>SIM 3 (Live 4-Stage Dynamic Engine):</b> <b>₹{tot_net:+,.2f}</b> | WR: {win_rate:.1f}%",
            f"🚀 <b>Live Engine Alpha vs SIM 1:</b> <b>₹{diff_s3_s1:+,.2f}</b>",
            f"🚀 <b>Live Engine Alpha vs SIM 2:</b> <b>₹{diff_s3_s2:+,.2f}</b>"
        ])

        if not no_telegram:
            send_telegram_alert("\n".join(tg_lines))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="09:40 Model Evening 3-Simulation Reconciler")
    parser.add_argument('--date', type=str, default=None, help="Target Date YYYY-MM-DD (defaults to today or latest pending)")
    parser.add_argument('--force-all', action='store_true', help="Re-reconcile even if already completed")
    parser.add_argument('--all-pending', action='store_true', help="Reconcile all historical pending trades")
    parser.add_argument('--no-telegram', action='store_true', help="Skip sending Telegram alert")
    args = parser.parse_args()

    reconcile_live_mimic(target_date=args.date, force_all=args.force_all, no_telegram=args.no_telegram, all_pending=args.all_pending)
