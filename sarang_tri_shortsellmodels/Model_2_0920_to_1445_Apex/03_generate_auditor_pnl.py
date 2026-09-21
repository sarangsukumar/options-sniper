import pandas as pd, pymysql
db = pymysql.connect(host='localhost', user='root', password='root', database='markets', cursorclass=pymysql.cursors.DictCursor)
cur = db.cursor()
out = []
for _, r in pd.read_csv('model2_raw_trades.csv').iterrows():
    d, s = r['date'], r['stock']
    cur.execute(f"SELECT time, price FROM scrapdata WHERE date='{d}' AND stockname='{s}' AND time >= '{d} 09:22:00' AND time <= '{d} 09:24:59' ORDER BY time ASC LIMIT 1")
    en = cur.fetchone()
    cur.execute(f"SELECT time, price FROM scrapdata WHERE date='{d}' AND stockname='{s}' AND time >= '{d} 14:45:00' AND time <= '{d} 14:47:59' ORDER BY time ASC LIMIT 1")
    ex = cur.fetchone()
    if en and ex:
        qty = int(1000000.0 / en['price'])
        to = (qty * en['price']) + (qty * ex['price'])
        comm = 40.0 + round(qty * ex['price'] * 0.00025) + (to * 0.0000322) + (to * 0.000001) + round(qty * en['price'] * 0.00003)
        comm += (40.0 + (to * 0.0000322) + (to * 0.000001)) * 0.18
        out.append({'date': d, 'stockname': s, 'entry_time': en['time'], 'entry_price': en['price'], 'exit_time': ex['time'], 'exit_price': ex['price'], 'commission': round(comm,2), 'qty': qty, 'upfront_margin_req': round((qty*en['price'])/5.0,2), 'net_pnl': round(((en['price']-ex['price'])*qty)-comm,2)})
res = pd.DataFrame(out)
res.to_csv('auditor_pnl_sheet.csv', index=False)
res['year'] = pd.to_datetime(res['date']).dt.year
for y in sorted(res['year'].unique()): print(f"Year {y}: PnL Rs {res[res['year']==y]['net_pnl'].sum():,.2f}")
print(f"TOTAL PNL: Rs {res['net_pnl'].sum():,.2f}")
