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

            # 1. Fetch Entry at 09:21:00
            cursor.execute(f"""
                SELECT price FROM scrapdata 
                WHERE date = '{d}' AND stockname = '{s}' AND time >= '{d} 09:21:00' 
                ORDER BY time ASC LIMIT 1
            """)
            res_entry = cursor.fetchone()

            # 2. Fetch Exit at 09:41:00
            cursor.execute(f"""
                SELECT price FROM scrapdata 
                WHERE date = '{d}' AND stockname = '{s}' AND time >= '{d} 09:41:00' 
                ORDER BY time ASC LIMIT 1
            """)
            res_exit = cursor.fetchone()

            if res_entry and res_exit and res_entry['price'] is not None and res_exit['price'] is not None:
                p_entry = float(res_entry['price'])
                p_exit = float(res_exit['price'])
                gross = (p_entry - p_exit) * lotsize
                net = gross - 300.0
                ret_pct = ((p_entry - p_exit) / p_entry) * 100.0

                df_ledger.at[idx, 'entry_price'] = round(p_entry, 2)
                df_ledger.at[idx, 'exit_price'] = round(p_exit, 2)
                df_ledger.at[idx, 'gross_pnl'] = round(gross, 2)
                df_ledger.at[idx, 'charges'] = 300.0
                df_ledger.at[idx, 'net_pnl'] = round(net, 2)
                df_ledger.at[idx, 'return_pct'] = round(ret_pct, 2)
                df_ledger.at[idx, 'status'] = 'COMPLETED'
                df_ledger.at[idx, 'reconciled_at'] = now_ts

                reconciled_dates.add(d)
                completed_count += 1
            else:
                missing = []
                if not res_entry: missing.append("09:21 Entry")
                if not res_exit: missing.append("09:41 Exit")
                print(f"⚠️ {d} | {s}: Incomplete market data ({', '.join(missing)}). Remains PENDING.")

    conn.close()

    # Save updated ledger
    df_ledger.to_csv(LEDGER_CSV, index=False)
    print(f"\n✔ Successfully reconciled {completed_count} trade(s). Ledger updated: {LEDGER_CSV}")

    # Generate Reports & Telegram Alerts for each reconciled date
    for d in sorted(list(reconciled_dates)):
        day_df = df_ledger[(df_ledger['date'] == d) & (df_ledger['status'] == 'COMPLETED')].sort_values('rank')
        if day_df.empty:
            continue

        day_gross = day_df['gross_pnl'].sum()
        day_net = day_df['net_pnl'].sum()
        wins = (day_df['net_pnl'] > 0).sum()
        losses = (day_df['net_pnl'] <= 0).sum()
        win_rate = (wins / len(day_df)) * 100.0 if len(day_df) > 0 else 0.0

        pnl_color = "🟢" if day_net >= 0 else "🔴"

        print("\n" + "=" * 90)
        print(f"📊 09:20 SCALP RECONCILED PNL REPORT: {d} (09:21 ENTRY -> 09:41 EXIT)")
        print("=" * 90)
        print(f"{'#':<3} | {'Stock':<12} | {'Lots':<6} | {'Entry (₹)':<10} | {'Exit (₹)':<10} | {'Return %':<9} | {'Gross PnL (₹)':<14} | {'Net PnL (₹)':<12}")
        print("-" * 90)
        for _, r in day_df.iterrows():
            stk = r['stockname']
            lots = int(r['lotsize'])
            ep = r['entry_price']
            xp = r['exit_price']
            ret = r['return_pct']
            gp = r['gross_pnl']
            np_val = r['net_pnl']
            print(f"{int(r['rank']):<3} | {stk:<12} | {lots:<6} | {ep:>9.2f}  | {xp:>9.2f}  | {ret:>7.2f}% | {gp:>13,.2f}  | {np_val:>11,.2f}")
        print("-" * 90)
        print(f"SUMMARY: Total Net PnL = ₹{day_net:,.2f} | Win Rate: {win_rate:.1f}% ({wins}W / {losses}L)")
        print("=" * 90)

        # Telegram Message
        tg_lines = [
            f"{pnl_color} <b>[09:20 SCALP: DAILY RECONCILED PNL REPORT]</b>",
            f"📅 <b>Date:</b> {d} | ⏱️ <b>Audit Time:</b> {now_ts} IST",
            f"🎯 <b>Holding Window:</b> 09:21 AM ➔ 09:41 AM (Strict 20-Min Scalp)",
            "",
            "<b>📋 EXECUTED TRADES BREAKDOWN:</b>"
        ]
        for _, r in day_df.iterrows():
            t_icon = "✅" if r['net_pnl'] > 0 else "❌"
            tg_lines.append(
                f"  {t_icon} <b>#{int(r['rank'])} {r['stockname']}</b>: Entry ₹{r['entry_price']:.2f} ➔ Exit ₹{r['exit_price']:.2f} | Lot {int(r['lotsize'])} | Net: <b>₹{r['net_pnl']:+,.2f}</b> ({r['return_pct']:+.2f}%)"
            )
        tg_lines.extend([
            "",
            f"💵 <b>Gross PnL:</b> ₹{day_gross:+,.2f}",
            f"⚡ <b>Statutory Charges:</b> -₹{len(day_df)*300:,.2f} (₹300/trade)",
            f"🏆 <b>FINAL NET PNL:</b> <b>₹{day_net:+,.2f}</b>",
            f"📈 <b>Daily Win Rate:</b> <b>{win_rate:.1f}%</b> ({wins} Wins / {losses} Losses)"
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
