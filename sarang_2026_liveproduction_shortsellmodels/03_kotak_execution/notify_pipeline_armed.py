#!/usr/bin/env python3
"""
notify_pipeline_armed.py
Broadcasts comprehensive pipeline armed status and active execution parameters
to all Telegram monitoring groups when the daily scheduler initiates trading pipelines.
"""

import sys
import os
import requests
import urllib3.util.connection as urllib3_cn
urllib3_cn.HAS_IPV6 = False
from datetime import datetime
import pytz

IST = pytz.timezone('Asia/Kolkata')

TELEGRAM_CHANNELS = [
    # (Bot Token, Chat ID, Label)
    ("5350311365:AAFkTUBR4IGvgS5Z9mJngz-mgk7-HkhFEYE", "-627025839", "kotak_Critical Alerts"),
    ("5350311365:AAFkTUBR4IGvgS5Z9mJngz-mgk7-HkhFEYE", "-698073972", "Order_Information"),
    ("5350311365:AAFkTUBR4IGvgS5Z9mJngz-mgk7-HkhFEYE", "5372262877", "Admin Direct"),
    ("7920868588:AAE4mPlDQJWnkv9CbmHO8idiSBVnP7K0Gko", "-1002365534285", "Status and Warnings"),
]

def broadcast_telegram(message_html):
    for token, chat_id, label in TELEGRAM_CHANNELS:
        try:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            payload = {
                "chat_id": chat_id,
                "text": message_html,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            }
            resp = requests.post(url, json=payload, timeout=8)
            if resp.status_code == 200:
                print(f"✔ Alert sent successfully to {label} ({chat_id})")
            else:
                print(f"⚠️ Failed to send to {label} ({chat_id}): {resp.text}")
        except Exception as e:
            print(f"❌ Error sending to {label} ({chat_id}): {e}")

def notify_0920():
    now = datetime.now(IST)
    date_str = now.strftime('%Y-%m-%d')
    time_str = now.strftime('%H:%M:%S IST')
    day_name = now.strftime('%A')

    msg = (
        f"🚀 <b>[09:20 SCALP MODEL PIPELINE ARMED & STARTED]</b>\n"
        f"📅 <b>Date:</b> {date_str} ({day_name}) | ⏱️ <b>Time:</b> {time_str}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>• Model:</b> 09:20 Scalp (Binary + Time-Decay ML)\n"
        f"<b>• Capital Allocation:</b> Strict ₹5,00,000 per stock\n"
        f"<b>• Current Workflow:</b>\n"
        f"   1️⃣ Morning tick ingestion running (09:15–09:19 ICICI data buffer)\n"
        f"   2️⃣ ML inference & feature pipeline executing\n"
        f"   3️⃣ Kotak order staging in progress\n"
        f"<b>• Order Entry Time:</b> <b>09:25:00 AM IST</b> (Exact open, -2 ticks entry buffer)\n"
        f"<b>• Exit Protections Armed (100% Single-Leg 3-Stage Trailing):</b>\n"
        f"   🛡️ <b>Stage 1 (Initial SL):</b> <b>-₹5,000 (1.00%)</b> per stock\n"
        f"   🔒 <b>Stage 2 (Profit Floor):</b> Peak ≥ <b>+₹2,000</b> ➔ Locks <b>+₹1,000</b> Floor\n"
        f"   🚀 <b>Stage 3 (Dynamic Trail):</b> Peak ≥ <b>+₹4,000</b> ➔ Locks <b>Peak - ₹750</b> (₹3,250, ₹4,250…)\n"
        f"   ⏱️ <b>5s Live Monitor (09:27–09:40):</b> 5-second Kotak LTP evaluation + <b>Dynamic Basket SL (0.70% / 0.60%)</b>\n"
        f"   🎯 <b>09:36–09:39:30 IST:</b> 30s Cadence Profit Square-Off (Net PnL >= ₹500)\n"
        f"   🚨 <b>09:40:00 IST:</b> Hard Limit-Chaser Cover (LTP + 1 tick)\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚡ <i>Scheduler Status: Online & Armed via thescheduler.js</i>"
    )
    broadcast_telegram(msg)

def notify_0940():
    now = datetime.now(IST)
    date_str = now.strftime('%Y-%m-%d')
    time_str = now.strftime('%H:%M:%S IST')
    day_name = now.strftime('%A')
    dow = now.weekday() # Monday is 0

    if dow == 0:
        msg = (
            f"ℹ️ <b>[09:40 HYBRID MODEL - MONDAY EXCLUSION]</b>\n"
            f"📅 <b>Date:</b> {date_str} ({day_name}) | ⏱️ <b>Time:</b> {time_str}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>• Status:</b> <b>STANDBY / NO TRADING TODAY</b>\n"
            f"<b>• Reason:</b> Monday trading is strictly excluded per empirical audit (-₹19.23L net penalty).\n"
            f"<b>• Next Active Trading Day:</b> Tuesday at 09:41:20 AM IST.\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        broadcast_telegram(msg)
        return

    msg = (
        f"🚀 <b>[09:40 HYBRID MODEL PIPELINE ARMED & STARTED]</b>\n"
        f"📅 <b>Date:</b> {date_str} ({day_name}) | ⏱️ <b>Time:</b> {time_str}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>• Model:</b> 09:42 Hybrid V6/V7 Rebound-Aware Model\n"
        f"<b>• Capital Allocation:</b> ₹7,50,000 per stock (Tue–Fri)\n"
        f"<b>• Current Workflow:</b>\n"
        f"   1️⃣ F1 & Cash tick synchronization (ticks up to 09:40 IST)\n"
        f"   2️⃣ Dual V6/V7 ML inference & Rule 1 pre-entry filtering\n"
        f"   3️⃣ Orders formulation & DB staging\n"
        f"<b>• Order Entry Time:</b> <b>09:42:00 AM IST</b> (Exact open, -2 ticks entry buffer)\n"
        f"<b>• 4-Stage Dynamic Loss Control & Trailing TP Suite Armed:</b>\n"
        f"   ⏱️ <b>Stage 1 (Time-Decay SL):</b> 3.00% (09:42–11:00) ➔ 1.50% (11:00–12:30) ➔ 1.00% (12:30–14:45)\n"
        f"   🔒 <b>Stage 2 (Pre-TP Profit Lock):</b> At +1.25% peak profit, SL locks in +0.50% guaranteed profit\n"
        f"   🚀 <b>Stage 3 (Trailing TP Engine):</b> Activates at +2.00% profit (1.75% initial floor, trails 0.50% behind peak)\n"
        f"   🔄 <b>Stage 4 (Leg 2 Re-Entry):</b> Armed on +0.50% bounce from Leg 1 TP exit (before 14:30)\n"
        f"      ↳ Leg 2 SL: Tight 1.50% above re-entry price\n"
        f"      ↳ Leg 2 Trailing TP: Activates at +1.50% profit, trails 0.75% behind peak\n"
        f"   ⏳ <b>14:30 Pre-Close Exit:</b> Limit cover at -0.20% discount (LTP * 0.998)\n"
        f"   ⚡ <b>14:45 Hard Chaser:</b> Unconditional square-off at LTP + 1 tick\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚡ <i>Scheduler Status: Online & Armed via thescheduler.js</i>"
    )
    broadcast_telegram(msg)

def check_and_set_cooldown(target_name):
    lock_file = f"/tmp/pipeline_armed_{target_name}.lock"
    now_ts = datetime.now().timestamp()
    if os.path.exists(lock_file):
        try:
            with open(lock_file, 'r') as f:
                last_ts = float(f.read().strip())
            if now_ts - last_ts < 120:
                print(f"ℹ️ Cooldown active for {target_name} ({int(now_ts - last_ts)}s ago) — skipping duplicate.")
                return False
        except Exception:
            pass
    try:
        with open(lock_file, 'w') as f:
            f.write(str(now_ts))
    except Exception:
        pass
    return True

if __name__ == "__main__":
    target = sys.argv[1].upper() if len(sys.argv) > 1 else ""
    if "920" in target:
        if check_and_set_cooldown("0920"):
            notify_0920()
    elif "940" in target or "942" in target or "HYBRID" in target:
        if check_and_set_cooldown("0940"):
            notify_0940()
    else:
        print("Usage: notify_pipeline_armed.py [0920|0940]")
