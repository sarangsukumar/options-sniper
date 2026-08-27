import pandas as pd
import mysql.connector

db = mysql.connector.connect(host='localhost', user='root', password='root', database='markets')
cursor = db.cursor(dictionary=True)

df_list = []
for y in [2024,2025,2026]:
    try:
        df_list.append(pd.read_csv(f'experiment_targets_{y}.csv'))
    except: pass
targets = pd.concat(df_list)
r1_r3 = targets[(targets['rank_type'].isin(['R1','R3'])) & (targets['buy_price'] != 'UNKNOWN')]

stats = {'total': len(r1_r3), 'missing_sell_date': 0, 'missing_entry': 0, 'missing_exit': 0, 'margin_cap': 0, 'success': 0}

from backtest_experiment import get_lot_size, generate_multi_strikes

for _, row in r1_r3.iterrows():
    stock, buy_date, buy_price = row['stock'], row['buy_date'], float(row['buy_price'])
    
    # Fast index query for sell_date
    cursor.execute("SELECT MIN(DATE(datetime)) as ed FROM scrapdata_options WHERE stock_code=%s AND datetime > %s LIMIT 1", (stock, f"{buy_date} 23:59:59"))
    res = cursor.fetchone()
    if not res or not res['ed']:
        stats['missing_sell_date'] += 1
        continue
    sell_date = str(res['ed'])
    
    strikes = generate_multi_strikes(buy_price)
    sell_strike = strikes[1]
    buy_strike = strikes[4]
    
    lot_size = get_lot_size(stock, buy_date)
    margin = (sell_strike - buy_strike) * lot_size
    if margin <= 0 or margin > 400000 or (400000 // margin) == 0:
        stats['margin_cap'] += 1
        continue
        
    # Check entry - Fast index query
    cursor.execute(f"SELECT TIME(datetime) as t, strike_price, close FROM scrapdata_options WHERE stock_code=%s AND (datetime BETWEEN '{buy_date} 15:20:00' AND '{buy_date} 15:32:00' OR datetime BETWEEN '{buy_date} 09:50:00' AND '{buy_date} 10:02:00')", (stock,))
    egroups = {}
    for r in cursor.fetchall():
        t = str(r['t'])
        if len(t) == 7: t = "0" + t
        sp = float(r['strike_price'])
        if t not in egroups: egroups[t] = {}
        egroups[t][sp] = float(r['close'])
        
    entry_mins = [('15:26:00', '09:56:00'), ('15:25:00', '09:55:00'), ('15:27:00', '09:57:00'), ('15:24:00', '09:54:00'), ('15:28:00', '09:58:00')]
    entry_ok = False
    for ist_t, utc_t in entry_mins:
        grp = egroups.get(ist_t, egroups.get(utc_t, {}))
        if buy_strike in grp and sell_strike in grp:
            entry_ok = True; break
    if not entry_ok:
        stats['missing_entry'] += 1
        continue
        
    # Check exit - Fast index query
    cursor.execute(f"SELECT TIME(datetime) as t, strike_price, open, close FROM scrapdata_options WHERE stock_code=%s AND (datetime BETWEEN '{sell_date} 09:25:00' AND '{sell_date} 09:35:00' OR datetime BETWEEN '{sell_date} 03:55:00' AND '{sell_date} 04:05:00')", (stock,))
    xgroups = {}
    for r in cursor.fetchall():
        t = str(r['t'])
        if len(t) == 7: t = "0" + t
        sp = float(r['strike_price'])
        px = float(r['open']) if r['open'] and r['open']>0 else float(r['close'])
        if t not in xgroups: xgroups[t] = {}
        xgroups[t][sp] = px
        
    exit_mins = [('09:29:00', '03:59:00'), ('09:28:00', '03:58:00'), ('09:30:00', '04:00:00'), ('09:27:00', '03:57:00'), ('09:31:00', '04:01:00')]
    exit_ok = False
    for ist_t, utc_t in exit_mins:
        grp = xgroups.get(ist_t, xgroups.get(utc_t, {}))
        if buy_strike in grp and sell_strike in grp:
            exit_ok = True; break
    if not exit_ok:
        stats['missing_exit'] += 1
        continue
        
    stats['success'] += 1

print(stats)
