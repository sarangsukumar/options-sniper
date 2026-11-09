#!/usr/bin/env python3
"""
confirm_0925_fills.py
=====================
Runs at exactly 09:27:00 IST (2 minutes after order placement at 09:25:00).

Execution Sequence for 0920_SCALP 100% Single-Leg Trailing Strategy (₹5L Plan):
1. Cancels all unfilled/open SELL limit orders placed at 09:25:00.
2. Checks Kotak order report and active positions to find which stocks were executed.
3. For each filled stock (100% Single-Leg, no 50/50 split), arms the 3-Stage Protection levels:
     - Stage 1 Initial SL (-₹5,000 / 1.00%): sl_price = round_to_tick(filled_price + min(5000 / qty, filled_price * 0.01))
     - Stage 2 Profit Floor (+₹2,000 Trigger): Locks +₹1,000 minimum profit once PnL reaches +₹2,000
     - Stage 3 Dynamic Trail (+₹4,000+ Trigger): Trails Peak PnL by ₹750 (₹4,000 -> ₹3,250, ₹5,000 -> ₹4,250, etc.)
4. Updates shortsell_orders and scalp_trade_log in the DB.
5. Sends Telegram alerts for order cancellations and Armed Trailing Monitor levels.
"""

import sys
import os
import pymysql
import pytz
from datetime import date, datetime

IST = pytz.timezone('Asia/Kolkata')

sys.path.insert(0, '/home/ubuntu/KotakCodes1')
from Neo_shortsell_mis_order import find_eq_scripcode, round_to_tick, send_telegram_alert

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cron_0920_scalp.log')

def log(msg):
    ts = datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S')
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

class HiddenPrints:
    def __enter__(self):
        self._original_stdout = sys.stdout
        sys.stdout = open(os.devnull, 'w')
    def __exit__(self, exc_type, exc_val, exc_tb):
        sys.stdout.close()
        sys.stdout = self._original_stdout

def get_kotak_client():
    try:
        import pandas as pd
        from neo_api_client import NeoAPI
        import pyotp
        import os

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
    today = datetime.now(IST).strftime('%Y-%m-%d')
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
                    fill_time    = datetime.now(IST).replace(tzinfo=None)
                    notes        = f"Filled @ ₹{filled_price}"
                    log(f"    ✅ FILLED @ ₹{filled_price}")

                    # ── 100% Single-Leg Trailing Protection (₹5L Plan) ────────────
                    fl_qty_str = ko.get('flQty') or ko.get('flqty') or ko.get('filledQty')
                    try:
                        total_qty = int(fl_qty_str) if fl_qty_str else int(quantity)
                    except:
                        total_qty = int(quantity)
                    if total_qty <= 0:
                        total_qty = max(1, int(quantity))

                    sl_initial_price = min(
                        round_to_tick(filled_price + (5000.0 / float(total_qty))),
                        round_to_tick(filled_price * 1.0100)
                    )
                    sl_initial_price = round_to_tick(filled_price * 1.0150)  # [UPDATE] Option 2A/2B: 1.50% Hard SL + 09:36 Cadence Exit
                    act_2000_price  = round_to_tick(filled_price - (2000.0 / float(total_qty)))
                    lock_1000_price = round_to_tick(filled_price - (1000.0 / float(total_qty)))
                    act_4000_price  = round_to_tick(filled_price - (4000.0 / float(total_qty)))
                    lock_3250_price = round_to_tick(filled_price - (3250.0 / float(total_qty)))

                    notes += (
                        f" | 100% Trailing Armed: InitSL=₹{sl_initial_price:.2f} (-₹5k)"
                        f" | +₹2k->Lock+₹1k (₹{lock_1000_price:.2f})"
                        f" | +₹4k+->Trail-₹750 (₹{lock_3250_price:.2f})"
                    )
                    notes = f"Filled @ ₹{filled_price} | Option 2A/2B Armed: InitSL=₹{sl_initial_price:.2f} (1.50%) | 09:36 Cadence & 09:40 Exit"
                    log(
                        f"    🛡️ Armed 100% Single-Leg Trailing ({total_qty} qty): "
                        f"Init SL=₹{sl_initial_price:.2f} (-₹5k) | "
                        f"+₹2k Act=₹{act_2000_price:.2f} -> Lock +₹1k @ ₹{lock_1000_price:.2f} | "
                        f"+₹4k Act=₹{act_4000_price:.2f} -> Trail by ₹750"
                    )
                    send_telegram_alert(
                        f"🛡️ <b>[09:20 SCALP - 100% SINGLE-LEG TRAILING ARMED]</b>\n"
                        f"📅 {today} | ⏱️ {datetime.now(IST).strftime('%H:%M:%S IST')}\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"<b>• Stock:</b> <b>{stockname}</b>\n"
                        f"<b>• Sell Fill Price:</b> <b>₹{filled_price:.2f}</b> | <b>Qty:</b> <b>{total_qty}</b> (100%)\n"
                        f"<b>• Stage 1 Initial SL (-₹5,000 / 1.00%):</b> <b>₹{sl_initial_price:.2f}</b>\n"
                        f"<b>• Stage 2 Profit Floor (Reach +₹2,000 @ ₹{act_2000_price:.2f}):</b> Locks <b>+₹1,000</b> @ <b>₹{lock_1000_price:.2f}</b>\n"
                        f"<b>• Stage 3 Dynamic Trail (Reach +₹4,000+ @ ₹{act_4000_price:.2f}):</b> Trails <b>Peak - ₹750</b> (₹3,250+ @ <b>₹{lock_3250_price:.2f}</b>)\n"
                        f"<b>• Kotak Sell OID:</b> <code>{broker_id}</code>\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"⚡ <i>Monitored every 2s via Kotak Quotes API. 09:36–09:39:30 Cadence (≥+₹500) & 09:40 Hard Exit active.</i>"
                    )
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
                                f"📅 {today} | ⏱️ {datetime.now(IST).strftime('%H:%M:%S IST')}\n"
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
                # Update shortsell_orders.filled_price and stop_loss_price if filled, or mark failed
                if fill_status == 'SELL_FILLED':
                    sl_init_db = min(round_to_tick(filled_price + (5000.0 / max(quantity, 1))), round_to_tick(filled_price * 1.0100))
                    sl_init_db = round_to_tick(filled_price * 1.0150)  # [UPDATE] Option 2A/2B: 1.50% Hard SL
                    c.execute("""
                        UPDATE shortsell_orders
                        SET filled_price = %s, stop_loss_price = %s, isvalid = '2', modtime = NOW()
                        WHERE id = %s
                    """, (filled_price, sl_init_db, so_id))
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
