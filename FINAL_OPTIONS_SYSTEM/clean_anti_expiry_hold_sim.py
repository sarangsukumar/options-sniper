import mysql.connector
import pandas as pd
import numpy as np
from backtest_experiment import get_lot_size

db = mysql.connector.connect(host='localhost', user='root', password='root', database='markets')
cursor = db.cursor(dictionary=True)

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
    return strikes[2], strikes[4]

def get_price(cursor, stock, date, strike, mode):
    if mode == 'entry':
        times = ["15:26:00","15:25:00","15:27:00","15:24:00","15:28:00",
                 "09:56:00","09:55:00","09:57:00","09:54:00","09:58:00"]
        col = 'close'
    else:
        times = ["09:29:00","09:28:00","09:30:00","09:27:00","09:31:00",
                 "03:59:00","03:58:00","04:00:00","03:57:00","04:01:00"]
        col = 'open'
    for t in times:
        cursor.execute(
            f"SELECT {col} as px FROM scrapdata_options "
            f"WHERE stock_code=%s AND DATE(datetime)=%s AND TIME(datetime)=%s "
            f"AND strike_price=%s AND `right`='Put' LIMIT 1",
            (stock, date, t, strike)
        )
        r = cursor.fetchone()
        if r and r['px'] and float(r['px']) > 0:
            return float(r['px'])
    return None

def get_trading_days(cursor, stock, start_date):
    cursor.execute(
        "SELECT DISTINCT DATE(datetime) as d FROM scrapdata_options "
        "WHERE stock_code=%s AND DATE(datetime) > %s ORDER BY d ASC LIMIT 5",
        (stock, start_date)
    )
    rows = cursor.fetchall()
    return [str(r['d']) for r in rows]

df_list = []
for y in [2024, 2025, 2026]:
    try:
        df = pd.read_csv(f'experiment_targets_{y}.csv')
        df['target_year'] = y
        df_list.append(df)
    except: pass
targets = pd.concat(df_list)
r1_r3 = targets[(targets['rank_type'].isin(['R1','R3'])) & (targets['buy_price'] != 'UNKNOWN')].copy()

clean_trades = []

for _, row in r1_r3.iterrows():
    stock = row['stock']
    buy_date = row['buy_date']
    price = float(row['buy_price'])
    y = row['target_year']
    expiry_str = str(row['expiry_date']).split('T')[0]
    
    future_dates = get_trading_days(cursor, stock, buy_date)
    if len(future_dates) < 2: continue
    
    day1_exit = future_dates[0]
    day2_exit = future_dates[1]
    
    # Check if holding to Day 2 crosses contract expiry!
    # If Day 2 > Expiry OR Day 1 >= Expiry -> CANNOT HOLD TO DAY 2! (Must force Day 1 exit)
    can_hold_to_day2 = True
    if expiry_str and expiry_str != 'None':
        if day2_exit > expiry_str or day1_exit >= expiry_str:
            can_hold_to_day2 = False
            
    sell_strike, buy_strike = generate_strikes(price)
    lot_size = get_lot_size(stock, buy_date)
    margin = (sell_strike - buy_strike) * lot_size
    lots = min(int(400000 // margin), 20) if margin > 0 else 0
    if lots == 0: continue
    
    se = get_price(cursor, stock, buy_date, sell_strike, 'entry')
    be = get_price(cursor, stock, buy_date, buy_strike, 'entry')
    sx1 = get_price(cursor, stock, day1_exit, sell_strike, 'exit')
    bx1 = get_price(cursor, stock, day1_exit, buy_strike, 'exit')
    
    if None in [se, be, sx1, bx1]: continue
    
    credit = se - be
    debit1 = sx1 - bx1
    comm = 300 * lots * 2
    pnl1 = ((credit - debit1) * lot_size * lots) - comm
    
    if can_hold_to_day2:
        sx2 = get_price(cursor, stock, day2_exit, sell_strike, 'exit')
        bx2 = get_price(cursor, stock, day2_exit, buy_strike, 'exit')
        if None in [sx2, bx2]:
            pnl2 = pnl1
        else:
            debit2 = sx2 - bx2
            pnl2 = ((credit - debit2) * lot_size * lots) - comm
    else:
        # Strict Expiry Rule: Force exit on Day 1! No Day 2 hold allowed.
        pnl2 = pnl1
        
    clean_trades.append({
        'year': y, 'stock': stock, 'buy_date': buy_date,
        'pnl1': pnl1, 'pnl2': pnl2,
        'can_hold_d2': can_hold_to_day2,
        'is_loss': pnl1 < 0
    })

df_clean = pd.DataFrame(clean_trades)
print(f"Total Valid Clean Trades: {len(df_clean)}")
print(f"Trades Barred from Day 2 Hold due to Expiry Proximity: {len(df_clean[df_clean['can_hold_d2']==False])}")

# Let's re-run the threshold optimization strictly under the Anti-Expiry Rule!
thresholds = [0, -5000, -15000, -30000, -50000, -75000]
results = []
baseline_pnl = df_clean['pnl1'].sum()

for th in thresholds:
    # Rule: Hold ONLY if pnl1 <= th AND can_hold_d2 == True
    effective_pnl = np.where((df_clean['pnl1'] <= th) & (df_clean['can_hold_d2'] == True), df_clean['pnl2'], df_clean['pnl1'])
    total_pnl = effective_pnl.sum()
    gain = total_pnl - baseline_pnl
    
    held = df_clean[(df_clean['pnl1'] <= th) & (df_clean['can_hold_d2'] == True)]
    held_cnt = len(held)
    improved_cnt = sum(held['pnl2'] > held['pnl1'])
    imp_rate = (improved_cnt / held_cnt * 100) if held_cnt > 0 else 0
    
    results.append({
        'Threshold (₹)': f"Loss worse than ₹{abs(th):,}" if th < 0 else "Hold ALL Safe Losses",
        'Trades Held': held_cnt,
        'Improved PnL': f"{improved_cnt} ({imp_rate:.1f}%)",
        'Total Portfolio PnL (₹)': total_pnl,
        'Net Extra Gain vs Baseline (₹)': gain
    })

print("\n" + "="*105)
print("=== CLEAN PRODUCTION RESULTS: DAY 2 HOLD WITH STRICT ANTI-EXPIRY RULE ===")
print("="*105)
print(pd.DataFrame(results).to_string(index=False))
print("="*105)
