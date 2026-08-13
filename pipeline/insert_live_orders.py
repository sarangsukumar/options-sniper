#!/usr/bin/env python3
import pandas as pd
import pymysql
import os
import csv
from datetime import datetime

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
BASE_DIR    = os.path.dirname(SCRIPT_DIR)
PREDICTIONS_FILE = os.path.join(BASE_DIR, "output", "predictedstocksfortoday.csv")

def main():
    print("="*60)
    print(" 🚀 INSERTING LIVE PREDICTIONS INTO MARKETS.ORDERS")
    print("="*60)

    if not os.path.exists(PREDICTIONS_FILE):
        print(f"❌ Error: Predictions file not found at {PREDICTIONS_FILE}")
        return

    # Read CSV manually since rows have variable lengths (2 or 3 cols) and no header
    today_dt_str = None
    today_records = []
    
    with open(PREDICTIONS_FILE, 'r') as f:
        reader = csv.reader(f)
        rows = list(reader)
        
    if not rows:
        print("ℹ️ No predictions found (file empty).")
        return
        
    # The last row should be today's predictions
    # We find the latest date in the file
    latest_date_val = max([r[0] for r in rows if r])
    
    for r in rows:
        if r and r[0] == latest_date_val:
            stock = r[1]
            qty = int(r[2]) if len(r) > 2 else 1
            today_records.append({'stock': stock, 'qty': qty})
            today_dt_str = r[0]

    if not today_records:
        print("ℹ️ No valid predictions found for today.")
        return

    # Parse YYYYMMDD to YYYY-MM-DD
    target_dt = datetime.strptime(today_dt_str, '%Y%m%d').strftime('%Y-%m-%d')
    print(f"Target Date: {target_dt}")

    # Connect to MySQL
    conn = pymysql.connect(host='localhost', user='root', password='root', database='markets')
    cursor = conn.cursor()

    del_query = "DELETE FROM orders WHERE simulationtime = %s AND USER = 'MANISHA'"
    cursor.execute(del_query, (target_dt,))
    print(f"🧹 Cleared {cursor.rowcount} old/duplicate MANISHA orders for {target_dt}.")

    insert_query = """
        INSERT INTO orders (
            stockname, price, quantity, type, ismarket, stoplossprice, 
            limitprice, limitprice_original, simulationtime, credate, 
            isvalid, is_future, USER, order_rank
        ) VALUES (
            %s, %s, %s, %s, %s, %s, 
            %s, %s, %s, %s, 
            %s, %s, %s, %s
        )
    """

    inserted = 0
    for idx, rec in enumerate(today_records, start=1):
        stockname = rec['stock']
        qty = rec['qty']
        
        cursor.execute(insert_query, (
            stockname, 0.0, qty, 'BUY', 'FALSE', 0.0,
            0.0, 0.0, target_dt, target_dt,
            'FALSE', 'TL', 'MANISHA', f'TL_{idx}'
        ))
        inserted += 1
        print(f"  ✔ Inserted: {stockname} (Qty: {qty}, Rank: TL_{idx})")

    conn.commit()
    cursor.close()
    conn.close()
    
    print(f"\n✅ Successfully inserted {inserted} live order(s) into markets.orders table for execution!")
    print("="*60)

if __name__ == '__main__':
    main()
