#!/usr/bin/env python3
"""
exit_0936_check.py
==================
Runs at exactly 09:36:00 IST.

For every SELL_FILLED position in scalp_trade_log today:
  - Fetches live LTP from Kotak API
  - Calculates profit_pct = (sell_price - live_ltp) / sell_price * 100
  - If profit_pct > 0.05%  → places Limit Buy order at LTP (early exit)
                             status = 'EXIT_PLACED_0936'
  - If profit_pct <= 0.05% → holds, status unchanged (09:40 will handle)
"""

import sys
import os
import pymysql
from datetime import date, datetime

sys.path.insert(0, '/home/ubuntu/KotakCodes1')

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cron_0920_scalp.log')

def log(msg):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{ts}] [EXIT_0936] {msg}"
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
    """Fetch live LTP using Kotak Neo client.quotes() — same as entry script."""
    try:
        # Load the token map the same way Neo_shortsell_mis_order does
        from Neo_shortsell_mis_order import get_instrument_token
        token = get_instrument_token(stockname)
        if not token:
            log(f"    ⚠️  No token for {stockname}")
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

def place_buy_cover(client, stockname, quantity, ltp, scripcode):
    """Place a Limit Buy-to-cover order at the current LTP."""
    try:
        from Neo_shortsell_mis_order import get_instrument_token
        # Format price to 2 decimal places
        limit_price = str(round(ltp, 2))
        resp = client.place_order(
            exchange_segment='nse_cm',
            product='MIS',
            price=limit_price,
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

def get_scripcode(client, stockname):
    """Get the trading symbol (scripcode) for Kotak order placement."""
    try:
        from Neo_shortsell_mis_order import get_instrument_token, TOKEN_TO_SYMBOL
        token = get_instrument_token(stockname)
        if token and token in TOKEN_TO_SYMBOL:
            return TOKEN_TO_SYMBOL[token]
        # Fallback — try EQ suffix format
        return f"{stockname}-EQ"
    except Exception as e:
        return f"{stockname}-EQ"

PROFIT_THRESHOLD_PCT = 0.05   # Exit early only if profit > 0.05%

def run():
    today = date.today().strftime('%Y-%m-%d')
    log(f"=== 09:36 Variable Exit Check starting for {today} ===")
    log(f"    Threshold: profit > {PROFIT_THRESHOLD_PCT}% → early exit | else hold to 09:40")

    # Fetch all SELL_FILLED positions for today
    db = get_db()
    try:
        with db.cursor() as c:
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
        log("No SELL_FILLED positions found — nothing to exit at 09:36.")
        return

    log(f"Found {len(positions)} open filled positions.")
    client = get_kotak_client()

    for pos in positions:
        row_id     = pos['id']
        stockname  = pos['stockname']
        quantity   = pos['quantity']
        sell_price = pos['sell_price']

        if not sell_price or sell_price <= 0:
            log(f"  {stockname}: No valid sell_price — skipping.")
            continue

        log(f"  {stockname} | sell_price=₹{sell_price} | qty={quantity}")

        # Fetch live LTP
        live_ltp = None
        if client:
            live_ltp = fetch_live_ltp(client, stockname)

        if not live_ltp or live_ltp <= 0:
            log(f"    ⚠️  Could not fetch LTP — holding to 09:40.")
            continue

        profit_pct = (sell_price - live_ltp) / sell_price * 100.0
        log(f"    LTP=₹{live_ltp} | profit={profit_pct:.3f}% (threshold={PROFIT_THRESHOLD_PCT}%)")

        db = get_db()
        try:
            with db.cursor() as c:
                if profit_pct > PROFIT_THRESHOLD_PCT:
                    # Place early exit order
                    log(f"    ✅ Profit > {PROFIT_THRESHOLD_PCT}% → placing early BUY cover at ₹{live_ltp}")
                    scripcode = get_scripcode(client, stockname)
                    resp = None
                    broker_buy_id = None

                    if client:
                        resp = place_buy_cover(client, stockname, quantity, live_ltp, scripcode)
                        if resp:
                            broker_buy_id = resp.get('nOrdNo') or resp.get('message', '')
                            log(f"    Order response: {resp}")

                    c.execute("""
                        UPDATE scalp_trade_log
                        SET buy_ltp_used = %s, broker_buy_order_id = %s,
                            exit_trigger = '0936', status = 'EXIT_PLACED_0936',
                            notes = CONCAT(IFNULL(notes,''), ' | 09:36 exit: profit=', %s, '%%'),
                            modtime = NOW()
                        WHERE id = %s
                    """, (live_ltp, broker_buy_id, round(profit_pct, 3), row_id))

                else:
                    log(f"    ⏳ Profit ≤ {PROFIT_THRESHOLD_PCT}% → holding to 09:40 exit.")
                    c.execute("""
                        UPDATE scalp_trade_log
                        SET notes = CONCAT(IFNULL(notes,''), ' | 09:36 skip: profit=', %s, '%%'),
                            modtime = NOW()
                        WHERE id = %s
                    """, (round(profit_pct, 3), row_id))

            db.commit()
        finally:
            db.close()

    log("=== 09:36 Variable Exit Check complete ===\n")

if __name__ == '__main__':
    run()
