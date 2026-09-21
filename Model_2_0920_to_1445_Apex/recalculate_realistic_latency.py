import pandas as pd
import pymysql
import time

print("Recalculating 12.7 Crore PnL using Realistic 09:22 Latency Buffer...")
df = pd.read_csv('/home/ubuntu/03_final_pnl_verification_0920.csv')

db = pymysql.connect(host='localhost', user='root', password='root', database='markets', cursorclass=pymysql.cursors.DictCursor)
cur = db.cursor()

def get_kotak_neo_charges(qty, sell_price, buy_price):
    turnover = (qty * sell_price) + (qty * buy_price)
    brokerage = 40.0
    stt = round(qty * sell_price * 0.00025)
    txn = turnover * 0.0000322
    sebi = turnover * 0.000001
    stamp = round(qty * buy_price * 0.00003)
    gst = (brokerage + txn + sebi) * 0.18
    return round(brokerage + stt + txn + sebi + stamp + gst, 2)

new_trades = []
start = time.time()

for i, row in df.iterrows():
    d = row['date']
    s = row['stock']
    
    # NEW ENTRY: 09:22 to 09:23
    cur.execute(f"SELECT price FROM scrapdata WHERE date='{d}' AND stockname='{s}' AND time >= '{d} 09:22:00' AND time <= '{d} 09:23:59' LIMIT 1")
    entry_res = cur.fetchone()
    
    # NEW EXIT: 14:45 to 14:47
    cur.execute(f"SELECT price FROM scrapdata WHERE date='{d}' AND stockname='{s}' AND time >= '{d} 14:45:00' AND time <= '{d} 14:47:59' LIMIT 1")
    exit_res = cur.fetchone()
    
    if entry_res and exit_res:
        sp = entry_res['price']
        bp = exit_res['price']
        qty = int(1000000.0 / sp)
        gross = (sp - bp) * qty
        net = gross - get_kotak_neo_charges(qty, sp, bp)
        
        new_trades.append({
            'year': row['year'],
            'date': d,
            'stock': s,
            'net_pnl': net
        })
        
    if i % 1000 == 0:
        print(f"Processed {i}/{len(df)} trades...")

res_df = pd.DataFrame(new_trades)
print(f"\nCompleted in {time.time() - start:.2f} seconds.\n")

print("========================================================")
print("09:22 REALISTIC EXECUTION (2-MINUTE BUFFER)")
print("========================================================")
for yr in sorted(res_df['year'].unique()):
    yr_df = res_df[res_df['year'] == yr]
    print(f"Year {yr}: Trades: {len(yr_df)} | Net PnL: Rs {yr_df['net_pnl'].sum():,.2f}")
print("--------------------------------------------------------")
print(f"TOTAL OOS TRADES: {len(res_df)}")
print(f"TOTAL OOS NET PNL: Rs {res_df['net_pnl'].sum():,.2f}")
print(f"TOTAL OOS WIN Rate: {(res_df['net_pnl']>0).mean()*100:.2f}%")
print("========================================================")
