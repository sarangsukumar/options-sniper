import os
import pymysql
import pandas as pd
from concurrent.futures import ThreadPoolExecutor

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
    d = row['date_str']
    s = row['clean_stock']
    
    conn = pymysql.connect(host='localhost', user='root', password='root', database='markets', cursorclass=pymysql.cursors.DictCursor)
    with conn.cursor() as cur:
        # Pull ticks from 09:42 to 14:50 (giving 5 mins buffer for the 14:45 exit)
        cur.execute(f"SELECT time, price, high FROM scrapdata WHERE date='{d}' AND stockname = '{s}' AND time>='{d} 09:42:00' AND time<='{d} 14:50:00' ORDER BY time ASC")
        ticks = cur.fetchall()
    conn.close()
    
    if not ticks: return None
    
    # 1. ENFORCE ENTRY LIQUIDITY (Must enter between 09:42 and 09:45)
    sell_price = float(ticks[0]['price'] or 0)
    sell_time = str(ticks[0]['time'])
    if sell_price <= 0: return None
    if sell_time > f"{d} 09:45:59": return None
    
    qty = int(1000000.0 / sell_price)
    sl_price = round(sell_price * 1.03, 2)
    
    # 2. ENFORCE EXIT LIQUIDITY
    buy_price = None
    buy_time = None
    for t in ticks:
        t_time = str(t['time'])
        h = float(t['high'] or t['price'] or 0)
        
        # Stop loss hit
        if h >= sl_price:
            buy_price = sl_price
            buy_time = t_time
            break
            
        # Time exit hit
        if t_time >= f"{d} 14:45:00":
            buy_price = float(t['price'] or 0)
            buy_time = t_time
            break
            
    if not buy_price:
        buy_price = float(ticks[-1]['price'] or 0)
        buy_time = str(ticks[-1]['time'])
        
    # Check if the exit took too long (No liquidity before 14:48)
    if buy_time > f"{d} 14:48:59":
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
pred_file = sys.argv[1] if len(sys.argv) > 1 else '0942_predictions.csv'
preds = pd.read_csv(os.path.join(BASE_DIR, pred_file))

print(f"2. Auditing {len(preds)} Trades against MySQL Ticks (Max 3-Min Liquidity Windows)...")
results = []
with ThreadPoolExecutor(max_workers=5) as ex:
    for res in ex.map(audit_trade, [row for _, row in preds.iterrows()]):
        if res: results.append(res)

df_res = pd.DataFrame(results)
out_file = os.path.join(BASE_DIR, '0942_verified_pnl_sheet.csv')
df_res.to_csv(out_file, index=False)

df_res['year'] = pd.to_datetime(df_res['Date']).dt.year
stats = df_res.groupby('year').agg(
    total_trades=('Net_PnL', 'count'),
    wins=('Net_PnL', lambda x: (x > 0).sum()),
    net_pnl=('Net_PnL', 'sum')
)
stats['win_rate'] = (stats['wins'] / stats['total_trades']) * 100
stats['net_pnl_lakhs'] = stats['net_pnl'] / 100000.0

print("\n--- 09:42 Hybrid Model Final Stats ---")
for year, row in stats.iterrows():
    print(f"{year}: Rs {row['net_pnl_lakhs']:.2f} Lakhs | {row['win_rate']:.2f}% Win Rate ({int(row['wins'])}/{int(row['total_trades'])})")
print(f"TOTAL: Rs {df_res['Net_PnL'].sum() / 1e7:.2f} Crores | Overall Win Rate: {(df_res['Net_PnL'] > 0).sum() / len(df_res) * 100:.2f}%")
