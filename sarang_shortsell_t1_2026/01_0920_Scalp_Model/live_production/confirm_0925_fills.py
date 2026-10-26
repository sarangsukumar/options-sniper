#!/usr/bin/env python3
"""
confirm_0925_fills.py
=====================
Runs at exactly 09:27:00 IST (2 minutes after order placement at 09:25:00).

Execution Sequence for 0920_SCALP 50/50 Split:
1. Cancels all unfilled/open SELL limit orders placed at 09:25:00.
2. Checks Kotak order report and active positions to find which stocks were executed.
3. For each filled stock, places 50% Leg 1 Resting Limit TP order for ₹2,000 profit target:
     target_drop = 2000.0 / total_qty
     tp_price = round_to_tick(filled_price - target_drop)
     leg1_qty = total_qty // 2
4. Updates shortsell_orders and scalp_trade_log in the DB.
5. Sends Telegram alerts for order cancellations and Leg 1 TP placements.
"""

import sys
import os
import pymysql
from datetime import date, datetime

sys.path.insert(0, '/home/ubuntu/KotakCodes1')
from Neo_shortsell_mis_order import find_eq_scripcode, round_to_tick, send_telegram_alert

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cron_0920_scalp.log')

def log(msg):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{ts}] [FILL_CONFIRM] {msg}"
    print(line)
    with open(LOG_FILE, 'a') as f:
        f.write(line + '\n')

def get_db():
    return pymysql.connect(
        host='localhost', user='root', password='root',
        database='markets', cursorclass=pymysql.cursors.DictCursor,
        autocommit=False
    )

def get_kotak_client():
    try:
        import pandas as pd
        from neo_api_client import NeoAPI
        import pyotp
        import os
        import sys

        class HiddenPrints:
            def __enter__(self):
                self._original_stdout = sys.stdout
                sys.stdout = open(os.devnull, 'w')
            def __exit__(self, exc_type, exc_val, exc_tb):
                sys.stdout.close()
                sys.stdout = self._original_stdout

        # Read User_table.csv for user
        user_table_path = '/home/ubuntu/KotakCodes1/User_table.csv'
        auth_csv_path = '/home/ubuntu/KotakCodes1/kotak_auth_userid.csv'
        with open(user_table_path) as f:
            next(f)
            user_id = next(f).strip()
            
        auth_df = pd.read_csv(auth_csv_path)
        auth = auth_df[auth_df['userid'] == user_id]
        if auth.empty:
            return None
        auth = auth.iloc[0]
        
        with HiddenPrints():
            client = NeoAPI(consumer_key=auth['consumer_key'], environment='prod', neo_fin_key='neotradeapi')
            totp_code = pyotp.TOTP(str(auth.get('totp_secret', '')).strip()).now()
            mobile = str(auth.get('mobile_number', '')).strip()
            formatted_mobile = mobile if mobile.startswith('+') else f'+91{mobile}'
            client.totp_login(mobile_number=formatted_mobile, ucc=user_id, totp=totp_code)
            client.totp_validate(mpin=str(int(auth['MPIN'])))
        return client
    except Exception as e:
        print(f"Login error: {e}")
        return None

def get_taxes(qty, sell_price, buy_price):
    """Approximate Kotak MIS charges — same formula used in backtests."""
    turnover = (qty * sell_price) + (qty * buy_price)
    stt      = round(qty * sell_price * 0.00025)
    txn      = turnover * 0.0000322
    sebi     = turnover * 0.000001
    stamp    = round(qty * buy_price * 0.00003)
    gst      = (40.0 + txn + sebi) * 0.18
    return round(40.0 + stt + txn + sebi + stamp + gst, 2)

def run():
    today = date.today().strftime('%Y-%m-%d')
    log(f"=== Fill Confirmation starting for {today} ===")

    # ------------------------------------------------------------------ #
    # 1. Fetch today's 0920_SCALP orders from shortsell_orders            #
    # ------------------------------------------------------------------ #
    db = get_db()
    try:
        with db.cursor() as c:
            c.execute("""
                SELECT id, stockname, quantity, limit_price, broker_order_id, isvalid
                FROM shortsell_orders
                WHERE trade_date = %s
                  AND model_name  = '0920_SCALP'
                  AND isvalid NOT IN ('FALSE', 'REJECTED')
                ORDER BY order_rank
            """, (today,))
            orders = c.fetchall()
    finally:
        db.close()

    if not orders:
        log("No 0920_SCALP orders found for today — nothing to confirm.")
        return

    log(f"Found {len(orders)} orders to confirm.")

    # ------------------------------------------------------------------ #
    # 2. Fetch Kotak order book                                           #
    # ------------------------------------------------------------------ #
    client = get_kotak_client()
    kotak_order_map = {}   # broker_order_id -> order dict

    if client:
        try:
            order_book_raw = client.order_report()
            order_book = order_book_raw.get('data', []) if isinstance(order_book_raw, dict) else order_book_raw
            
            if isinstance(order_book, list):
                for o in order_book:
                    oid = o.get('nOrdNo') or o.get('orderId', '')
                    if oid:
                        kotak_order_map[str(oid)] = o
                log(f"Kotak order book fetched: {len(kotak_order_map)} orders.")
            else:
                log(f"⚠️  Unexpected order_report format: {type(order_book)}")
        except Exception as e:
            log(f"⚠️  Could not fetch Kotak order book: {e}")
    else:
        log("⚠️  Running without Kotak client — will mark orders as UNFILLED.")

    # ------------------------------------------------------------------ #
    # 3. Process each order                                               #
    # ------------------------------------------------------------------ #
    db = get_db()
    try:
        for order in orders:
            so_id       = order['id']
            stockname   = order['stockname']
            quantity    = order['quantity']
            limit_price = order['limit_price']
            broker_id   = str(order['broker_order_id'] or '')

            log(f"  Processing {stockname} | qty={quantity} | broker_id={broker_id}")

            # Determine fill status
            fill_status  = 'UNFILLED'
            filled_price = None
            fill_time    = None
            notes        = ''

            if broker_id and broker_id in kotak_order_map:
                ko = kotak_order_map[broker_id]
                ord_status = ko.get('ordSt', '').lower()
                avg_prc    = ko.get('avgPrc') or ko.get('avgprc') or ko.get('flPrc') or 0
                try:
                    avg_prc = float(avg_prc)
                except:
                    avg_prc = 0.0

                if ord_status == 'complete' and avg_prc > 0:
                    fill_status  = 'SELL_FILLED'
                    filled_price = round(avg_prc, 2)
                    fill_time    = datetime.now()
                    notes        = f"Filled @ ₹{filled_price}"
                    log(f"    ✅ FILLED @ ₹{filled_price}")

                    # ── 50/50 Split Strategy: Leg 1 Resting Limit TP ────────────
                    has_open_buy = False
                    for oid_k, ko_item in kotak_order_map.items():
                        if ko_item.get('exSeg') == 'nse_cm' and ko_item.get('trnsTp') in ('B', 'BUY'):
                            st = str(ko_item.get('ordSt', '')).lower()
                            if st in ('open', 'pending', 'trigger pending', 'put order req received'):
                                sym = ko_item.get('trdSym', '') or ko_item.get('sym', '')
                                clean = sym.replace('-EQ', '').replace('_EQ', '').strip().upper()
                                if clean == stockname.upper():
                                    has_open_buy = True
                                    break

                    if not has_open_buy and client:
                        fl_qty_str = ko.get('flQty') or ko.get('flqty') or ko.get('filledQty')
                        try:
                            total_qty = int(fl_qty_str) if fl_qty_str else int(quantity)
                        except:
                            total_qty = int(quantity)
                        leg1_qty = total_qty // 2
                        if leg1_qty <= 0:
                            leg1_qty = 1

                        tp_target_rs = 2000.0
                        tp_drop = tp_target_rs / float(total_qty)
                        tp_price = round_to_tick(filled_price - tp_drop)
                        if tp_price > 0:
                            scripcode = find_eq_scripcode(stockname) or f"{stockname}-EQ"
                            try:
                                with HiddenPrints():
                                    resp = client.place_order(
                                        exchange_segment='nse_cm',
                                        product='MIS',
                                        price=str(tp_price),
                                        order_type='L',
                                        quantity=str(leg1_qty),
                                        validity='DAY',
                                        trading_symbol=scripcode,
                                        transaction_type='B',
                                        amo='NO',
                                        disclosed_quantity='0',
                                        trigger_price='0'
                                    )
                                if resp and (resp.get('stat') == 'Ok' or resp.get('stCode') == 200):
                                    tp_oid = resp.get('nOrdNo') or resp.get('orderId', '')
                                    notes += f" | Leg 1 TP placed @ ₹{tp_price} (OID: {tp_oid})"
                                    log(f"    🎯 Placed Leg 1 TP: {leg1_qty}/{total_qty} qty @ ₹{tp_price} (OID: {tp_oid})")
                                    send_telegram_alert(
                                        f"🎯 <b>[09:20 SCALP - 50% LEG 1 LIMIT TP PLACED]</b>\n"
                                        f"📅 {today} | ⏱️ {datetime.now().strftime('%H:%M:%S IST')}\n"
                                        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                                        f"<b>• Stock:</b> <b>{stockname}</b>\n"
                                        f"<b>• Action:</b> <b>Passive Limit BUY TP</b>\n"
                                        f"<b>• Sell Fill Price:</b> ₹{filled_price:.2f}\n"
                                        f"<b>• Target Exit Limit:</b> <b>₹{tp_price:.2f}</b> (-₹{tp_drop:.2f})\n"
                                        f"<b>• Quantity:</b> {leg1_qty} / {total_qty} (50%)\n"
                                        f"<b>• Target Profit:</b> <b>₹2,000</b>\n"
                                        f"<b>• Kotak Order ID:</b> <code>{tp_oid}</code>\n"
                                        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                                        f"⚡ <i>Rests on NSE book. Fills passively at zero slippage. Leg 2 (50%) managed from 09:36.</i>"
                                    )
                                else:
                                    log(f"    ⚠️ Leg 1 TP placement returned non-OK status: {resp}")
                            except Exception as tpe:
                                log(f"    ⚠️ Leg 1 TP placement failed: {tpe}")
                elif ord_status in ('rejected', 'cancelled', 'canceled'):
                    fill_status = 'REJECTED'
                    notes       = f"Kotak status: {ord_status}"
                    log(f"    ❌ REJECTED by Kotak")
                else:
                    fill_status = 'UNFILLED'
                    notes       = f"Kotak status: {ord_status} (pending/partial)"
                    log(f"    ⚠️  UNFILLED — status={ord_status}")
                    # Auto-cancel pending order at 09:27:00 cutoff to prevent late fills
                    if client and broker_id and ord_status in ('open', 'pending', 'new', 'trigger_pending', 'put order req received'):
                        try:
                            with HiddenPrints():
                                client.cancel_order(order_id=broker_id)
                            notes += " | Auto-cancelled at 09:27 cutoff"
                            log(f"    🚫 Auto-cancelled open order {broker_id} at 09:27 cutoff")
                            send_telegram_alert(
                                f"🚫 <b>[09:20 SCALP - UNFILLED SELL CANCELLED]</b>\n"
                                f"📅 {today} | ⏱️ {datetime.now().strftime('%H:%M:%S IST')}\n"
                                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                                f"<b>• Stock:</b> <b>{stockname}</b>\n"
                                f"<b>• Status:</b> <b>Cancelled at 09:27 Cutoff</b>\n"
                                f"<b>• Reason:</b> Limit sell order not filled within 2 mins\n"
                                f"<b>• Order ID:</b> <code>{broker_id}</code>\n"
                                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                                f"⚡ <i>Prevented late fill. Stock will not be traded today.</i>"
                            )
                        except Exception as ce:
                            log(f"    ⚠️ Cancel open order {broker_id} failed: {ce}")
            elif not broker_id:
                fill_status = 'UNFILLED'
                notes       = 'No broker_order_id — order may not have been placed'
                log(f"    ⚠️  No broker_order_id found")
            else:
                # broker_id exists but not in order book — mark UNFILLED
                fill_status = 'UNFILLED'
                notes       = f'broker_id {broker_id} not found in order book'
                log(f"    ⚠️  broker_id not in Kotak order book")

            with db.cursor() as c:
                # Update shortsell_orders.filled_price if filled or mark failed
                if fill_status == 'SELL_FILLED':
                    c.execute("""
                        UPDATE shortsell_orders
                        SET filled_price = %s, isvalid = '2', modtime = NOW()
                        WHERE id = %s
                    """, (filled_price, so_id))
                elif fill_status == 'REJECTED':
                    c.execute("""
                        UPDATE shortsell_orders
                        SET isvalid = '3', notes = %s, modtime = NOW()
                        WHERE id = %s
                    """, (notes, so_id))

                # Upsert into scalp_trade_log
                c.execute("""
                    SELECT id FROM scalp_trade_log
                    WHERE trade_date = %s AND stockname = %s AND model_name = '0920_SCALP'
                """, (today, stockname))
                existing = c.fetchone()

                if existing:
                    c.execute("""
                        UPDATE scalp_trade_log
                        SET sell_price = %s, sell_time = %s,
                            broker_sell_order_id = %s, status = %s, notes = %s,
                            modtime = NOW()
                        WHERE id = %s
                    """, (filled_price, fill_time, broker_id, fill_status, notes, existing['id']))
                else:
                    c.execute("""
                        INSERT INTO scalp_trade_log
                            (trade_date, model_name, shortsell_order_id, stockname, quantity,
                             sell_ltp_used, sell_price, sell_time, broker_sell_order_id,
                             status, notes)
                        VALUES (%s, '0920_SCALP', %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (today, so_id, stockname, quantity,
                          limit_price, filled_price, fill_time, broker_id,
                          fill_status, notes))

            db.commit()
            log(f"    DB updated → status={fill_status}")

        # ── 4. Safety Sweep: Cancel any remaining open SELL orders for 0920_SCALP stocks ──
        if client and isinstance(kotak_order_map, dict):
            scalp_symbols = {o['stockname'].upper() for o in orders}
            for oid_k, ko in kotak_order_map.items():
                if ko.get('exSeg') == 'nse_cm' and ko.get('trnsTp') in ('S', 'SELL'):
                    st = str(ko.get('ordSt', '')).lower()
                    if st in ('open', 'pending', 'new', 'trigger pending', 'put order req received'):
                        sym = ko.get('trdSym', '') or ko.get('sym', '')
                        clean = sym.replace('-EQ', '').replace('_EQ', '').strip().upper()
                        if clean in scalp_symbols:
                            try:
                                with HiddenPrints():
                                    client.cancel_order(order_id=oid_k)
                                log(f"  🚫 Safety sweep cancelled lingering open SELL order {oid_k} for {clean}")
                            except Exception as ce:
                                log(f"  ⚠️ Safety sweep cancel failed for {oid_k}: {ce}")

    finally:
        db.close()

    log("=== Fill Confirmation complete ===\n")

if __name__ == '__main__':
    run()
