#!/usr/bin/env python3
"""
insert_shortsell_orders.py
--------------------------
Shared helper: inserts top-4 ML short-sell picks into markets.shortsell_orders.
Called by both live_0920_scalp_pipeline.py and live_0940_hybrid_pipeline.py
immediately after prediction.

isvalid lifecycle:
  FALSE  → not yet ready
  TRUE   → ready to place (set here immediately — time-based trigger)
  1.5    → order placed via Kotak API
  2      → order confirmed filled
  3      → order failed/rejected
  4      → skipped (already in open position)
"""

import pymysql
from datetime import datetime


def get_db_connection():
    return pymysql.connect(
        host='localhost', user='root', password='root',
        database='markets', cursorclass=pymysql.cursors.DictCursor
    )



def get_tick_size(price):
    if price <= 250:   return 0.01
    if price <= 1000:  return 0.05
    if price <= 5000:  return 0.10
    if price <= 10000: return 0.50
    if price <= 20000: return 1.00
    return 5.00

def round_to_tick(price):
    tick = get_tick_size(price)
    return round(round(price / tick) * tick, 2)

def insert_shortsell_orders(df_top4, model_name, trade_date=None, user_api='MANISHA', blocked_stocks=None):
    """
    Insert top-4 predictions into shortsell_orders table.

    Parameters
    ----------
    df_top4         : DataFrame of stocks that PASSED filters (will be isvalid=TRUE)
    model_name      : '0920_SCALP' or '0942_HYBRID'
    trade_date      : str YYYY-MM-DD (defaults to today)
    user_api        : Kotak user identifier (default 'MANISHA')
    blocked_stocks  : list of dicts {'stock', 'entry', 'qty', 'reason'} for audit trail
    """
    if trade_date is None:
        import pytz
        trade_date = datetime.now(pytz.timezone('Asia/Kolkata')).strftime('%Y-%m-%d')

    conn = get_db_connection()
    inserted = 0
    skipped  = 0

    try:
        with conn.cursor() as cursor:
            for order_rank, (_, row) in enumerate(df_top4.iterrows(), start=1):
                stockname = str(row.get('stockname') or row.get('clean_stock', '')).strip().upper()

                # Resolve quantity column name
                qty = int(
                    row.get('lotsize') or
                    row.get('total_quantity') or
                    row.get('quantity') or 0
                )

                # Resolve price column name
                price = float(
                    row.get('close_0919') or
                    row.get('entry_price_0940') or
                    row.get('limit_price') or 0.0
                )

                # Apply 2-tick slippage tolerance for 0920 Scalp Limit Orders
                if model_name == '0920_SCALP':
                    tick = get_tick_size(price)
                    price = price - (2 * tick)
                    
                # Snap to exact Kotak/NSE tick size
                price_r = round_to_tick(price)
                
                # SL: -₹5,000 / 1.00% Initial SL for 0920_SCALP (100% Single-Leg Trailing), 3.00%->1.50%->1.00% Dynamic SL for 0940/0942 HYBRID, 2% default
                if model_name == '0920_SCALP':
                    sl_price = min(
                        round_to_tick(price_r + (5000.0 / max(qty, 1))),
                        round_to_tick(price_r * 1.0100)
                    )
                elif '0940' in model_name or '0942' in model_name or 'HYBRID' in model_name:
                    sl_price = round_to_tick(price_r * 1.0300)
                else:
                    sl_price = round_to_tick(price_r * 1.02)

                if qty <= 0 or price_r <= 0:
                    print(f"  ⚠️  Skipping rank {order_rank} ({stockname}): invalid qty={qty} or price={price_r}")
                    skipped += 1
                    continue

                # Check if a non-FALSE row already exists (order already placed/filled)
                cursor.execute("""
                    SELECT id, isvalid FROM shortsell_orders
                    WHERE trade_date=%s AND model_name=%s AND order_rank=%s
                """, (trade_date, model_name, order_rank))
                existing = cursor.fetchone()

                if existing and existing['isvalid'] not in ('FALSE',):
                    print(f"  ℹ️  Rank {order_rank} ({stockname}) already has isvalid='{existing['isvalid']}' — skipping overwrite")
                    skipped += 1
                    continue

                # Upsert — safe to rerun
                cursor.execute("""
                    INSERT INTO shortsell_orders
                        (trade_date, model_name, order_rank, stockname, quantity,
                         limit_price, limit_price_original, stop_loss_price,
                         order_type, product_type, exchange_seg, isvalid, user_api)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'SELL', 'MIS', 'nse_cm', 'TRUE', %s)
                    ON DUPLICATE KEY UPDATE
                        stockname            = VALUES(stockname),
                        quantity             = VALUES(quantity),
                        limit_price          = VALUES(limit_price),
                        limit_price_original = VALUES(limit_price_original),
                        stop_loss_price      = VALUES(stop_loss_price),
                        isvalid              = 'TRUE',
                        user_api             = VALUES(user_api),
                        modtime              = NOW()
                """, (trade_date, model_name, order_rank, stockname, qty,
                      price_r, price_r, sl_price, user_api))
                inserted += 1
                print(f"  ✔  Rank {order_rank}: {stockname} | Qty={qty} | Price=₹{price_r} | SL=₹{sl_price} → isvalid=TRUE")

        conn.commit()
        print(f"\n  📋 shortsell_orders: {inserted} inserted/updated, {skipped} skipped [{model_name} | {trade_date}]")

        # ── Write blocked stocks as isvalid=FALSE (audit trail, Kotak will never pick these up) ──
        if blocked_stocks:
            with conn.cursor() as cursor:
                for b in blocked_stocks:
                    bstock = str(b.get('stock', '')).strip().upper()
                    bprice = round(float(b.get('entry', 0.0)), 2)
                    bqty   = int(b.get('qty', 0))
                    bsl    = round(bprice * 1.03, 2) if bprice else 0.0
                    breason = str(b.get('reason', 'FILTER_BLOCKED'))[:255]
                    # Use order_rank = 0 to mark these as "never traded"
                    # Or find existing rank from main insert — use stockname match
                    cursor.execute("""
                        INSERT INTO shortsell_orders
                            (trade_date, model_name, order_rank, stockname, quantity,
                             limit_price, limit_price_original, stop_loss_price,
                             order_type, product_type, exchange_seg, isvalid, user_api, notes)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'SELL', 'MIS', 'nse_cm', 'FALSE', %s, %s)
                        ON DUPLICATE KEY UPDATE
                            isvalid  = 'FALSE',
                            notes    = VALUES(notes),
                            modtime  = NOW()
                    """, (trade_date, model_name, 0, bstock, bqty,
                          bprice, bprice, bsl, user_api, breason))
                    print(f"  ⛔  BLOCKED: {bstock} | Qty={bqty} | Price=₹{bprice} → isvalid=FALSE | {breason}")
            conn.commit()

    except Exception as e:
        print(f"  ❌ Error inserting shortsell_orders: {e}")
        conn.rollback()
    finally:
        conn.close()


if __name__ == '__main__':
    # Quick test — show today's pending orders
    conn = get_db_connection()
    with conn.cursor() as c:
        c.execute("SELECT * FROM shortsell_orders WHERE trade_date=CURDATE() ORDER BY model_name, order_rank")
        rows = c.fetchall()
    conn.close()
    if rows:
        print(f"\nToday's shortsell_orders ({len(rows)} rows):")
        for r in rows:
            print(f"  [{r['model_name']}] Rank {r['order_rank']}: {r['stockname']} "
                  f"qty={r['quantity']} price=₹{r['limit_price']} isvalid={r['isvalid']}")
    else:
        print("No shortsell_orders found for today.")
