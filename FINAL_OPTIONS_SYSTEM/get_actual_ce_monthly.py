import mysql.connector
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import sys

# Import the existing lot size function
sys.path.append('/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/FINAL_OPTIONS_SYSTEM')
from backtest_experiment import get_lot_size

print("Loading futures predictions...")
fut_file = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/historical_models/output/trades_dynamic_threshold.csv'
fut_df = pd.read_csv(fut_file)
fut_df['date_str'] = pd.to_datetime(fut_df['date']).dt.strftime('%Y-%m-%d')
fut_df['rank'] = fut_df.groupby('date').cumcount() + 1
fut_df['year'] = pd.to_datetime(fut_df['date']).dt.year
fut_df['month'] = pd.to_datetime(fut_df['date']).dt.strftime('%Y-%m')

r1_r3 = fut_df[(fut_df['year'] >= 2024) & (fut_df['rank'].isin([1, 3]))].copy()
stocks = r1_r3['stock'].unique().tolist()
dates = r1_r3['date_str'].unique().tolist()

print("Connecting to DB...")
db = mysql.connector.connect(host='localhost', user='root', password='root', database='markets')
c = db.cursor(dictionary=True)

# We need the next trading day for each date to check exits
c.execute("SELECT DISTINCT DATE(datetime) as dt FROM scrapdata_options")
all_db_dates = sorted([str(r['dt']) for r in c.fetchall()])

valid_trades = []
req_dates = set()
for _, r in r1_r3.iterrows():
    s, d, m = r['stock'], r['date_str'], r['month']
    days = [x for x in all_db_dates if x > d]
    if not days: continue
    d1 = days[0]
    valid_trades.append({'stock': s, 'date': d, 'exit_date': d1, 'month': m})
    req_dates.add(d)
    req_dates.add(d1)

stocks_str = "', '".join(stocks)
dates_str = "', '".join(req_dates)

print(f"Fetching options data for {len(req_dates)} dates...")
query = f"""
SELECT stock_code, DATE(datetime) as dt, TIME(datetime) as tm, strike_price, `close`, `open` 
FROM scrapdata_options 
WHERE `right`='Call' 
AND stock_code IN ('{stocks_str}') 
AND DATE(datetime) IN ('{dates_str}') 
AND ( (TIME(datetime) BETWEEN '15:15:00' AND '15:37:00') OR (TIME(datetime) BETWEEN '09:14:00' AND '09:36:00') )
"""
c.execute(query)
rows = c.fetchall()
c.close()
db.close()

tmap = {}
strike_dict = {}
for r in rows:
    stk, d, sp = r['stock_code'], str(r['dt']), float(r['strike_price'])
    t_str = str(r['tm'])
    if len(t_str) == 7: t_str = "0" + t_str
    px = float(r['close']) if r['close'] else float(r['open']) if r['open'] else 0
    if px > 0:
        tmap[(stk, d, t_str, sp)] = px
        if (stk, d) not in strike_dict: strike_dict[(stk, d)] = set()
        strike_dict[(stk, d)].add(sp)

def get_strike_step(price):
    if price > 2500: return 50
    if price > 1000: return 20
    if price > 500: return 10
    if price > 100: return 5
    if price > 50: return 2.5
    return 1

print("Calculating PnL...")
trade_records = []
for tr in valid_trades:
    stk = tr['stock']
    d = tr['date']
    d1 = tr['exit_date']
    
    if (stk, d) not in strike_dict: continue
    sample_strikes = list(strike_dict[(stk, d)])
    if not sample_strikes: continue
    price = float(np.median(sample_strikes))
    
    step = get_strike_step(price)
    atm = round(price / step) * step
    b_str, s_str = atm - step, atm + step
    
    def lookup(date, strike, target_time_str):
        target_dt = datetime.strptime(f"{date} {target_time_str}", "%Y-%m-%d %H:%M:%S")
        for delta in range(0, 11):
            for sign in [1, -1]:
                if delta == 0 and sign == -1: continue
                curr = target_dt + timedelta(minutes=delta*sign)
                t_str = curr.strftime("%H:%M:%S")
                if (stk, date, t_str, float(strike)) in tmap:
                    return tmap[(stk, date, t_str, float(strike))]
        return None

    be = lookup(d, b_str, "15:26:00")
    se = lookup(d, s_str, "15:26:00")
    bx = lookup(d1, b_str, "09:25:00")
    sx = lookup(d1, s_str, "09:25:00")
    
    if None in [be, se, bx, sx]: continue
    
    dp = be - se
    if dp <= 0: continue
    
    lot_size = get_lot_size(stk, d)
    margin = dp * lot_size
    if margin <= 0: continue
    
    lots = min(int(400000 // margin), 20)
    if lots == 0: continue
    
    cr = bx - sx
    pnl = ((cr - dp) * lot_size * lots) - (400 * lots)
    trade_records.append({'month': tr['month'], 'pnl': pnl})

df = pd.DataFrame(trade_records)
if not df.empty:
    monthly = df.groupby('month')['pnl'].sum().reset_index()
    print("\n--- ACTUAL MONTHLY BULL CALL PNL (2024 - 2026) ---")
    print(monthly.to_string(index=False))
    
    tot = len(monthly)
    wins = len(monthly[monthly['pnl'] > 0])
    print("\n====================")
    print(f"Total Months: {tot}")
    print(f"Winning Months: {wins}")
    print(f"Win Rate: {(wins/tot)*100:.1f}%")
    print(f"Total PnL: ₹{monthly['pnl'].sum():,.2f}")
    print("====================")
else:
    print("No valid trades recovered.")
