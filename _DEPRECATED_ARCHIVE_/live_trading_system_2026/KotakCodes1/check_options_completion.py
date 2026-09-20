#!/usr/bin/env python3
import mysql.connector
import datetime
import os
import subprocess

DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': 'root',
    'database': 'markets'
}

def main():
    today_str = datetime.date.today().strftime('%Y-%m-%d')
    flag_file = f"/home/ubuntu/KotakCodes1/options_pnl_sent_{today_str}.flag"
    
    # If we already sent the PNL today, just exit silently
    if os.path.exists(flag_file):
        return

    conn = mysql.connector.connect(**DB_CONFIG)
    cursor = conn.cursor(dictionary=True)
    
    # Count how many orders exist today
    cursor.execute("SELECT COUNT(*) as total, SUM(CASE WHEN isvalid IN ('4', 'TRUE') THEN 1 ELSE 0 END) as completed FROM orders_option WHERE DATE(simulationtime) = %s", (today_str,))
    row = cursor.fetchone()
    
    cursor.close()
    conn.close()

    total_orders = row['total'] if row and row['total'] else 0
    completed_orders = row['completed'] if row and row['completed'] else 0

    if total_orders > 0 and total_orders == completed_orders:
        print(f"[{datetime.datetime.now()}] All {total_orders} options orders completed! Triggering PNL pipeline...")
        
        # 1. Sync the broker database
        print("Running Neo_insert_into_broker_orders.py...")
        subprocess.run(["python3", "/home/ubuntu/KotakCodes1/Neo_insert_into_broker_orders.py"])
        
        # 2. Send the Telegram PNL alert
        print("Running notify_options_pnl.py...")
        subprocess.run(["python3", "/home/ubuntu/KotakCodes1/notify_options_pnl.py", "PNL"])
        
        
        # 3. Verify completely flat Kotak positions (Safety Check)
        print("Running verify_flat_positions.py...")
        subprocess.run(["python3", "/home/ubuntu/KotakCodes1/verify_flat_positions.py"])
        
        # 4. Create flag file so it doesn't run again today

        with open(flag_file, 'w') as f:
            f.write("Sent!")
        
        print("Pipeline finished successfully.")

if __name__ == "__main__":
    main()
