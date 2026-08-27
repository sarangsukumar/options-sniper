import redis
import mysql.connector
import json
import logging
import sys
from datetime import datetime

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    stream=sys.stdout,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def update_limit_prices_from_redis():
    """
    Fetches the latest LTP for stocks from Redis (LTP:<STOCKNAME>) 
    and updates the limitprice field in markets.orders for today's valid orders.
    """
    logging.info("Starting Redis LTP sync to markets.orders limitprice...")

    # Connect to Redis
    try:
        r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
        r.ping()
        logging.info("Connected to Redis successfully.")
    except Exception as e:
        logging.error(f"Failed to connect to Redis: {e}")
        return

    # Connect to MySQL DB
    try:
        db = mysql.connector.connect(
            host="localhost",
            user="root",
            password="root",
            database="markets"
        )
        cursor = db.cursor(dictionary=True)
        logging.info("Connected to MySQL database 'markets' successfully.")
    except Exception as e:
        logging.error(f"Failed to connect to MySQL database: {e}")
        return

    # Fetch today's orders from markets.orders
    todaysdate = datetime.now().strftime("%Y-%m-%d")
    query = f"""
        SELECT id, stockname, limitprice, USER 
        FROM markets.orders 
        WHERE DATE_FORMAT(simulationtime, '%Y-%m-%d') = '{todaysdate}'
    """
    cursor.execute(query)
    orders = cursor.fetchall()

    if not orders:
        logging.info(f"No orders found in markets.orders for today ({todaysdate}).")
        db.close()
        return

    logging.info(f"Found {len(orders)} order(s) for today to process.")

    updated_count = 0
    for order in orders:
        order_id = order['id']
        stockname = order['stockname'].strip()

        # Query Redis key format "LTP:<STOCKNAME>"
        redis_key = f"LTP:{stockname}"
        raw_val = r.get(redis_key)

        if not raw_val:
            logging.warning(f"No Redis key found for {redis_key}. Skipping order ID {order_id}.")
            continue

        try:
            val_data = json.loads(raw_val)
            ltp = val_data.get('ltp')
            if ltp is not None and float(ltp) > 0:
                ltp_float = float(ltp)
                update_sql = "UPDATE markets.orders SET limitprice = %s, limitprice_original = %s, isvalid = 'FALSE' WHERE id = %s"
                cursor.execute(update_sql, (ltp_float, ltp_float, order_id))
                logging.info(f"Updated Order ID {order_id} ({stockname}) User: {order['USER']} - Set limitprice & limitprice_original: {ltp_float}, isvalid: FALSE")
                updated_count += 1
            else:
                logging.warning(f"Invalid LTP value in Redis for {stockname}: {raw_val}")
        except Exception as err:
            logging.error(f"Error parsing Redis data for {stockname}: {err}")

    db.commit()
    db.close()
    logging.info(f"Redis LTP Sync Complete! Updated {updated_count} order(s).")

    # --- Dispatch Telegram Status Alert to Main Group (-698073972) ---
    if updated_count > 0:
        import requests
        bot_token = "5350311365:AAFkTUBR4IGvgS5Z9mJngz-mgk7-HkhFEYE"
        chat_id = "-698073972"
        
        msg = f"🔒 <b>3:23 PM BASE PRICES LOCKED ({todaysdate})</b>\n"
        msg += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        for idx, o in enumerate(orders, 1):
            stock = o['stockname'].strip()
            usr = o['USER']
            rk = f"LTP:{stock}"
            rv = r.get(rk)
            ltp_val = "N/A"
            if rv:
                try: 
                    ltp_val = f"₹{float(json.loads(rv).get('ltp')):.2f}"
                except: 
                    pass
            msg += f"<b>{idx}. {stock}</b> (BUY) - {usr}\n"
            msg += f"  • 3:23 PM Locked Base LTP: {ltp_val}\n"
            msg += f"  • Status: Dip Watch Started (LTP <= Base Price)\n"
            msg += "------------------------------------\n"
        
        try:
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            payload = {
                "chat_id": chat_id,
                "text": msg,
                "parse_mode": "HTML"
            }
            resp = requests.post(url, json=payload, timeout=10)
            logging.info(f"Dispatched 3:23 PM Base Price Lock Telegram Alert to Group {chat_id}: {resp.status_code}")
        except Exception as e_bot:
            logging.error(f"Error sending Telegram alert: {e_bot}")

if __name__ == "__main__":
    update_limit_prices_from_redis()
