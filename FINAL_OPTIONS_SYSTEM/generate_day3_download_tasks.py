import mysql.connector
import pandas as pd

db = mysql.connector.connect(host='localhost', user='root', password='root', database='markets')
cursor = db.cursor(dictionary=True)

# Fetch all unique trading dates from existing database to accurately know NSE trading calendar
cursor.execute("SELECT DISTINCT DATE(datetime) as d FROM scrapdata_options ORDER BY d ASC")
trading_days = [str(r['d']) for r in cursor.fetchall()]
trading_days_sorted = sorted(list(set(trading_days)))

def get_next_trading_days(base_date_str, count=3):
    future_days = [d for d in trading_days_sorted if d > base_date_str]
    return future_days[:count]

def get_strike_step(price):
    if price > 2500: return 50
    if price > 1000: return 20
    if price > 500:  return 10
    if price > 100:  return 5
    if price > 50:   return 2.5
    return 1

def generate_strikes(buy_price):
    step = get_strike_step(buy_price)
    atm = round(buy_price / step) * step
    strikes = [atm + step*i for i in range(2, -7, -1)]
    return strikes[2], strikes[4] # +1 ITM, -2 OTM

df_list = []
for y in [2024, 2025, 2026]:
    try:
        df_list.append(pd.read_csv(f'experiment_targets_{y}.csv'))
    except: pass
targets = pd.concat(df_list)
r1_r3 = targets[(targets['rank_type'].isin(['R1','R3'])) & (targets['buy_price'] != 'UNKNOWN')].copy()

download_tasks = []

for _, row in r1_r3.iterrows():
    stock = row['stock']
    buy_date = row['buy_date']
    buy_price = float(row['buy_price'])
    expiry = row['expiry_date']
    expiry_str = str(expiry).split('T')[0]
    
    sell_strike, buy_strike = generate_strikes(buy_price)
    
    # Get Day 1, Day 2, Day 3
    next_days = get_next_trading_days(buy_date, 3)
    day1_date = next_days[0] if len(next_days) > 0 else None
    day2_date = next_days[1] if len(next_days) > 1 else None
    day3_date = next_days[2] if len(next_days) > 2 else None
    
    # Anti-expiry check for Day 3!
    # If Day 3 falls past expiry or Day 1/2 is expiry day -> Cannot hold Day 3!
    can_hold_d3 = True
    if expiry_str and expiry_str != 'None':
        if day3_date and day3_date > expiry_str:
            can_hold_d3 = False
        if day1_date and day1_date >= expiry_str:
            can_hold_d3 = False
        if day2_date and day2_date >= expiry_str:
            can_hold_d3 = False
            
    # Add Day 3 Exit Task (09:20 - 09:35) if safe
    if day3_date and can_hold_d3:
        download_tasks.append({
            'stock': stock,
            'date': day3_date,
            'time_window': '09:20 - 09:35',
            'sell_strike': sell_strike,
            'buy_strike': buy_strike,
            'expiry_date': expiry,
            'role': 'Day 3 Hold Exit (09:25)'
        })

df_tasks = pd.DataFrame(download_tasks)
df_tasks = df_tasks.drop_duplicates(subset=['stock', 'date', 'sell_strike', 'buy_strike'])
df_tasks.to_csv('day3_hold_download_tasks.csv', index=False)

print(f"Total Unique Day 3 Download Targets Created: {len(df_tasks)}")
print(df_tasks.head(10).to_string())

cursor.close()
db.close()
