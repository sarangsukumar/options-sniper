#!/usr/bin/env python3
import pandas as pd
import pymysql
import os
import csv
from datetime import datetime

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
BASE_DIR    = os.path.dirname(SCRIPT_DIR)
PREDICTIONS_FILE = os.path.join(BASE_DIR, "output", "predictedstocksfortoday.csv")


def last_tuesday_of_month(year, month):
    import calendar
    import datetime
    last_day = calendar.monthrange(year, month)[1]
    dt = datetime.date(year, month, last_day)
    offset = (dt.weekday() - 1) % 7
    return dt - datetime.timedelta(days=offset)

def get_active_expiry():
    import datetime
    import re
    today = datetime.datetime.utcnow().date() + datetime.timedelta(hours=5, minutes=30)
    
    try:
        with open('/home/ubuntu/KotakCodes1/expiry_dates.txt', 'r') as f:
            txt_content = f.read()
        match = re.search(r'const expiryDatesList = "(.*)";', txt_content)
        if not match:
            raise ValueError("Regex failed to find expiryDatesList string")
            
        dates_str = match.group(1)
        valid_dates = []
        for d in dates_str.split(','):
            try:
                valid_dates.append(datetime.datetime.strptime(d.strip(), '%Y-%m-%d').date())
            except:
                pass
                
        valid_dates.sort()
        future_expiries = [d for d in valid_dates if d >= today]
        
        if future_expiries:
            expiry = future_expiries[0]
        else:
            raise ValueError("No future expiry dates found in txt file")
            
    except Exception as e:
        print(f"⚠️ Falling back to manual expiry calculation: {e}")
        expiry = last_tuesday_of_month(today.year, today.month)
        if today > expiry:
            if today.month == 12:
                expiry = last_tuesday_of_month(today.year + 1, 1)
            else:
                expiry = last_tuesday_of_month(today.year, today.month + 1)
    return expiry

def is_expiry_day():
    import datetime
    today = datetime.datetime.utcnow().date() + datetime.timedelta(hours=5, minutes=30)
    expiry_date = get_active_expiry()
    return today >= expiry_date


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

    # ── SNIPER R1+R3 EXECUTION FILTER ───────────────────────────────────────
    # The CSV contains up to 4 baseline trades for ML threshold integrity.
    # Only Rank 1 (index 0) and Rank 3 (index 2) are actual execution orders.
    # On scarce days (fewer than 3 candidates), only Rank 1 is inserted.
    if len(today_records) >= 3:
        execution_records = [today_records[0], today_records[2]]  # R1 and R3
        print(f"ℹ️  Normal Day: Inserting R1 ({today_records[0]['stock']}) and R3 ({today_records[2]['stock']}) only.")
    elif len(today_records) >= 1:
        execution_records = [today_records[0]]  # R1 only on scarce days
        print(f"ℹ️  Scarce Day: Inserting R1 ({today_records[0]['stock']}) only.")
    else:
        execution_records = []

    inserted = 0
    for idx, rec in enumerate(execution_records, start=1):
        stockname = rec['stock']
        qty = rec['qty']
        rank_label = 'TL_1' if idx == 1 else 'TL_3'

        cursor.execute(insert_query, (
            stockname, 0.0, qty, 'BUY', 'FALSE', 0.0,
            0.0, 0.0, target_dt, target_dt,
            'FALSE', 'TL', 'MANISHA', rank_label
        ))
        inserted += 1
        print(f"  ✔ Inserted: {stockname} (Qty: {qty}, Rank: {rank_label})")

    conn.commit()
    cursor.close()
    conn.close()
    
    print(f"\n✅ Successfully inserted {inserted} live order(s) into markets.orders table for execution!")
    print("="*60)

if __name__ == '__main__':
    main()
