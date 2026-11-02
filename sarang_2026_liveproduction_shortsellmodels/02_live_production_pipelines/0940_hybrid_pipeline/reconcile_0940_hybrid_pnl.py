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
    import pytz
    now_ts = datetime.now(pytz.timezone('Asia/Kolkata')).strftime('%Y-%m-%d %H:%M:%S')
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

            # Sync margin-adjusted quantity and filled_price from shortsell_orders if present
            live_filled_ep = None
            try:
                cursor.execute(f"""
                    SELECT filled_price, quantity
                    FROM shortsell_orders
                    WHERE trade_date = '{d}' AND stockname = '{s}'
                      AND model_name LIKE '%0942%'
                      AND isvalid NOT IN ('FALSE', 'REJECTED')
                    ORDER BY id DESC LIMIT 1
                """)
                ord_row = cursor.fetchone()
                if ord_row and ord_row.get('filled_price') and float(ord_row['filled_price']) > 0:
                    live_filled_ep = float(ord_row['filled_price'])
                if ord_row and ord_row.get('quantity') and int(ord_row['quantity']) > 0:
                    total_qty = int(ord_row['quantity'])
                    df_ledger.loc[idx, 'total_quantity'] = total_qty
            except Exception:
                pass

            # 1. Query scrapdata_F1 between 09:42:00 and 14:45:00
            q_f1 = f"""
            SELECT time, CAST(price AS DECIMAL(10,2)) as price, CAST(IFNULL(high, price) AS DECIMAL(10,2)) as high, CAST(IFNULL(low, price) AS DECIMAL(10,2)) as low
            FROM scrapdata_F1
            WHERE date = '{d}' AND stockname = '{s}'
              AND TIME(time) >= '09:42:00' AND TIME(time) <= '14:45:00'
              AND price IS NOT NULL AND price > 0
              AND (isvalid = 'TRUE' OR isvalid IS NULL OR isvalid = '1' OR isvalid = '')
            ORDER BY time ASC
            """
            cursor.execute(q_f1)
            ticks_f1 = cursor.fetchall()

            # 2. Query scrapdata (Cash Equity) between 09:42:00 and 14:45:00
            q_eq = f"""
            SELECT time, CAST(price AS DECIMAL(10,2)) as price, CAST(IFNULL(high, price) AS DECIMAL(10,2)) as high, CAST(IFNULL(low, price) AS DECIMAL(10,2)) as low
            FROM scrapdata
            WHERE date = '{d}' AND stockname = '{s}'
              AND TIME(time) >= '09:42:00' AND TIME(time) <= '14:45:00'
              AND price IS NOT NULL AND price > 0
              AND (isvalid = 'TRUE' OR isvalid IS NULL OR isvalid = '1' OR isvalid = '')
            ORDER BY time ASC
            """
            cursor.execute(q_eq)
            ticks_eq = cursor.fetchall()

            if not ticks_f1 and not ticks_eq:
                print(f"⚠️ No tick data found for {s} on {d} in both scrapdata_F1 and scrapdata. Leaving as PENDING.")
                continue

            from reconcile_0940_live_mimic_pnl import simulate_sim3_live_4stage_engine

            res_f1 = simulate_sim3_live_4stage_engine(ticks_f1, total_qty, override_ep=live_filled_ep) if ticks_f1 else None
            res_eq = simulate_sim3_live_4stage_engine(ticks_eq, total_qty, override_ep=live_filled_ep) if ticks_eq else None

            if not res_f1 and not res_eq:
                print(f"⚠️ Could not simulate 4-Stage engine for {s} on {d}. Leaving as PENDING.")
                continue

            if res_f1:
                f1_exit_p = res_f1['leg2_exit_price'] if res_f1['has_leg2'] else res_f1['leg1_exit_price']
                f1_exit_reason = f"{res_f1['leg1_exit_reason']}+{res_f1['leg2_exit_reason']}" if res_f1['has_leg2'] else res_f1['leg1_exit_reason']
                df_ledger.loc[idx, 'f1_entry_price'] = res_f1['entry_price']
                df_ledger.loc[idx, 'f1_exit_price'] = f1_exit_p
                df_ledger.loc[idx, 'f1_exit_reason'] = f1_exit_reason
                df_ledger.loc[idx, 'f1_net_pnl'] = res_f1['net_pnl']
                df_ledger.loc[idx, 'f1_return_pct'] = res_f1['return_pct']

            if res_eq:
                eq_exit_p = res_eq['leg2_exit_price'] if res_eq['has_leg2'] else res_eq['leg1_exit_price']
                eq_exit_reason = f"{res_eq['leg1_exit_reason']}+{res_eq['leg2_exit_reason']}" if res_eq['has_leg2'] else res_eq['leg1_exit_reason']
                df_ledger.loc[idx, 'eq_entry_price'] = res_eq['entry_price']
                df_ledger.loc[idx, 'eq_exit_price'] = eq_exit_p
                df_ledger.loc[idx, 'eq_exit_reason'] = eq_exit_reason
                df_ledger.loc[idx, 'eq_net_pnl'] = res_eq['net_pnl']
                df_ledger.loc[idx, 'eq_return_pct'] = res_eq['return_pct']

            # Primary columns (prioritize Cash Equity scrapdata since live trading is on EQ, fallback to Futures)
            primary = res_eq if res_eq else res_f1
            p_entry = primary['entry_price']
            p_sl = round(p_entry * 1.0300, 2)
            p_exit = primary['leg2_exit_price'] if primary['has_leg2'] else primary['leg1_exit_price']
            p_exit_time = primary['leg2_exit_time'] if primary['has_leg2'] else primary['leg1_exit_time']
            p_exit_reason = f"{primary['leg1_exit_reason']}+{primary['leg2_exit_reason']}" if primary['has_leg2'] else primary['leg1_exit_reason']
            p_pts = round(primary['gross_pnl'] / total_qty, 2) if total_qty > 0 else round(p_entry - p_exit, 2)
            p_gross = primary['gross_pnl']
            p_charges = primary['charges']
            p_net = primary['net_pnl']
            p_ret = primary['return_pct']

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
            f"🎯 <b>Holding Window:</b> 09:42 AM ➔ 14:45 PM (4-Stage Dynamic Exit Engine)",
            f"🛡️ <b>Risk Protection:</b> Stage-1 Time-Decay SL (3.00% ➔ 1.50% @ 11:00 ➔ 1.00% @ 12:30, 3-Min) | Stage-2 Lock (+1.25% ➔ +0.50%) | Stage-3 Trail TP (+2.00%)",
            "",
            "<b>📋 EXECUTED TRADES (FUTURES vs CASH EQUITY):</b>"
        ]
        for i, (_, r) in enumerate(day_df.iterrows()):
            stk_name = str(r['clean_stock']) if 'clean_stock' in r and pd.notna(r['clean_stock']) else str(r['stockname'])
            t_icon = "✅" if r['net_pnl'] > 0 else "❌"
            f1_n = r.get('f1_net_pnl', r.get('net_pnl', 0.0))
            f1_ret = r.get('f1_return_pct', r.get('return_pct', 0.0))
            f1_reason = r.get('f1_exit_reason', r.get('exit_reason', ''))
            f1_badge = f" [{f1_reason}]"

            eq_n = r.get('eq_net_pnl', 0.0)
            eq_ret = r.get('eq_return_pct', 0.0)
            eq_reason = r.get('eq_exit_reason', '')
            eq_badge = f" [{eq_reason}]"

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
