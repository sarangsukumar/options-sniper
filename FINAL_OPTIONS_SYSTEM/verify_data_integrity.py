import mysql.connector
import pandas as pd

db = mysql.connector.connect(host='localhost', user='root', password='root', database='markets')
cursor = db.cursor(dictionary=True)

print("=== DATA INTEGRITY CHECK (09:15 to 09:30 Window) ===")

# 1. Check for 0 or negative prices
cursor.execute("""
    SELECT COUNT(*) as bad_rows
    FROM scrapdata_options
    WHERE TIME(datetime) BETWEEN '15:15:00' AND '15:30:00'
      AND (close <= 0 OR open <= 0)
""")
bad_prices = cursor.fetchone()['bad_rows']
print(f"1. Rows with zero or negative prices: {bad_prices}")

# 2. Check for missing/zero volume (some providers put 0 volume if carried forward)
cursor.execute("""
    SELECT COUNT(*) as zero_vol
    FROM scrapdata_options
    WHERE TIME(datetime) BETWEEN '15:15:00' AND '15:30:00'
      AND volume = 0
""")
zero_vol = cursor.fetchone()['zero_vol']
print(f"2. Rows with ZERO volume in morning window: {zero_vol}")

# 3. Dump a raw random sample to visually inspect
print("\n3. Raw Data Sample (Checking HAL on a random morning):")
cursor.execute("""
    SELECT datetime, strike_price, open, high, low, close, volume
    FROM scrapdata_options
    WHERE stock_code = 'HAL' 
      AND DATE(datetime) = '2024-04-18' 
      AND TIME(datetime) BETWEEN '15:15:00' AND '15:30:00'
    ORDER BY strike_price DESC, datetime ASC
""")
rows = cursor.fetchall()
if rows:
    df = pd.DataFrame(rows)
    print(df.to_string(index=False))
else:
    print("No data found for HAL on 2024-04-18 morning. (Checking another...)")
    cursor.execute("""
        SELECT datetime, strike_price, open, high, low, close, volume
        FROM scrapdata_options
        WHERE stock_code = 'HAL' 
          AND DATE(datetime) = (SELECT MAX(DATE(datetime)) FROM scrapdata_options WHERE stock_code='HAL')
          AND TIME(datetime) BETWEEN '15:15:00' AND '15:30:00'
        ORDER BY strike_price DESC, datetime ASC
        LIMIT 30
    """)
    rows2 = cursor.fetchall()
    df2 = pd.DataFrame(rows2)
    print(df2.to_string(index=False))

