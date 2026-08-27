import mysql.connector, pandas as pd
db = mysql.connector.connect(host='localhost', user='root', password='root', database='markets')
cursor = db.cursor(dictionary=True)
df = pd.read_csv('options_download_targets_2024_verified.csv')
fails = {'no_sell': 0, 'no_strikes': 0, 'no_entry': 0, 'no_exit': 0, 'success': 0}
for _, row in df.iterrows():
    stock, buy_date = row['stock'], row['buy_date']
    cursor.execute("SELECT MIN(DATE(datetime)) as ed FROM scrapdata_options WHERE stock_code=%s AND DATE(datetime)>%s", (stock, buy_date))
    res = cursor.fetchone()
    if not res or not res['ed']:
        fails['no_sell'] += 1
        continue
    sell_date = str(res['ed'])
    cursor.execute("SELECT DISTINCT strike_price FROM scrapdata_options WHERE stock_code=%s AND DATE(datetime)=%s ORDER BY strike_price DESC", (stock, buy_date))
    strikes = [float(r['strike_price']) for r in cursor.fetchall()]
    if len(strikes) <= 4:
        fails['no_strikes'] += 1
        continue
    sell_strike = strikes[1]; buy_strike = strikes[4]
    cursor.execute("SELECT TIME(datetime) as t, strike_price, close FROM scrapdata_options WHERE stock_code=%s AND DATE(datetime)=%s AND TIME(datetime) BETWEEN '15:26:00' AND '15:27:00' ORDER BY datetime ASC", (stock, buy_date))
    erows = cursor.fetchall()
    egroups = {}
    for r in erows:
        t = str(r['t'])
        sp = float(r['strike_price'])
        if t not in egroups: egroups[t] = {}
        egroups[t][sp] = float(r['close'])
    entry_buy = egroups.get('15:26:00', {}).get(buy_strike)
    entry_sell = egroups.get('15:27:00', {}).get(sell_strike)
    if None in (entry_buy, entry_sell):
        fails['no_entry'] += 1
        continue
    
    cursor.execute("SELECT TIME(datetime) as t, strike_price, open, close FROM scrapdata_options WHERE stock_code=%s AND DATE(datetime)=%s AND TIME(datetime) BETWEEN '09:29:00' AND '09:30:00' ORDER BY datetime ASC", (stock, sell_date))
    xrows = cursor.fetchall()
    xgroups = {}
    for r in xrows:
        t = str(r['t'])
        sp = float(r['strike_price'])
        px = float(r['open']) if r['open'] and r['open']>0 else float(r['close'])
        if t not in xgroups: xgroups[t] = {}
        xgroups[t][sp] = px
    exit_sell = xgroups.get('09:29:00', {}).get(sell_strike)
    exit_buy = xgroups.get('09:30:00', {}).get(buy_strike)
    if None in (exit_sell, exit_buy):
        fails['no_exit'] += 1
        continue
    
    fails['success'] += 1
print(fails)
