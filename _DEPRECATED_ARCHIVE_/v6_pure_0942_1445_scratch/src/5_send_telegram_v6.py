#!/usr/bin/env python3
"""
5_send_telegram_v6.py
---------------------
Live Telegram Bot Notification Engine for Model v6.
Executes daily at 09:40 AM to generate the Top 4 Short Sell orders and send
an automated alert to Telegram via status_Info_bot.js.
"""

import os
import sys
import subprocess
import pandas as pd
from datetime import date

BASE_DIR = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/v6_pure_0942_1445_scratch'
PREDICT_SCRIPT = os.path.join(BASE_DIR, 'src', '4_predict_today_v6.py')
BOT_SCRIPT = '/home/ubuntu/KotakCodes1/status_Info_bot.js'

def send_telegram_msg(msg):
    if os.path.exists(BOT_SCRIPT):
        try:
            res = subprocess.run(['node', BOT_SCRIPT, msg], capture_output=True, text=True, timeout=15)
            print("Telegram Status Bot Response:", res.stdout.strip())
        except Exception as e:
            print(f"Error calling Telegram Bot script: {e}")
    else:
        print("Warning: Telegram Bot script status_Info_bot.js not found.")

def run_prediction_and_notify(target_date=None):
    today_str = target_date if target_date else date.today().strftime('%Y-%m-%d')
    print(f"🚀 Running Model v6 09:40 AM Prediction for Date: {today_str}...")
    
    cmd = ['python3', PREDICT_SCRIPT]
    if target_date:
        cmd.extend(['--date', target_date])
        
    res = subprocess.run(cmd, capture_output=True, text=True)
    print(res.stdout)
    
    csv_file = os.path.join(BASE_DIR, 'output', f'live_predictions_v6_{today_str}.csv')
    if not os.path.exists(csv_file):
        print(f"Error: Prediction file {csv_file} not generated.")
        return
        
    df_top4 = pd.read_csv(csv_file)
    if len(df_top4) == 0:
        print("No trades selected today.")
        return
        
    msg = f"📉 <b>MODEL v6 LIVE SHORT SELL ORDERS ({today_str})</b>\n"
    msg += f"<b>Entry Time:</b> 09:42 AM IST | <b>Exit Time:</b> 14:45 PM IST\n"
    msg += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    
    for idx, row in df_top4.iterrows():
        stock = row['clean_stock']
        rank = int(row['rank'])
        prob = float(row['prob_win']) * 100.0
        p_0942 = float(row['db_entry_0942_f1'])
        ret = float(row['stock_ret_940'])
        
        msg += f"<b>{rank}. {stock}</b> (SHORT SELL)\n"
        msg += f"  • Est 09:42 Entry Price: ₹{p_0942:.2f}\n"
        msg += f"  • Model Win Prob: {prob:.1f}%\n"
        msg += f"  • 09:40 Return: {ret:+.2f}%\n"
        msg += "------------------------------------\n"
        
    msg += "⚡ <i>Automated signals via Model v6 (100% Pure scrapdata_F1 Ticks)</i>"
    
    print("\nFormatted Telegram Message:\n", msg)
    send_telegram_msg(msg)

if __name__ == '__main__':
    target = None
    if len(sys.argv) > 1:
        if sys.argv[1] == '--date' and len(sys.argv) > 2:
            target = sys.argv[2]
        else:
            target = sys.argv[1]
    run_prediction_and_notify(target)
