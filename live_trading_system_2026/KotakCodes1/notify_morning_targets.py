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

def load_lot_sizes():
    lot_size_map = {}
    csv_path = "/home/ubuntu/KotakCodes1/masterfile/ICICImaster.csv"
    try:
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
        print(f"Warning loading lot sizes: {e}")
    return lot_size_map

def notify_morning_targets():
    lot_size_map = load_lot_sizes()
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
            SELECT stockname, limitprice, limitprice_original, quantity, type, USER
            FROM markets.orders
            WHERE DATE(simulationtime) = '{today_str}'
            ORDER BY id ASC
        """
        cursor.execute(query)
        orders = cursor.fetchall()
        cursor.close()
        conn.close()
        
        if not orders:
            msg = f"🎯 <b>MORNING SQUARE-OFF TARGETS ({today_str})</b>\nNo square-off orders scheduled for today."
        else:
            msg = f"🎯 <b>MORNING SQUARE-OFF TARGETS ({today_str})</b>\n"
            msg += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            for idx, order in enumerate(orders, 1):
                stock = order['stockname']
                user = order['USER']
                num_lots = int(order['quantity'])
                target_limit = order['limitprice_original'] if order['limitprice_original'] and order['limitprice_original'] > 0 else order['limitprice']
                
                lot_sz = lot_size_map.get(stock, 1)
                total_qty = num_lots * lot_sz
                
                # Morning Square-off exit is a SELL order
                msg += f"<b>{idx}. {stock}</b> (SELL Square-Off) - {user}\n"
                msg += f"  • Target Limit Price: ₹{target_limit:.2f}\n"
                msg += f"  • Quantity: {total_qty} ({num_lots} {'lot' if num_lots==1 else 'lots'} x {lot_sz})\n"
                msg += "------------------------------------\n"
                
        print("Sending Telegram Alert via Status Bot:\n", msg)
        bot_script = "/home/ubuntu/KotakCodes1/status_Info_bot.js"
        res = subprocess.run(['node', bot_script, msg], capture_output=True, text=True, timeout=15)
        print("Status Bot Output:", res.stdout)
        
    except Exception as e:
        print(f"Error notifying morning targets: {e}")

if __name__ == "__main__":
    notify_morning_targets()
