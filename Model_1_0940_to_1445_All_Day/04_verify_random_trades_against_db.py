import pandas as pd
import pymysql

df = pd.read_csv('03_final_pnl_verification_ledger.csv')
sample = df.sample(5, random_state=42)

def get_kotak_neo_charges(qty, sell_price, buy_price):
    turnover = (qty * sell_price) + (qty * buy_price)
    brokerage = 40.0
    stt = round(qty * sell_price * 0.00025)
    txn = turnover * 0.0000322
    sebi = turnover * 0.000001
    stamp = round(qty * buy_price * 0.00003)
    gst = (brokerage + txn + sebi) * 0.18
    return round(brokerage + stt + txn + sebi + stamp + gst, 2)

db = pymysql.connect(host='localhost', user='root', password='root', database='markets', cursorclass=pymysql.cursors.DictCursor)
cur = db.cursor()

for _, row in sample.iterrows():
    d = row['date']
    s = row['stock']
    print(f"\n--- VERIFYING {s} on {d} ---")
    print(f"CSV SAYS: Sell at {row['sp']}, Buy at {row['bp']}, Qty: {row['qty']}, Net PnL: Rs {row['net_pnl']:,.2f}")
    
    cur.execute(f"SELECT price FROM scrapdata WHERE date='{d}' AND stockname='{s}' AND time >= '{d} 09:42:00' LIMIT 1")
    sp_db = cur.fetchone()['price']
    
    cur.execute(f"SELECT price FROM scrapdata WHERE date='{d}' AND stockname='{s}' AND time >= '{d} 14:45:00' LIMIT 1")
    bp_db = cur.fetchone()['price']
    
    qty_check = int(1000000.0 / sp_db)
    net_check = ((sp_db - bp_db) * qty_check) - get_kotak_neo_charges(qty_check, sp_db, bp_db)
    print(f"MYSQL PHYSICAL: 09:42 tick = {sp_db}, 14:45 tick = {bp_db}, Qty: {qty_check}, Net PnL: Rs {net_check:,.2f}")

db.close()
