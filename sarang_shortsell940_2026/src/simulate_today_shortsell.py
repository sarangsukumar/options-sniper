#!/usr/bin/env python3
import os
import sys
import subprocess
import calendar
from datetime import datetime, time
import pandas as pd
import numpy as np
import mysql.connector

# Base Paths
BASE_DIR = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold'
SHORT_DIR = os.path.join(BASE_DIR, 'sarang_shortsell940_2026')
TARGETS_CSV = os.path.join(SHORT_DIR, 'output', 'todays_short_targets.csv')
LOTSIZE_CSV = os.path.join(BASE_DIR, 'config', 'historical_lotsize_new.csv')
TRACKING_CSV = os.path.join(SHORT_DIR, 'output', 'live_shortsell_tracking_history.csv')
BOT_SCRIPT = '/home/ubuntu/telegram_bot/New_OrderInfoBot.js'

DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': 'root',
    'database': 'markets'
}

def send_telegram(msg):
    try:
        if os.path.exists(BOT_SCRIPT):
            subprocess.run(['node', BOT_SCRIPT, msg], check=True, timeout=20)
            print("Telegram report dispatched successfully.")
        else:
            print(f"[Warning] Telegram bot not found at {BOT_SCRIPT}")
    except Exception as e:
        print(f"[Error] Failed to send Telegram alert: {e}")

def get_lot_size(stock, lotsize_df):
    sub = lotsize_df[lotsize_df['stock_clean'] == stock]
    if not sub.empty:
        return float(sub.iloc[-1]['lotsize'])
    return 1000.0  # Safe default fallback

def run_afternoon_simulation():
    today_str = datetime.now().strftime('%Y-%m-%d')
    now_time_str = datetime.now().strftime('%H:%M')
    print(f"=======================================================")
    print(f"📊 Starting Afternoon Short Sell Simulation for {today_str}")
    print(f"=======================================================")

    if not os.path.exists(TARGETS_CSV):
        msg = f"📉 <b>09:41 SHORT SELL DAILY PNL REPORT</b>\n📅 Date: {today_str}\n\n⚠️ No target orders file found for today. Zero trades taken."
        print(msg)
        send_telegram(msg)
        return

    targets_df = pd.read_csv(TARGETS_CSV)
    if targets_df.empty:
        msg = f"📉 <b>09:41 SHORT SELL DAILY PNL REPORT</b>\n📅 Date: {today_str}\n\n⚠️ No short sell targets met the execution threshold today. Zero trades taken."
        print(msg)
        send_telegram(msg)
        return

    # Check date of targets
    file_date = str(targets_df['Date_x'].iloc[0]) if 'Date_x' in targets_df.columns else today_str
    if file_date != today_str:
        print(f"[Notice] Target file date is {file_date}, current date is {today_str}. Simulating for {file_date}...")
        sim_date = file_date
    else:
        sim_date = today_str

    # Load lot sizes
    lotsize_df = pd.read_csv(LOTSIZE_CSV, low_memory=False)
    lotsize_df['stock_clean'] = lotsize_df['stockname'].str.strip().str.upper()

    # Filter for Top 4 Fortress (Ranks 2, 3, 4, 5)
    fortress_ranks = [2, 3, 4, 5]
    trades_df = targets_df[targets_df['daily_rank'].isin(fortress_ranks)].sort_values('daily_rank').copy()

    if trades_df.empty:
        msg = f"📉 <b>09:41 SHORT SELL DAILY PNL REPORT</b>\n📅 Date: {sim_date}\n\n⚠️ No candidates qualified for Top 4 Fortress (Ranks 2, 3, 4, 5) today."
        print(msg)
        send_telegram(msg)
        return

    # Connect to MySQL
    conn = mysql.connector.connect(**DB_CONFIG)
    cur = conn.cursor(dictionary=True)

    sim_results = []

    for _, row in trades_df.iterrows():
        stock = row['clean_stock'].strip().upper()
        rank = int(row['daily_rank'])
        prob = float(row.get('ml_prob', 0.0))
        qty = get_lot_size(stock, lotsize_df)

        cur.execute('''
            SELECT time, open, high, low, close 
            FROM scrapdata_F1 
            WHERE date = %s 
              AND stockname = %s 
              AND is_future = 'F1'
              AND TIME(time) >= '09:41:00'
              AND TIME(time) <= '14:45:00'
            ORDER BY time ASC
        ''', (sim_date, stock))
        ticks = cur.fetchall()

        if not ticks:
            print(f"[Warning] No F1 ticks found for {stock} on {sim_date} between 09:41 and 14:45.")
            continue

        # 1. Entry at 09:41:00 close
        entry_tick = ticks[0]
        entry_price = float(entry_tick['close'])
        entry_time_str = str(entry_tick['time'])[11:16]

        sl_price = round(entry_price * 1.04, 2)  # 4.0% Stop Loss
        tp_price = round(entry_price * 0.99, 2)  # 1.0% Take Profit

        exit_price = None
        exit_time_str = None
        exit_reason = None

        # 2. Monitor minute-by-minute bars from 09:42 onwards
        for t in ticks[1:]:
            t_str = str(t['time'])[11:16]
            h = float(t['high'])
            l = float(t['low'])

            # Stop Loss & Take Profit in same candle -> Worst-case assumption: SL hit first
            if h >= sl_price and l <= tp_price:
                exit_price = sl_price
                exit_time_str = t_str
                exit_reason = "🛑 Stop Loss (4.0%)"
                break
            elif l <= tp_price:
                exit_price = tp_price
                exit_time_str = t_str
                exit_reason = "🎯 Target Hit (1.0%)"
                break
            elif h >= sl_price:
                exit_price = sl_price
                exit_time_str = t_str
                exit_reason = "🛑 Stop Loss (4.0%)"
                break

        # 3. Hard Time Exit at 14:45 Close
        if exit_price is None:
            last_tick = ticks[-1]
            exit_price = float(last_tick['close'])
            exit_time_str = str(last_tick['time'])[11:16]
            exit_reason = "⏱️ Time Exit (14:45)"

        gross_pnl = (entry_price - exit_price) * qty
        net_pnl = gross_pnl - 300.0  # ₹300 flat deduction
        return_pct = ((entry_price - exit_price) / entry_price) * 100

        sim_results.append({
            'date': sim_date,
            'stock': stock,
            'rank': rank,
            'prob': prob,
            'qty': int(qty),
            'entry_time': entry_time_str,
            'entry_price': entry_price,
            'exit_time': exit_time_str,
            'exit_price': exit_price,
            'exit_reason': exit_reason,
            'gross_pnl': gross_pnl,
            'net_pnl': net_pnl,
            'return_pct': return_pct,
            'is_win': 1 if net_pnl > 0 else 0
        })

    cur.close()
    conn.close()

    if not sim_results:
        msg = f"📉 <b>09:41 SHORT SELL DAILY PNL REPORT</b>\n📅 Date: {sim_date}\n\n⚠️ Failed to retrieve price ticks for today's candidates in scrapdata_F1."
        print(msg)
        send_telegram(msg)
        return

    res_df = pd.DataFrame(sim_results)

    # Save to Master Live Tracking CSV
    if os.path.exists(TRACKING_CSV):
        master_df = pd.read_csv(TRACKING_CSV)
        # Avoid duplicate date + stock entries
        master_df = master_df[~((master_df['date'] == sim_date) & (master_df['stock'].isin(res_df['stock'])))]
        master_df = pd.concat([master_df, res_df], ignore_index=True)
    else:
        master_df = res_df
    master_df.to_csv(TRACKING_CSV, index=False)
    print(f"Saved results to tracking CSV: {TRACKING_CSV}")

    # Build Telegram Message
    total_trades = len(res_df)
    wins = int(res_df['is_win'].sum())
    losses = total_trades - wins
    win_rate = (wins / total_trades) * 100 if total_trades > 0 else 0.0
    total_net_pnl = res_df['net_pnl'].sum()
    total_gross_pnl = res_df['gross_pnl'].sum()

    pnl_sign = "🟢" if total_net_pnl >= 0 else "🔴"
    pnl_formatted = f"+₹{total_net_pnl:,.0f}" if total_net_pnl >= 0 else f"-₹{abs(total_net_pnl):,.0f}"

    tg_lines = []
    tg_lines.append(f"📉 <b>09:41 SHORT SELL DAILY PNL REPORT</b>")
    tg_lines.append(f"📅 <b>Date:</b> {sim_date} | <b>Time:</b> {now_time_str} IST")
    tg_lines.append(f"━━━━━━━━━━━━━━━━━━━━━━━━━━")
    tg_lines.append(f"🏆 <b>STRATEGY: TOP 4 FORTRESS (R2, R3, R4, R5)</b>")
    tg_lines.append(f"━━━━━━━━━━━━━━━━━━━━━━━━━━")

    for _, r in res_df.iterrows():
        trade_pnl = r['net_pnl']
        badge = "✅" if trade_pnl > 0 else "❌"
        trade_pnl_str = f"+₹{trade_pnl:,.0f}" if trade_pnl >= 0 else f"-₹{abs(trade_pnl):,.0f}"
        
        tg_lines.append(f"{badge} <b>RANK #{r['rank']} | {r['stock']}</b>")
        tg_lines.append(f"   • Entry: ₹{r['entry_price']:.2f} @ {r['entry_time']}")
        tg_lines.append(f"   • Exit:  ₹{r['exit_price']:.2f} @ {r['exit_time']} ({r['exit_reason']})")
        tg_lines.append(f"   • Qty: {r['qty']} | Move: {r['return_pct']:+.2f}%")
        tg_lines.append(f"   • <b>Net PnL: {trade_pnl_str}</b> (after ₹300 fee)")
        tg_lines.append("")

    tg_lines.append(f"━━━━━━━━━━━━━━━━━━━━━━━━━━")
    tg_lines.append(f"📊 <b>DAY PERFORMANCE SUMMARY:</b>")
    tg_lines.append(f"• Total Trades: <b>{total_trades}</b>")
    tg_lines.append(f"• Win Rate: <b>{win_rate:.1f}%</b> ({wins}W / {losses}L)")
    tg_lines.append(f"• Total Gross PnL: ₹{total_gross_pnl:,.0f}")
    tg_lines.append(f"• <b>TOTAL DAY NET PnL: {pnl_sign} {pnl_formatted}</b>")
    tg_lines.append(f"━━━━━━━━━━━━━━━━━━━━━━━━━━")

    tg_msg = "\n".join(tg_lines)
    print("\n" + tg_msg)
    send_telegram(tg_msg)

if __name__ == '__main__':
    run_afternoon_simulation()
