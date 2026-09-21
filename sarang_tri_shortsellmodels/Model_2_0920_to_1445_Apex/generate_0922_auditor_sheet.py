import pandas as pd
import pymysql
import time

print("Generating Auditor Verification Sheet with Strict 09:22-09:24 Timestamps...")
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
    
    # NEW ENTRY: 09:22 to 09:24 (Query exactly the time and price)
    cur.execute(f"SELECT time, price FROM scrapdata WHERE date='{d}' AND stockname='{s}' AND time >= '{d} 09:22:00' AND time <= '{d} 09:24:59' ORDER BY time ASC LIMIT 1")
    entry_res = cur.fetchone()
    
    # NEW EXIT: 14:45 to 14:47
    cur.execute(f"SELECT time, price FROM scrapdata WHERE date='{d}' AND stockname='{s}' AND time >= '{d} 14:45:00' AND time <= '{d} 14:47:59' ORDER BY time ASC LIMIT 1")
    exit_res = cur.fetchone()
    
    if entry_res and exit_res:
        sp = entry_res['price']
        bp = exit_res['price']
        entry_time = entry_res['time']
        exit_time = exit_res['time']
        
        qty = int(1000000.0 / sp)
        margin_req = round((qty * sp) / 5.0, 2)
        comm = get_kotak_neo_charges(qty, sp, bp)
        
        gross = (sp - bp) * qty
        net = gross - comm
        
        new_trades.append({
            'date': d,
            'stockname': s,
            'entry_time': entry_time,
            'entry_price': sp,
            'exit_time': exit_time,
            'exit_price': bp,
            'commission': comm,
            'qty': qty,
            'upfront_margin_req': margin_req,
            'net_pnl': round(net, 2)
        })
        
    if i % 1000 == 0:
        print(f"Processed {i}/{len(df)} trades...")

res_df = pd.DataFrame(new_trades)
res_df.to_csv('/home/ubuntu/All_Stocks_0920_Model/auditor_0922_latency_sheet.csv', index=False)
print(f"Generated auditor_0922_latency_sheet.csv with {len(res_df)} verified trades in {time.time() - start:.2f} seconds.")

db.close()
