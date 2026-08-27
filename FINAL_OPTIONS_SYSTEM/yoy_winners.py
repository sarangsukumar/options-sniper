import mysql.connector
import pandas as pd
from backtest_experiment import get_lot_size, generate_multi_strikes

db = mysql.connector.connect(host='localhost', user='root', password='root', database='markets')
cursor = db.cursor(dictionary=True)

df_list = []
for y in [2024, 2025, 2026]:
    try:
        df = pd.read_csv(f'experiment_targets_{y}.csv')
        df['year'] = y
        df_list.append(df)
    except: pass
targets = pd.concat(df_list)

r1_r3 = targets[(targets['rank_type'].isin(['R1','R3'])) & (targets['buy_price'] != 'UNKNOWN')]
r2_r4 = targets[(targets['rank_type'].isin(['R2','R4'])) & (targets['buy_price'] != 'UNKNOWN')]

winners = [
    ("R1+R3 Wide Spread (+1 ITM / -3 OTM)", r1_r3, 1, 5),
    ("R2+R4 Current System (+1 ITM / -2 OTM)", r2_r4, 1, 4)
]

print("=== YEAR-OVER-YEAR PROFIT (THE TWO WINNERS) ===")

for name, df_group, sell_idx, buy_idx in winners:
    yoy = {2024: 0, 2025: 0, 2026: 0}
    
    for _, row in df_group.iterrows():
        stock, buy_date, buy_price, year = row['stock'], row['buy_date'], float(row['buy_price']), row['year']
        
        cursor.execute("SELECT MIN(DATE(datetime)) as ed FROM scrapdata_options WHERE stock_code=%s AND datetime > %s LIMIT 1", (stock, f"{buy_date} 23:59:59"))
        res = cursor.fetchone()
        if not res or not res['ed']: continue
        sell_date = str(res['ed'])
        
        strikes_list = generate_multi_strikes(buy_price)
        if len(strikes_list) <= max(sell_idx, buy_idx): continue
        
        lot_size = get_lot_size(stock, buy_date)
        sell_strike, buy_strike = strikes_list[sell_idx], strikes_list[buy_idx]
        
        margin = (sell_strike - buy_strike) * lot_size
        if margin <= 0 or margin > 400000 or (400000 // margin) == 0: continue
        lots = int(400000 // margin)
        
        # Pre-fetch entry
        cursor.execute(f"SELECT TIME(datetime) as t, strike_price, close FROM scrapdata_options WHERE stock_code=%s AND (datetime BETWEEN '{buy_date} 15:20:00' AND '{buy_date} 15:32:00' OR datetime BETWEEN '{buy_date} 09:50:00' AND '{buy_date} 10:02:00')", (stock,))
        egroups = {}
        for r in cursor.fetchall():
            t = str(r['t'])
            if len(t) == 7: t = "0" + t
            sp = float(r['strike_price'])
            if t not in egroups: egroups[t] = {}
            egroups[t][sp] = float(r['close'])
            
        entry_mins = [('15:26:00', '09:56:00'), ('15:25:00', '09:55:00'), ('15:27:00', '09:57:00'), ('15:24:00', '09:54:00'), ('15:28:00', '09:58:00')]
        entry_buy = entry_sell = None
        for ist_t, utc_t in entry_mins:
            grp = egroups.get(ist_t, egroups.get(utc_t, {}))
            if buy_strike in grp and sell_strike in grp:
                entry_buy = grp[buy_strike]
                entry_sell = grp[sell_strike]
                break
        if entry_buy is None or entry_sell is None: continue
        
        # Pre-fetch exit
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
        exit_buy = exit_sell = None
        for ist_t, utc_t in exit_mins:
            grp = xgroups.get(ist_t, xgroups.get(utc_t, {}))
            if buy_strike in grp and sell_strike in grp:
                exit_buy = grp[buy_strike]
                exit_sell = grp[sell_strike]
                break
        if exit_buy is None or exit_sell is None: continue
        
        net_credit = entry_sell - entry_buy
        net_debit = exit_sell - exit_buy
        gross_pnl = (net_credit - net_debit) * lot_size * lots
        net_pnl = gross_pnl - (300 * lots)
        
        yoy[year] += net_pnl
        
    print(f"\n{name}:")
    print(f"2024: ₹{yoy[2024]:,.2f}")
    print(f"2025: ₹{yoy[2025]:,.2f}")
    print(f"2026: ₹{yoy[2026]:,.2f}")
    print(f"TOTAL: ₹{sum(yoy.values()):,.2f}")
