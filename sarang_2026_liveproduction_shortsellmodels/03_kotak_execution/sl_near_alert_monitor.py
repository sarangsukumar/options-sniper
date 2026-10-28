#!/usr/bin/env python3
"""
sl_near_alert_monitor.py
========================
1-Minute Active Stop-Loss Proximity Monitor for Short-Sell Models.
Monitors active short positions every 1 minute during market hours.

Key Functions:
1. 09:40 Model (09:50 to 14:40):
   - Instant 2.0% Take Profit (Limit Buy Cover at Kotak LTP).
   - Alerts Telegram on 2.0% SL approaches.
   - 2.25% SL Auto Square-Off Engine (3 consecutive minutes).
   - Hourly status to Status and Warnings.
   
2. 09:20 Model (09:25 to 09:40):
   - Instant Telegram Alert to Status & Warnings group on:
     a) 2.0% Stop Loss breach.
     b) Rs 5000 Total Profit breach.
"""

import os
import sys
import json
import time
import subprocess
import pymysql
import pandas as pd
from datetime import datetime
import warnings
from neo_api_client import NeoAPI
import pyotp

warnings.filterwarnings('ignore')

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(SCRIPT_DIR, 'logs')
STATE_FILE = os.path.join(LOG_DIR, 'sl_alert_state.json')
AUTH_CSV = os.path.join(SCRIPT_DIR, 'kotak_auth_userid.csv')
MASTER_FILE = os.path.join(SCRIPT_DIR, 'masterfile/ICICImaster_EQ.csv')

# Telegram routing: Order_info_bot & Multi-channel Broadcast
TELEGRAM_BOT_TOKEN = "5350311365:AAFkTUBR4IGvgS5Z9mJngz-mgk7-HkhFEYE"
TELEGRAM_CRITICAL_CHAT_ID = "-627025839"      # kotak_Critical Alerts
TELEGRAM_STATUS_CHAT_ID = "-627025839"        # kotak_Critical Alerts (Hourly Status & Alerts)

TELEGRAM_ALL_GROUPS = [
    ("5350311365:AAFkTUBR4IGvgS5Z9mJngz-mgk7-HkhFEYE", "-627025839", "kotak_Critical Alerts"),
    ("5350311365:AAFkTUBR4IGvgS5Z9mJngz-mgk7-HkhFEYE", "-698073972", "Order_Information"),
    ("5350311365:AAFkTUBR4IGvgS5Z9mJngz-mgk7-HkhFEYE", "5372262877", "Admin Direct"),
    ("7920868588:AAE4mPlDQJWnkv9CbmHO8idiSBVnP7K0Gko", "-1002365534285", "Status and Warnings"),
]

os.makedirs(LOG_DIR, exist_ok=True)

def get_db_connection():
    return pymysql.connect(
        host='localhost',
        user='root',
        password='root',
        database='markets',
        cursorclass=pymysql.cursors.DictCursor
    )

SYMBOL_ALIASES = {
    'TATAMOTORS': 'TMPV',
    'TMPV': 'TMPV',
    'IBULHSGFIN': 'SAMMAANCAP',
    'SAMMAANCAP': 'SAMMAANCAP',
    'GMRINFRA': 'GMRP&UI',
    'GMRP&UI': 'GMRP&UI',
    'L&TFH': 'LTF',
    'LTF': 'LTF',
    'LTIMINDTREE': 'LTM',
    'LTIM': 'LTM',
}

_MASTER_TOKEN_CACHE = None
_STOCK_TICK_CACHE = {}

def get_tick_size(price, stockname=None, client=None):
    if stockname:
        raw_sym = str(stockname).strip().upper()
        clean_sym = SYMBOL_ALIASES.get(raw_sym, raw_sym)
        if clean_sym in _STOCK_TICK_CACHE:
            return _STOCK_TICK_CACHE[clean_sym]
        if client is not None:
            try:
                res = client.search_scrip(exchange_segment='nse_cm', symbol=clean_sym)
                data = res if isinstance(res, list) else (res.get('data', []) if isinstance(res, dict) else [])
                for d in data:
                    if str(d.get('pTrdSymbol', '')).strip().upper() == f"{clean_sym}-EQ":
                        dtick = float(d.get('dTickSize', 0) or 0)
                        if dtick > 0:
                            tick_rs = round(dtick / 100.0, 2)
                            _STOCK_TICK_CACHE[clean_sym] = tick_rs
                            _STOCK_TICK_CACHE[raw_sym] = tick_rs
                            return tick_rs
            except Exception:
                pass
    if price <= 250:   return 0.01
    if price <= 1000:  return 0.05
    if price <= 5000:  return 0.10
    if price <= 10000: return 0.50
    if price <= 20000: return 1.00
    return 5.00

def round_to_tick(price, tick_val=None, stockname=None, client=None):
    if price is None or price <= 0:
        return 0.0
    tick = tick_val if tick_val is not None else get_tick_size(price, stockname=stockname, client=client)
    return round(round(price / tick) * tick, 2)

def find_eq_numeric_token(stockname):
    global _MASTER_TOKEN_CACHE
    if not stockname:
        return None
    raw_sym = str(stockname).strip().upper()
    clean_sym = SYMBOL_ALIASES.get(raw_sym, raw_sym)
    try:
        if _MASTER_TOKEN_CACHE is None and os.path.exists(MASTER_FILE):
            df = pd.read_csv(MASTER_FILE, low_memory=False)
            eq_df = df[df['series'].astype(str).str.strip().str.upper() == 'EQ']
            _MASTER_TOKEN_CACHE = dict(zip(
                eq_df['stockcodes'].astype(str).str.strip().str.upper(),
                eq_df['token'].astype(str).str.strip()
            ))
        if _MASTER_TOKEN_CACHE:
            return _MASTER_TOKEN_CACHE.get(clean_sym) or _MASTER_TOKEN_CACHE.get(raw_sym)
    except Exception:
        pass
    return None

def fetch_live_ltp(client, stockname):
    token = find_eq_numeric_token(stockname)
    if not token:
        return 0.0
    try:
        resp = client.quotes([{"instrument_token": token, "exchange_segment": "nse_cm"}], quote_type="ltp")
        if isinstance(resp, list) and len(resp) > 0 and 'ltp' in resp[0]:
            return float(resp[0]['ltp'])
    except Exception:
        pass
    return 0.0

def get_open_buy_orders(client):
    open_orders = {}
    try:
        order_book = client.order_report()
        raw_orders = order_book.get('data', []) if isinstance(order_book, dict) else order_book
        if isinstance(raw_orders, list):
            for o in raw_orders:
                if o.get('exSeg') == 'nse_cm' and o.get('trnsTp') in ('B', 'BUY'):
                    status = str(o.get('ordSt', '')).lower()
                    if status in ('open', 'pending', 'trigger pending', 'put order req received'):
                        sym = o.get('trdSym', '') or o.get('sym', '')
                        clean_sym = sym.replace('-EQ', '').replace('_EQ', '').strip().upper()
                        open_orders[clean_sym] = {
                            'order_id': str(o.get('nOrdNo') or o.get('orderId')),
                            'price': float(o.get('prc') or o.get('price') or 0.0)
                        }
    except Exception as e:
        print(f"⚠️ Order book fetch failed: {e}")
    return open_orders

def reconstruct_lots_from_order_book(client, min_time_str=None, max_time_str=None, exclude_order_ids=None):
    lots_summary = {}
    if exclude_order_ids is None:
        exclude_order_ids = set()
    try:
        order_book = client.order_report()
        raw_orders = order_book.get('data', []) if isinstance(order_book, dict) else order_book
        if not isinstance(raw_orders, list):
            return lots_summary

        filled = [o for o in raw_orders if int(o.get('fldQty', 0) or 0) > 0 or str(o.get('ordSt', '')).lower() == 'complete']
        by_sym = {}
        for o in filled:
            # Exclude explicit order IDs (e.g. from 0920 scalp model when tracking 0940)
            ord_id = str(o.get('nOrdNo', '') or o.get('orderId', '')).strip()
            if ord_id and ord_id in exclude_order_ids:
                continue

            # Time-based model boundary filtering (e.g., 0940 orders start >= 09:41:00)
            ord_dt_tm = str(o.get('ordDtTm', '')).strip()
            parts = ord_dt_tm.split()
            ord_time = parts[1] if len(parts) > 1 else ''
            if ord_time:
                if min_time_str and ord_time < min_time_str:
                    continue
                if max_time_str and ord_time > max_time_str:
                    continue

            sym = (o.get('trdSym', '') or o.get('sym', '')).replace('-EQ', '').replace('_EQ', '').strip().upper()
            if 'GMRP' in sym or 'GMRINFRA' in sym:
                sym = 'GMRINFRA'
            by_sym.setdefault(sym, []).append(o)

        for sym, o_list in by_sym.items():
            o_list.sort(key=lambda x: str(x.get('ordDtTm', '')))
            leg1_sells = []
            leg2_sells = []
            seen_buy = False

            for o in o_list:
                ttype = str(o.get('trnsTp', '')).upper()
                fld = int(o.get('fldQty', 0) or 0)
                qty = fld if fld > 0 else int(o.get('qty', 0) or 0)
                prc = float(o.get('avgPrc', 0) or o.get('prc', 0))
                if qty <= 0 or prc <= 0:
                    continue

                if ttype in ('S', 'SELL'):
                    if seen_buy or leg2_sells:
                        leg2_sells.append({'qty': qty, 'orig_qty': qty, 'price': prc, 'time': o.get('ordDtTm')})
                    else:
                        leg1_sells.append({'qty': qty, 'orig_qty': qty, 'price': prc, 'time': o.get('ordDtTm')})
                elif ttype in ('B', 'BUY'):
                    seen_buy = True

            realized_l1 = 0.0
            realized_l2 = 0.0
            has_l2 = len(leg2_sells) > 0

            all_sells = []
            for s in leg1_sells:
                all_sells.append({'leg': 1, 'qty': s['qty'], 'price': s['price']})
            for s in leg2_sells:
                all_sells.append({'leg': 2, 'qty': s['qty'], 'price': s['price']})

            total_closed_qty = 0
            for o in o_list:
                ttype = str(o.get('trnsTp', '')).upper()
                fld = int(o.get('fldQty', 0) or 0)
                qty = fld if fld > 0 else int(o.get('qty', 0) or 0)
                prc = float(o.get('avgPrc', 0) or o.get('prc', 0))
                if qty <= 0 or prc <= 0:
                    continue

                if ttype in ('B', 'BUY'):
                    rem = qty
                    while rem > 0 and all_sells:
                        top = all_sells[0]
                        matched = min(rem, top['qty'])
                        pnl = (top['price'] - prc) * matched
                        if top['leg'] == 1:
                            realized_l1 += pnl
                        else:
                            realized_l2 += pnl
                        top['qty'] -= matched
                        rem -= matched
                        total_closed_qty += matched
                        if top['qty'] == 0:
                            all_sells.pop(0)

            open_l1_qty = sum(s['qty'] for s in all_sells if s['leg'] == 1)
            open_l2_qty = sum(s['qty'] for s in all_sells if s['leg'] == 2)
            cur_open_qty = open_l1_qty + open_l2_qty
            is_closed = (cur_open_qty == 0)

            orig_entry = (sum(s['orig_qty'] * s['price'] for s in leg1_sells) / sum(s['orig_qty'] for s in leg1_sells)) if leg1_sells else 0.0
            orig_entry = round(orig_entry, 2)
            latest_reentry_price = (sum(s['orig_qty'] * s['price'] for s in leg2_sells) / sum(s['orig_qty'] for s in leg2_sells)) if leg2_sells else 0.0
            latest_reentry_price = round(latest_reentry_price, 2)

            cur_open_ep = (sum(s['qty'] * s['price'] for s in all_sells) / cur_open_qty) if cur_open_qty > 0 else 0.0

            lots_summary[sym] = {
                'orig_entry': orig_entry,
                'latest_reentry_price': latest_reentry_price,
                'cur_open_ep': cur_open_ep,
                'has_l2': has_l2,
                'is_reentry': has_l2 and (open_l2_qty > 0 or cur_open_qty > 0),
                'cur_open_qty': cur_open_qty,
                'open_l1_qty': open_l1_qty,
                'open_l2_qty': open_l2_qty,
                'is_closed': is_closed,
                'total_closed_qty': total_closed_qty,
                'realized_l1': round(realized_l1, 2) if (len(leg1_sells) > 0 and open_l1_qty < sum(s['orig_qty'] for s in leg1_sells)) else None,
                'realized_l2': round(realized_l2, 2) if (has_l2 and open_l2_qty < sum(s['orig_qty'] for s in leg2_sells)) else None,
                'total_realized': round(realized_l1 + realized_l2, 2)
            }
    except Exception as e:
        print(f"⚠️ Reconstruct lots failed: {e}")
    return lots_summary

def execute_limit_squareoff_order(client, stockname, qty, limit_price, model_name, loss_pct, open_buy_orders, action_type="AUTO SQUARE-OFF", stock_pnl=0.0, **kwargs):
    now_str = datetime.now().strftime('%H:%M:%S IST')
    
    raw_sym = str(stockname).strip().upper()
    clean_sym = SYMBOL_ALIASES.get(raw_sym, raw_sym)
    scripcode = f"{clean_sym}-EQ"

    # Cancel open order if it exists
    if stockname in open_buy_orders:
        old_val = open_buy_orders[stockname]
        old_order_id = old_val['order_id'] if isinstance(old_val, dict) else str(old_val)
        print(f"🔄 Cancelling existing open BUY order {old_order_id} for {stockname} before placing {action_type} exit...")
        try:
            client.cancel_order(order_id=old_order_id)
            time.sleep(1) # wait for Kotak to process cancellation
        except Exception as e:
            print(f"⚠️ Cancel failed for {old_order_id}: {e}")
            
    if not qty or int(qty) <= 0:
        print(f"⚠️ [SKIP] {action_type} for {stockname}: Quantity is <= 0 ({qty}). Position already closed.")
        return False

    limit_price = round_to_tick(limit_price, stockname=stockname, client=client)
    limit_price_fmt = f"{limit_price:.2f}"
    print("=" * 75)
    print(f"🚀 [LIVE EXECUTION] {action_type} FOR {model_name}:")
    print(f"   • Stock Name            : {stockname} ({scripcode})")
    print(f"   • Cover Quantity        : {qty}")
    print(f"   • Limit Cover Price     : ₹{limit_price_fmt}")
    if stock_pnl != 0.0:
        print(f"   • Stock PnL             : ₹{stock_pnl:+,.2f}")
    print("=" * 75)

    try:
        resp = client.place_order(
            exchange_segment='nse_cm', product='MIS', price=limit_price_fmt,
            order_type='L', quantity=str(qty), validity='DAY',
            trading_symbol=scripcode, transaction_type='B', amo='NO',
            disclosed_quantity='0', trigger_price='0'
        )
        print(f"Kotak Response: {resp}")
        
        # Check if response indicates success
        if isinstance(resp, dict) and ('Error' in resp or resp.get('stat') == 'Not_Ok' or 'fault' in resp):
            print(f"❌ Order placement rejected by broker for {stockname}: {resp}")
            return False

        order_id = resp.get('nOrdNo') if isinstance(resp, dict) else None
        if not order_id:
            print(f"⚠️ Order placement returned unexpected format for {stockname}: {resp}")
            # If there's an error string or no valid order id, avoid broadcasting false success
            if not isinstance(resp, dict) or 'stat' not in resp:
                return False

        is_profit = ("PROFIT" in action_type.upper() or "TRAIL" in action_type.upper() or "TP" in action_type.upper())
        status_emoji = "🎯" if is_profit else "🚨"
        trigger_label = "Profit Trigger" if is_profit else "Loss Trigger"
        trigger_val = f"+{abs(loss_pct):.2f}%" if is_profit else f"-{loss_pct:.2f}%"
        pnl_line = f" (<b>₹{stock_pnl:+,.2f}</b>)" if stock_pnl != 0.0 else ""
        msg = (
            f"{status_emoji} <b>[{model_name} - {action_type} EXECUTED]</b>\n"
            f"📅 {datetime.now().strftime('%Y-%m-%d')} | ⏱️ {now_str}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>• Stock:</b> <b>{stockname}</b>\n"
            f"<b>• {trigger_label}:</b> <b>{trigger_val}</b>{pnl_line}\n"
            f"<b>• Quantity Covered:</b> {qty}\n"
            f"<b>• Limit Cover Price:</b> <b>₹{limit_price_fmt}</b>\n"
            f"<b>• Kotak Order ID:</b> <code>{order_id or 'UNKNOWN'}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        )
        broadcast_telegram_alert(msg)
        return True
    except Exception as e:
        print(f"❌ Place order failed for {stockname}: {e}")
        return False

def load_alert_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_alert_state(state):
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f, indent=2)
    except Exception:
        pass

def broadcast_telegram_alert(msg):
    """Broadcasts a critical message to all configured Telegram channels."""
    for token, chat_id, label in TELEGRAM_ALL_GROUPS:
        try:
            import urllib.request
            import urllib.parse
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            data = urllib.parse.urlencode({
                'chat_id': chat_id,
                'text': msg,
                'parse_mode': 'HTML',
                'disable_web_page_preview': 'true'
            }).encode('utf-8')
            req = urllib.request.Request(url, data=data)
            with urllib.request.urlopen(req, timeout=8) as resp:
                pass
            print(f"✔ Broadcast alert sent to {label} ({chat_id})")
        except Exception as e:
            print(f"❌ Error broadcasting to {label} ({chat_id}): {e}")

def get_0940_active_sl_pct(current_time_int):
    """
    Returns (sl_pct, tier_name, tier_desc) for the 09:40 model based on time of day.
    Stage 1 Dynamic Time-Decaying SL:
      - 09:42 to 11:00: 2.25% (Morning Volatility Window)
      - 11:00 to 12:30: 1.50% (Midday Consolidation Window)
      - 12:30 to 14:45: 1.00% (Afternoon Trending / Defense Window)
    """
    if current_time_int >= 1230:
        return 1.00, "1.00% AFTERNOON TIGHTENED SL", "Late afternoon risk defense tier (Max loss capped at 1.00%)"
    elif current_time_int >= 1100:
        return 1.50, "1.50% MIDDAY TIGHTENED SL", "Midday consolidation tier (Max loss capped at 1.50%)"
    else:
        return 2.25, "2.25% MORNING INITIAL SL", "Morning volatility tolerance tier (Max loss capped at 2.25%)"

def send_telegram_alert(msg, chat_id=TELEGRAM_CRITICAL_CHAT_ID):
    try:
        import urllib.request
        import urllib.parse
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = urllib.parse.urlencode({
            'chat_id': chat_id,
            'text': msg,
            'parse_mode': 'HTML'
        }).encode('utf-8')
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req, timeout=10) as resp:
            res_data = json.loads(resp.read().decode('utf-8'))
            if res_data.get('ok'):
                print(f"✔ Telegram alert sent successfully to {chat_id}.")
                return True
            else:
                print(f"❌ Telegram API error: {res_data}")
    except Exception as e:
        print(f"❌ Error sending Telegram alert: {e}")
    return False

def send_telegram_photo(image_path, caption, chat_id=TELEGRAM_STATUS_CHAT_ID):
    try:
        import requests
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
        with open(image_path, 'rb') as photo_file:
            resp = requests.post(url, data={'chat_id': chat_id, 'caption': caption, 'parse_mode': 'HTML'}, files={'photo': photo_file}, timeout=15)
        if resp.status_code == 200 and resp.json().get('ok'):
            print(f"✔ Telegram photo alert sent successfully to {chat_id}.")
            return True
        else:
            print(f"❌ Telegram photo error ({resp.status_code}): {resp.text}")
    except Exception as e:
        print(f"❌ Failed to send Telegram photo alert: {e}")
    return False

def generate_pnl_report_image(hourly_items, total_open_pnl, total_realized_pnl, open_count, closed_count, timestamp_str, output_path='/tmp/pnl_report.png'):
    try:
        from PIL import Image, ImageDraw, ImageFont
        from collections import defaultdict

        try:
            font_title = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 26)
            font_subtitle = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 16)
            font_section = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 19)
            font_rule = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 14)
            font_header = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 14)
            font_body = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 14)
            font_body_bold = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 14)
            font_summary_title = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 19)
            font_summary_bold = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 26)
        except Exception:
            font_title = font_subtitle = font_section = font_rule = font_header = font_body = font_body_bold = font_summary_title = font_summary_bold = ImageFont.load_default()

        grouped = defaultdict(list)
        for it in hourly_items:
            grouped[it['model']].append(it)

        width = 1200
        header_h = 100
        summary_h = 150
        table_row_h = 46
        model_header_h = 52
        table_header_h = 40

        total_rows = sum(len(items) for items in grouped.values())
        total_models = len(grouped)

        content_h = (total_models * model_header_h) + (total_models * table_header_h) + (total_rows * table_row_h) + (total_models * 20)
        total_h = header_h + content_h + summary_h + 30

        img = Image.new('RGB', (width, total_h), (15, 23, 42)) # #0F172A
        draw = ImageDraw.Draw(img)

        # --- HEADER BANNER ---
        draw.rectangle([(0, 0), (width, header_h)], fill=(30, 41, 59))
        draw.text((35, 20), '09:40 HYBRID MODEL HOURLY STATUS REPORT', font=font_title, fill=(255, 255, 255))
        draw.text((35, 62), f'Date: {timestamp_str}  |  Dynamic Multi-Leg PnL (L1 & L2 Realized/Unrealized)', font=font_subtitle, fill=(56, 189, 248))

        show_realized_l1   = any(it.get('realized_l1') is not None for it in hourly_items)
        show_unrealized_l1 = any(it.get('unrealized_l1') is not None for it in hourly_items)
        show_realized_l2   = any(it.get('realized_l2') is not None for it in hourly_items)
        show_unrealized_l2 = any(it.get('unrealized_l2') is not None for it in hourly_items)
        all_closed         = all(it.get('is_closed', False) for it in hourly_items)

        pnl_cols = []
        if show_realized_l1:
            pnl_cols.append(('realized_l1', 'Realized (L1)'))
        if show_unrealized_l1:
            pnl_cols.append(('unrealized_l1', 'Unrealized (L1)'))
        if show_realized_l2:
            pnl_cols.append(('realized_l2', 'Realized (L2)'))
        if show_unrealized_l2:
            pnl_cols.append(('unrealized_l2', 'Unrealized (L2)'))
        pnl_cols.append(('total_pnl', 'Total PnL'))

        base_cols = [
            ('stock', 'Stock Name', 145, 'left'),
            ('qty', 'Qty', 55, 'center'),
            ('entry', 'Entry', 95, 'right'),
            ('ltp', 'Status / LTP', 105, 'right'),
        ]
        last_col = ('exit_reason', 'Exit Reason' if all_closed else 'SL / TP Target', 230, 'left')

        avail_pnl_w = (width - 70) - sum(c[2] for c in base_cols) - last_col[2] - 20 # 20px buffer before last col
        pnl_w = int(avail_pnl_w / len(pnl_cols))

        cols = []
        x = 35
        for cid, name, w, align in base_cols:
            cols.append({'id': cid, 'name': name, 'w': w, 'x': x, 'align': align})
            x += w

        for cid, name in pnl_cols:
            cols.append({'id': cid, 'name': name, 'w': pnl_w, 'x': x, 'align': 'right'})
            x += pnl_w

        x += 20 # spacing before last col
        cols.append({'id': last_col[0], 'name': last_col[1], 'w': last_col[2], 'x': x, 'align': last_col[3]})

        y = header_h + 15

        for model_name, items in grouped.items():
            draw.rectangle([(30, y), (width - 30, y + 44)], fill=(15, 23, 42))
            draw.rectangle([(30, y + 5), (38, y + 38)], fill=(250, 204, 21)) # Gold accent bar
            draw.text((50, y + 9), f'Model: {model_name}', font=font_section, fill=(250, 204, 21))
            if '0920' in model_name:
                rule_text = 'Rule: 0.8% TP | 2.0% SL'
            else:
                rule_text = 'Rule: L1 TP 2.0% / SL 2.25% | Re-Entry TP 1.75% / SL Zero Risk'
            draw.text((560, y + 13), rule_text, font=font_rule, fill=(148, 163, 184))
            y += 48

            draw.rectangle([(30, y), (width - 30, y + table_header_h)], fill=(51, 65, 85))
            for col in cols:
                if col['align'] == 'left':
                    draw.text((col['x'], y + 10), col['name'], font=font_header, fill=(203, 213, 225))
                elif col['align'] == 'center':
                    draw.text((col['x'] + col['w']//2, y + 10), col['name'], font=font_header, fill=(203, 213, 225), anchor='ma')
                elif col['align'] == 'right':
                    draw.text((col['x'] + col['w'] - 5, y + 10), col['name'], font=font_header, fill=(203, 213, 225), anchor='ra')
            y += table_header_h

            for idx, it in enumerate(items):
                row_bg = (30, 41, 59) if idx % 2 == 0 else (17, 24, 39)
                draw.rectangle([(30, y), (width - 30, y + table_row_h)], fill=row_bg)

                for col in cols:
                    cid = col['id']
                    if cid == 'stock':
                        draw.text((col['x'], y + 13), it['stock'], font=font_body_bold, fill=(248, 250, 252))
                    elif cid == 'qty':
                        draw.text((col['x'] + col['w']//2, y + 13), str(it['qty']), font=font_body, fill=(226, 232, 240), anchor='ma')
                    elif cid == 'entry':
                        draw.text((col['x'] + col['w'] - 5, y + 13), f"₹{it['entry']:.2f}", font=font_body, fill=(226, 232, 240), anchor='ra')
                    elif cid == 'ltp':
                        ltp_txt = 'CLOSED' if it['is_closed'] else f"₹{it['ltp']:.2f}"
                        c_ltp = (148, 163, 184) if it['is_closed'] else (226, 232, 240)
                        draw.text((col['x'] + col['w'] - 5, y + 13), ltp_txt, font=font_body, fill=c_ltp, anchor='ra')
                    elif cid == 'realized_l1':
                        val = it.get('realized_l1')
                        txt = f"₹{val:+,.2f}" if val is not None else '---'
                        c = (34, 197, 94) if (val is not None and val >= 0) else ((239, 68, 68) if val is not None else (148, 163, 184))
                        draw.text((col['x'] + col['w'] - 5, y + 13), txt, font=font_body_bold, fill=c, anchor='ra')
                    elif cid == 'unrealized_l1':
                        val = it.get('unrealized_l1')
                        pct = it.get('unrealized_l1_pct', 0.0)
                        txt = f"₹{val:+,.2f} ({pct:+.2f}%)" if val is not None else '---'
                        c = (34, 197, 94) if (val is not None and val >= 0) else ((239, 68, 68) if val is not None else (148, 163, 184))
                        draw.text((col['x'] + col['w'] - 5, y + 13), txt, font=font_body_bold, fill=c, anchor='ra')
                    elif cid == 'realized_l2':
                        val = it.get('realized_l2')
                        txt = f"₹{val:+,.2f}" if val is not None else '---'
                        c = (34, 197, 94) if (val is not None and val >= 0) else ((239, 68, 68) if val is not None else (148, 163, 184))
                        draw.text((col['x'] + col['w'] - 5, y + 13), txt, font=font_body_bold, fill=c, anchor='ra')
                    elif cid == 'unrealized_l2':
                        val = it.get('unrealized_l2')
                        pct = it.get('unrealized_l2_pct', 0.0)
                        txt = f"₹{val:+,.2f} ({pct:+.2f}%)" if val is not None else '---'
                        c = (34, 197, 94) if (val is not None and val >= 0) else ((239, 68, 68) if val is not None else (148, 163, 184))
                        draw.text((col['x'] + col['w'] - 5, y + 13), txt, font=font_body_bold, fill=c, anchor='ra')
                    elif cid == 'total_pnl':
                        tot = it['total_pnl']
                        c = (34, 197, 94) if tot >= 0 else (239, 68, 68)
                        draw.text((col['x'] + col['w'] - 5, y + 13), f"₹{tot:+,.2f}", font=font_body_bold, fill=c, anchor='ra')
                    elif cid == 'exit_reason':
                        r_txt = it.get('exit_reason', '---')
                        r_c = (239, 68, 68) if 'SL HIT' in r_txt else ((34, 197, 94) if 'PROFIT' in r_txt else (251, 146, 60))
                        draw.text((col['x'], y + 13), r_txt, font=font_body, fill=r_c)

                y += table_row_h

            y += 18

        total_pnl = total_open_pnl + total_realized_pnl
        draw.rectangle([(30, y), (width - 30, y + 115)], fill=(30, 41, 59), outline=(51, 65, 85), width=2)
        draw.text((50, y + 16), 'TOTAL PnL SUMMARY', font=font_summary_title, fill=(255, 255, 255))

        open_s = f"₹{total_open_pnl:+,.2f}"
        open_c = (34, 197, 94) if total_open_pnl >= 0 else (239, 68, 68)
        draw.text((50, y + 50), f'• Open Positions ({open_count}):', font=font_body, fill=(203, 213, 225))
        draw.text((310, y + 50), open_s, font=font_body_bold, fill=open_c)

        realized_s = f"₹{total_realized_pnl:+,.2f}"
        realized_c = (34, 197, 94) if total_realized_pnl >= 0 else (239, 68, 68)
        draw.text((50, y + 78), f'• Closed Realized ({closed_count}):', font=font_body, fill=(203, 213, 225))
        draw.text((310, y + 78), realized_s, font=font_body_bold, fill=realized_c)

        tot_bg = (22, 101, 52) if total_pnl >= 0 else (153, 27, 27)
        draw.rectangle([(720, y + 16), (width - 50, y + 98)], fill=tot_bg, outline=(255, 255, 255), width=2)
        draw.text((750, y + 24), 'OVERALL TOTAL PnL', font=font_subtitle, fill=(226, 232, 240))
        draw.text((750, y + 52), f'₹{total_pnl:+,.2f}', font=font_summary_bold, fill=(255, 255, 255))

        img.save(output_path)
        return output_path
    except Exception as e:
        print(f"❌ Image generation failed: {e}")
        return None
        return None

def generate_sl_warning_image(alert_items, timestamp_str, output_path='/tmp/sl_warning_card.png'):
    try:
        from PIL import Image, ImageDraw, ImageFont
        try:
            font_title = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 28)
            font_subtitle = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 17)
            font_stock = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 24)
            font_label = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 17)
            font_val = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 18)
            font_val_red = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 20)
        except Exception:
            font_title = font_subtitle = font_stock = font_label = font_val = font_val_red = ImageFont.load_default()

        width = 950
        card_h = 240
        header_h = 100
        total_h = header_h + (len(alert_items) * (card_h + 15)) + 40

        img = Image.new('RGB', (width, total_h), (15, 23, 42))
        draw = ImageDraw.Draw(img)

        # Header Banner
        draw.rectangle([(0, 0), (width, header_h)], fill=(153, 27, 27)) # Crimson Red
        draw.text((30, 20), '⚠️ STOP-LOSS PROXIMITY WARNING ALERT', font=font_title, fill=(255, 255, 255))
        draw.text((30, 62), f'📅 {timestamp_str}  |  ⚡ Crossed 2.0% Loss Threshold (2.25% SL Auto Cover)', font=font_subtitle, fill=(254, 202, 202))

        y = header_h + 20

        for a in alert_items:
            stk = a['stock']
            model = a['model']
            qty = a['qty']
            ep = a['entry']
            ltp = a['ltp']
            sl_225 = round(ep * 1.0225, 2)
            dist_to_sl = round(sl_225 - ltp, 2)
            loss_pct = a['loss_pct']
            spnl = a['stock_pnl']
            breaches = a.get('consecutive_breaches', 1)

            draw.rectangle([(30, y), (width - 30, y + card_h)], fill=(30, 41, 59), outline=(239, 68, 68), width=3)
            
            draw.rectangle([(30, y), (width - 30, y + 50)], fill=(127, 29, 29))
            draw.text((50, y + 10), f'🚨 {stk}', font=font_stock, fill=(255, 255, 255))
            draw.text((300, y + 15), f'Model: {model}  |  Qty: {qty}', font=font_subtitle, fill=(254, 202, 202))

            draw.text((50, y + 65), '• Entry Price:', font=font_label, fill=(203, 213, 225))
            draw.text((180, y + 65), f'₹{ep:.2f}', font=font_val, fill=(248, 250, 252))

            draw.text((380, y + 65), '• Current LTP:', font=font_label, fill=(203, 213, 225))
            draw.text((520, y + 65), f'₹{ltp:.2f}', font=font_val_red, fill=(239, 68, 68))

            draw.text((50, y + 105), '• Current Loss %:', font=font_label, fill=(203, 213, 225))
            draw.text((210, y + 105), f'-{loss_pct:.2f}%', font=font_val_red, fill=(239, 68, 68))

            draw.text((380, y + 105), '• Current Loss (₹):', font=font_label, fill=(203, 213, 225))
            draw.text((560, y + 105), f'₹{spnl:+.2f}', font=font_val_red, fill=(239, 68, 68))

            draw.text((50, y + 145), '• 2.25% SL Level:', font=font_label, fill=(203, 213, 225))
            draw.text((220, y + 145), f'₹{sl_225:.2f}', font=font_val, fill=(251, 146, 60))

            draw.text((380, y + 145), '• Distance to SL Exit:', font=font_label, fill=(203, 213, 225))
            dist_str = f'₹{dist_to_sl:.2f} away' if dist_to_sl > 0 else 'BREACHED'
            draw.text((580, y + 145), dist_str, font=font_val_red, fill=(250, 204, 21))

            draw.rectangle([(50, y + 185), (width - 50, y + 225)], fill=(17, 24, 39))
            draw.text((70, y + 193), f'⚠️ Action Trigger: Auto Square-off on 3 consecutive breaches (Current Count: {breaches}/3)', font=font_subtitle, fill=(252, 165, 165))

            y += card_h + 15

        img.save(output_path)
        return output_path
    except Exception as e:
        print(f"❌ SL Warning image generation failed: {e}")
        return None

def main():
    import pytz
    ist = pytz.timezone('Asia/Kolkata')
    now = datetime.now(ist)
    today_str = now.strftime('%Y-%m-%d')
    now_ts = time.time()
    
    force_hourly = '--force-hourly' in sys.argv
    current_time_int = int(now.strftime('%H%M'))
    
    # Check if inside any valid window
    is_0920_window = (925 <= current_time_int <= 940)
    is_0940_window = (943 <= current_time_int <= 1515) or force_hourly
    
    if not (is_0920_window or is_0940_window or force_hourly):
        print(f"[{now.strftime('%H:%M:%S IST')}] Outside monitoring windows (09:25-09:40 & 09:43-15:15). Exiting.")
        return

    # Fetch Today's Active Short Sell Orders
    conn = get_db_connection()
    with conn.cursor() as c:
        c.execute("""
            SELECT model_name, stockname, quantity, limit_price, filled_price, broker_order_id
            FROM shortsell_orders
            WHERE trade_date = CURDATE()
              AND (model_name LIKE '%0940%' OR model_name LIKE '%0942%' OR model_name LIKE '%HYBRID%' OR model_name LIKE '%0920%')
        """)
        orders = c.fetchall()
    conn.close()

    if not orders:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] No relevant active orders found today. Exiting.")
        return

    # Extract broker order IDs from 0920 scalp model so they are completely excluded from 0940 lot reconstruction
    scalp_0920_order_ids = {
        str(r['broker_order_id']).strip()
        for r in orders
        if r.get('broker_order_id') and '0920' in str(r.get('model_name', '')).upper()
    }

    stock_map = {}
    for r in orders:
        model = str(r['model_name']).strip()
        is_0940 = any(m_id in model.upper() for m_id in ('0940', '0942', 'HYBRID'))
        is_0920 = '0920' in model.upper()
        
        # Only process if they fit the current time window (hourly report will only show active model's stocks)
        if is_0940 and not is_0940_window and not force_hourly:
            continue
        if is_0920 and not is_0920_window and not force_hourly:
            continue
            
        stk = r['stockname'].strip().upper()
        ep = float(r['filled_price'] or r['limit_price'] or 0.0)
        stock_map[stk] = {
            'model_name': model,
            'quantity': r['quantity'],
            'entry_price': ep,
            'is_0940': is_0940,
            'is_0920': is_0920
        }

    if not stock_map:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] No active orders for the current time window. Exiting.")
        return

    try:
        df_auth = pd.read_csv(AUTH_CSV)
        row = df_auth.iloc[0]
        client = NeoAPI(consumer_key=str(row['consumer_key']), environment='prod', neo_fin_key='neotradeapi')
        totp_code = pyotp.TOTP(str(row['totp_secret'])).now()
        client.totp_login(mobile_number=f"+91{row['mobile_number']}", ucc=str(row['userid']), totp=totp_code)
        client.totp_validate(mpin=str(row['MPIN']))
    except Exception as e:
        print(f"❌ Kotak login failed: {e}")
        return

    try:
        pos_resp = client.positions()
        pos_list = pos_resp.get('data', []) if isinstance(pos_resp, dict) else (pos_resp if isinstance(pos_resp, list) else [])
    except Exception as e:
        print(f"❌ Failed to fetch positions: {e}")
        return

    open_buy_orders = get_open_buy_orders(client)

    # Reconstruct lots with strict model boundaries:
    # 0940 model orders start strictly >= 09:41:00 and exclude any 0920 scalp order IDs
    if is_0940_window:
        lots_summary = reconstruct_lots_from_order_book(
            client,
            min_time_str='09:41:00',
            exclude_order_ids=scalp_0920_order_ids
        )
    elif is_0920_window:
        lots_summary = reconstruct_lots_from_order_book(
            client,
            max_time_str='09:40:59'
        )
    else:
        lots_summary = reconstruct_lots_from_order_book(client)

    broker_positions = {}
    total_realized_pnl = 0.0
    closed_count = 0
    for p in pos_list:
        if p.get('prod') != 'MIS':
            continue
        sym = (p.get('trdSym', '') or p.get('sym', '')).replace('-EQ', '').replace('_EQ', '').strip().upper()
        if "GMRP" in sym or "GMRINFRA" in sym: sym = "GMRINFRA"
        fl_sell, cf_sell = int(p.get('flSellQty', 0) or 0), int(p.get('cfSellQty', 0) or 0)
        fl_buy, cf_buy   = int(p.get('flBuyQty', 0) or 0), int(p.get('cfBuyQty', 0) or 0)
        sell_qty = fl_sell + cf_sell
        buy_qty = fl_buy + cf_buy
        net_short = sell_qty - buy_qty
        
        sell_amt = float(p.get('sellAmt', 0) or 0)
        buy_amt = float(p.get('buyAmt', 0) or 0)
        avg_sell_price = round(sell_amt / sell_qty, 2) if sell_qty > 0 else 0.0
        avg_buy_price = round(buy_amt / buy_qty, 2) if buy_qty > 0 else 0.0
        
        is_closed = (net_short == 0 and sell_qty > 0)
        realized_pnl = round(sell_amt - buy_amt, 2) if is_closed else 0.0
        
        broker_positions[sym] = {
            'qty': net_short,
            'avg_entry': avg_sell_price,
            'avg_buy': avg_buy_price,
            'is_closed': is_closed,
            'realized_pnl': realized_pnl
        }

    # Enhance broker_positions with FIFO order book reconstruction
    for sym, lot in lots_summary.items():
        if sym in broker_positions:
            bp = broker_positions[sym]
            bp['cur_open_qty'] = lot['cur_open_qty']
            bp['cur_open_ep'] = lot['cur_open_ep']
            bp['latest_reentry_price'] = lot['latest_reentry_price']
            bp['orig_entry'] = lot['orig_entry']
            # Override blended broker entry price with exact model-isolated entry price
            if lot['cur_open_ep'] > 0:
                bp['avg_entry'] = lot['cur_open_ep']
            elif lot['orig_entry'] > 0:
                bp['avg_entry'] = lot['orig_entry']
            if lot['cur_open_qty'] > 0:
                bp['qty'] = lot['cur_open_qty']
            bp['realized_pnl'] = lot.get('total_realized', 0.0)
            bp['total_realized'] = lot.get('total_realized', 0.0)
            bp['realized_l1'] = lot.get('realized_l1')
            bp['realized_l2'] = lot.get('realized_l2')
            bp['has_l2'] = lot.get('has_l2', False)
            bp['is_reentry'] = lot['is_reentry']
            bp['is_closed'] = lot['is_closed'] or (bp.get('qty', 0) <= 0)
            bp['total_closed_qty'] = lot['total_closed_qty']
        else:
            broker_positions[sym] = {
                'qty': lot['cur_open_qty'],
                'cur_open_qty': lot['cur_open_qty'],
                'cur_open_ep': lot['cur_open_ep'],
                'latest_reentry_price': lot['latest_reentry_price'],
                'orig_entry': lot['orig_entry'],
                'avg_entry': lot['cur_open_ep'] if lot['cur_open_ep'] > 0 else lot['orig_entry'],
                'avg_buy': 0.0,
                'is_closed': lot['is_closed'],
                'realized_pnl': lot.get('total_realized', 0.0),
                'total_realized': lot.get('total_realized', 0.0),
                'realized_l1': lot.get('realized_l1'),
                'realized_l2': lot.get('realized_l2'),
                'has_l2': lot.get('has_l2', False),
                'is_reentry': lot['is_reentry'],
                'total_closed_qty': lot['total_closed_qty']
            }

    alert_state = load_alert_state()
    meta = alert_state.get('_meta', {})
    last_global_hourly = meta.get('last_hourly_report_time', 0)
    force_hourly = '--force-hourly' in sys.argv
    is_hourly_due = force_hourly or (now_ts - last_global_hourly >= 3600)

    alerts_to_send_0940 = []
    hourly_items = []
    total_open_pnl = 0.0
    open_count = 0

    print(f"[{datetime.now(ist).strftime('%H:%M:%S')}] Monitoring {len(stock_map)} matched stocks across Kotak shorts...")

    for stk, info in stock_map.items():
        if stk not in broker_positions:
            continue 

        broker_pos = broker_positions[stk]
        stk_state = alert_state.get(stk, {})
        model = info['model_name']
        if stk_state.get('trade_date') != today_str or stk_state.get('active_model') != model:
            stk_state = {
                'trade_date': today_str,
                'active_model': model,
                'is_armed_notified': False,
                'last_hourly_time': 0,
                'consecutive_breaches': 0,
                'tp_executed': False,
                'tp_trigger_time': 0,
                'last_sq_trigger_time': 0
            }

        is_reentry = broker_pos.get('is_reentry', False)
        is_closed = broker_pos.get('is_closed', False) or (broker_pos.get('qty', 0) <= 0)
        realized_pnl = broker_pos.get('realized_pnl', 0.0)
        orig_ep = broker_pos.get('orig_entry') or info['entry_price']

        # Auto-detect re-entry status in state (whether manual or automated)
        if is_reentry:
            stk_state['reentry_status'] = 'REENTRY_ACTIVE'
            stk_state['reentry_executed'] = True
            stk_state['reentry_price'] = broker_pos.get('latest_reentry_price', broker_pos.get('cur_open_ep', orig_ep))
            stk_state['reentry_qty'] = broker_pos.get('cur_open_qty', broker_pos['qty'])
            stk_state['leg1_entry_price'] = orig_ep
            stk_state['leg1_realized_pnl'] = realized_pnl
            stk_state['reentry_sl'] = round_to_tick(stk_state['reentry_price'] * 1.015, stockname=stk, client=client)  # Tight 1.50% SL above Leg 2 re-entry
            stk_state['reentry_tp2'] = round_to_tick(stk_state['reentry_price'] * 0.985, stockname=stk, client=client) # 1.50% profit trailing activation

        # If stock is already squared off in broker
        if is_closed:
            if broker_pos.get('has_l2'):
                stk_state['reentry_executed'] = True
                if stk_state.get('reentry_status') not in ('REENTRY_COMPLETED', 'FLAT_COMPLETED'):
                    stk_state['reentry_status'] = 'REENTRY_COMPLETED'
            if info['is_0940'] and is_hourly_due:
                tot_pnl = broker_pos.get('total_realized', realized_pnl)
                if stk_state.get('sl_triggered'):
                    exit_reason = 'CLOSED (SL HIT)'
                elif stk_state.get('pre_tp_lock_triggered'):
                    exit_reason = 'CLOSED (PRE-TP LOCK +0.50%)'
                elif stk_state.get('tp_triggered') or stk_state.get('tp2_triggered'):
                    exit_reason = 'CLOSED (TRAILING TP HIT)'
                elif tot_pnl > 0:
                    exit_reason = 'CLOSED (PROFIT / EOD EXIT)'
                else:
                    exit_reason = 'CLOSED (EOD EXIT)'

                hourly_items.append({
                    'stock': stk,
                    'model': model,
                    'qty': broker_pos.get('total_closed_qty', info.get('quantity', 0)),
                    'is_closed': True,
                    'is_reentry': broker_pos.get('has_l2', False),
                    'entry': broker_pos.get('orig_entry', orig_ep),
                    'ltp': 0.0,
                    'pnl_pct': 0.0,
                    'sl_price': 0.0,
                    'tp_price': 0.0,
                    'stock_pnl': 0.0,
                    'realized_l1': broker_pos.get('realized_l1'),
                    'unrealized_l1': None,
                    'realized_l2': broker_pos.get('realized_l2'),
                    'unrealized_l2': None,
                    'total_pnl': tot_pnl,
                    'exit_reason': exit_reason
                })

            # Leg 2 Re-entry evaluation for 09:40 Model (only if not already re-entered):
            if info['is_0940'] and is_0940_window and not is_reentry and not broker_pos.get('has_l2') and not stk_state.get('reentry_executed'):
                # Check realized profit percentage for closed positions (supports automated and manual TP >= 1.50%)
                entry_p = broker_pos.get('orig_entry') or broker_pos.get('avg_entry') or info['entry_price']
                exit_p = broker_pos.get('avg_buy', 0.0)
                closed_qty = broker_pos.get('total_closed_qty') or info.get('quantity', 0)
                realized_pnl = broker_pos.get('total_realized') if broker_pos.get('total_realized') is not None else broker_pos.get('realized_pnl', 0.0)

                booked_profit_pct = 0.0
                if entry_p > 0 and exit_p > 0:
                    booked_profit_pct = ((entry_p - exit_p) / entry_p) * 100.0
                elif entry_p > 0 and closed_qty > 0 and realized_pnl > 0:
                    booked_profit_pct = (realized_pnl / (entry_p * closed_qty)) * 100.0

                is_auto_tp = (stk_state.get('tp_triggered') or stk_state.get('leg1_status') == 'TP_EXECUTED')
                is_manual_tp = (not is_auto_tp) and (booked_profit_pct >= 1.50)
                qualifies_for_reentry = (is_auto_tp or is_manual_tp)

                # 1. Detect if Leg 1 TP completed filling in Kotak (Automated 2.0% or Manual >= 1.50%)
                if qualifies_for_reentry:
                    if stk_state.get('reentry_status') not in ('AWAITING_REENTRY', 'FLAT_COMPLETED', 'REENTRY_ACTIVE', 'REENTRY_COMPLETED'):
                        tp_exit_price = exit_p or stk_state.get('tp_price') or round_to_tick(entry_p * 0.9800)
                        if tp_exit_price <= 0:
                            tp_exit_price = round_to_tick(entry_p * 0.9800)
                        rep = round_to_tick(tp_exit_price * 1.0050) # +0.50% bounce trigger level

                        actual_realized = realized_pnl if realized_pnl != 0.0 else round((entry_p - tp_exit_price) * closed_qty, 2)

                        stk_state['leg1_status'] = 'TP_EXECUTED'
                        stk_state['leg1_entry_price'] = entry_p
                        stk_state['leg1_exit_price'] = tp_exit_price
                        stk_state['leg1_realized_pnl'] = actual_realized
                        stk_state['leg1_qty'] = closed_qty
                        stk_state['reentry_status'] = 'AWAITING_REENTRY'
                        stk_state['reentry_trigger_price'] = rep
                        alert_state[stk] = stk_state
                        save_alert_state(alert_state)

                        mode_label = f"MANUAL TP (+{booked_profit_pct:.2f}%)" if is_manual_tp else "LEG 1 TP"
                        print(f"🎯 [{stk}] {mode_label} Confirmed Filled @ ₹{tp_exit_price:.2f}. Awaiting Re-Entry Bounce at ₹{rep:.2f} (+0.50%).")

                        mode_note = f"<b>• Mode:</b> Manual Square-Off (+{booked_profit_pct:.2f}% >= 1.50%)\n" if is_manual_tp else ""
                        broadcast_telegram_alert(
                            f"🎯 <b>[{model} - {mode_label} FILLED & MONITORING RE-ENTRY]</b>\n"
                            f"📅 {today_str} | ⏱️ {datetime.now(ist).strftime('%H:%M:%S IST')}\n"
                            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                            f"<b>• Stock:</b> <b>{stk}</b>\n"
                            f"<b>• Leg 1 Entry:</b> ₹{entry_p:.2f} | <b>Exit (TP):</b> ₹{tp_exit_price:.2f}\n"
                            f"<b>• Realized Profit:</b> <b>+₹{actual_realized:+,.2f}</b> (+{booked_profit_pct:.2f}%)\n"
                            f"{mode_note}"
                            f"<b>• Re-Entry Trigger:</b> <b>₹{rep:.2f}</b> (+0.50% Bounce from TP)\n"
                            f"<b>• Window:</b> Active until 14:30 IST\n"
                            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                        )

                        # Update notes in MySQL if manual TP
                        if is_manual_tp:
                            try:
                                conn_db = get_db_connection()
                                with conn_db.cursor() as c_db:
                                    c_db.execute("""
                                        UPDATE shortsell_orders
                                        SET notes = CONCAT(IFNULL(notes, ''), ' | MANUAL_TP_EXIT_₹', %s)
                                        WHERE trade_date = CURDATE() AND stockname = %s AND model_name LIKE %s
                                    """, (f"{tp_exit_price:.2f}", stk, f"%{model}%"))
                                conn_db.commit()
                                conn_db.close()
                            except Exception as e_db:
                                print(f"⚠️ Note update failed for {stk}: {e_db}")

                # 2. 1-Minute Active Monitoring for Re-entry Bounce
                if stk_state.get('reentry_status') == 'AWAITING_REENTRY':
                    if current_time_int > 1430:
                        print(f"⏳ [{stk}] 14:30 reached. Re-entry window closed without bounce.")
                        stk_state['reentry_status'] = 'FLAT_COMPLETED'
                        alert_state[stk] = stk_state
                        save_alert_state(alert_state)
                        continue

                    ltp = fetch_live_ltp(client, stk)
                    if ltp <= 0:
                        continue

                    rep = stk_state['reentry_trigger_price']
                    print(f"👀 [{stk}] Monitoring Re-Entry: LTP=₹{ltp:.2f} | Trigger=₹{rep:.2f} (Need >= ₹{rep:.2f})")

                    if ltp >= rep:
                        print(f"🚀 [{stk}] BOUNCE DETECTED! LTP ₹{ltp:.2f} >= Trigger ₹{rep:.2f}. Calling Neo_shortsell_mis_order.py REENTRY...")
                        re_qty = stk_state.get('leg1_qty', info['quantity'])
                        re_limit = round_to_tick(ltp)

                        reentry_script = os.path.join(SCRIPT_DIR, 'Neo_shortsell_mis_order.py')
                        cmd = [
                            sys.executable,
                            reentry_script,
                            model,
                            'REENTRY',
                            stk,
                            str(re_qty),
                            str(re_limit)
                        ]
                        try:
                            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                            print(f"Re-entry stdout:\n{proc.stdout}")
                            if proc.returncode != 0:
                                print(f"⚠️ Re-entry stderr:\n{proc.stderr}")
                        except Exception as pe:
                            print(f"❌ Failed to run re-entry subprocess: {pe}")

                        # Reload / Update state
                        stk_state['reentry_status'] = 'REENTRY_ACTIVE'
                        stk_state['reentry_price'] = re_limit
                        stk_state['reentry_qty'] = re_qty
                        stk_state['reentry_time'] = now_ts
                        stk_state['reentry_sl'] = round_to_tick(re_limit * 1.015)  # Tight 1.50% SL above Leg 2 re-entry
                        stk_state['reentry_tp2'] = round_to_tick(re_limit * 0.985)  # 1.50% trailing activation
                        stk_state['reentry_executed'] = True
                        alert_state[stk] = stk_state
                        save_alert_state(alert_state)

            # Don't do active SL/TP checks for closed positions
            continue

        ltp = fetch_live_ltp(client, stk)
        if ltp <= 0:
            continue

        qty = broker_pos['qty']

        # Determine if this position is Leg 2 Re-entry or Leg 1
        is_leg2 = (stk_state.get('reentry_status') == 'REENTRY_ACTIVE')
        if is_leg2:
            ep = stk_state.get('reentry_price', broker_pos['avg_entry'])
        else:
            ep = broker_pos['avg_entry'] if broker_pos['avg_entry'] > 0 else info['entry_price']

        if ep <= 0:
            continue

        loss_pct = ((ltp - ep) / ep) * 100.0
        stock_pnl = (ep - ltp) * qty
        total_open_pnl += stock_pnl
        open_count += 1
        pnl_pct = -loss_pct  # positive is profit, negative is loss

        # ==========================================
        # LOGIC FOR 09:20 MODEL (09:25 to 09:40)
        # ==========================================
        # ==========================================
        # LOGIC FOR 09:20 MODEL (09:25 to 09:40)
        # 50/50 Split Strategy: Base Stop Loss (₹3,000 / 0.60%)
        # Take Profit is handled by passive resting book order (Leg 1, ₹2,000 TP)
        # and 09:36-09:39 30s cadence check (Leg 2, ₹500+ TP).
        # ==========================================
        if info['is_0920'] and is_0920_window:
            # Base Stop Loss: ₹3,000 risk or 0.60% adverse move
            hit_sl = (loss_pct >= 0.60 or stock_pnl <= -3000.0 or loss_pct >= 2.0)
            
            if hit_sl:
                limit_cover_price = round_to_tick(ltp + 0.10)
                action_type = "BASE STOP LOSS (₹3,000 / 0.60%)"
                    
                existing_open = open_buy_orders.get(stk)
                open_price = existing_open['price'] if isinstance(existing_open, dict) else 0.0
                if existing_open and abs(open_price - limit_cover_price) < 0.01:
                    print(f"⏳ [{stk}] 09:20 {action_type} limit buy order already resting at ₹{limit_cover_price:.2f}. Awaiting fill.")
                else:
                    execute_limit_squareoff_order(client, stk, qty, limit_cover_price, model, loss_pct, open_buy_orders, action_type, stock_pnl=stock_pnl)
                    
            alert_state[stk] = stk_state

        # ==========================================
        # LOGIC FOR 09:40 MODEL (09:50 to 14:40)
        # ==========================================
        if info['is_0940'] and is_0940_window:
            if is_leg2:
                # Stage 4: Leg 2 Re-Entry Logic
                orig_ep = stk_state.get('leg1_entry_price', info['entry_price'])
                
                # New Tight 1.50% SL above Re-entry Price
                leg2_sl = stk_state.get('reentry_sl')
                if not leg2_sl or leg2_sl == orig_ep: # Backward compatibility
                    leg2_sl = round_to_tick(ep * 1.015)
                    stk_state['reentry_sl'] = leg2_sl
                
                # Leg 2 Trailing TP Engine Setup
                min_ltp_l2 = min(ltp, stk_state.get('leg2_min_ltp', ltp))
                stk_state['leg2_min_ltp'] = min_ltp_l2
                max_profit_pct_l2 = ((ep - min_ltp_l2) / ep) * 100.0
                
                trail_active2 = stk_state.get('leg2_trail_active', False)
                leg2_tp_activation = round_to_tick(ep * 0.985) # 1.50% profit activation
                
                if not trail_active2 and ltp <= leg2_tp_activation:
                    trail_active2 = True
                    stk_state['leg2_trail_active'] = True
                    # Telegram Alert for Leg 2 Trail Activation
                    msg = (
                        f"🚀 <b>[{model} - LEG 2 TRAILING ACTIVATED]</b>\n"
                        f"<b>• Stock:</b> <b>{stk}</b>\n"
                        f"<b>• Re-entry:</b> ₹{ep:.2f} | <b>LTP:</b> ₹{ltp:.2f} (+{pnl_pct:.2f}%)\n"
                        f"<b>• Rule:</b> Activated at 1.50%. Trailing 0.75% behind peak.\n"
                    )
                    broadcast_telegram_alert(msg)
                
                # Update Trailing Stop if active
                if trail_active2:
                    trail_dist = 0.75
                    leg2_active_sl = min(leg2_tp_activation, round_to_tick(min_ltp_l2 * (1.0 + trail_dist / 100.0)))
                else:
                    leg2_active_sl = leg2_sl

                if not stk_state.get('is_leg2_armed_notified'):
                    pnl_s = "+" if stock_pnl >= 0 else "-"
                    pnl_pct_s = "+" if pnl_pct >= 0 else ""
                    armed_msg = (
                        f"🛡️ <b>[{model} - LEG 2 EXIT MONITOR ARMED]</b>\n"
                        f"<b>• Stock:</b> <b>{stk}</b>\n"
                        f"<b>• Leg 2 Re-Entry Price:</b> ₹{ep:.2f} | <b>Qty:</b> {qty}\n"
                        f"<b>• Leg 2 Trailing Target:</b> Activates at <b>₹{leg2_tp_activation:.2f}</b> (1.50% profit)\n"
                        f"<b>• Leg 2 SL (1.50% Risk):</b> <b>₹{leg2_sl:.2f}</b>\n"
                        f"<b>• Current PnL:</b> <b>{pnl_pct_s}{pnl_pct:.2f}%</b> (<b>₹{pnl_s}{abs(stock_pnl):.2f}</b>)\n"
                        f"<b>• Rules:</b> Immediate Limit Cover at LTP upon SL breach or Trailing Target hit."
                    )
                    broadcast_telegram_alert(armed_msg)
                    stk_state['is_leg2_armed_notified'] = True

                if is_hourly_due:
                    hourly_items.append({
                        'stock': f"{stk} (RE-ENTRY)", 'model': model, 'qty': qty,
                        'is_closed': False, 'is_reentry': True, 'entry': ep, 'orig_entry': orig_ep,
                        'ltp': ltp, 'pnl_pct': pnl_pct, 'sl_price': leg2_active_sl, 'tp_price': leg2_tp_activation,
                        'stock_pnl': stock_pnl, 'realized_l1': broker_pos.get('realized_l1', stk_state.get('leg1_realized_pnl', realized_pnl)),
                        'unrealized_l1': None, 'realized_l2': None, 'unrealized_l2': stock_pnl,
                        'unrealized_l2_pct': pnl_pct,
                        'total_pnl': round((broker_pos.get('realized_l1') or stk_state.get('leg1_realized_pnl', 0.0) or 0.0) + stock_pnl, 2),
                        'exit_reason': f"SL: ₹{leg2_active_sl:.2f}"
                    })

                # Exit Logic for Leg 2 (SL or Trailing TP)
                if ltp >= leg2_active_sl:
                    limit_cover_price = round_to_tick(ltp)
                    reason_str = "LEG 2 TRAILING TP EXIT" if trail_active2 else "LEG 2 STOP LOSS (1.50%)"
                    existing_open = open_buy_orders.get(stk)
                    open_price = existing_open['price'] if isinstance(existing_open, dict) else 0.0
                    if existing_open and abs(open_price - limit_cover_price) < 0.01:
                        print(f"⏳ [{stk}] {reason_str} limit buy order already resting at ₹{limit_cover_price:.2f}. Awaiting fill.")
                        success = False
                    else:
                        print(f"🛑 [{stk}] {reason_str} Hit! LTP: ₹{ltp:.2f} >= Trigger: ₹{leg2_active_sl:.2f}")
                        success = execute_limit_squareoff_order(
                            client=client, stockname=stk, qty=qty, limit_price=limit_cover_price,
                            model_name=model, loss_pct=loss_pct, open_buy_orders=open_buy_orders,
                            action_type=reason_str, stock_pnl=stock_pnl
                        )
                    if success:
                        stk_state['reentry_status'] = 'REENTRY_COMPLETED'
                        stk_state['reentry_exit_price'] = limit_cover_price
                        stk_state['reentry_realized_pnl'] = stock_pnl
                        if trail_active2:
                            stk_state['tp2_triggered'] = True
                        else:
                            stk_state['sl2_triggered'] = True
                        try:
                            conn_db = get_db_connection()
                            with conn_db.cursor() as c_db:
                                db_note = f" | LEG2_TRAIL_TP_₹{limit_cover_price:.2f}" if trail_active2 else f" | LEG2_SL_EXIT_₹{limit_cover_price:.2f}"
                                c_db.execute(f"UPDATE shortsell_orders SET notes = CONCAT(IFNULL(notes, ''), '{db_note}') WHERE trade_date = CURDATE() AND stockname = '{stk}' AND model_name LIKE '%{model}%'")
                            conn_db.commit()
                            conn_db.close()
                        except Exception as e_db:
                            print(f"⚠️ Note update failed for {stk}: {e_db}")

            else:
                # Stage 1: Dynamic Time-Decay SL
                decay_sl_pct, decay_tier_name, _ = get_0940_active_sl_pct(current_time_int)
                base_sl = round_to_tick(ep * (1.0 + decay_sl_pct / 100.0))
                
                # Check for Telegram Alert on SL Tightening Transition
                last_alerted_tier = stk_state.get('alerted_sl_tier')
                if last_alerted_tier != decay_tier_name:
                    stk_state['alerted_sl_tier'] = decay_tier_name
                    if last_alerted_tier is not None:
                        msg = (
                            f"⏱️ <b>[{model} - STOP-LOSS TIGHTENED]</b>\n"
                            f"<b>• Stock:</b> <b>{stk}</b>\n"
                            f"<b>• New Tier:</b> <b>{decay_tier_name}</b>\n"
                            f"<b>• New SL Level:</b> <b>₹{base_sl:.2f}</b> (from earlier broader tier)\n"
                            f"<b>• LTP:</b> ₹{ltp:.2f} (PnL: {pnl_pct:.2f}%)\n"
                        )
                        broadcast_telegram_alert(msg)
                
                # Min LTP Tracking for Pre-TP and Trailing
                min_ltp = min(ltp, stk_state.get('min_ltp_seen', ltp))
                stk_state['min_ltp_seen'] = min_ltp
                max_profit_pct = ((ep - min_ltp) / ep) * 100.0
                
                active_sl = base_sl
                trail_active = stk_state.get('trail_active', False)
                tp_activation_price = round_to_tick(ep * 0.9800) # 2.0% profit
                
                # Stage 2: Pre-TP Profit Lock (If >= +1.25% profit, lock +0.50% profit)
                pre_tp_lock_price = round_to_tick(ep * 0.9950) # +0.50% profit
                if max_profit_pct >= 1.25 and not trail_active:
                    active_sl = min(active_sl, pre_tp_lock_price)
                    if not stk_state.get('pre_tp_locked'):
                        stk_state['pre_tp_locked'] = True
                        msg = (
                            f"🔒 <b>[{model} - PRE-TP PROFIT LOCKED]</b>\n"
                            f"<b>• Stock:</b> <b>{stk}</b>\n"
                            f"<b>• Trigger:</b> Reached +1.25% profit peak.\n"
                            f"<b>• Protected SL:</b> <b>₹{pre_tp_lock_price:.2f}</b> (+0.50% min profit locked)\n"
                        )
                        broadcast_telegram_alert(msg)
                        
                # Stage 3: Trailing Activation & Ratchet
                if not trail_active and ltp <= tp_activation_price:
                    trail_active = True
                    stk_state['trail_active'] = True
                    msg = (
                        f"🚀 <b>[{model} - TRAILING ENGINE ACTIVATED]</b>\n"
                        f"<b>• Stock:</b> <b>{stk}</b>\n"
                        f"<b>• Trigger:</b> Reached 2.00% profit (₹{tp_activation_price:.2f}).\n"
                        f"<b>• Action:</b> Initial floor set at 1.75% profit. Trailing 0.50% behind peak.\n"
                    )
                    broadcast_telegram_alert(msg)
                    
                if trail_active:
                    initial_floor = round_to_tick(ep * 0.9825, stockname=stk, client=client) # 1.75% profit floor
                    trail_dist = 0.50
                    active_sl = min(initial_floor, round_to_tick(min_ltp * (1.0 + trail_dist / 100.0), stockname=stk, client=client))
                    
                if not stk_state.get('is_armed_notified'):
                    pnl_s = "+" if stock_pnl >= 0 else "-"
                    pnl_pct_s = "+" if pnl_pct >= 0 else ""
                    armed_msg = (
                        f"🛡️ <b>[{model} - ADVANCED EXIT MONITOR ARMED]</b>\n"
                        f"<b>• Stock:</b> <b>{stk}</b>\n"
                        f"<b>• Entry Price:</b> ₹{ep:.2f} | <b>Qty:</b> {qty}\n"
                        f"<b>• Initial SL:</b> <b>₹{base_sl:.2f}</b> ({decay_tier_name})\n"
                        f"<b>• Stage 2 Lock:</b> <b>₹{pre_tp_lock_price:.2f}</b> (Locks +0.50% when peak reaches +1.25%)\n"
                        f"<b>• Stage 3 Trail:</b> Activates at <b>₹{tp_activation_price:.2f}</b> (2.0% profit)\n"
                        f"<b>• Current PnL:</b> <b>{pnl_pct_s}{pnl_pct:.2f}%</b> (<b>₹{pnl_s}{abs(stock_pnl):.2f}</b>)\n"
                    )
                    broadcast_telegram_alert(armed_msg)
                    stk_state['is_armed_notified'] = True
                    
                if is_hourly_due:
                    hourly_items.append({
                        'stock': stk, 'model': model, 'qty': qty,
                        'is_closed': False, 'is_reentry': False, 'entry': ep, 'orig_entry': ep,
                        'ltp': ltp, 'pnl_pct': pnl_pct, 'sl_price': active_sl, 'tp_price': tp_activation_price if not trail_active else active_sl,
                        'stock_pnl': stock_pnl, 'realized_l1': broker_pos.get('realized_l1'),
                        'unrealized_l1': stock_pnl, 'unrealized_l1_pct': pnl_pct,
                        'realized_l2': None, 'unrealized_l2': None,
                        'total_pnl': round((broker_pos.get('realized_l1') or 0.0) + stock_pnl, 2),
                        'exit_reason': f"SL/Trail: ₹{active_sl:.2f}"
                    })

                # Check SL / Protected SL / Trailing SL Execution
                is_profit_protection = bool(trail_active or (max_profit_pct >= 1.25 and active_sl == pre_tp_lock_price))

                if ltp >= active_sl:
                    limit_cover_price = round_to_tick(ltp)
                    if is_profit_protection:
                        # Stage 2 (Pre-TP Profit Lock) & Stage 3 (Trailing TP): Immediate execution at LTP
                        stk_state['consecutive_breaches'] = 0
                        stk_state['stale_tp_count'] = 0
                        if trail_active:
                            action_type = "TRAILING TP EXIT"
                            log_msg = f"🎯 [{stk}] Trailing TP Hit! LTP: ₹{ltp:.2f} >= Trail SL: ₹{active_sl:.2f} (Peak: +{max_profit_pct:.2f}%)"
                        else:
                            action_type = "PRE-TP PROFIT LOCK EXIT"
                            log_msg = f"🔒 [{stk}] Pre-TP Lock Hit! LTP: ₹{ltp:.2f} >= Locked SL: ₹{active_sl:.2f} (+0.50% Secured)"
                        print(log_msg)

                        existing_open = open_buy_orders.get(stk)
                        open_price = existing_open['price'] if isinstance(existing_open, dict) else 0.0
                        if existing_open and abs(open_price - limit_cover_price) < 0.01:
                            print(f"⏳ [{stk}] {action_type} limit buy order already resting at ₹{limit_cover_price:.2f}. Awaiting fill.")
                            success = False
                        else:
                            success = execute_limit_squareoff_order(
                                client=client, stockname=stk, qty=qty, limit_price=limit_cover_price,
                                model_name=model, loss_pct=loss_pct, open_buy_orders=open_buy_orders,
                                action_type=action_type, stock_pnl=stock_pnl
                            )
                        if success:
                            is_pre_tp_exit = (action_type == "PRE-TP PROFIT LOCK EXIT")
                            stk_state['sl_triggered'] = False
                            stk_state['pre_tp_lock_triggered'] = is_pre_tp_exit
                            stk_state['tp_triggered'] = bool(trail_active)
                            if stk_state['tp_triggered']:
                                stk_state['tp_trigger_time'] = now_ts
                                stk_state['tp_price'] = limit_cover_price
                                stk_state['tp_pnl'] = stock_pnl
                                stk_state['tp_pnl_pct'] = pnl_pct
                                stk_state['leg1_entry_price'] = ep
                                stk_state['leg1_qty'] = qty
                            stk_state['last_sq_trigger_time'] = now_ts
                            try:
                                conn_db = get_db_connection()
                                with conn_db.cursor() as c_db:
                                    db_note = f" | {action_type}_₹{limit_cover_price:.2f}"
                                    c_db.execute(f"UPDATE shortsell_orders SET notes = CONCAT(IFNULL(notes, ''), '{db_note}') WHERE trade_date = CURDATE() AND stockname = '{stk}' AND model_name LIKE '%{model}%'")
                                conn_db.commit()
                                conn_db.close()
                            except Exception as e_db:
                                print(f"⚠️ Note update failed for {stk}: {e_db}")
                    else:
                        # Stage 1 (Time-Decay Stop Loss): 3-Minute Consecutive Breach Check
                        breaches = stk_state.get('consecutive_breaches', 0) + 1
                        stk_state['consecutive_breaches'] = breaches
                        action_type = f"{decay_sl_pct}% STOP LOSS (3-MIN)"
                        print(f"⚠️ [{stk}] {decay_sl_pct}% Time-Decay SL Breach Count: {breaches}/3 (LTP: ₹{ltp:.2f} >= SL Level: ₹{base_sl:.2f})")

                        if breaches >= 3:
                            existing_open = open_buy_orders.get(stk)
                            open_price = existing_open['price'] if isinstance(existing_open, dict) else 0.0
                            if existing_open and abs(open_price - limit_cover_price) < 0.01:
                                print(f"⏳ [{stk}] {action_type} limit buy order already resting at ₹{limit_cover_price:.2f}. Awaiting fill.")
                                success = False
                            else:
                                success = execute_limit_squareoff_order(
                                    client=client, stockname=stk, qty=qty, limit_price=limit_cover_price,
                                    model_name=model, loss_pct=loss_pct, open_buy_orders=open_buy_orders,
                                    action_type=action_type, stock_pnl=stock_pnl
                                )
                            if success:
                                stk_state['sl_triggered'] = True
                                stk_state['last_sq_trigger_time'] = now_ts
                                try:
                                    conn_db = get_db_connection()
                                    with conn_db.cursor() as c_db:
                                        db_note = f" | SL_{decay_sl_pct}PCT_EXIT_₹{limit_cover_price:.2f}"
                                        c_db.execute(f"UPDATE shortsell_orders SET notes = CONCAT(IFNULL(notes, ''), '{db_note}') WHERE trade_date = CURDATE() AND stockname = '{stk}' AND model_name LIKE '%{model}%'")
                                    conn_db.commit()
                                    conn_db.close()
                                except Exception as e_db:
                                    print(f"⚠️ Note update failed for {stk}: {e_db}")
                else:
                    # LTP is below active_sl (safe / in favor of short)
                    if stk_state.get('consecutive_breaches', 0) > 0:
                        print(f"✅ [{stk}] Price recovered below {decay_sl_pct}% SL (₹{base_sl:.2f}). Resetting breach counter (was {stk_state['consecutive_breaches']}/3).")
                    stk_state['consecutive_breaches'] = 0

                    # Stale Open Cover Order Auto-Cancellation (3-Min) before 14:30 IST
                    existing_open = open_buy_orders.get(stk)
                    if existing_open and current_time_int < 1430:
                        stale_count = stk_state.get('stale_tp_count', 0) + 1
                        stk_state['stale_tp_count'] = stale_count
                        print(f"⏳ [{stk}] LTP ₹{ltp:.2f} < Active Trigger ₹{active_sl:.2f}. Resting BUY order stale count: {stale_count}/3 min.")
                        if stale_count >= 3:
                            ord_id = existing_open.get('order_id')
                            open_p = existing_open.get('price', 0.0)
                            print(f"🔄 [{stk}] 3 minutes elapsed with LTP < ₹{active_sl:.2f}. Cancelling stale BUY order {ord_id} @ ₹{open_p:.2f}...")
                            try:
                                client.cancel_order(order_id=ord_id)
                                print(f"✔ Successfully cancelled stale BUY order {ord_id} for {stk}.")
                                stk_state['tp_triggered'] = False
                                stk_state['pre_tp_lock_triggered'] = False
                                stk_state['stale_tp_count'] = 0
                                open_buy_orders.pop(stk, None)
                                cancel_msg = (
                                    f"ℹ️ <b>[{model} - STALE COVER ORDER CANCELLED (3-MIN)]</b>\n"
                                    f"📅 {today_str} | ⏱️ {datetime.now(ist).strftime('%H:%M:%S IST')}\n"
                                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                                    f"<b>• Stock:</b> <b>{stk}</b>\n"
                                    f"<b>• Cancelled Order:</b> <code>{ord_id}</code> @ ₹{open_p:.2f}\n"
                                    f"<b>• Current LTP:</b> <b>₹{ltp:.2f}</b> (Below trigger ₹{active_sl:.2f})\n"
                                    f"<b>• Action:</b> Cleaned resting order. Reverted to active monitoring.\n"
                                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                                )
                                broadcast_telegram_alert(cancel_msg)
                            except Exception as ce:
                                print(f"❌ Failed to cancel stale order {ord_id}: {ce}")
                    else:
                        stk_state['stale_tp_count'] = 0

                # Stop-Loss Proximity Near Warning Alert (within 0.25% of active Time-Decay SL)
                if not is_profit_protection and loss_pct >= max(0.75, decay_sl_pct - 0.25):
                    last_type = stk_state.get('last_alert_type')
                    last_time = stk_state.get('last_alert_time', 0)
                    if last_type != 'SL_BREACH' or (now_ts - last_time) >= 3600:
                        alerts_to_send_0940.append({
                            'stock': stk, 'model': model, 'qty': qty,
                            'ltp': ltp, 'entry': ep, 'sl': base_sl, 'sl_pct': decay_sl_pct,
                            'loss_pct': loss_pct,
                            'stock_pnl': stock_pnl, 'total_open_pnl': total_open_pnl
                        })
                        stk_state['last_alert_type'] = 'SL_BREACH'
                        stk_state['last_alert_time'] = now_ts
                        
            alert_state[stk] = stk_state

    save_alert_state(alert_state)

    if is_hourly_due and hourly_items:
        meta['last_hourly_report_time'] = now_ts
        alert_state['_meta'] = meta
        save_alert_state(alert_state)

        total_realized_pnl = sum((it.get('realized_l1') or 0.0) + (it.get('realized_l2') or 0.0) for it in hourly_items)
        total_open_pnl = sum((it.get('unrealized_l1') or 0.0) + (it.get('unrealized_l2') or 0.0) for it in hourly_items)
        total_pnl = total_open_pnl + total_realized_pnl
        open_count = sum(1 for it in hourly_items if not it.get('is_closed'))
        closed_count = sum(1 for it in hourly_items if it.get('is_closed'))

        timestamp_str = f"{today_str} | {datetime.now(ist).strftime('%H:%M:%S IST')}"
        img_path = generate_pnl_report_image(hourly_items, total_open_pnl, total_realized_pnl, open_count, closed_count, timestamp_str)

        if open_count > 0:
            caption = (
                f"⏳ <b>[09:40 HYBRID MODEL HOURLY MONITORING REPORT]</b>\n"
                f"📅 {today_str} | ⏱️ {datetime.now(ist).strftime('%H:%M:%S IST')}\n"
                f"⚡ <i>{open_count} Positions Active & Armed | {closed_count} Lots Closed</i>\n"
                f"📊 <b>Total PnL:</b> <b>₹{total_pnl:+,.2f}</b> (Realized: ₹{total_realized_pnl:+,.2f} | Open: ₹{total_open_pnl:+,.2f})"
            )
        else:
            caption = (
                f"⏳ <b>[09:40 HYBRID MODEL STATUS SUMMARY REPORT]</b>\n"
                f"📅 {today_str} | ⏱️ {datetime.now(ist).strftime('%H:%M:%S IST')}\n"
                f"⚡ <i>All {len(hourly_items)} Positions Completed / Closed</i>\n"
                f"📊 <b>Total Realized PnL:</b> <b>₹{total_realized_pnl:+,.2f}</b>"
            )

        if img_path and os.path.exists(img_path):
            sent = send_telegram_photo(img_path, caption, chat_id=TELEGRAM_STATUS_CHAT_ID)
            if not sent:
                send_telegram_alert(caption, chat_id=TELEGRAM_STATUS_CHAT_ID)
        else:
            send_telegram_alert(caption, chat_id=TELEGRAM_STATUS_CHAT_ID)

    if alerts_to_send_0940:
        timestamp_str = f"{today_str} | {datetime.now(ist).strftime('%H:%M:%S IST')}"
        warning_img_path = generate_sl_warning_image(alerts_to_send_0940, timestamp_str)

        msg = "⚠️ <b>[STOP-LOSS PROXIMITY NEAR WARNING ALERT]</b>\n"
        msg += f"📅 {today_str} | ⏱️ {datetime.now(ist).strftime('%H:%M:%S IST')}\n"
        msg += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"

        for a in alerts_to_send_0940:
            spnl = a['stock_pnl']
            spnl_s = "+" if spnl >= 0 else "-"
            sl_lvl = a.get('sl') or round_to_tick(a['entry'] * 1.0225)
            sl_pct_lbl = a.get('sl_pct', 2.25)
            dist_to_sl = round(sl_lvl - a['ltp'], 2)
            dist_str = f"₹{dist_to_sl:.2f} away" if dist_to_sl > 0 else "BREACHED"
            msg += f"\n🚨 <b>STOCK: {a['stock']}</b> ({a['model']})\n"
            msg += f"  • <b>Current LTP:</b> <b>₹{a['ltp']:.2f}</b> | Entry: ₹{a['entry']:.2f} (Qty: {a['qty']})\n"
            msg += f"  • <b>Current Loss:</b> <b>-{a['loss_pct']:.2f}%</b> (<b>₹{spnl_s}{abs(spnl):.2f}</b>)\n"
            msg += f"  • <b>{sl_pct_lbl}% SL Level:</b> <b>₹{sl_lvl:.2f}</b> (<b>{dist_str}</b>)\n"
            msg += f"------------------------------------\n"

        topnl = alerts_to_send_0940[-1]['total_open_pnl']
        topnl_s = "+" if topnl >= 0 else "-"
        msg += f"📊 <b>Total Open PnL:</b> <b>₹{topnl_s}{abs(topnl):.2f}</b>\n"
        msg += "⚡ <i>Auto Square-Off executes at 3 consecutive 1-min breaches of active Time-Decay SL</i>"

        if warning_img_path and os.path.exists(warning_img_path):
            sent = send_telegram_photo(warning_img_path, msg, chat_id=TELEGRAM_CRITICAL_CHAT_ID)
            if not sent:
                broadcast_telegram_alert(msg)
        else:
            broadcast_telegram_alert(msg)
    else:
        print(f"[{datetime.now(ist).strftime('%H:%M:%S')}] All positions checked. No active generic alerts needed.")

if __name__ == '__main__':
    main()
