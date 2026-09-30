import os
import pymysql
import pandas as pd
from concurrent.futures import ThreadPoolExecutor

"""
====================================================================
TICK-BY-TICK VERIFICATION ENGINE (09:20 SCALP MODEL)
====================================================================
This script verifies the exact PnL by querying tick data and applying:
1. ENTRY: Exactly at the 09:25:00 open price (simulating limit entry).
2. STOP LOSS: Strict 3% tick-by-tick stop loss during the hold.
3. TAKE PROFIT: Evaluates trailing profit (>0.05%) precisely at the minute opens of 09:36, 09:37, 09:38, and 09:39.
4. HARD SQUARE-OFF: Closes position unconditionally at 09:40:00.
====================================================================
"""

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def get_taxes(qty, sell_price, buy_price):
    turnover = (qty * sell_price) + (qty * buy_price)
    stt = round(qty * sell_price * 0.00025)
    txn = turnover * 0.0000322
    sebi = turnover * 0.000001
    stamp = round(qty * buy_price * 0.00003)
    gst = (40.0 + txn + sebi) * 0.18
    return round(40.0 + stt + txn + sebi + stamp + gst, 2)

def audit_trade(row):
    d = row['short_date']
    s = row['clean_stock']
    
    conn = pymysql.connect(host='localhost', user='root', password='root', database='markets', cursorclass=pymysql.cursors.DictCursor)
    with conn.cursor() as cur:
        # Pull ticks from 09:25 to 09:45 (giving 5 mins buffer for the 09:40 exit)
        cur.execute(f"SELECT time, price, high FROM scrapdata WHERE date='{d}' AND stockname = '{s}' AND time>='{d} 09:25:00' AND time<='{d} 09:45:00' ORDER BY time ASC")
        ticks = cur.fetchall()
    conn.close()
    
    if not ticks: return None
    
    # 1. ENFORCE ENTRY LIQUIDITY (Must enter between 09:25 and 09:25:59)
    sell_price = float(ticks[0]['price'] or 0)
    sell_time = str(ticks[0]['time'])
    if sell_price <= 0: return None
    if sell_time > f"{d} 09:25:59": return None
    
    qty = int(1000000.0 / sell_price)
    sl_price = round(sell_price * 1.03, 2)
    
    # 2. ENFORCE EXIT LIQUIDITY
    buy_price = None
    buy_time = None
    tp_minutes = [f"{d} 09:36", f"{d} 09:37", f"{d} 09:38", f"{d} 09:39"]
    tp_checked = set()
    
    for t in ticks:
        t_time = str(t['time'])
        h = float(t['high'] or t['price'] or 0)
        p = float(t['price'] or 0)
        
        # Stop loss hit
        if h >= sl_price:
            buy_price = sl_price
            buy_time = t_time
            break
            
        # Trailing profit check at specific minute opens
        minute_prefix = t_time[:16] # e.g., "YYYY-MM-DD 09:36"
        if minute_prefix in tp_minutes and minute_prefix not in tp_checked:
            tp_checked.add(minute_prefix)
            if p < sell_price * 0.9995: # >0.05% profit for short sell
                buy_price = p
                buy_time = t_time
                break
                
        # Time exit hit
        if t_time >= f"{d} 09:40:00":
            buy_price = p
            buy_time = t_time
            break
            
    if not buy_price:
        buy_price = float(ticks[-1]['price'] or 0)
        buy_time = str(ticks[-1]['time'])
        
    # Check if the exit took too long (No liquidity before 09:43)
    if buy_time > f"{d} 09:43:59":
        return None
        
    net_pnl = ((sell_price - buy_price) * qty) - get_taxes(qty, sell_price, buy_price)
    
    return {
        'Date': d,
        'Stock': s,
        'Sell_Time': sell_time,
        'Sell_Price': sell_price,
        'Buy_Time': buy_time,
        'Buy_Price': buy_price,
        'Qty': qty,
        'Margin_Req': 1000000,
        'Commission': get_taxes(qty, sell_price, buy_price),
        'Net_PnL': net_pnl
    }

print("1. Loading Predictions...")
import sys
pred_file = sys.argv[1] if len(sys.argv) > 1 else '0920_predictions.csv'
out_name  = sys.argv[2] if len(sys.argv) > 2 else '0920_verified_pnl_sheet.csv'
preds = pd.read_csv(os.path.join(BASE_DIR, pred_file))

print(f"2. Auditing {len(preds)} Trades against MySQL Ticks (Max 3-Min Liquidity Windows)...")
results = []
with ThreadPoolExecutor(max_workers=5) as ex:
    for res in ex.map(audit_trade, [row for _, row in preds.iterrows()]):
        if res: results.append(res)
        if len(results) % 100 == 0:
            print(f"Audited {len(results)} trades...", flush=True)

df_res = pd.DataFrame(results)
out_file = os.path.join(BASE_DIR, out_name)
df_res.to_csv(out_file, index=False)

df_res['year'] = pd.to_datetime(df_res['Date']).dt.year
stats = df_res.groupby('year').agg(
    total_trades=('Net_PnL', 'count'),
    wins=('Net_PnL', lambda x: (x > 0).sum()),
    net_pnl=('Net_PnL', 'sum')
)
stats['win_rate'] = (stats['wins'] / stats['total_trades']) * 100
stats['net_pnl_lakhs'] = stats['net_pnl'] / 100000.0

print("\n--- 09:20 Scalp Model Final Stats ---")
for year, row in stats.iterrows():
    print(f"{year}: Rs {row['net_pnl_lakhs']:.2f} Lakhs | {row['win_rate']:.2f}% Win Rate ({int(row['wins'])}/{int(row['total_trades'])})")
print(f"TOTAL: Rs {df_res['Net_PnL'].sum() / 1e7:.2f} Crores | Overall Win Rate: {(df_res['Net_PnL'] > 0).sum() / len(df_res) * 100:.2f}%")
