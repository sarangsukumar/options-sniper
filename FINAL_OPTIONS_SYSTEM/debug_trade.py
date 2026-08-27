import mysql.connector
db = mysql.connector.connect(host='localhost', user='root', password='root', database='markets')
cursor = db.cursor(dictionary=True)
stock = 'MARICO'
buy_date = '2026-01-05'
cursor.execute("SELECT MIN(DATE(datetime)) as ed FROM scrapdata_options WHERE stock_code=%s AND DATE(datetime)>%s", (stock, buy_date))
sell_date = str(cursor.fetchone()['ed'])
print(f"Sell Date: {sell_date}")

cursor.execute("SELECT DISTINCT strike_price FROM scrapdata_options WHERE stock_code=%s AND DATE(datetime)=%s ORDER BY strike_price DESC", (stock, buy_date))
strikes = [float(r['strike_price']) for r in cursor.fetchall()]
print(f"Strikes: {strikes}")
buy_strike, sell_strike = strikes[4], strikes[1]

cursor.execute("SELECT TIME(datetime) as t, strike_price, close FROM scrapdata_options WHERE stock_code=%s AND DATE(datetime)=%s AND (TIME(datetime) BETWEEN '15:26:00' AND '15:27:00' OR TIME(datetime) BETWEEN '09:56:00' AND '09:57:00') ORDER BY datetime ASC", (stock, buy_date))
egroups = {}
for r in cursor.fetchall():
    t = str(r['t'])
    sp = float(r['strike_price'])
    if t not in egroups: egroups[t] = {}
    egroups[t][sp] = float(r['close'])
print(f"Entry Groups: {egroups}")

cursor.execute("SELECT TIME(datetime) as t, strike_price, open, close FROM scrapdata_options WHERE stock_code=%s AND DATE(datetime)=%s AND (TIME(datetime) BETWEEN '09:29:00' AND '09:30:00' OR TIME(datetime) BETWEEN '03:59:00' AND '04:00:00') ORDER BY datetime ASC", (stock, sell_date))
xgroups = {}
for r in cursor.fetchall():
    t = str(r['t'])
    sp = float(r['strike_price'])
    px = float(r['open']) if r['open'] and r['open']>0 else float(r['close'])
    if t not in xgroups: xgroups[t] = {}
    xgroups[t][sp] = px
print(f"Exit Groups: {xgroups}")
