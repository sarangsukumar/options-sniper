import mysql.connector
import pandas as pd

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

def simulate_trade(stock, buy_date):
    cursor.execute("SELECT MIN(DATE(datetime)) as ed FROM scrapdata_options WHERE stock_code=%s AND DATE(datetime)>%s", (stock, buy_date))
    res = cursor.fetchone()
    if not res or not res['ed']: return None
    sell_date = str(res['ed'])
    cursor.execute("SELECT DISTINCT strike_price FROM scrapdata_options WHERE stock_code=%s AND DATE(datetime)=%s ORDER BY strike_price DESC", (stock, buy_date))
    strikes = [float(r['strike_price']) for r in cursor.fetchall()]
    if len(strikes) <= 4: return None
    sell_strike, buy_strike = strikes[1], strikes[4]
    lot_size = get_lot_size(stock, buy_date)
    margin_per_lot = (sell_strike - buy_strike) * lot_size
    if margin_per_lot <= 0 or margin_per_lot > 400000: return None
    lots = int(400000 // margin_per_lot)
    if lots == 0: return None

    cursor.execute("SELECT TIME(datetime) as t, strike_price, close FROM scrapdata_options WHERE stock_code=%s AND DATE(datetime)=%s AND (TIME(datetime) BETWEEN '15:26:00' AND '15:27:00' OR TIME(datetime) BETWEEN '09:56:00' AND '09:57:00') ORDER BY datetime ASC", (stock, buy_date))
    egroups = {}
    for r in cursor.fetchall():
        t = str(r['t'])
        if len(t) == 7: t = "0" + t
        sp = float(r['strike_price'])
        if t not in egroups: egroups[t] = {}
        egroups[t][sp] = float(r['close'])
    entry_buy = egroups.get('15:26:00', egroups.get('09:56:00', {})).get(buy_strike)
    entry_sell = egroups.get('15:27:00', egroups.get('09:57:00', {})).get(sell_strike)

    cursor.execute("SELECT TIME(datetime) as t, strike_price, open, close FROM scrapdata_options WHERE stock_code=%s AND DATE(datetime)=%s AND (TIME(datetime) BETWEEN '09:29:00' AND '09:30:00' OR TIME(datetime) BETWEEN '03:59:00' AND '04:00:00') ORDER BY datetime ASC", (stock, sell_date))
    xgroups = {}
    for r in cursor.fetchall():
        t = str(r['t'])
        if len(t) == 7: t = "0" + t
        sp = float(r['strike_price'])
        px = float(r['open']) if r['open'] and r['open']>0 else float(r['close'])
        if t not in xgroups: xgroups[t] = {}
        xgroups[t][sp] = px
    exit_sell = xgroups.get('09:29:00', xgroups.get('03:59:00', {})).get(sell_strike)
    exit_buy = xgroups.get('09:30:00', xgroups.get('04:00:00', {})).get(buy_strike)
    
    if None in (entry_sell, entry_buy, exit_sell, exit_buy): return None
    return (entry_sell - entry_buy - (exit_sell - exit_buy)) * lot_size * lots - (300 * lots)

targets = pd.read_csv('experiment_targets_2026.csv')
targets = targets[targets['buy_price'] != 'UNKNOWN']

wins = {'R1_R3': 0, 'R2_R4': 0, 'RAND': 0}
counts = {'R1_R3': 0, 'R2_R4': 0, 'RAND': 0}

for _, row in targets.iterrows():
    pnl = simulate_trade(row['stock'], row['buy_date'])
    if pnl is not None:
        rt = row['rank_type']
        grp = 'R1_R3' if rt in ['R1', 'R3'] else 'R2_R4' if rt in ['R2', 'R4'] else 'RAND'
        counts[grp] += 1
        if pnl > 0: wins[grp] += 1

print("Win Rates:")
print(f"R1_R3: {wins['R1_R3']}/{counts['R1_R3']} = {wins['R1_R3']/counts['R1_R3']*100:.2f}%")
print(f"R2_R4: {wins['R2_R4']}/{counts['R2_R4']} = {wins['R2_R4']/counts['R2_R4']*100:.2f}%")
print(f"RAND: {wins['RAND']}/{counts['RAND']} = {wins['RAND']/counts['RAND']*100:.2f}%")
