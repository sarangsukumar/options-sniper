import mysql.connector
import pandas as pd
import numpy as np
import datetime

db = mysql.connector.connect(host='localhost', user='root', password='root', database='markets')
cursor = db.cursor(dictionary=True)

def get_trading_days(cursor, stock, start_date):
    cursor.execute(
        "SELECT DISTINCT DATE(datetime) as d FROM scrapdata_options "
        "WHERE stock_code=%s AND DATE(datetime) > %s ORDER BY d ASC LIMIT 5",
        (stock, start_date)
    )
    rows = cursor.fetchall()
    return [str(r['d']) for r in rows]

# Load all targets
df_list = []
for y in [2024, 2025, 2026]:
    try:
        df = pd.read_csv(f'experiment_targets_{y}.csv')
        df_list.append(df)
    except: pass
targets = pd.concat(df_list)
r1_r3 = targets[(targets['rank_type'].isin(['R1','R3'])) & (targets['buy_price'] != 'UNKNOWN')].copy()

cross_expiry_trades = []
safe_trades = []

for _, row in r1_r3.iterrows():
    stock = row['stock']
    buy_date = row['buy_date']
    expiry_str = str(row['expiry_date']).split('T')[0] # e.g. 2024-01-25
    
    future_dates = get_trading_days(cursor, stock, buy_date)
    if len(future_dates) < 2: continue
    
    day1_exit = future_dates[0]
    day2_exit = future_dates[1]
    
    # Check if Day 2 Exit is AFTER the expiry date!
    # Or if Day 1 is the expiry date (meaning Day 2 is in the next month!)
    is_cross_expiry = False
    if expiry_str and expiry_str != 'None':
        # If Day 2 falls past expiry date
        if day2_exit > expiry_str:
            is_cross_expiry = True
        # If Day 1 was expiry day, then holding to Day 2 crosses contract death!
        if day1_exit >= expiry_str:
            is_cross_expiry = True
            
    if is_cross_expiry:
        cross_expiry_trades.append({
            'stock': stock, 'buy_date': buy_date,
            'day1_exit': day1_exit, 'day2_exit': day2_exit,
            'expiry': expiry_str
        })
    else:
        safe_trades.append({
            'stock': stock, 'buy_date': buy_date,
            'day1_exit': day1_exit, 'day2_exit': day2_exit,
            'expiry': expiry_str
        })

print(f"Total Evaluated Trades: {len(cross_expiry_trades) + len(safe_trades)}")
print(f"Safe Trades (Day 2 finishes BEFORE or ON Expiry): {len(safe_trades)}")
print(f"DANGEROUS CROSS-EXPIRY TRADES (Day 2 crosses past Expiry Date): {len(cross_expiry_trades)}")

print("\n--- Examples of Cross-Expiry Trades Found ---")
df_cross = pd.DataFrame(cross_expiry_trades)
if not df_cross.empty:
    print(df_cross.head(15).to_string(index=False))
else:
    print("None found!")
