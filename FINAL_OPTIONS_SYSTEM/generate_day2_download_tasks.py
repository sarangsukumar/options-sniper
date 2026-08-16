import mysql.connector
import pandas as pd
import datetime

# Connect to DB to get the true list of NSE trading days
db = mysql.connector.connect(host='localhost', user='root', password='root', database='markets')
cursor = db.cursor(dictionary=True)

# Fetch all unique trading dates from existing database to accurately know NSE trading calendar
cursor.execute("SELECT DISTINCT DATE(datetime) as d FROM scrapdata_options ORDER BY d ASC")
trading_days = [str(r['d']) for r in cursor.fetchall()]

# Build a fast lookup / ordered list of trading days
trading_days_set = set(trading_days)
trading_days_sorted = sorted(list(trading_days_set))

def get_next_trading_days(base_date_str, count=2):
    # Find base_date in list
    future_days = [d for d in trading_days_sorted if d > base_date_str]
    return future_days[:count]

# Helper for strike generation
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
    sell_strike = strikes[2] # +1 ITM
    buy_strike = strikes[4]  # -2 OTM
    return sell_strike, buy_strike

# Load R1 and R3 targets across 2024, 2025, 2026
df_list = []
for y in [2024, 2025, 2026]:
    try:
        df_list.append(pd.read_csv(f'experiment_targets_{y}.csv'))
    except:
        pass
targets = pd.concat(df_list)
r1_r3 = targets[(targets['rank_type'].isin(['R1','R3'])) & (targets['buy_price'] != 'UNKNOWN')].copy()

# Generate the complete list of download tasks
download_tasks = []

for _, row in r1_r3.iterrows():
    stock = row['stock']
    buy_date = row['buy_date']
    buy_price = float(row['buy_price'])
    expiry = row['expiry_date']
    
    # Calculate exact strikes for our best strategy (+1 ITM / -2 OTM)
    sell_strike, buy_strike = generate_strikes(buy_price)
    
    # Get Day 1 (Next Trading Day) and Day 2 (Second Next Trading Day)
    next_days = get_next_trading_days(buy_date, 2)
    day1_date = next_days[0] if len(next_days) > 0 else None
    day2_date = next_days[1] if len(next_days) > 1 else None
    
    # Task 1: Day 0 Entry (15:20 - 15:30)
    download_tasks.append({
        'stock': stock,
        'date': buy_date,
        'time_window': '15:20 - 15:30',
        'sell_strike': sell_strike,
        'buy_strike': buy_strike,
        'expiry_date': expiry,
        'role': 'Day 0 Entry (15:26)'
    })
    
    # Task 2: Day 1 Exit (09:20 - 09:35)
    if day1_date:
        download_tasks.append({
            'stock': stock,
            'date': day1_date,
            'time_window': '09:20 - 09:35',
            'sell_strike': sell_strike,
            'buy_strike': buy_strike,
            'expiry_date': expiry,
            'role': 'Day 1 Exit (09:25)'
        })
        
    # Task 3: Day 2 Exit (09:20 - 09:35) -> THE NEW DAY 2 HOLDING DATA
    if day2_date:
        download_tasks.append({
            'stock': stock,
            'date': day2_date,
            'time_window': '09:20 - 09:35',
            'sell_strike': sell_strike,
            'buy_strike': buy_strike,
            'expiry_date': expiry,
            'role': 'Day 2 Hold Exit (09:25)'
        })

df_tasks = pd.DataFrame(download_tasks)
# Drop duplicates if same stock, date, and strikes
df_tasks = df_tasks.drop_duplicates(subset=['stock', 'date', 'sell_strike', 'buy_strike'])

# Save to CSV for the downloader
df_tasks.to_csv('day2_hold_download_tasks.csv', index=False)

print(f"Total Unique Download Targets Created: {len(df_tasks)}")
print("\nSample of Tasks to Download:")
print(df_tasks.head(15).to_string())

cursor.close()
db.close()
