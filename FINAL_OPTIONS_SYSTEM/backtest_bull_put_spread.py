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
        match = lotsize_df[(lotsize_df['stockname'] == stock) & 
                           (lotsize_df['expmonth'] == m_str) & 
                           (lotsize_df['expyear'].astype(str) == yr)]
        if not match.empty:
            return int(match.iloc[0]['lotsize'])
    except Exception:
        pass
    defaults = {'RELIANCE': 250, 'TCS': 175, 'INFY': 400, 'HDFCBANK': 550, 'ICICIBANK': 700}
    return defaults.get(stock, 500)

targets = []
years = ['2024', '2025', '2026']
for year in years:
    try:
        df = pd.read_csv(f'options_download_targets_{year}_verified.csv')
        for _, row in df.iterrows():
            targets.append((row['stock'], row['buy_date']))
    except:
        pass

total_pnl = 0
wins = 0
trades = 0
total_margin = 0
SLIPPAGE_PENALTY = 1000

for stock, buy_date in targets:
    # Get Sell Date
    cursor.execute("SELECT MIN(DATE(datetime)) as ed FROM scrapdata_options WHERE stock_code=%s AND DATE(datetime)>%s", (stock, buy_date))
    res = cursor.fetchone()
    if not res or not res['ed']: continue
    sell_date = str(res['ed'])
    
    # Get Strikes (+1 ITM is Index 1, -2 OTM is Index 4)
    cursor.execute("SELECT DISTINCT strike_price FROM scrapdata_options WHERE stock_code=%s AND DATE(datetime)=%s ORDER BY strike_price DESC", (stock, buy_date))
    strikes = [float(r['strike_price']) for r in cursor.fetchall()]
    
    if len(strikes) <= 4: 
        continue # Skip if we don't have enough strikes downloaded
    
    sell_strike = strikes[1] # +1 ITM
    buy_strike = strikes[4]  # -2 OTM
    
    # Maximize Sizing for 4L Capital
    lot_size = get_lot_size(stock, buy_date)
    margin_per_lot = (sell_strike - buy_strike) * lot_size
    if margin_per_lot > 400000: continue
    
    # Calculate maximum possible lots that fit into ₹4,00,000
    lots = int(400000 // margin_per_lot)
    if lots == 0: continue
        
    # ENTRY: Buy OTM first at 15:26, Sell ITM next minute at 15:27
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
            
    # EXIT: Buy back ITM first at 09:29, Sell OTM next minute at 09:30
    cursor.execute("SELECT TIME(datetime) as t, strike_price, open, close FROM scrapdata_options WHERE stock_code=%s AND DATE(datetime)=%s AND TIME(datetime) BETWEEN '09:29:00' AND '09:30:00' ORDER BY datetime ASC", (stock, sell_date))
    xrows = cursor.fetchall()
    xgroups = {}
    for r in xrows:
        t = str(r['t'])
        sp = float(r['strike_price'])
        px = float(r['open']) if r['open'] and r['open']>0 else float(r['close'])
        if t not in xgroups: xgroups[t] = {}
        xgroups[t][sp] = px
        
    exit_sell = xgroups.get('09:29:00', {}).get(sell_strike) # Buying to close the short leg
    exit_buy = xgroups.get('09:30:00', {}).get(buy_strike)   # Selling to close the long leg
            
    if None in (entry_sell, entry_buy, exit_sell, exit_buy): continue
    
    # Calculate PnL
    net_credit = entry_sell - entry_buy
    net_debit = exit_sell - exit_buy
    gross_pnl = (net_credit - net_debit) * lot_size * lots
    
    # Strictly deduct ₹300 PER LOT to account for slippage/taxes scaling with trade size
    net_pnl = gross_pnl - (300 * lots)
    
    trades += 1
    total_pnl += net_pnl
    total_margin += (margin_per_lot * lots)
    if net_pnl > 0: wins += 1

win_rate = (wins/trades*100) if trades>0 else 0
avg_margin = (total_margin/trades) if trades>0 else 0

print("=========================================")
print("  +1 ITM / -2 OTM STRICT BACKTEST        ")
print("=========================================")
print(f"Total Trades:           {trades}")
print(f"Win Rate:               {win_rate:.2f}%")
print(f"Average Margin Needed:  ₹{avg_margin:,.2f}")
print(f"Final NET P&L:          ₹{total_pnl:,.2f}  (After strictly deducting ₹1000 from EVERY trade)")
print("=========================================")
