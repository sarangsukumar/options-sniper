import mysql.connector
import pandas as pd
import numpy as np
from backtest_experiment import get_lot_size, generate_multi_strikes

db = mysql.connector.connect(host='localhost', user='root', password='root', database='markets')
cursor = db.cursor(dictionary=True)

df_list = []
for y in [2024, 2025, 2026]:
    try:
        df_list.append(pd.read_csv(f'experiment_targets_{y}.csv'))
    except: pass
targets = pd.concat(df_list)

r123 = targets[(targets['rank_type'].isin(['R1','R2','R3'])) & (targets['buy_price'] != 'UNKNOWN')]

groups_to_test = [
    ("R1+R2+R3 (Current Sys: +1 ITM / -2 OTM)", r123, 1, 4),
    ("R1+R2+R3 (Wide Spread: +1 ITM / -3 OTM)", r123, 1, 5)
]

print("=== R1 + R2 + R3 COMBINED METRICS ===\n")

for name, df_group, sell_idx, buy_idx in groups_to_test:
    pnls = []
    
    for _, row in df_group.iterrows():
        stock, buy_date, buy_price = row['stock'], row['buy_date'], float(row['buy_price'])
        
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
        
        # Entry
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
                entry_buy, entry_sell = grp[buy_strike], grp[sell_strike]
                break
        if entry_buy is None or entry_sell is None: continue
        
        # Exit
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
                exit_buy, exit_sell = grp[buy_strike], grp[sell_strike]
                break
        if exit_buy is None or exit_sell is None: continue
        
        net_credit = entry_sell - entry_buy
        net_debit = exit_sell - exit_buy
        gross_pnl = (net_credit - net_debit) * lot_size * lots
        net_pnl = gross_pnl - (300 * lots)
        pnls.append(net_pnl)

    if len(pnls) == 0:
        print(f"| {name} | NO TRADES |")
        continue

    pnls_array = np.array(pnls)
    cumulative = np.cumsum(pnls_array)
    running_max = np.maximum.accumulate(cumulative)
    drawdowns = running_max - cumulative
    max_drawdown = drawdowns.max() if len(drawdowns) > 0 else 0

    wins = pnls_array[pnls_array > 0]
    win_rate = (len(wins) / len(pnls_array)) * 100
    
    out = (
        f"**{name}**\n"
        f"- Total Trades: {len(pnls_array)}\n"
        f"- Win Rate: {win_rate:.1f}%\n"
        f"- Total Sum PnL: ₹{pnls_array.sum():,.2f}\n"
        f"- Avg PnL / Trade: ₹{pnls_array.mean():,.2f}\n"
        f"- Max Drawdown: ₹{max_drawdown:,.2f}\n"
        "----------------------------------------"
    )
    print(out)
