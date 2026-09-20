import mysql.connector
import datetime
import subprocess
import pandas as pd
import sys
import os

DB_HOST = "localhost"
DB_USER = "root"
DB_PASSWORD = "root"
DB_NAME = "markets"

def notify_options_morning_targets():
    today_str = datetime.date.today().strftime('%Y-%m-%d')
    
    try:
        conn = mysql.connector.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME
        )
        cursor = conn.cursor(dictionary=True)
        
        query = f"""
            SELECT stockname, strikeprice, optiontype, type, quantity, limitprice, USER
            FROM markets.orders_option
            WHERE DATE(simulationtime) = '{today_str}' 
            AND is_future = 'OPTIONS' 
            AND order_rank LIKE 'TL_opt_%'
            ORDER BY stockname ASC, type ASC
        """
        cursor.execute(query)
        orders = cursor.fetchall()
        cursor.close()
        conn.close()
        
        if not orders:
            msg = f"🎯 <b>MORNING OPTIONS SQUARE-OFF TARGETS ({today_str})</b>\nNo options square-off orders scheduled for today."
        else:
            msg = f"🎯 <b>MORNING OPTIONS SQUARE-OFF TARGETS ({today_str})</b>\n"
            msg += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            for idx, order in enumerate(orders, 1):
                stock = order['stockname']
                strike = order['strikeprice']
                opt_type = order['optiontype']
                user = order['USER']
                num_lots = float(order['quantity'])
                limit_str = f"₹{order['limitprice']:.2f}" if order['limitprice'] is not None else "Will be fetched live from Redis at 09:28"
                trade_type = order['type']
                
                msg += f"<b>{idx}. {stock} {strike:.2f} {opt_type}</b> ({trade_type}) - {user}\n"
                msg += f"  • Limit Set: {limit_str}\n"
                msg += f"  • Quantity: {num_lots} Lots\n"
                msg += "------------------------------------\n"
                
        print("Sending Telegram Alert via Status Bot:\n", msg)
        bot_script = "/home/ubuntu/KotakCodes1/status_Info_bot.js"
        res = subprocess.run(['node', bot_script, msg], capture_output=True, text=True, timeout=15)
        print("Status Bot Output:", res.stdout)
        
    except Exception as e:
        print(f"Error notifying options morning targets: {e}")

if __name__ == "__main__":
    notify_options_morning_targets()
