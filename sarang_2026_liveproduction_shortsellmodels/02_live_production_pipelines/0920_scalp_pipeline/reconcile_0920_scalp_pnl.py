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
import time
import argparse
import subprocess
from datetime import datetime
import requests
import urllib3.util.connection as urllib3_cn
urllib3_cn.HAS_IPV6 = False
import numpy as np
import pandas as pd
import pymysql

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROD_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..'))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
try:
    from reconcile_0920_options_helper import simulate_0920_option_for_trade
except ImportError:
    simulate_0920_option_for_trade = None
LEDGER_CSV = os.path.join(SCRIPT_DIR, 'daily_0920_live_ledger.csv')
BOT_SCRIPT = '/home/ubuntu/KotakCodes1/status_Info_bot.js'
STATUS_BOT_TOKEN = "7920868588:AAE4mPlDQJWnkv9CbmHO8idiSBVnP7K0Gko"
STATUS_CHAT_ID = "-1002365534285"

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
    sent_ok = False
    if os.path.exists(BOT_SCRIPT):
        try:
            res = subprocess.run(['node', BOT_SCRIPT, msg], capture_output=True, text=True, timeout=35)
            out_str = res.stdout.strip()
            print(f"[Telegram Bot Response]: {out_str[:100]}")
            if res.returncode == 0 and "Message sent successfully" in out_str:
                sent_ok = True
        except Exception as e:
            print(f"⚠️ Telegram node script error: {e}")

    if not sent_ok:
        url = f"https://api.telegram.org/bot{STATUS_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": STATUS_CHAT_ID, "text": msg, "parse_mode": "HTML", "disable_web_page_preview": True}
        for attempt in range(1, 5):
            try:
                resp = requests.post(url, json=payload, timeout=12)
                if resp.status_code == 200:
                    print(f"[Telegram Direct IPv4 Fallback]: Sent successfully (attempt {attempt})")
                    sent_ok = True
                    break
                print(f"⚠️ Telegram direct HTTP status {resp.status_code} (attempt {attempt})")
            except Exception as e:
                print(f"⚠️ Telegram direct HTTP error (attempt {attempt}/4): {e}")
            time.sleep(2 * attempt)
    return sent_ok

def simulate_scalp(ticks, qty, date_str):
    """
    Single-stock wrapper around simulate_scalp_basket (Base SL: ₹6,250 / 1.25%).
    """
    if not ticks:
        return None
    res_map = simulate_scalp_basket({0: {'ticks': ticks, 'qty': qty}}, date_str)
    return res_map.get(0)


def simulate_scalp_basket(stocks_data, date_str):
    """
    Simulates the 100% Single-Leg 3-Stage Trailing & Stop-Loss Strategy for 0920_SCALP (₹5L per stock):
      - Stage 1 (Peak PnL < +₹2,000): Initial Stop-Loss = -₹5,000 (1.00% adverse move).
      - Stage 2 (+₹2,000 <= Peak PnL < +₹4,000): Minimum Profit Floor Lock = +₹1,000 (+0.20%).
      - Stage 3 (Peak PnL >= +₹4,000): Dynamic Trailing Profit Lock = Peak PnL - ₹750 (₹3,250, ₹4,250, ...).
      - Stage 4 (09:36:00 to 09:39:30): 30s/1m Cadence check for profit >= +₹500, else 09:40:00 Hard Exit.
    """
    results = {}

    for key, info in stocks_data.items():
        ticks = info.get('ticks')
        qty = int(info.get('qty', 1))
        if not ticks or qty <= 0:
            continue

        entry_p = float(ticks[0]['price'])
        entry_t = str(ticks[0]['time']).split()[-1]
        initial_sl_p = min(round(entry_p + (5000.0 / qty), 2), round(entry_p * 1.0100, 2))

        max_pnl_rs = 0.0
        exit_p = None
        exit_t = None
        exit_reason = 'TIME_EXIT_0940'

        for i in range(1, len(ticks)):
            tk = ticks[i]
            t_time = str(tk['time'])
            t_short = t_time.split()[-1]
            p = float(tk['price'])
            h = float(tk.get('high') or p)
            l = float(tk.get('low') or p)
            c_close = float(ticks[i + 1]['price']) if (i + 1) < len(ticks) else p

            # Determine active protection level from running peak PnL prior to this candle's adverse spike
            if max_pnl_rs >= 4000.0:
                locked_pnl_rs = max_pnl_rs - 750.0
                active_stop_p = round(entry_p - (locked_pnl_rs / qty), 2)
                stop_reason = f"TRAIL_LOCK_+{int(locked_pnl_rs)}"
            elif max_pnl_rs >= 2000.0:
                locked_pnl_rs = 1000.0
                active_stop_p = round(entry_p - (1000.0 / qty), 2)
                stop_reason = "FLOOR_LOCK_+1000"
            else:
                locked_pnl_rs = -5000.0
                active_stop_p = initial_sl_p
                stop_reason = "INITIAL_SL_-5000"

            # 1. Check Stop-Loss / Trailing Profit Floor Breach (active >= 09:27:00)
            if t_time >= f"{date_str} 09:27:00" and h >= active_stop_p:
                exit_p = active_stop_p
                exit_t = t_short
                exit_reason = stop_reason
                break

            # 2. Update running peak profit from candle low
            candle_best_pnl = (entry_p - min(l, p)) * qty
            if candle_best_pnl > max_pnl_rs:
                max_pnl_rs = candle_best_pnl

            # Check if intrabar low activated floor/trail and candle close (next bar open) retraced above new lock
            if t_time >= f"{date_str} 09:27:00":
                if max_pnl_rs >= 4000.0:
                    new_lock_rs = max_pnl_rs - 750.0
                    new_stop_p = round(entry_p - (new_lock_rs / qty), 2)
                    if c_close >= new_stop_p:
                        exit_p = new_stop_p
                        exit_t = t_short
                        exit_reason = f"TRAIL_LOCK_+{int(new_lock_rs)}"
                        break
                elif max_pnl_rs >= 2000.0:
                    new_stop_p = round(entry_p - (1000.0 / qty), 2)
                    if c_close >= new_stop_p:
                        exit_p = new_stop_p
                        exit_t = t_short
                        exit_reason = "FLOOR_LOCK_+1000"
                        break

            # 3. Late Cadence Profit Check (09:36:00 to 09:39:30)
            if f"{date_str} 09:36:00" <= t_time <= f"{date_str} 09:39:30":
                if (entry_p - p) * qty >= 500.0:
                    exit_p = p
                    exit_t = t_short
                    exit_reason = f"CADENCE_{t_short[:5]}"
                    break

            # 4. Hard Square-off at 09:40:00
            if t_time >= f"{date_str} 09:40:00":
                exit_p = p
                exit_t = t_short
                exit_reason = 'TIME_EXIT_0940'
                break

        if exit_p is None:
            exit_p = float(ticks[-1]['price'])
            exit_t = str(ticks[-1]['time']).split()[-1]
            exit_reason = 'TIME_EXIT_0940'

        gross = round((entry_p - exit_p) * qty, 2)
        taxes = round(get_taxes(qty, entry_p, exit_p), 2)
        net = round(gross - taxes, 2)
        ret_pct = round(((entry_p - exit_p) / entry_p) * 100.0, 2) if entry_p > 0 else 0.0

        results[key] = {
            'entry_price': round(entry_p, 2),
            'entry_time': entry_t,
            'exit_price': round(exit_p, 2),
            'exit_time': exit_t,
            'exit_reason': exit_reason,
            'gross_pnl': gross,
            'net_pnl': net,
            'return_pct': ret_pct,
            'taxes': taxes
        }

    return results

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
    import pytz
    now_ts = datetime.now(pytz.timezone('Asia/Kolkata')).strftime('%Y-%m-%d %H:%M:%S')
    reconciled_dates = set()
    completed_count = 0

    target_dates = sorted(df_ledger.loc[target_indices, 'date'].astype(str).unique().tolist())

    with conn.cursor() as cursor:
        for d in target_dates:
            day_all_indices = df_ledger[df_ledger['date'].astype(str) == d].index.tolist()
            eq_basket_input = {}
            stock_by_idx = {}

            for idx in day_all_indices:
                row = df_ledger.loc[idx]
                s = str(row['stockname']).strip().upper()
                stock_by_idx[idx] = s
                raw_lotsize = row.get('lotsize')
                if pd.isna(raw_lotsize) or raw_lotsize is None:
                    raw_lotsize = row.get('qty', 1)
                try:
                    lotsize = int(float(raw_lotsize))
                except Exception:
                    lotsize = 1

                # Fetch Cash Equity (scrapdata) ticks from 09:25:00 to 09:42:00
                cursor.execute(f"""
                    SELECT time, CAST(price AS DECIMAL(10,2)) as price, CAST(IFNULL(high, price) AS DECIMAL(10,2)) as high, CAST(IFNULL(low, price) AS DECIMAL(10,2)) as low
                    FROM scrapdata 
                    WHERE date = '{d}' AND stockname = '{s}' 
                      AND time >= '{d} 09:25:00' AND time <= '{d} 09:42:00'
                      AND (isvalid = 'TRUE' OR isvalid IS NULL OR isvalid = '1' OR isvalid = '')
                    ORDER BY time ASC
                """)
                ticks_eq = cursor.fetchall()
                if ticks_eq:
                    eq_basket_input[idx] = {'ticks': ticks_eq, 'qty': lotsize}

            eq_basket_res = simulate_scalp_basket(eq_basket_input, d) if eq_basket_input else {}

            for idx in day_all_indices:
                if idx not in target_indices:
                    continue
                s = stock_by_idx[idx]
                res_eq = eq_basket_res.get(idx)

                if not res_eq:
                    print(f"⚠️ {d} | {s}: Incomplete market data in scrapdata. Remains PENDING.")
                    continue

                for col in ['f1_entry_price', 'f1_exit_price', 'f1_gross_pnl', 'f1_net_pnl', 'f1_return_pct']:
                    df_ledger.at[idx, col] = np.nan

                # Populate Cash Equity fields (from scrapdata)
                df_ledger.at[idx, 'eq_entry_price'] = res_eq['entry_price']
                df_ledger.at[idx, 'eq_exit_price'] = res_eq['exit_price']
                df_ledger.at[idx, 'eq_gross_pnl'] = res_eq['gross_pnl']
                df_ledger.at[idx, 'eq_net_pnl'] = res_eq['net_pnl']
                df_ledger.at[idx, 'eq_return_pct'] = res_eq['return_pct']

                # Primary ledger fields strictly from scrapdata (Cash Equity)
                primary = res_eq

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

                # Populate Put Option Simulation (ExactSync_0920 & SmartSync_0920 on ₹1L/stock)
                if simulate_0920_option_for_trade is not None:
                    try:
                        opt_res = simulate_0920_option_for_trade(
                            cursor, conn, s, d,
                            float(primary['entry_price']),
                            str(primary['entry_time']),
                            str(primary['exit_time']),
                            str(primary['exit_reason'])
                        )
                        for k_opt, v_opt in opt_res.items():
                            df_ledger.at[idx, k_opt] = v_opt
                    except Exception as e_opt:
                        print(f"⚠️ {d} | {s}: Option simulation error: {e_opt}")

                reconciled_dates.add(d)
                completed_count += 1

    conn.close()

    # Save updated ledger
    df_ledger.to_csv(LEDGER_CSV, index=False)
    print(f"\n✔ Successfully reconciled {completed_count} trade(s). Ledger updated: {LEDGER_CSV}")

    # Generate Reports & Telegram Alerts for each reconciled date (strictly on scrapdata)
    for d in sorted(list(reconciled_dates)):
        day_df = df_ledger[(df_ledger['date'] == d) & (df_ledger['status'] == 'COMPLETED')].sort_values('rank')
        if day_df.empty:
            continue

        day_net_eq = day_df['net_pnl'].dropna().sum()
        wins = (day_df['net_pnl'] > 0).sum()
        win_rate = (wins / len(day_df)) * 100.0 if len(day_df) > 0 else 0.0
        pnl_color = "🟢" if day_net_eq >= 0 else "🔴"

        print("\n" + "=" * 100)
        print(f"📊 09:20 SCALP RECONCILED PNL REPORT: {d} (CASH EQUITY - scrapdata)")
        print("=" * 100)
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
        if 'opt_exactsync_net_pnl' in day_df.columns and day_df['opt_exactsync_net_pnl'].notna().any():
            opt_ex_tot = day_df['opt_exactsync_net_pnl'].dropna().sum()
            opt_sm_tot = day_df['opt_smartsync_net_pnl'].dropna().sum()
            print("-" * 100)
            print(f"🎯 09:20 PUT OPTION SIMULATION (₹1.0L/Stock | Max ₹2.0L | ₹0.05 Tick Compliant):")
            for _, r in day_df.iterrows():
                if pd.notna(r.get('opt_exactsync_net_pnl')):
                    print(f"  #{int(r['rank'])} {r['stockname']:<10} | {r.get('opt_strike')} PE ({r.get('opt_role')}) | Lots: {int(r.get('opt_lots', 0))} (₹{r.get('opt_capital_used', 0):,.0f}) | Entry: ₹{r.get('opt_entry_price', 0):.2f} ({r.get('opt_entry_time')}) | ExactSync: ₹{r.get('opt_exactsync_exit_price', 0):.2f} ({r.get('opt_exactsync_exit_time')}) ➔ Net ₹{r.get('opt_exactsync_net_pnl', 0):+,.2f} ({r.get('opt_exactsync_ret_pct', 0):+.2f}%) | SmartSync: ₹{r.get('opt_smartsync_exit_price', 0):.2f} ({r.get('opt_smartsync_exit_time')} {r.get('opt_smartsync_exit_reason')}) ➔ Net ₹{r.get('opt_smartsync_net_pnl', 0):+,.2f} ({r.get('opt_smartsync_ret_pct', 0):+.2f}%)")
            print(f"OPTION SUMMARY: ExactSync_0920 Net = ₹{opt_ex_tot:+,.2f} | SmartSync_0920 Net = ₹{opt_sm_tot:+,.2f}")
        print("=" * 100)

        # Telegram Message
        tg_lines = [
            f"{pnl_color} <b>[09:20 SCALP: RECONCILED PNL REPORT]</b>",
            f"📅 <b>Date:</b> {d} | ⏱️ <b>Audit Time:</b> {now_ts} IST",
            f"🎯 <b>Strategy:</b> 100% Single-Leg 3-Stage Trail (-₹5,000 SL | +₹2k➔+₹1k Floor | +₹4k+➔Peak-₹750 | 09:36 Cadence)",
            "",
            "<b>📋 EXECUTED TRADES (scrapdata):</b>"
        ]
        for _, r in day_df.iterrows():
            t_icon = "✅" if r['net_pnl'] > 0 else "❌"
            lot_display = int(r['lotsize']) if pd.notna(r.get('lotsize')) else int(r.get('qty', 1)) if pd.notna(r.get('qty')) else 1
            reason = str(r.get('exit_reason', ''))
            reason_str = f" [{reason}]" if reason and reason != 'nan' else ""
            net_val = r.get('net_pnl', 0.0)
            ret_val = r.get('return_pct', 0.0)
            tg_lines.append(
                f"  {t_icon} <b>#{int(r['rank'])} {r['stockname']}</b> (Qty {lot_display}{reason_str}):"
                f"\n      • Net: <b>₹{net_val:+,.2f}</b> ({ret_val:+.2f}%)"
            )
        total_charges = day_df['charges'].sum() if 'charges' in day_df and day_df['charges'].notna().any() else len(day_df) * 300.0
        tg_lines.append("")
        tg_lines.append(f"⚡ <b>Statutory Charges:</b> -₹{total_charges:,.2f}")
        tg_lines.append(f"🏆 <b>TOTAL CASH MIS NET PNL:</b> <b>₹{day_net_eq:+,.2f}</b> ({win_rate:.1f}% Win Rate)")

        if 'opt_exactsync_net_pnl' in day_df.columns and day_df['opt_exactsync_net_pnl'].notna().any():
            opt_ex_tot = day_df['opt_exactsync_net_pnl'].dropna().sum()
            opt_sm_tot = day_df['opt_smartsync_net_pnl'].dropna().sum()
            tg_lines.append("")
            tg_lines.append("🔥 <b>PUT OPTION SIMULATION (₹1.0L/Stock | Max ₹2.0L):</b>")
            for _, r in day_df.iterrows():
                if pd.notna(r.get('opt_exactsync_net_pnl')):
                    ex_n = r.get('opt_exactsync_net_pnl', 0.0)
                    sm_n = r.get('opt_smartsync_net_pnl', 0.0)
                    ex_ic = "✅" if ex_n > 0 else "❌"
                    sm_ic = "✅" if sm_n > 0 else "❌"
                    tg_lines.append(
                        f"  • <b>#{int(r['rank'])} {r['stockname']} {r.get('opt_strike')} PE</b> ({r.get('opt_role')} | {int(r.get('opt_lots', 0))} Lots = ₹{r.get('opt_capital_used', 0):,.0f} | Buy ₹{r.get('opt_entry_price', 0):.2f}):"
                        f"\n      {ex_ic} <b>ExactSync_0920:</b> Sell ₹{r.get('opt_exactsync_exit_price', 0):.2f} @ {r.get('opt_exactsync_exit_time')} ➔ <b>₹{ex_n:+,.2f}</b> ({r.get('opt_exactsync_ret_pct', 0):+.2f}%)"
                        f"\n      {sm_ic} <b>SmartSync_0920:</b> Sell ₹{r.get('opt_smartsync_exit_price', 0):.2f} @ {r.get('opt_smartsync_exit_time')} [{r.get('opt_smartsync_exit_reason')}] ➔ <b>₹{sm_n:+,.2f}</b> ({r.get('opt_smartsync_ret_pct', 0):+.2f}%)"
                    )
            tg_lines.append(f"🎯 <b>ExactSync_0920 Total Net:</b> <b>₹{opt_ex_tot:+,.2f}</b>")
            tg_lines.append(f"🛡️ <b>SmartSync_0920 Total Net:</b> <b>₹{opt_sm_tot:+,.2f}</b>")

        if not no_telegram:
            send_telegram_alert("\n".join(tg_lines))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="09:20 - 09:40 Scalp Engine Evening Reconciler")
    parser.add_argument('--date', type=str, default=None, help="Target Date YYYY-MM-DD (defaults to all PENDING)")
    parser.add_argument('--force-all', action='store_true', help="Re-reconcile even if already completed")
    parser.add_argument('--no-telegram', action='store_true', help="Skip sending Telegram alert")
    args = parser.parse_args()

    reconcile_scalp_trades(target_date=args.date, force_all=args.force_all, no_telegram=args.no_telegram)
