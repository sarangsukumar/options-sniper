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
    except Exception: pass
    defaults = {'RELIANCE': 250, 'TCS': 175, 'INFY': 400, 'HDFCBANK': 550, 'ICICIBANK': 700}
    return defaults.get(stock, 500)

targets = []
for year in ['2024', '2025', '2026']:
    try:
        df = pd.read_csv(f'options_download_targets_{year}_verified.csv')
        for _, row in df.iterrows(): targets.append((row['stock'], row['buy_date']))
    except: pass

max_lots = 0
max_lots_trade = None

for stock, buy_date in targets:
    cursor.execute("SELECT DISTINCT strike_price FROM scrapdata_options WHERE stock_code=%s AND DATE(datetime)=%s ORDER BY strike_price DESC", (stock, buy_date))
    strikes = [float(r['strike_price']) for r in cursor.fetchall()]
    if len(strikes) <= 4: continue
    sell_strike = strikes[1]
    buy_strike = strikes[4]
    lot_size = get_lot_size(stock, buy_date)
    margin_per_lot = (sell_strike - buy_strike) * lot_size
    if margin_per_lot > 400000: continue
    
    lots = int(400000 // margin_per_lot)
    if lots > max_lots:
        max_lots = lots
        max_lots_trade = (stock, buy_date, margin_per_lot, lot_size)

print(f"Max Lots Traded: {max_lots}")
print(f"Stock: {max_lots_trade[0]} on {max_lots_trade[1]}")
print(f"Margin per lot: {max_lots_trade[2]}")
print(f"Share Lot Size: {max_lots_trade[3]}")
