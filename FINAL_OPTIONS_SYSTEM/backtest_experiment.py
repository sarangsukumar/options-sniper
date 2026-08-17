import mysql.connector
import pandas as pd
import numpy as np

db = mysql.connector.connect(host='localhost', user='root', password='root', database='markets')
cursor = db.cursor(dictionary=True)

lotsize_df = pd.read_csv('/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/config/historical_lotsize_new.csv')
lotsize_df['stockname'] = lotsize_df['stockname'].str.strip()

def get_lot_size(stock, date_str):
    try:
        dt = pd.to_datetime(date_str)
        yr = str(dt.year)[-2:]
        m_str = dt.strftime('%b').upper()
        match = lotsize_df[(lotsize_df['stockname'] == stock) & (lotsize_df['expmonth'] == m_str) & (lotsize_df['expyear'].astype(str) == yr)]
        if not match.empty: return int(match.iloc[0]['lotsize'])
    except: pass
    defaults = {'RELIANCE': 250, 'TCS': 175, 'INFY': 400, 'HDFCBANK': 550, 'ICICIBANK': 700}
    return defaults.get(stock, 500)

def generate_multi_strikes(buy_price):
    step = 5
    if buy_price > 2500: step = 50
    elif buy_price > 1000: step = 20
    elif buy_price > 500: step = 10
    elif buy_price > 100: step = 5
    elif buy_price > 50: step = 2.5
    else: step = 1
    
    rounded = round(buy_price / step) * step
    strikes = set()
    for i in range(-6, 3):
        s = rounded + (step * i)
        if s > 0: strikes.add(s)
    return sorted(list(strikes), reverse=True)

def simulate_trade(stock, buy_date, buy_price, rank_type, margin_cap=400000, comm_per_lot=400):
    cursor.execute("SELECT MIN(DATE(datetime)) as ed FROM scrapdata_options WHERE stock_code=%s AND DATE(datetime)>%s", (stock, buy_date))
    res = cursor.fetchone()
    if not res or not res['ed']: return None
    sell_date = str(res['ed'])
    
    try:
        buy_price = float(buy_price)
    except:
        return None
        
    # 1. Calculate Option Legs based on Target Rank Type
    strikes = generate_multi_strikes(buy_price)
    if len(strikes) < 7: return None  # need index 5 for Wide Spread
    
    if rank_type in ['R1', 'R3']:
        sell_strike = strikes[1] # +1 ITM
        buy_strike = strikes[5]  # -3 OTM (WIDE SPREAD — Original Winner: Sharpe 5.78, 86.7% monthly WR)
    else:
        sell_strike = strikes[1] # +1 ITM
        buy_strike = strikes[4]  # -2 OTM (R2+R4 Current System)

    lot_size = get_lot_size(stock, buy_date)
    margin_per_lot = (sell_strike - buy_strike) * lot_size
    if margin_per_lot <= 0 or margin_per_lot > margin_cap: return None
    lots = int(margin_cap // margin_per_lot)
    lots = min(lots, 20)  # Hard cap to prevent NSE Quantity Freeze Limit rejection
    if lots == 0: return None

    # ENTRY: Pull wider window
    cursor.execute("SELECT TIME(datetime) as t, strike_price, close FROM scrapdata_options WHERE stock_code=%s AND DATE(datetime)=%s AND (TIME(datetime) BETWEEN '15:20:00' AND '15:32:00' OR TIME(datetime) BETWEEN '09:50:00' AND '10:02:00')", (stock, buy_date))
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
            
    if entry_buy is None or entry_sell is None: return None

    # EXIT: Pull wider window
    cursor.execute("SELECT TIME(datetime) as t, strike_price, open, close FROM scrapdata_options WHERE stock_code=%s AND DATE(datetime)=%s AND (TIME(datetime) BETWEEN '09:25:00' AND '09:35:00' OR TIME(datetime) BETWEEN '03:55:00' AND '04:05:00')", (stock, sell_date))
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
            
    if exit_buy is None or exit_sell is None: return None
    
    net_credit = entry_sell - entry_buy
    net_debit = exit_sell - exit_buy
    gross_pnl = (net_credit - net_debit) * lot_size * lots
    net_pnl = gross_pnl - (comm_per_lot * lots)
    return net_pnl

targets_list = []
for yr in [2024, 2025, 2026]:
    try:
        df = pd.read_csv(f'experiment_targets_{yr}.csv')
        targets_list.append(df)
    except: pass
targets = pd.concat(targets_list, ignore_index=True) if targets_list else pd.DataFrame()
if not targets.empty:
    targets = targets[targets['buy_price'] != 'UNKNOWN']

results = {'R1_R3': 0, 'R2_R4': 0, 'RAND': 0}
counts = {'R1_R3': 0, 'R2_R4': 0, 'RAND': 0}
daily_pnl = {}

for _, row in targets.iterrows():
    pnl = simulate_trade(row['stock'], row['buy_date'], row['buy_price'], row['rank_type'])
    if pnl is not None:
        dt = row['buy_date']
        if dt not in daily_pnl: daily_pnl[dt] = {'R1_R3': 0, 'R2_R4': 0, 'RAND': 0}
        
        rt = row['rank_type']
        if rt in ['R1', 'R3']:
            results['R1_R3'] += pnl
            counts['R1_R3'] += 1
            daily_pnl[dt]['R1_R3'] += pnl
        elif rt in ['R2', 'R4']:
            results['R2_R4'] += pnl
            counts['R2_R4'] += 1
            daily_pnl[dt]['R2_R4'] += pnl
        elif rt in ['RAND1', 'RAND2']:
            results['RAND'] += pnl
            counts['RAND'] += 1
            daily_pnl[dt]['RAND'] += pnl

with open('experiment_report.md', 'w') as f:
    f.write("# Target Rank Strategy Backtest Comparison (2024-2026)\n\n")
    f.write("Comparing the options +1 ITM / -2 OTM Bull Put Spread strategy on ML Model Ranks vs Random Control.\n\n")
    f.write(f"- **R1 + R3 (Original Sniper)**: ₹{results['R1_R3']:,.2f} ({counts['R1_R3']} trades)\n")
    f.write(f"- **R2 + R4 (Lower Confidence)**: ₹{results['R2_R4']:,.2f} ({counts['R2_R4']} trades)\n")
    f.write(f"- **Random Control (Blind Pick)**: ₹{results['RAND']:,.2f} ({counts['RAND']} trades)\n\n")
    
    f.write("## Daily Breakdown\n")
    f.write("| Date | R1_R3 Net | R2_R4 Net | RAND Net |\n")
    f.write("|------|-----------|-----------|----------|\n")
    for d in sorted(daily_pnl.keys()):
        v = daily_pnl[d]
        f.write(f"| {d} | {v['R1_R3']:,.2f} | {v['R2_R4']:,.2f} | {v['RAND']:,.2f} |\n")

print("Backtest complete. Generated experiment_report.md")
