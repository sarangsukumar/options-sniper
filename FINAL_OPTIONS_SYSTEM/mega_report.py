import mysql.connector
import pandas as pd
import numpy as np
from backtest_experiment import get_lot_size, generate_multi_strikes
from collections import defaultdict

db = mysql.connector.connect(host='localhost', user='root', password='root', database='markets')
cursor = db.cursor(dictionary=True)

df_list = []
for y in [2024, 2025, 2026]:
    try:
        df_list.append(pd.read_csv(f'experiment_targets_{y}.csv'))
    except: pass
targets = pd.concat(df_list)

r1_r3 = targets[(targets['rank_type'].isin(['R1','R3'])) & (targets['buy_price'] != 'UNKNOWN')]
rand  = targets[(targets['rank_type'] == 'RAND') & (targets['buy_price'] != 'UNKNOWN')]

groups_to_test = [
    ("R1+R3 Wide Spread (+1 ITM / -3 OTM)", r1_r3, 1, 5),
    ("R1+R3 Current Sys (+1 ITM / -2 OTM)", r1_r3, 1, 4),
    ("RAND Wide Spread (+1 ITM / -3 OTM)", rand, 1, 5),
    ("RAND Current Sys (+1 ITM / -2 OTM)", rand, 1, 4)
]

print("=== MEGA INSTITUTIONAL PERFORMANCE REPORT ===\n")

for name, df_group, sell_idx, buy_idx in groups_to_test:
    pnls = []
    dates = []
    
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
        dates.append(buy_date)

    if len(pnls) == 0:
        print(f"| {name} | NO TRADES |")
        continue

    df_res = pd.DataFrame({'date': pd.to_datetime(dates), 'pnl': pnls})
    df_res = df_res.sort_values('date')
    
    # Time groupings
    df_res['month'] = df_res['date'].dt.to_period('M')
    df_res['quarter'] = df_res['date'].dt.to_period('Q')
    df_res['week'] = df_res['date'].dt.to_period('W')
    
    daily = df_res.groupby('date')['pnl'].sum()
    monthly = df_res.groupby('month')['pnl'].sum()
    quarterly = df_res.groupby('quarter')['pnl'].sum()
    weekly = df_res.groupby('week')['pnl'].sum()
    
    daily_win_rate = (len(daily[daily > 0]) / len(daily)) * 100 if len(daily) > 0 else 0
    monthly_win_rate = (len(monthly[monthly > 0]) / len(monthly)) * 100 if len(monthly) > 0 else 0
    quarterly_win_rate = (len(quarterly[quarterly > 0]) / len(quarterly)) * 100 if len(quarterly) > 0 else 0
    
    # Consecutive losing weeks
    max_loss_streak_weeks = 0
    cur_loss = 0
    for wpnl in weekly:
        if wpnl <= 0:
            cur_loss += 1
            max_loss_streak_weeks = max(max_loss_streak_weeks, cur_loss)
        else:
            cur_loss = 0
            
    # Regular streaks (trades)
    max_win_streak = max_loss_streak = 0
    cur_win = cur_loss = 0
    for p in df_res['pnl']:
        if p > 0:
            cur_win += 1
            max_win_streak = max(max_win_streak, cur_win)
            cur_loss = 0
        else:
            cur_loss += 1
            max_loss_streak = max(max_loss_streak, cur_loss)
            cur_win = 0

    arr = df_res['pnl'].values
    cum = np.cumsum(arr)
    run_max = np.maximum.accumulate(cum)
    drawdowns = run_max - cum
    max_dd = drawdowns.max() if len(drawdowns) > 0 else 0
    
    wins = arr[arr > 0]
    losses = arr[arr <= 0]
    
    trade_win_rate = (len(wins) / len(arr)) * 100
    gross_profit = wins.sum() if len(wins) > 0 else 0
    gross_loss = abs(losses.sum()) if len(losses) > 0 else 1
    profit_factor = gross_profit / gross_loss
    
    avg_win = wins.mean() if len(wins) > 0 else 0
    avg_loss = losses.mean() if len(losses) > 0 else 0
    reward_to_risk = abs(avg_win / avg_loss) if avg_loss != 0 else 0
    
    starting_capital = 400000
    final_capital = starting_capital + arr.sum()
    # CAGR = (Ending Value / Beginning Value) ^ (1 / Years) - 1
    # 2024 to 2026 is exactly 3 years
    cagr = ((final_capital / starting_capital) ** (1/3) - 1) * 100 if final_capital > 0 else 0
    
    mean_pnl = arr.mean()
    std_pnl = arr.std()
    sharpe = (mean_pnl / std_pnl) * np.sqrt(252) if std_pnl != 0 else 0

    print(f"**{name}**")
    print(f"Total Trades         : {len(arr)}")
    print(f"Total Net Profit     : ₹{arr.sum():,.2f}")
    print(f"CAGR (3 Yrs)         : {cagr:.1f}%")
    print(f"Profit Factor        : {profit_factor:.2f}")
    print(f"Reward-to-Risk       : {reward_to_risk:.2f}")
    print(f"Trade Win Rate       : {trade_win_rate:.1f}%")
    print(f"Daily Win Rate       : {daily_win_rate:.1f}%")
    print(f"Monthly Win Rate     : {monthly_win_rate:.1f}%")
    print(f"Quarterly Win Rate   : {quarterly_win_rate:.1f}%")
    print(f"Max Drawdown         : ₹{max_dd:,.2f}")
    print(f"Max Trade Win Streak : {max_win_streak}")
    print(f"Max Trade Loss Streak: {max_loss_streak}")
    print(f"Max Week Loss Streak : {max_loss_streak_weeks}")
    print(f"Approx Sharpe Ratio  : {sharpe:.2f}")
    print("---------------------------------------------------------")
