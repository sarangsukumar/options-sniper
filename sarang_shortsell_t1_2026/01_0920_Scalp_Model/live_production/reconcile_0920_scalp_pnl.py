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

def simulate_scalp(ticks, qty, date_str):
    """
    Simulates the 50/50 Split Execution Strategy for 0920_SCALP:
      - Leg 1 (50% qty): Passive resting Limit TP order on book at entry - (2000.0 / total_qty).
      - Leg 2 (50% qty): Evaluated at 30s cadence (09:36:00 to 09:39:30) for profit >= ₹500, else 09:40 exit.
      - Base Stop Loss: ₹3,000 risk or 0.60% adverse move.
    """
    if not ticks:
        return None

    entry_p = float(ticks[0]['price'])
    entry_t = str(ticks[0]['time']).split()[-1]
    
    q1 = qty // 2
    if q1 <= 0: q1 = 1
    q2 = qty - q1

    # Leg 1 TP: ₹2,000 profit
    tp1_target = 2000.0
    tp1_price = round(entry_p - (tp1_target / qty), 2)
    # Base SL: ₹3,000 risk or 0.60% adverse move
    sl_p = min(round(entry_p + (3000.0 / qty), 2), round(entry_p * 1.006, 2))

    leg1_filled = False
    leg1_p = None
    leg1_t = None
    leg1_reason = None

    leg2_filled = False
    leg2_p = None
    leg2_t = None
    leg2_reason = None

    for t in ticks:
        t_time = str(t['time'])
        p = float(t['price'])
        h = float(t.get('high') or p)
        l = float(t.get('low') or p)

        # 1. Base Stop loss check
        if h >= sl_p:
            if not leg1_filled:
                leg1_filled = True
                leg1_p = sl_p
                leg1_t = t_time.split()[-1]
                leg1_reason = 'STOP_LOSS_3000'
            if not leg2_filled:
                leg2_filled = True
                leg2_p = sl_p
                leg2_t = t_time.split()[-1]
                leg2_reason = 'STOP_LOSS_3000'
            break

        # 2. Leg 1 Resting Take Profit check (₹2,000 profit)
        if not leg1_filled and l <= tp1_price:
            leg1_filled = True
            leg1_p = tp1_price
            leg1_t = t_time.split()[-1]
            leg1_reason = 'LEG1_TP_2000'

        # 3. Leg 2 / Remaining Trailing profit exit between 09:36:00 and 09:39:30
        if f"{date_str} 09:36:00" <= t_time <= f"{date_str} 09:39:30":
            if leg1_filled and not leg2_filled:
                if (entry_p - p) * q2 >= 500.0:
                    leg2_filled = True
                    leg2_p = p
                    leg2_t = t_time.split()[-1]
                    leg2_reason = f'LEG2_CADENCE_{leg2_t[:5]}'
                    break
            elif not leg1_filled and not leg2_filled:
                if (entry_p - p) * qty >= 500.0:
                    leg1_filled = True
                    leg1_p = p
                    leg1_t = t_time.split()[-1]
                    leg1_reason = f'CADENCE_{leg1_t[:5]}'
                    leg2_filled = True
                    leg2_p = p
                    leg2_t = t_time.split()[-1]
                    leg2_reason = f'CADENCE_{leg2_t[:5]}'
                    break

        # 4. Hard Square-off at 09:40:00
        if t_time >= f"{date_str} 09:40:00":
            if not leg1_filled:
                leg1_filled = True
                leg1_p = p
                leg1_t = t_time.split()[-1]
                leg1_reason = 'TIME_EXIT_0940'
            if not leg2_filled:
                leg2_filled = True
                leg2_p = p
                leg2_t = t_time.split()[-1]
                leg2_reason = 'TIME_EXIT_0940'
            break

    # Fallback to last tick if not filled
    if not leg1_filled or not leg2_filled:
        last_p = float(ticks[-1]['price'])
        last_t = str(ticks[-1]['time']).split()[-1]
        if not leg1_filled:
            leg1_filled = True
            leg1_p = last_p
            leg1_t = last_t
            leg1_reason = 'TIME_EXIT_0940'
        if not leg2_filled:
            leg2_filled = True
            leg2_p = last_p
            leg2_t = last_t
            leg2_reason = 'TIME_EXIT_0940'

    gross = round((entry_p - leg1_p) * q1 + (entry_p - leg2_p) * q2, 2)
    taxes = round(get_taxes(q1, entry_p, leg1_p) + get_taxes(q2, entry_p, leg2_p), 2)
    net = round(gross - taxes, 2)
    avg_exit_p = round((leg1_p * q1 + leg2_p * q2) / qty, 2)
    ret_pct = round(((entry_p - avg_exit_p) / entry_p) * 100.0, 2) if entry_p > 0 else 0.0
    exit_t = max(leg1_t, leg2_t) if leg1_t and leg2_t else (leg1_t or leg2_t)
    exit_reason = f"{leg1_reason} + {leg2_reason}" if leg1_reason != leg2_reason else leg1_reason

    return {
        'entry_price': round(entry_p, 2),
        'entry_time': entry_t,
        'exit_price': avg_exit_p,
        'exit_time': exit_t,
        'exit_reason': exit_reason,
        'gross_pnl': gross,
        'net_pnl': net,
        'return_pct': ret_pct,
        'taxes': taxes
    }

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
            raw_lotsize = row.get('lotsize')
            if pd.isna(raw_lotsize) or raw_lotsize is None:
                raw_lotsize = row.get('qty', 1)
            try:
                lotsize = int(float(raw_lotsize))
            except Exception:
                lotsize = 1

            # 1. Fetch Futures (scrapdata_F1) ticks from 09:25:00 to 09:42:00
            cursor.execute(f"""
                SELECT time, CAST(price AS DECIMAL(10,2)) as price, CAST(IFNULL(high, price) AS DECIMAL(10,2)) as high, CAST(IFNULL(low, price) AS DECIMAL(10,2)) as low
                FROM scrapdata_F1 
                WHERE date = '{d}' AND stockname = '{s}' 
                  AND time >= '{d} 09:25:00' AND time <= '{d} 09:42:00'
                  AND (isvalid = 'TRUE' OR isvalid IS NULL OR isvalid = '1' OR isvalid = '')
                ORDER BY time ASC
            """)
            ticks_f1 = cursor.fetchall()

            # 2. Fetch Cash Equity (scrapdata) ticks from 09:25:00 to 09:42:00
            cursor.execute(f"""
                SELECT time, CAST(price AS DECIMAL(10,2)) as price, CAST(IFNULL(high, price) AS DECIMAL(10,2)) as high, CAST(IFNULL(low, price) AS DECIMAL(10,2)) as low
                FROM scrapdata 
                WHERE date = '{d}' AND stockname = '{s}' 
                  AND time >= '{d} 09:25:00' AND time <= '{d} 09:42:00'
                  AND (isvalid = 'TRUE' OR isvalid IS NULL OR isvalid = '1' OR isvalid = '')
                ORDER BY time ASC
            """)
            ticks_eq = cursor.fetchall()

            res_f1 = simulate_scalp(ticks_f1, lotsize, d) if ticks_f1 else None
            res_eq = simulate_scalp(ticks_eq, lotsize, d) if ticks_eq else None

            if not res_f1 and not res_eq:
                print(f"⚠️ {d} | {s}: Incomplete market data in both scrapdata and scrapdata_F1. Remains PENDING.")
                continue

            # Populate Futures fields
            if res_f1:
                df_ledger.at[idx, 'f1_entry_price'] = res_f1['entry_price']
                df_ledger.at[idx, 'f1_exit_price'] = res_f1['exit_price']
                df_ledger.at[idx, 'f1_gross_pnl'] = res_f1['gross_pnl']
                df_ledger.at[idx, 'f1_net_pnl'] = res_f1['net_pnl']
                df_ledger.at[idx, 'f1_return_pct'] = res_f1['return_pct']
            else:
                for col in ['f1_entry_price', 'f1_exit_price', 'f1_gross_pnl', 'f1_net_pnl', 'f1_return_pct']:
                    df_ledger.at[idx, col] = np.nan

            # Populate Cash Equity fields
            if res_eq:
                df_ledger.at[idx, 'eq_entry_price'] = res_eq['entry_price']
                df_ledger.at[idx, 'eq_exit_price'] = res_eq['exit_price']
                df_ledger.at[idx, 'eq_gross_pnl'] = res_eq['gross_pnl']
                df_ledger.at[idx, 'eq_net_pnl'] = res_eq['net_pnl']
                df_ledger.at[idx, 'eq_return_pct'] = res_eq['return_pct']
            else:
                for col in ['eq_entry_price', 'eq_exit_price', 'eq_gross_pnl', 'eq_net_pnl', 'eq_return_pct']:
                    df_ledger.at[idx, col] = np.nan

            # Primary ledger fields (prioritize Futures if available, otherwise Cash Equity)
            primary = res_f1 if res_f1 else res_eq

            df_ledger.at[idx, 'entry_price'] = primary['entry_price']
            df_ledger.at[idx, 'exit_price'] = primary['exit_price']
            df_ledger.at[idx, 'entry_time'] = primary['entry_time']
            df_ledger.at[idx, 'exit_time'] = primary['exit_time']
            df_ledger.at[idx, 'exit_reason'] = primary['exit_reason']
            df_ledger.at[idx, 'gross_pnl'] = primary['gross_pnl']
            df_ledger.at[idx, 'charges'] = primary['taxes']
            df_ledger.at[idx, 'net_pnl'] = primary['net_pnl']
            df_ledger.at[idx, 'return_pct'] = primary['return_pct']
            df_ledger.at[idx, 'is_win'] = 1 if primary['net_pnl'] > 0 else 0
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

        has_f1 = 'f1_net_pnl' in day_df and day_df['f1_net_pnl'].notna().any()
        day_gross_f1 = day_df['f1_gross_pnl'].dropna().sum() if has_f1 else 0.0
        day_net_f1 = day_df['f1_net_pnl'].dropna().sum() if has_f1 else 0.0
        day_net_eq = day_df['eq_net_pnl'].dropna().sum() if ('eq_net_pnl' in day_df and day_df['eq_net_pnl'].notna().any()) else day_df['net_pnl'].dropna().sum()

        wins = (day_df['net_pnl'] > 0).sum()
        win_rate = (wins / len(day_df)) * 100.0 if len(day_df) > 0 else 0.0

        target_net = day_net_f1 if has_f1 else day_net_eq
        pnl_color = "🟢" if target_net >= 0 else "🔴"

        print("\n" + "=" * 100)
        mode_title = "FUTURES & CASH EQUITY" if has_f1 else "CASH EQUITY"
        print(f"📊 09:20 SCALP RECONCILED PNL REPORT: {d} ({mode_title})")
        print("=" * 100)
        if has_f1:
            print(f"{'#':<3} | {'Stock':<10} | {'F1 Net (₹)':<12} | {'F1 Ret %':<9} | {'EQ Net (₹)':<12} | {'EQ Ret %':<9} | {'Exit Reason':<22} | {'Exit Time':<8}")
            print("-" * 100)
            for _, r in day_df.iterrows():
                stk = r['stockname']
                f1_n = r.get('f1_net_pnl', 0.0)
                f1_r = r.get('f1_return_pct', 0.0)
                eq_n = r.get('eq_net_pnl', r.get('net_pnl', 0.0))
                eq_r = r.get('eq_return_pct', r.get('return_pct', 0.0))
                reason = str(r.get('exit_reason', '-'))
                ex_t = str(r.get('exit_time', '-'))
                print(f"{int(r['rank']):<3} | {stk:<10} | {f1_n:>10,.2f}   | {f1_r:>7.2f}%  | {eq_n:>10,.2f}   | {eq_r:>7.2f}%  | {reason:<22} | {ex_t:<8}")
            print("-" * 100)
            print(f"SUMMARY: Futures Net PnL = ₹{day_net_f1:,.2f} | Equity Net PnL = ₹{day_net_eq:,.2f} | Win Rate: {win_rate:.1f}%")
        else:
            print(f"{'#':<3} | {'Stock':<10} | {'Net PnL (₹)':<12} | {'Return %':<9} | {'Exit Reason':<24} | {'Exit Time':<8}")
            print("-" * 100)
            for _, r in day_df.iterrows():
                stk = r['stockname']
                net_val = r.get('net_pnl', 0.0)
                ret_val = r.get('return_pct', 0.0)
                reason = str(r.get('exit_reason', '-'))
                ex_t = str(r.get('exit_time', '-'))
                print(f"{int(r['rank']):<3} | {stk:<10} | {net_val:>10,.2f}   | {ret_val:>7.2f}%  | {reason:<24} | {ex_t:<8}")
            print("-" * 100)
            print(f"SUMMARY: Total Net PnL = ₹{day_net_eq:,.2f} | Win Rate: {win_rate:.1f}%")
        print("=" * 100)

        # Telegram Message
        tg_header = "[09:20 SCALP: DUAL RECONCILED PNL REPORT]" if has_f1 else "[09:20 SCALP: RECONCILED PNL REPORT]"
        tg_lines = [
            f"{pnl_color} <b>{tg_header}</b>",
            f"📅 <b>Date:</b> {d} | ⏱️ <b>Audit Time:</b> {now_ts} IST",
            f"🎯 <b>Holding Window:</b> 09:25 Entry ➔ 0.05% Trailing Profit (09:36–09:39) / 09:40 Square-Off",
            "",
            "<b>📋 EXECUTED TRADES:</b>"
        ]
        for _, r in day_df.iterrows():
            t_icon = "✅" if r['net_pnl'] > 0 else "❌"
            lot_display = int(r['lotsize']) if pd.notna(r.get('lotsize')) else int(r.get('qty', 1)) if pd.notna(r.get('qty')) else 1
            reason = str(r.get('exit_reason', ''))
            reason_str = f" [{reason}]" if reason and reason != 'nan' else ""
            if has_f1:
                f1_n = r.get('f1_net_pnl', 0.0)
                f1_r = r.get('f1_return_pct', 0.0)
                eq_n = r.get('eq_net_pnl', r.get('net_pnl', 0.0))
                eq_r = r.get('eq_return_pct', r.get('return_pct', 0.0))
                tg_lines.append(
                    f"  {t_icon} <b>#{int(r['rank'])} {r['stockname']}</b> (Qty {lot_display}{reason_str}):"
                    f"\n      • <b>F1:</b> Net <b>₹{f1_n:+,.2f}</b> ({f1_r:+.2f}%)"
                    f"\n      • <b>EQ:</b> Net <b>₹{eq_n:+,.2f}</b> ({eq_r:+.2f}%)"
                )
            else:
                net_val = r.get('net_pnl', 0.0)
                ret_val = r.get('return_pct', 0.0)
                tg_lines.append(
                    f"  {t_icon} <b>#{int(r['rank'])} {r['stockname']}</b> (Qty {lot_display}{reason_str}):"
                    f"\n      • Net: <b>₹{net_val:+,.2f}</b> ({ret_val:+.2f}%)"
                )
        total_charges = day_df['charges'].sum() if 'charges' in day_df and day_df['charges'].notna().any() else len(day_df) * 300.0
        tg_lines.append("")
        tg_lines.append(f"⚡ <b>Statutory Charges:</b> -₹{total_charges:,.2f}")
        if has_f1:
            tg_lines.extend([
                f"🏆 <b>TOTAL FUTURES NET PNL:</b> <b>₹{day_net_f1:+,.2f}</b> ({win_rate:.1f}% Win Rate)",
                f"📊 <b>TOTAL EQUITY NET PNL:</b> <b>₹{day_net_eq:+,.2f}</b>"
            ])
        else:
            tg_lines.append(f"🏆 <b>TOTAL NET PNL:</b> <b>₹{day_net_eq:+,.2f}</b> ({win_rate:.1f}% Win Rate)")

        if not no_telegram:
            send_telegram_alert("\n".join(tg_lines))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="09:20 - 09:40 Scalp Engine Evening Reconciler")
    parser.add_argument('--date', type=str, default=None, help="Target Date YYYY-MM-DD (defaults to all PENDING)")
    parser.add_argument('--force-all', action='store_true', help="Re-reconcile even if already completed")
    parser.add_argument('--no-telegram', action='store_true', help="Skip sending Telegram alert")
    args = parser.parse_args()

    reconcile_scalp_trades(target_date=args.date, force_all=args.force_all, no_telegram=args.no_telegram)
