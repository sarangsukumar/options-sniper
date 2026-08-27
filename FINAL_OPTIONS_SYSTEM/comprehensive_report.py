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

r1_r3 = targets[(targets['rank_type'].isin(['R1','R3'])) & (targets['buy_price'] != 'UNKNOWN')]

groups_to_test = [
    ("R1+R3 (Wide Spread: +1 ITM / -3 OTM)", r1_r3, 1, 5),
    ("R1+R3 (Current Sys: +1 ITM / -2 OTM)", r1_r3, 1, 4)
]

print("=== INSTITUTIONAL PERFORMANCE REPORT (R1 + R3 ONLY) ===\n")

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
        continue

    arr = np.array(pnls)
    cum = np.cumsum(arr)
    run_max = np.maximum.accumulate(cum)
    drawdowns = run_max - cum
    max_dd = drawdowns.max() if len(drawdowns) > 0 else 0
    
    wins = arr[arr > 0]
    losses = arr[arr <= 0]
    
    win_rate = (len(wins) / len(arr)) * 100
    gross_profit = wins.sum() if len(wins) > 0 else 0
    gross_loss = abs(losses.sum()) if len(losses) > 0 else 1
    profit_factor = gross_profit / gross_loss
    
    avg_win = wins.mean() if len(wins) > 0 else 0
    avg_loss = losses.mean() if len(losses) > 0 else 0
    reward_to_risk = abs(avg_win / avg_loss) if avg_loss != 0 else 0
    
    # Capital required is our margin cap
    starting_capital = 400000
    roi_percent = (arr.sum() / starting_capital) * 100
    
    # Sharpe Ratio Approximation (Daily PnL standard deviation)
    # Assuming ~252 trading days a year. We don't have daily timestamps here, so we use trade sequence.
    mean_pnl = arr.mean()
    std_pnl = arr.std()
    sharpe = (mean_pnl / std_pnl) * np.sqrt(252) if std_pnl != 0 else 0
    
    # Consecutive metrics
    max_win_streak = max_loss_streak = 0
    cur_win = cur_loss = 0
    for p in arr:
        if p > 0:
            cur_win += 1
            max_win_streak = max(max_win_streak, cur_win)
            cur_loss = 0
        else:
            cur_loss += 1
            max_loss_streak = max(max_loss_streak, cur_loss)
            cur_win = 0

    print(f"**{name}**")
    print(f"- Total Executed Trades : {len(arr)}")
    print(f"- Net Profit (3 Years)  : ₹{arr.sum():,.2f}")
    print(f"- Return on Investment  : {roi_percent:,.1f}% (On ₹4L Margin)")
    print(f"- Absolute Win Rate     : {win_rate:.1f}%")
    print(f"- Profit Factor         : {profit_factor:.2f} (Gross Profit / Gross Loss)")
    print(f"- Average Win           : ₹{avg_win:,.2f}")
    print(f"- Average Loss          : ₹{avg_loss:,.2f}")
    print(f"- Reward-to-Risk Ratio  : {reward_to_risk:.2f}")
    print(f"- Max Drawdown (Valley) : ₹{max_dd:,.2f}")
    print(f"- Approx Sharpe Ratio   : {sharpe:.2f}")
    print(f"- Max Win Streak        : {max_win_streak} trades")
    print(f"- Max Losing Streak     : {max_loss_streak} trades")
    print("---------------------------------------------------------")
