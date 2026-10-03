#!/usr/bin/env python3
"""
reconcile_0920_scalp_pnl.py
----------------------------
Evening / Post-Trade Reconciler for the 09:20–09:40 Short Sell Scalp Engine.

Workflow:
  1. Reads `daily_0920_live_ledger.csv`.
  2. Finds trades with status 'PENDING' (or for a specific --date).
  3. Queries MySQL `scrapdata` for actual market execution:
       - Entry Price at 09:21:00 AM IST
       - Exit Price at 09:41:00 AM IST (20-min strict hold)
  4. Calculates:
       - Gross PnL = (Entry - Exit) * LotSize
       - Net PnL = Gross PnL - ₹300 (Statutory Charges)
       - Return % = ((Entry - Exit) / Entry) * 100
  5. Updates the master ledger with status 'COMPLETED' and timestamp.
  6. Prints an audited day summary and broadcasts an Evening Telegram Alert.

Usage:
  python3 reconcile_0920_scalp_pnl.py                  # Reconciles all pending records
  python3 reconcile_0920_scalp_pnl.py --date 2026-03-25 # Reconciles specific date
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
PROD_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..'))
LEDGER_CSV = os.path.join(SCRIPT_DIR, 'daily_0920_live_ledger.csv')
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

def reconcile_scalp_trades(target_date=None, force_all=False, no_telegram=False):
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
            s = str(row['stockname']).strip().upper()
            lotsize = int(row['lotsize'])

            # 1. Fetch Futures (scrapdata_F1) Entry & Exit
            cursor.execute(f"""
                SELECT price FROM scrapdata_F1 
                WHERE date = '{d}' AND stockname = '{s}' AND time >= '{d} 09:21:00' 
                ORDER BY time ASC LIMIT 1
            """)
            res_entry_f1 = cursor.fetchone()

            cursor.execute(f"""
                SELECT price FROM scrapdata_F1 
                WHERE date = '{d}' AND stockname = '{s}' AND time >= '{d} 09:41:00' 
                ORDER BY time ASC LIMIT 1
            """)
            res_exit_f1 = cursor.fetchone()

            # 2. Fetch Cash Equity (scrapdata) Entry & Exit
            cursor.execute(f"""
                SELECT price FROM scrapdata 
                WHERE date = '{d}' AND stockname = '{s}' AND time >= '{d} 09:21:00' 
                ORDER BY time ASC LIMIT 1
            """)
            res_entry_eq = cursor.fetchone()

            cursor.execute(f"""
                SELECT price FROM scrapdata 
                WHERE date = '{d}' AND stockname = '{s}' AND time >= '{d} 09:41:00' 
                ORDER BY time ASC LIMIT 1
            """)
            res_exit_eq = cursor.fetchone()

            has_f1 = (res_entry_f1 and res_exit_f1 and res_entry_f1['price'] is not None and res_exit_f1['price'] is not None)
            has_eq = (res_entry_eq and res_exit_eq and res_entry_eq['price'] is not None and res_exit_eq['price'] is not None)

            if not has_f1 and not has_eq:
                print(f"⚠️ {d} | {s}: Incomplete market data in both scrapdata and scrapdata_F1. Remains PENDING.")
                continue

            # Calculate Futures metrics
            if has_f1:
                p_entry_f1 = float(res_entry_f1['price'])
                p_exit_f1 = float(res_exit_f1['price'])
                gross_f1 = (p_entry_f1 - p_exit_f1) * lotsize
                net_f1 = gross_f1 - get_taxes(lotsize, p_entry_f1, p_exit_f1)
                ret_pct_f1 = ((p_entry_f1 - p_exit_f1) / p_entry_f1) * 100.0

                df_ledger.at[idx, 'f1_entry_price'] = round(p_entry_f1, 2)
                df_ledger.at[idx, 'f1_exit_price'] = round(p_exit_f1, 2)
                df_ledger.at[idx, 'f1_gross_pnl'] = round(gross_f1, 2)
                df_ledger.at[idx, 'f1_net_pnl'] = round(net_f1, 2)
                df_ledger.at[idx, 'f1_return_pct'] = round(ret_pct_f1, 2)
            else:
                p_entry_f1, p_exit_f1, gross_f1, net_f1, ret_pct_f1 = None, None, None, None, None

            # Calculate Cash Equity metrics
            if has_eq:
                p_entry_eq = float(res_entry_eq['price'])
                p_exit_eq = float(res_exit_eq['price'])
                gross_eq = (p_entry_eq - p_exit_eq) * lotsize
                net_eq = gross_eq - get_taxes(lotsize, p_entry_eq, p_exit_eq)
                ret_pct_eq = ((p_entry_eq - p_exit_eq) / p_entry_eq) * 100.0

                df_ledger.at[idx, 'eq_entry_price'] = round(p_entry_eq, 2)
                df_ledger.at[idx, 'eq_exit_price'] = round(p_exit_eq, 2)
                df_ledger.at[idx, 'eq_gross_pnl'] = round(gross_eq, 2)
                df_ledger.at[idx, 'eq_net_pnl'] = round(net_eq, 2)
                df_ledger.at[idx, 'eq_return_pct'] = round(ret_pct_eq, 2)
            else:
                p_entry_eq, p_exit_eq, gross_eq, net_eq, ret_pct_eq = None, None, None, None, None

            # Primary ledger fields (prioritize Futures if available, otherwise Equity)
            primary_ep = p_entry_f1 if has_f1 else p_entry_eq
            primary_xp = p_exit_f1 if has_f1 else p_exit_eq
            primary_gross = gross_f1 if has_f1 else gross_eq
            primary_net = net_f1 if has_f1 else net_eq
            primary_ret = ret_pct_f1 if has_f1 else ret_pct_eq

            df_ledger.at[idx, 'entry_price'] = round(primary_ep, 2)
            df_ledger.at[idx, 'exit_price'] = round(primary_xp, 2)
            df_ledger.at[idx, 'gross_pnl'] = round(primary_gross, 2)
            df_ledger.at[idx, 'charges'] = 300.0
            df_ledger.at[idx, 'net_pnl'] = round(primary_net, 2)
            df_ledger.at[idx, 'return_pct'] = round(primary_ret, 2)
            df_ledger.at[idx, 'status'] = 'COMPLETED'
            df_ledger.at[idx, 'reconciled_at'] = now_ts

            reconciled_dates.add(d)
            completed_count += 1

    conn.close()

    # Save updated ledger
    df_ledger.to_csv(LEDGER_CSV, index=False)
    print(f"\n✔ Successfully reconciled {completed_count} trade(s). Ledger updated: {LEDGER_CSV}")

    # Generate Reports & Telegram Alerts for each reconciled date
    for d in sorted(list(reconciled_dates)):
        day_df = df_ledger[(df_ledger['date'] == d) & (df_ledger['status'] == 'COMPLETED')].sort_values('rank')
        if day_df.empty:
            continue

        day_gross_f1 = day_df['f1_gross_pnl'].dropna().sum() if 'f1_gross_pnl' in day_df else day_df['gross_pnl'].sum()
        day_net_f1 = day_df['f1_net_pnl'].dropna().sum() if 'f1_net_pnl' in day_df else day_df['net_pnl'].sum()
        day_net_eq = day_df['eq_net_pnl'].dropna().sum() if 'eq_net_pnl' in day_df else 0.0

        wins_f1 = (day_df['net_pnl'] > 0).sum()
        losses_f1 = (day_df['net_pnl'] <= 0).sum()
        win_rate_f1 = (wins_f1 / len(day_df)) * 100.0 if len(day_df) > 0 else 0.0

        pnl_color = "🟢" if day_net_f1 >= 0 else "🔴"

        print("\n" + "=" * 100)
        print(f"📊 09:20 SCALP RECONCILED PNL REPORT: {d} (FUTURES & CASH EQUITY)")
        print("=" * 100)
        print(f"{'#':<3} | {'Stock':<10} | {'F1 Net (₹)':<12} | {'F1 Ret %':<9} | {'EQ Net (₹)':<12} | {'EQ Ret %':<9}")
        print("-" * 100)
        for _, r in day_df.iterrows():
            stk = r['stockname']
            f1_n = r.get('f1_net_pnl', r.get('net_pnl', 0.0))
            f1_r = r.get('f1_return_pct', r.get('return_pct', 0.0))
            eq_n = r.get('eq_net_pnl', 0.0)
            eq_r = r.get('eq_return_pct', 0.0)
            print(f"{int(r['rank']):<3} | {stk:<10} | {f1_n:>10,.2f}   | {f1_r:>7.2f}%  | {eq_n:>10,.2f}   | {eq_r:>7.2f}%")
        print("-" * 100)
        print(f"SUMMARY: Futures Net PnL = ₹{day_net_f1:,.2f} | Equity Net PnL = ₹{day_net_eq:,.2f} | Win Rate: {win_rate_f1:.1f}%")
        print("=" * 100)

        # Telegram Message
        tg_lines = [
            f"{pnl_color} <b>[09:20 SCALP: DUAL RECONCILED PNL REPORT]</b>",
            f"📅 <b>Date:</b> {d} | ⏱️ <b>Audit Time:</b> {now_ts} IST",
            f"🎯 <b>Holding Window:</b> 09:21 AM ➔ 09:41 AM (Strict 20-Min Scalp)",
            "",
            "<b>📋 EXECUTED TRADES (FUTURES vs CASH EQUITY):</b>"
        ]
        for _, r in day_df.iterrows():
            t_icon = "✅" if r['net_pnl'] > 0 else "❌"
            f1_n = r.get('f1_net_pnl', r.get('net_pnl', 0.0))
            f1_r = r.get('f1_return_pct', r.get('return_pct', 0.0))
            eq_n = r.get('eq_net_pnl', 0.0)
            eq_r = r.get('eq_return_pct', 0.0)
            tg_lines.append(
                f"  {t_icon} <b>#{int(r['rank'])} {r['stockname']}</b> (Lot {int(r['lotsize'])}):"
                f"\n      • <b>F1:</b> Net <b>₹{f1_n:+,.2f}</b> ({f1_r:+.2f}%)"
                f"\n      • <b>EQ:</b> Net <b>₹{eq_n:+,.2f}</b> ({eq_r:+.2f}%)"
            )
        tg_lines.extend([
            "",
            f"⚡ <b>Statutory Charges:</b> -₹{len(day_df)*300:,.2f} (₹300/trade)",
            f"🏆 <b>TOTAL FUTURES NET PNL:</b> <b>₹{day_net_f1:+,.2f}</b> ({win_rate_f1:.1f}% Win Rate)",
            f"📊 <b>TOTAL EQUITY NET PNL:</b> <b>₹{day_net_eq:+,.2f}</b>"
        ])
        if not no_telegram:
            send_telegram_alert("\n".join(tg_lines))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="09:20 - 09:40 Scalp Engine Evening Reconciler")
    parser.add_argument('--date', type=str, default=None, help="Target Date YYYY-MM-DD (defaults to all PENDING)")
    parser.add_argument('--force-all', action='store_true', help="Re-reconcile even if already completed")
    parser.add_argument('--no-telegram', action='store_true', help="Skip sending Telegram alert")
    args = parser.parse_args()

    reconcile_scalp_trades(target_date=args.date, force_all=args.force_all, no_telegram=args.no_telegram)
