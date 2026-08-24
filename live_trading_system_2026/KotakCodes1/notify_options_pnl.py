#!/usr/bin/env python3
import mysql.connector
import requests
import datetime
import os

# Telegram Configuration for OrderInfoBot
TELEGRAM_BOT_TOKEN = "5350311365:AAFkTUBR4IGvgS5Z9mJngz-mgk7-HkhFEYE"
TELEGRAM_CHAT_ID = "-698073972"

# Database Configuration
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': 'root',
    'database': 'markets'
}

def fetch_today_executed_orders():
    today_str = datetime.date.today().strftime('%Y-%m-%d')
    conn = mysql.connector.connect(**DB_CONFIG)
    cursor = conn.cursor(dictionary=True)
    
    query = """
    SELECT 
        b.orderexecutiondate AS exec_date,
        b.stockname AS stockname,
        b.strike_price AS strike_price,
        b.option_type AS option_type,
        b.type AS trade_type,
        b.quantity AS quantity,
        COALESCE(o.limitprice, 0.0) AS limit_price_set,
        COALESCE(o.limitprice_original, o.limitprice, 0.0) AS orig_limit_price,
        b.price AS executed_price,
        b.orderexecutiontime AS exec_time,
        b.order_tag AS order_tag,
        b.USER AS user_name,
        buy.price AS buy_price,
        buy.orderexecutiondate AS buy_date
    FROM broker_options_orders b
    LEFT JOIN orders_option o 
        ON b.stockname = o.stockname 
        AND b.strike_price = o.strikeprice
        AND b.option_type = o.optiontype
        AND DATE(b.orderexecutiontime) = DATE(o.simulationtime)
        AND b.USER = o.USER
    LEFT JOIN broker_options_orders buy
        ON b.stockname = buy.stockname
        AND b.strike_price = buy.strike_price
        AND b.option_type = buy.option_type
        AND b.USER = buy.USER
        AND buy.type != b.type
        AND buy.orderexecutiondate = (
            SELECT MAX(orderexecutiondate)
            FROM broker_options_orders
            WHERE stockname = b.stockname
              AND strike_price = b.strike_price
              AND option_type = b.option_type
              AND USER = b.USER
              AND type != b.type
              AND orderexecutiondate < b.orderexecutiondate
        )
    WHERE DATE(b.orderexecutiontime) = %s
    ORDER BY b.orderexecutiontime ASC
    """
    
    cursor.execute(query, (today_str,))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows

def load_lot_sizes():
    """Loads a mapping of stockcode -> lot_size from ICICImaster.csv."""
    lot_size_map = {}
    csv_path = "/home/ubuntu/KotakCodes1/masterfile/ICICImaster.csv"
    try:
        import pandas as pd
        df = pd.read_csv(csv_path, low_memory=False)
        df.columns = df.columns.str.strip().str.lower()
        for _, row in df.iterrows():
            stock = str(row['stockcodes']).strip().upper()
            try:
                ls = int(row['lotsize'])
                lot_size_map[stock] = ls
            except:
                pass
    except Exception as e:
        print(f"Warning: Could not load lot sizes from CSV: {e}")
    return lot_size_map

def format_telegram_message(orders, report_mode='ALL'):
    lot_size_map = load_lot_sizes()
    
    if report_mode == 'ENTRY':
        entry_orders = orders
        if not entry_orders:
            return f"ℹ️ *OPTIONS ENTRY REPORT ({datetime.date.today().strftime('%Y-%m-%d')})*\nNo entry orders executed today."
            
        msg = f"📊 *OPTIONS ENTRY EXECUTED ORDERS ({datetime.date.today().strftime('%Y-%m-%d')})*\n"
        msg += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        
        for idx, order in enumerate(entry_orders, 1):
            exec_time_str = order['exec_time'].strftime('%H:%M:%S') if isinstance(order['exec_time'], datetime.datetime) else str(order['exec_time'])
            limit_price = order['limit_price_set']
            exec_price = order['executed_price']
            qty = order['quantity']
            stock_name = f"{order['stockname']} {order['strike_price']} {order['option_type']}"
            
            lot_sz = lot_size_map.get(order['stockname'], qty)
            num_lots = max(1, round(qty / lot_sz)) if lot_sz > 0 else 1
            
            diff = exec_price - limit_price if limit_price > 0 else 0
            diff_str = f"({diff:+.2f})" if limit_price > 0 else ""
            
            msg += f"*{idx}. {stock_name}* ({order['trade_type']}) - {order['user_name']}\n"
            msg += f"  • *Exec Time:* `{exec_time_str}`\n"
            msg += f"  • *Limit Set:* ₹{limit_price:.2f} | *Exec Price:* ₹{exec_price:.2f} {diff_str}\n"
            msg += f"  • *Quantity:* {qty} ({num_lots} {'lot' if num_lots==1 else 'lots'})\n"
            msg += f"  • *Tag:* `{order['order_tag']}`\n"
            msg += "------------------------------------\n"
        return msg

    elif report_mode == 'PNL':
        sqoff_orders = orders
        if not sqoff_orders:
            return f"ℹ️ *Square-Off PnL Report ({datetime.date.today().strftime('%Y-%m-%d')})*\nNo square-off orders executed today."
            
        buy_date_val = sqoff_orders[0].get('buy_date')
        buy_date_str = str(buy_date_val) if buy_date_val else "Prev Day"
        today_date_str = datetime.date.today().strftime('%Y-%m-%d')
        
        msg = f"📊 *OPTIONS SQUARE-OFF PnL REPORT*\n"
        msg += f"🗓️ *Entry Date:* `{buy_date_str}` ➔ *Square-Off Date:* `{today_date_str}`\n"
        msg += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        
        total_gross_pnl = 0.0
        total_commission = 0.0
        total_net_pnl = 0.0
        FLAT_COMMISSION_PER_LOT = 200.0
        
        for idx, order in enumerate(sqoff_orders, 1):
            exec_time_str = order['exec_time'].strftime('%H:%M:%S') if isinstance(order['exec_time'], datetime.datetime) else str(order['exec_time'])
            orig_limit = order['orig_limit_price']
            limit_price = order['limit_price_set']
            exec_price = order['executed_price']
            buy_price = order['buy_price']
            qty = order['quantity']
            qty = order['quantity']
            stock_name = f"{order['stockname']} {order['strike_price']} {order['option_type']}"
            
            lot_sz = lot_size_map.get(order['stockname'], qty)
            num_lots = max(1, round(qty / lot_sz)) if lot_sz > 0 else 1
            
            diff = exec_price - limit_price if limit_price > 0 else 0
            diff_str = f"({diff:+.2f})" if limit_price > 0 else ""
            
            msg += f"*{idx}. {stock_name}* (SQUARE-OFF) - {order['user_name']}\n"
            msg += f"  • *Exec Time:* `{exec_time_str}`\n"
            msg += f"  • *Custom Limit (0%):* ₹{orig_limit:.2f}\n"
            msg += f"  • *Triggered Limit:* ₹{limit_price:.2f} | *Exec Price:* ₹{exec_price:.2f} {diff_str}\n"
            msg += f"  • *Quantity:* {qty} ({num_lots} {'lot' if num_lots==1 else 'lots'})\n"
            
            if buy_price is not None:
                # If we are SELLING today, we bought yesterday (Long). Profit = Exit - Entry
                if order['trade_type'] == 'SELL':
                    gross_pnl = (exec_price - buy_price) * qty
                    pnl_pct = ((exec_price - buy_price) / buy_price * 100) if buy_price > 0 else 0.0
                # If we are BUYING today, we sold yesterday (Short). Profit = Entry - Exit
                else:
                    gross_pnl = (buy_price - exec_price) * qty
                    pnl_pct = ((buy_price - exec_price) / buy_price * 100) if buy_price > 0 else 0.0

                comm = num_lots * FLAT_COMMISSION_PER_LOT
                net_pnl = gross_pnl - comm
                
                total_gross_pnl += gross_pnl
                total_commission += comm
                total_net_pnl += net_pnl
                
                pnl_icon = "🟢" if net_pnl >= 0 else "🔴"
                msg += f"  • *Entry Price:* ₹{buy_price:.2f}\n"
                msg += f"  • *Gross PnL:* ₹{gross_pnl:+.2f} ({pnl_pct:+.2f}%)\n"
                msg += f"  • *Commission/Charges:* ₹{comm:.2f} ({num_lots} x ₹200)\n"
                msg += f"  • *Net PnL:* {pnl_icon} *₹{net_pnl:+.2f}*\n"
            
            msg += "------------------------------------\n"
            
        if total_gross_pnl != 0.0 or total_commission != 0.0:
            summary_icon = "🟢" if total_net_pnl >= 0 else "🔴"
            msg += f"\n💰 *TOTAL SUMMARY*\n"
            msg += f"  • *Total Gross PnL:* ₹{total_gross_pnl:+.2f}\n"
            msg += f"  • *Total Charges (₹200/lot):* ₹{total_commission:.2f}\n"
            msg += f"  • *Total Net PnL:* {summary_icon} *₹{total_net_pnl:+.2f}*\n"
            
        return msg

    else:
        return format_telegram_message(orders, report_mode='PNL') + "\n\n" + format_telegram_message(orders, report_mode='ENTRY')

def send_telegram_notification(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': text,
        'parse_mode': 'Markdown'
    }
    response = requests.post(url, data=payload, timeout=10)
    return response.json()

if __name__ == "__main__":
    import sys
    try:
        mode = 'AUTO'
        if len(sys.argv) > 1:
            mode = sys.argv[1].upper()
        else:
            current_hour = datetime.datetime.now().hour
            mode = 'PNL' if current_hour < 12 else 'ENTRY'
            
        executed_orders = fetch_today_executed_orders()
        message = format_telegram_message(executed_orders, report_mode=mode)
        print("Generated Message:\n", message)
        res = send_telegram_notification(message)
        print("Telegram API Response:", res)
    except Exception as e:
        print("Error executing notification script:", e)
