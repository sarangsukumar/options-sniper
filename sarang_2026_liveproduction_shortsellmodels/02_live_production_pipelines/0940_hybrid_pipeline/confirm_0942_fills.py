#!/usr/bin/env python3
"""
confirm_0925_fills.py
=====================
Runs at ~09:26:30 IST (90 seconds after order placement at 09:25).

Reads all SELL_PLACED entries from shortsell_orders for today's 0920_SCALP model,
confirms fill status from Kotak API order_report(), then:
  - If filled:   writes sell_price (avgPrc) into shortsell_orders.filled_price
                 creates/updates row in scalp_trade_log with status='SELL_FILLED'
  - If unfilled: marks scalp_trade_log status='UNFILLED'  (skipped in exit scripts)
  - If rejected: marks scalp_trade_log status='REJECTED'  (skipped in exit scripts)
"""

import sys
import os
import pymysql
from datetime import date, datetime

sys.path.insert(0, '/home/ubuntu/KotakCodes1')

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cron_0942_hybrid.log')

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
    # 1. Fetch today's 0942_HYBRID orders from shortsell_orders            #
    # ------------------------------------------------------------------ #
    db = get_db()
    try:
        with db.cursor() as c:
            c.execute("""
                SELECT id, stockname, quantity, limit_price, broker_order_id, isvalid
                FROM shortsell_orders
                WHERE trade_date = %s
                  AND model_name  = '0942_HYBRID'
                  AND isvalid NOT IN ('FALSE', 'REJECTED')
                ORDER BY order_rank
            """, (today,))
            orders = c.fetchall()
    finally:
        db.close()

    if not orders:
        log("No 0942_HYBRID orders found for today — nothing to confirm.")
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
                ord_status = str(ko.get('ordSt', '')).lower().strip()
                avg_prc    = ko.get('avgPrc') or ko.get('avgprc') or ko.get('flPrc') or 0
                fld_qty    = int(ko.get('fldQty') or ko.get('fldqty') or 0)
                try:
                    avg_prc = float(avg_prc)
                except:
                    avg_prc = 0.0

                if ord_status == 'complete' and avg_prc > 0:
                    fill_status  = 'SELL_FILLED'
                    filled_price = round(avg_prc, 2)
                    if fld_qty > 0:
                        quantity = fld_qty
                    fill_time    = datetime.now()
                    notes        = f"Filled @ ₹{filled_price} (Qty: {quantity})"
                    log(f"    ✅ FILLED @ ₹{filled_price} (Qty: {quantity})")
                elif fld_qty > 0 and avg_prc > 0:
                    # Partial fill: cancel remaining open quantity on Kotak and record filled portion
                    if ord_status in ('open', 'pending', 'trigger pending', 'put order req received') and client:
                        try:
                            client.cancel_order(order_id=broker_id)
                            log(f"    🔄 Cancelled remaining unfilled portion of partially filled order {broker_id} ({fld_qty}/{quantity} filled)")
                        except Exception as ce:
                            log(f"    ⚠️ Cancel remainder failed for {broker_id}: {ce}")
                    fill_status  = 'SELL_FILLED'
                    filled_price = round(avg_prc, 2)
                    quantity     = fld_qty
                    fill_time    = datetime.now()
                    notes        = f"Partial Fill @ ₹{filled_price} (Qty: {quantity}); remainder cancelled"
                    log(f"    ✅ PARTIAL FILL CONFIRMED @ ₹{filled_price} (Qty: {quantity})")
                elif ord_status in ('rejected', 'cancelled', 'canceled'):
                    fill_status = 'REJECTED'
                    notes       = f"Kotak status: {ord_status}"
                    log(f"    ❌ REJECTED by Kotak")
                else:
                    # Unfilled order still resting in order book at confirmation time -> cancel it so it cannot fill hours later
                    if ord_status in ('open', 'pending', 'trigger pending', 'put order req received', 'after market order req received') and client:
                        try:
                            client.cancel_order(order_id=broker_id)
                            log(f"    🔄 Cancelled unfilled open SELL order {broker_id} for {stockname}")
                            notes = f"Kotak status: {ord_status} (unfilled -> cancelled at confirmation)"
                        except Exception as ce:
                            log(f"    ⚠️ Failed to cancel unfilled order {broker_id}: {ce}")
                            notes = f"Kotak status: {ord_status} (pending/unfilled)"
                    else:
                        notes = f"Kotak status: {ord_status} (pending/unfilled)"
                    fill_status = 'UNFILLED'
                    log(f"    ⚠️  UNFILLED — status={ord_status}")
            elif not broker_id:
                fill_status = 'UNFILLED'
                notes       = 'No broker_order_id — order may not have been placed'
                log(f"    ⚠️  No broker_order_id found")
            else:
                # broker_id exists but not in order book — wait a little longer
                fill_status = 'UNFILLED'
                notes       = f'broker_id {broker_id} not found in order book'
                log(f"    ⚠️  broker_id not in Kotak order book")

            with db.cursor() as c:
                # Update shortsell_orders.filled_price and quantity if filled
                if fill_status == 'SELL_FILLED':
                    c.execute("""
                        UPDATE shortsell_orders
                        SET filled_price = %s, quantity = %s, isvalid = '2', modtime = NOW()
                        WHERE id = %s
                    """, (filled_price, quantity, so_id))

                # Upsert into scalp_trade_log
                c.execute("""
                    SELECT id FROM scalp_trade_log
                    WHERE trade_date = %s AND stockname = %s AND model_name = '0942_HYBRID'
                """, (today, stockname))
                existing = c.fetchone()

                if existing:
                    c.execute("""
                        UPDATE scalp_trade_log
                        SET quantity = %s, sell_price = %s, sell_time = %s,
                            broker_sell_order_id = %s, status = %s, notes = %s,
                            modtime = NOW()
                        WHERE id = %s
                    """, (quantity, filled_price, fill_time, broker_id, fill_status, notes, existing['id']))
                else:
                    c.execute("""
                        INSERT INTO scalp_trade_log
                            (trade_date, model_name, shortsell_order_id, stockname, quantity,
                             sell_ltp_used, sell_price, sell_time, broker_sell_order_id,
                             status, notes)
                        VALUES (%s, '0942_HYBRID', %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """, (today, so_id, stockname, quantity,
                          limit_price, filled_price, fill_time, broker_id,
                          fill_status, notes))

            db.commit()
            log(f"    DB updated → status={fill_status}")

    finally:
        db.close()

    log("=== Fill Confirmation complete ===\n")

if __name__ == '__main__':
    run()
