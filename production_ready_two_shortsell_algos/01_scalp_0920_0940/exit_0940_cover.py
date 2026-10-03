#!/usr/bin/env python3
"""
exit_0940_cover.py
==================
Runs at exactly 09:40:00 IST.

Covers all remaining open short positions that were NOT exited at 09:36.
These are rows with status = 'SELL_FILLED' (not yet exited).

Places Limit Buy order at live LTP for each, updates scalp_trade_log.
"""

import sys
import os
import pymysql
from datetime import date, datetime

sys.path.insert(0, '/home/ubuntu/KotakCodes1')

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cron_0920_scalp.log')

def log(msg):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{ts}] [EXIT_0940] {msg}"
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
        from Neo_login import get_logged_in_client
        return get_logged_in_client()
    except Exception as e:
        log(f"⚠️  Could not get Kotak client: {e}")
        return None

def fetch_live_ltp(client, stockname):
    try:
        from Neo_shortsell_mis_order import get_instrument_token
        token = get_instrument_token(stockname)
        if not token:
            return None
        resp = client.quotes(
            [{"instrument_token": token, "exchange_segment": "nse_cm"}],
            quote_type="ltp"
        )
        if isinstance(resp, list) and len(resp) > 0 and 'ltp' in resp[0]:
            return float(resp[0]['ltp'])
        return None
    except Exception as e:
        log(f"    ⚠️  LTP fetch error for {stockname}: {e}")
        return None

def place_buy_cover(client, stockname, quantity, ltp):
    try:
        scripcode = f"{stockname}-EQ"
        try:
            from Neo_shortsell_mis_order import TOKEN_TO_SYMBOL, get_instrument_token
            token = get_instrument_token(stockname)
            if token and token in TOKEN_TO_SYMBOL:
                scripcode = TOKEN_TO_SYMBOL[token]
        except:
            pass

        resp = client.place_order(
            exchange_segment='nse_cm',
            product='MIS',
            price=str(round(ltp, 2)),
            order_type='L',
            quantity=str(quantity),
            validity='DAY',
            trading_symbol=scripcode,
            transaction_type='B',
            amo='NO',
            disclosed_quantity='0',
            trigger_price='0',
        )
        return resp
    except Exception as e:
        log(f"    ⚠️  place_buy_cover error for {stockname}: {e}")
        return None

def get_taxes(qty, sell_price, buy_price):
    turnover = (qty * sell_price) + (qty * buy_price)
    stt      = round(qty * sell_price * 0.00025)
    txn      = turnover * 0.0000322
    sebi     = turnover * 0.000001
    stamp    = round(qty * buy_price * 0.00003)
    gst      = (40.0 + txn + sebi) * 0.18
    return round(40.0 + stt + txn + sebi + stamp + gst, 2)

def run():
    today = date.today().strftime('%Y-%m-%d')
    log(f"=== 09:40 Hard Exit Cover starting for {today} ===")

    db = get_db()
    try:
        with db.cursor() as c:
            # Only cover positions still open (SELL_FILLED = not yet exited)
            c.execute("""
                SELECT id, stockname, quantity, sell_price
                FROM scalp_trade_log
                WHERE trade_date = %s
                  AND model_name  = '0920_SCALP'
                  AND status      = 'SELL_FILLED'
            """, (today,))
            positions = c.fetchall()
    finally:
        db.close()

    if not positions:
        log("No SELL_FILLED positions remaining — all already exited at 09:36. ✅")
        return

    log(f"Found {len(positions)} positions to cover at 09:40.")
    client = get_kotak_client()

    for pos in positions:
        row_id     = pos['id']
        stockname  = pos['stockname']
        quantity   = pos['quantity']
        sell_price = pos['sell_price'] or 0

        log(f"  {stockname} | sell_price=₹{sell_price} | qty={quantity}")

        live_ltp = None
        if client:
            live_ltp = fetch_live_ltp(client, stockname)

        if not live_ltp or live_ltp <= 0:
            log(f"    ⚠️  Could not fetch live LTP — using 0 as placeholder.")
            live_ltp = 0.0

        log(f"    LTP=₹{live_ltp} → placing BUY cover order")

        resp = None
        broker_buy_id = None
        if client and live_ltp > 0:
            resp = place_buy_cover(client, stockname, quantity, live_ltp)
            if resp:
                broker_buy_id = resp.get('nOrdNo') or resp.get('message', '')
                log(f"    Order response: {resp}")

        # Estimate PnL (will be confirmed precisely by confirm_exits.py later)
        est_pnl = None
        if sell_price > 0 and live_ltp > 0:
            charges = get_taxes(quantity, sell_price, live_ltp)
            est_pnl = round(((sell_price - live_ltp) * quantity) - charges, 2)

        db = get_db()
        try:
            with db.cursor() as c:
                c.execute("""
                    UPDATE scalp_trade_log
                    SET buy_ltp_used         = %s,
                        buy_price            = %s,
                        buy_time             = NOW(),
                        broker_buy_order_id  = %s,
                        exit_trigger         = '0940',
                        net_pnl              = %s,
                        status               = 'EXIT_PLACED_0940',
                        modtime              = NOW()
                    WHERE id = %s
                """, (live_ltp, live_ltp, broker_buy_id, est_pnl, row_id))
            db.commit()
            log(f"    ✅ DB updated → EXIT_PLACED_0940 | est_pnl=₹{est_pnl}")
        finally:
            db.close()

    log("=== 09:40 Hard Exit Cover complete ===\n")

if __name__ == '__main__':
    run()
