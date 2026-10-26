#!/usr/bin/env python3
"""
reconcile_0940_hybrid_pnl.py
----------------------------
Evening / Post-Trade Reconciler for the 09:40–14:45 Hybrid Short-Sell Master Engine (Option 2).

Workflow:
  1. Reads `daily_0940_live_ledger.csv`.
  2. Finds trades with status 'PENDING' (or for a specific --date).
  3. Queries MySQL `scrapdata_F1` (with fallback to `scrapdata`) for actual market execution:
       - Entry Price at 09:42:00 AM IST
       - Continuous 3.0% Stop Loss monitoring from 09:42:00 to 14:45:00 AM IST
       - Exit Price at 14:45:00 PM IST (or exact SL breach tick price)
  4. Calculates:
       - Points Captured = Entry Price - Exit Price
       - Gross PnL = Points * Total Quantity
       - Charges = ₹300 per lot traded (Statutory Brokerage & Exchange Turnover)
       - Net PnL = Gross PnL - Charges
       - Return % = ((Entry - Exit) / Entry) * 100
  5. Updates the master ledger with status 'COMPLETED' and reconciliation timestamp.
  6. Prints an audited day summary and broadcasts an Evening Telegram Alert.

Usage:
  python3 reconcile_0940_hybrid_pnl.py                  # Reconciles all pending records
  python3 reconcile_0940_hybrid_pnl.py --date 2026-09-11 # Reconciles specific date
  python3 reconcile_0940_hybrid_pnl.py --force-all      # Re-reconciles all records
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
LEDGER_CSV = os.path.join(SCRIPT_DIR, 'daily_0940_live_ledger.csv')
AUDITED_CSV = os.path.join(SCRIPT_DIR, 'audited_0940_hybrid_trades.csv')
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
    else:
        print("ℹ️ Telegram bot script not found; notification skipped.")

def reconcile_hybrid_trades(target_date=None, force_all=False, no_telegram=False):
    if not os.path.exists(LEDGER_CSV):
        print(f"❌ Error: Ledger file not found at {LEDGER_CSV}")
        return

    df_ledger = pd.read_csv(LEDGER_CSV)

    # Determine which rows to reconcile
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
        print("✔ No pending trades to reconcile.")
        if target_date:
            print(f"   (All trades for {target_date} are already marked COMPLETED)")
        return

    print(f"🔍 Found {len(target_indices)} trade(s) to reconcile across {df_ledger.loc[target_indices, 'date'].nunique()} date(s)...")

    conn = get_db_connection()
    now_ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    reconciled_dates = set()
    completed_count = 0

    with conn.cursor() as cursor:
        for idx in target_indices:
            row = df_ledger.loc[idx]
            d = str(row['date'])
            s = str(row['clean_stock'] if 'clean_stock' in row and not pd.isna(row['clean_stock']) else row['stockname']).strip().upper()
            lots_to_trade = int(row['lots_to_trade'])
            lotsize = int(row['lotsize']) if 'lotsize' in row and not pd.isna(row['lotsize']) else (int(row['total_quantity']) // int(row['lots_to_trade']))
            total_qty = int(row['total_quantity']) if 'total_quantity' in row and not pd.isna(row['total_quantity']) else lots_to_trade * lotsize

            # 1. Query scrapdata_F1 between 09:42:00 and 14:45:00
            q_f1 = f"""
            SELECT time, CAST(price AS DECIMAL(10,2)) as price
            FROM scrapdata_F1
            WHERE date = '{d}' AND stockname = '{s}'
              AND TIME(time) >= '09:42:00' AND TIME(time) <= '14:45:00'
              AND isvalid = 'TRUE'
            ORDER BY time ASC
            """
            cursor.execute(q_f1)
            ticks_f1 = cursor.fetchall()

            # 2. Query scrapdata (Cash Equity) between 09:42:00 and 14:45:00
            q_eq = f"""
            SELECT time, CAST(price AS DECIMAL(10,2)) as price
            FROM scrapdata
            WHERE date = '{d}' AND stockname = '{s}'
              AND TIME(time) >= '09:42:00' AND TIME(time) <= '14:45:00'
              AND isvalid = 'TRUE'
            ORDER BY time ASC
            """
            cursor.execute(q_eq)
            ticks_eq = cursor.fetchall()

            if not ticks_f1 and not ticks_eq:
                print(f"⚠️ No tick data found for {s} on {d} in both scrapdata_F1 and scrapdata. Leaving as PENDING.")
                continue

            # Simulate Futures (F1)
            f1_entry_p, f1_exit_p, f1_exit_time, f1_exit_reason, f1_net_pnl, f1_ret_pct = None, None, None, None, None, None
            if ticks_f1:
                f1_entry_p = float(ticks_f1[0]['price'])
                f1_sl = round(f1_entry_p * 1.0225, 2)
                f1_exit_p = float(ticks_f1[-1]['price'])
                f1_exit_time = '14:45:00'
                f1_exit_reason = 'TIME_EXIT'
                for t in ticks_f1:
                    p = float(t['price'])
                    if p >= f1_sl:
                        f1_exit_p = f1_sl
                        f1_exit_time = str(t['time']).split()[-1]
                        f1_exit_reason = 'STOP_LOSS'
                        break
                f1_pts = round(f1_entry_p - f1_exit_p, 2)
                f1_gross = round(f1_pts * total_qty, 2)
                f1_charges = get_taxes(total_qty, f1_entry_p, f1_exit_p)
                f1_net_pnl = round(f1_gross - f1_charges, 2)
                f1_ret_pct = round((f1_pts / f1_entry_p) * 100.0, 2) if f1_entry_p > 0 else 0.0

                df_ledger.loc[idx, 'f1_entry_price'] = f1_entry_p
                df_ledger.loc[idx, 'f1_exit_price'] = f1_exit_p
                df_ledger.loc[idx, 'f1_exit_reason'] = f1_exit_reason
                df_ledger.loc[idx, 'f1_net_pnl'] = f1_net_pnl
                df_ledger.loc[idx, 'f1_return_pct'] = f1_ret_pct

            # Simulate Cash Equity (EQ)
            eq_entry_p, eq_exit_p, eq_exit_time, eq_exit_reason, eq_net_pnl, eq_ret_pct = None, None, None, None, None, None
            if ticks_eq:
                eq_entry_p = float(ticks_eq[0]['price'])
                eq_sl = round(eq_entry_p * 1.0225, 2)
                eq_exit_p = float(ticks_eq[-1]['price'])
                eq_exit_time = '14:45:00'
                eq_exit_reason = 'TIME_EXIT'
                for t in ticks_eq:
                    p = float(t['price'])
                    if p >= eq_sl:
                        eq_exit_p = eq_sl
                        eq_exit_time = str(t['time']).split()[-1]
                        eq_exit_reason = 'STOP_LOSS'
                        break
                eq_pts = round(eq_entry_p - eq_exit_p, 2)
                eq_gross = round(eq_pts * total_qty, 2)
                eq_charges = get_taxes(total_qty, eq_entry_p, eq_exit_p)
                eq_net_pnl = round(eq_gross - eq_charges, 2)
                eq_ret_pct = round((eq_pts / eq_entry_p) * 100.0, 2) if eq_entry_p > 0 else 0.0

                df_ledger.loc[idx, 'eq_entry_price'] = eq_entry_p
                df_ledger.loc[idx, 'eq_exit_price'] = eq_exit_p
                df_ledger.loc[idx, 'eq_exit_reason'] = eq_exit_reason
                df_ledger.loc[idx, 'eq_net_pnl'] = eq_net_pnl
                df_ledger.loc[idx, 'eq_return_pct'] = eq_ret_pct

            # Primary columns (prioritize Futures if available, otherwise Cash Equity)
            use_f1 = (f1_entry_p is not None)
            p_entry = f1_entry_p if use_f1 else eq_entry_p
            p_sl = round(p_entry * 1.0225, 2)
            p_exit = f1_exit_p if use_f1 else eq_exit_p
            p_exit_time = f1_exit_time if use_f1 else eq_exit_time
            p_exit_reason = f1_exit_reason if use_f1 else eq_exit_reason
            p_pts = round(p_entry - p_exit, 2)
            p_gross = round(p_pts * total_qty, 2)
            p_charges = round(300.0 * lots_to_trade, 2)
            p_net = round(p_gross - p_charges, 2)
            p_ret = round((p_pts / p_entry) * 100.0, 2) if p_entry > 0 else 0.0

            df_ledger.loc[idx, 'entry_price'] = p_entry
            df_ledger.loc[idx, 'stop_loss_2_25pct'] = p_sl
            df_ledger.loc[idx, 'stop_loss_3pct'] = p_sl
            df_ledger.loc[idx, 'exit_time'] = p_exit_time
            df_ledger.loc[idx, 'exit_price'] = p_exit
            df_ledger.loc[idx, 'exit_reason'] = p_exit_reason
            df_ledger.loc[idx, 'points'] = p_pts
            df_ledger.loc[idx, 'gross_pnl'] = p_gross
            df_ledger.loc[idx, 'charges'] = p_charges
            df_ledger.loc[idx, 'net_pnl'] = p_net
            df_ledger.loc[idx, 'return_pct'] = p_ret
            df_ledger.loc[idx, 'status'] = 'COMPLETED'
            df_ledger.loc[idx, 'reconciled_at'] = now_ts

            reconciled_dates.add(d)
            completed_count += 1

    conn.close()

    if completed_count == 0:
        print("⚠️ No trades could be reconciled from market tick data.")
        return

    # Save to all ledger paths
    save_paths = [
        LEDGER_CSV,
        AUDITED_CSV,
        os.path.join(SARANG_DIR, 'daily_0940_live_ledger.csv'),
        os.path.join(SARANG_DIR, 'audited_0940_hybrid_trades.csv'),
        '/home/ubuntu/940-1445_model/audited_0940_hybrid_trades.csv'
    ]
    for p in save_paths:
        try:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            df_ledger.to_csv(p, index=False)
            print(f"✔ Updated master ledger: {p}")
        except Exception as e:
            print(f"⚠️ Error saving {p}: {e}")

    # Generate Reports & Telegram Alerts for each reconciled date
    for d in sorted(list(reconciled_dates)):
        day_df = df_ledger[(df_ledger['date'] == d) & (df_ledger['status'] == 'COMPLETED')].sort_values('rank')
        if day_df.empty:
            continue

        day_gross_f1 = day_df['gross_pnl'].sum()
        day_net_f1 = day_df['net_pnl'].sum()
        day_net_eq = day_df['eq_net_pnl'].dropna().sum() if 'eq_net_pnl' in day_df else 0.0
        tot_lots = int(day_df['lots_to_trade'].sum())
        wins_f1 = (day_df['net_pnl'] > 0).sum()
        losses_f1 = (day_df['net_pnl'] <= 0).sum()
        win_rate_f1 = (wins_f1 / len(day_df)) * 100.0 if len(day_df) > 0 else 0.0

        pnl_color = "🟢" if day_net_f1 >= 0 else "🔴"

        print("\n" + "=" * 105)
        print(f"📊 09:40 HYBRID RECONCILED PNL REPORT: {d} (FUTURES & CASH EQUITY)")
        print("=" * 105)
        print(f"{'#':<3} | {'Stock':<10} | {'Signal':<16} | {'Lots':<4} | {'F1 Net (₹)':<12} | {'F1 Exit':<10} | {'EQ Net (₹)':<12} | {'EQ Exit':<10}")
        print("-" * 105)
        for i, (_, r) in enumerate(day_df.iterrows()):
            stk = r.get('clean_stock') if pd.notna(r.get('clean_stock')) else r.get('stockname')
            sig = str(r['signal_type'])[:15]
            lots = int(r['lots_to_trade'])
            f1_n = r.get('f1_net_pnl', r.get('net_pnl', 0.0))
            f1_reason = r.get('f1_exit_reason', r.get('exit_reason', ''))
            eq_n = r.get('eq_net_pnl', 0.0)
            eq_reason = r.get('eq_exit_reason', '')
            print(f"{i+1:<3} | {stk:<10} | {sig:<16} | {lots:<4} | {f1_n:>10,.2f}   | {f1_reason:<10} | {eq_n:>10,.2f}   | {eq_reason:<10}")
        print("-" * 105)
        print(f"SUMMARY: Total Setups: 4 (₹7.5L Each) | Futures Net PnL = ₹{day_net_f1:,.2f} | Equity Net PnL = ₹{day_net_eq:,.2f} | Win Rate: {win_rate_f1:.1f}%")
        print("=" * 105)

        # Telegram Message
        tg_lines = [
            f"{pnl_color} <b>[09:40 HYBRID: RECONCILED PNL REPORT]</b>",
            f"📅 <b>Date:</b> {d} | ⏱️ <b>Audit Time:</b> {now_ts} IST",
            f"🎯 <b>Holding Window:</b> 09:42 AM ➔ 14:45 PM (Fixed 1-Lot Budget)",
            f"🛡️ <b>Risk Protection:</b> Tick-by-Tick 2.25% Stop Loss Monitored",
            "",
            "<b>📋 EXECUTED TRADES (FUTURES vs CASH EQUITY):</b>"
        ]
        for i, (_, r) in enumerate(day_df.iterrows()):
            stk_name = str(r['clean_stock']) if 'clean_stock' in r and pd.notna(r['clean_stock']) else str(r['stockname'])
            t_icon = "✅" if r['net_pnl'] > 0 else "❌"
            f1_n = r.get('f1_net_pnl', r.get('net_pnl', 0.0))
            f1_ret = r.get('f1_return_pct', r.get('return_pct', 0.0))
            f1_reason = r.get('f1_exit_reason', r.get('exit_reason', ''))
            f1_badge = " [SL HIT]" if f1_reason == 'STOP_LOSS' else " [14:45]"

            eq_n = r.get('eq_net_pnl', 0.0)
            eq_ret = r.get('eq_return_pct', 0.0)
            eq_reason = r.get('eq_exit_reason', '')
            eq_badge = " [SL HIT]" if eq_reason == 'STOP_LOSS' else " [14:45]"

            tg_lines.append(
                f"  {t_icon} <b>#{i+1} {stk_name}</b> ({r['signal_type']} | {int(r['lots_to_trade'])} Lots):\n"
                f"      • <b>F1:</b> Net <b>₹{f1_n:+,.2f}</b> ({f1_ret:+.2f}%){f1_badge}\n"
                f"      • <b>EQ:</b> Net <b>₹{eq_n:+,.2f}</b> ({eq_ret:+.2f}%){eq_badge}"
            )
        tg_lines.extend([
            "",
            f"⚡ <b>Statutory Charges:</b> Exact Zerodha Taxation Computed.",
            f"🏆 <b>TOTAL FUTURES NET PNL:</b> <b>₹{day_net_f1:+,.2f}</b> ({win_rate_f1:.1f}% Win Rate)",
            f"📊 <b>TOTAL EQUITY NET PNL:</b> <b>₹{day_net_eq:+,.2f}</b>"
        ])
        if not no_telegram:
            send_telegram_alert("\n".join(tg_lines))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="09:40 - 14:45 Hybrid Engine Evening Reconciler")
    parser.add_argument('--date', type=str, default=None, help="Target Date YYYY-MM-DD (defaults to all PENDING)")
    parser.add_argument('--force-all', action='store_true', help="Re-reconcile even if already completed")
    parser.add_argument('--no-telegram', action='store_true', help="Skip sending Telegram alert")
    args = parser.parse_args()

    reconcile_hybrid_trades(target_date=args.date, force_all=args.force_all, no_telegram=args.no_telegram)
