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
from datetime import datetime
import numpy as np
import pandas as pd
import pymysql

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SOURCE_LEDGER_CSV = os.path.join(SCRIPT_DIR, 'daily_0940_live_ledger.csv')
MIMIC_LEDGER_CSV = os.path.join(SCRIPT_DIR, 'daily_0940_live_mimic_ledger.csv')
AUDITED_MIMIC_CSV = os.path.join(SCRIPT_DIR, 'audited_0940_live_mimic_trades.csv')
SARANG_DIR = '/home/ubuntu/sarang_2026_shortsell_algos/02_Best_Longer_Window_0942_1445'
BOT_SCRIPT = '/home/ubuntu/KotakCodes1/status_Info_bot.js'

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
    if os.path.exists(BOT_SCRIPT):
        try:
            res = subprocess.run(['node', BOT_SCRIPT, msg], capture_output=True, text=True, timeout=20)
            print(f"[Telegram Bot Response]: {res.stdout.strip()[:100]}")
        except Exception as e:
            print(f"⚠️ Telegram notification error: {e}")
        try:
            from KotakCodes1.sl_near_alert_monitor import TELEGRAM_BOT_TOKEN, TELEGRAM_CRITICAL_CHAT_ID
            import urllib.request, urllib.parse, json
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            data = urllib.parse.urlencode({'chat_id': TELEGRAM_CRITICAL_CHAT_ID, 'text': msg, 'parse_mode': 'HTML'}).encode('utf-8')
            req = urllib.request.Request(url, data=data)
            urllib.request.urlopen(req, timeout=10)
        except Exception:
            pass
    else:
        print("ℹ️ Telegram bot script not found; notification skipped.")

def simulate_trade_live_mimic(ticks, total_qty):
    """
    Simulates a stock's tick-by-tick trajectory mirroring KotakCodes1 live engine.
    """
    if not ticks:
        return None

    ep = float(ticks[0]['price'])
    entry_time = str(ticks[0]['time']).split()[-1]
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

    for t in ticks:
        tm = str(t['time']).split()[-1]
        p = float(t['price'])
        l = float(t.get('low', p))
        h = float(t.get('high', p))

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
        leg1_exit_p = float(ticks[-1]['price'])
        leg1_exit_t = str(ticks[-1]['time']).split()[-1]
        leg1_reason = 'TIME_EXIT_1445'

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

def reconcile_live_mimic(target_date=None, force_all=False, no_telegram=False):
    if not os.path.exists(SOURCE_LEDGER_CSV):
        print(f"❌ Error: Source ledger file not found at {SOURCE_LEDGER_CSV}")
        return

    # Load existing mimic ledger if present, otherwise initialize from source ledger
    if os.path.exists(MIMIC_LEDGER_CSV) and not force_all:
        df_ledger = pd.read_csv(MIMIC_LEDGER_CSV)
    else:
        df_ledger = pd.read_csv(SOURCE_LEDGER_CSV).copy()
        df_ledger['status'] = 'PENDING'

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
    now_ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    reconciled_dates = set()
    completed_count = 0

    with conn.cursor() as cursor:
        for idx in target_indices:
            row = df_ledger.loc[idx]
            d = str(row['date'])
            s = str(row['clean_stock'] if 'clean_stock' in row and not pd.isna(row['clean_stock']) else row['stockname']).strip().upper()
            lots_to_trade = int(row['lots_to_trade']) if 'lots_to_trade' in row and not pd.isna(row['lots_to_trade']) else 1
            lotsize = int(row['lotsize']) if 'lotsize' in row and not pd.isna(row['lotsize']) else (int(row['total_quantity']) // lots_to_trade if 'total_quantity' in row and pd.notna(row['total_quantity']) else 100)
            total_qty = int(row['total_quantity']) if 'total_quantity' in row and not pd.isna(row['total_quantity']) else lots_to_trade * lotsize

            # Query scrapdata_F1 (Futures) first
            cursor.execute(f"""
                SELECT time, CAST(price AS DECIMAL(10,2)) as price, CAST(IFNULL(high, price) AS DECIMAL(10,2)) as high, CAST(IFNULL(low, price) AS DECIMAL(10,2)) as low
                FROM scrapdata_F1
                WHERE date = '{d}' AND stockname = '{s}'
                  AND TIME(time) >= '09:42:00' AND TIME(time) <= '14:45:00'
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

            # Update fields in dataframe
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

        tot_net = day_df['net_pnl'].sum()
        tot_gross = day_df['gross_pnl'].sum()
        tot_charges = day_df['charges'].sum()
        wins = (day_df['net_pnl'] > 0).sum()
        win_rate = (wins / len(day_df)) * 100.0 if len(day_df) > 0 else 0.0
        pnl_color = "🟢" if tot_net >= 0 else "🔴"

        print("\n" + "=" * 110)
        print(f"📊 09:42 LIVE MIMIC RECONCILED PNL REPORT: {d} (2.0% TP + 0.5% REBOUND + 1.75% TP2 + 2.25% SL)")
        print("=" * 110)
        print(f"{'#':<3} | {'Stock':<10} | {'Leg 1 Exit':<20} | {'Leg 1 (₹)':<11} | {'Leg 2':<7} | {'Leg 2 Exit':<20} | {'Total Net (₹)':<12}")
        print("-" * 110)
        for i, (_, r) in enumerate(day_df.iterrows()):
            stk = r.get('clean_stock') if pd.notna(r.get('clean_stock')) else r.get('stockname')
            l1_r = str(r.get('leg1_exit_reason', ''))[:19]
            l1_n = r.get('leg1_net_pnl', 0.0)
            h_l2 = "YES" if r.get('has_leg2') else "NO"
            l2_r = str(r.get('leg2_exit_reason', '-'))[:19] if r.get('has_leg2') else "-"
            t_net = r.get('net_pnl', 0.0)
            print(f"{i+1:<3} | {stk:<10} | {l1_r:<20} | {l1_n:>10,.2f}  | {h_l2:<7} | {l2_r:<20} | {t_net:>11,.2f}")
        print("-" * 110)
        print(f"SUMMARY: Total Net PnL = ₹{tot_net:,.2f} | Gross = ₹{tot_gross:,.2f} | Charges = ₹{tot_charges:,.2f} | Win Rate: {win_rate:.1f}%")
        print("=" * 110)

        # Telegram Alert
        tg_lines = [
            f"{pnl_color} <b>[09:42 LIVE MIMIC: RECONCILED PNL REPORT]</b>",
            f"📅 <b>Date:</b> {d} | ⏱️ <b>Audit Time:</b> {now_ts} IST",
            f"🎯 <b>Model:</b> 09:42 Live Rebound Engine (Exact Broker Logic)",
            f"🛡️ <b>Rules:</b> 2.0% TP ➔ +0.50% Rebound Re-entry ➔ 1.75% TP2 | 2.25% SL / Zero Risk SL2 | 14:30 Exit",
            "",
            "<b>📋 EXECUTED TRADES (LEG 1 & LEG 2 BREAKDOWN):</b>"
        ]

        for i, (_, r) in enumerate(day_df.iterrows()):
            stk_name = str(r['clean_stock']) if 'clean_stock' in r and pd.notna(r['clean_stock']) else str(r['stockname'])
            t_icon = "✅" if r['net_pnl'] > 0 else "❌"
            l1_reason = r.get('leg1_exit_reason', '')
            l1_net = r.get('leg1_net_pnl', 0.0)
            l1_ret = r.get('leg1_return_pct', 0.0)
            tot_n = r.get('net_pnl', 0.0)

            tg_lines.append(
                f"  {t_icon} <b>#{i+1} {stk_name}</b> (Qty {int(r['total_quantity'])}):\n"
                f"      • <b>Leg 1:</b> Net <b>₹{l1_net:+,.2f}</b> ({l1_ret:+.2f}%) [{l1_reason}]"
            )
            if r.get('has_leg2'):
                l2_reason = r.get('leg2_exit_reason', '')
                l2_net = r.get('leg2_net_pnl', 0.0)
                l2_ret = r.get('leg2_return_pct', 0.0)
                tg_lines.append(
                    f"      • <b>Leg 2:</b> Net <b>₹{l2_net:+,.2f}</b> ({l2_ret:+.2f}%) [{l2_reason}]\n"
                    f"      • <b>Stock Total:</b> <b>₹{tot_n:+,.2f}</b>"
                )
            else:
                tg_lines.append(f"      • <b>Stock Total:</b> <b>₹{tot_n:+,.2f}</b>")

        tg_lines.extend([
            "",
            f"⚡ <b>Statutory Zerodha Taxes:</b> -₹{tot_charges:,.2f}",
            f"🏆 <b>TOTAL NET PNL:</b> <b>₹{tot_net:+,.2f}</b> ({win_rate:.1f}% Win Rate)"
        ])

        if not no_telegram:
            send_telegram_alert("\n".join(tg_lines))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="09:42 Live Mimic Engine Evening Reconciler")
    parser.add_argument('--date', type=str, default=None, help="Target Date YYYY-MM-DD (defaults to all PENDING)")
    parser.add_argument('--force-all', action='store_true', help="Re-reconcile even if already completed")
    parser.add_argument('--no-telegram', action='store_true', help="Skip sending Telegram alert")
    args = parser.parse_args()

    reconcile_live_mimic(target_date=args.date, force_all=args.force_all, no_telegram=args.no_telegram)
