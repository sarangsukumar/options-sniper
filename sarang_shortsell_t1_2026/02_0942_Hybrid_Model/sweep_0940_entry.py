import os
import pymysql
import pandas as pd
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
preds = pd.read_csv(os.path.join(BASE_DIR, '0942_monthly_predictions.csv'))

# 1. Macro Filters Setup
tickers = {'NIFTY': '^NSEI'}
data = yf.download(list(tickers.values()), start='2018-01-01', end='2026-12-31', progress=False)
df_close = data['Close'].reset_index()
df_open = data['Open'].reset_index()
dates = pd.date_range(start='2018-01-01', end='2026-12-31', freq='B')
features = pd.DataFrame({'date': dates})
features['date_str'] = features['date'].dt.strftime('%Y-%m-%d')
features = features.merge(df_close[['Date', '^NSEI']].rename(columns={'Date':'date','^NSEI':'nifty_close'}), on='date', how='left')
features = features.merge(df_open[['Date', '^NSEI']].rename(columns={'Date':'date','^NSEI':'nifty_open'}), on='date', how='left')
features['nifty_gap'] = ((features['nifty_open'] / features['nifty_close'].shift(1)) - 1) * 100
features['nifty_gap'] = features['nifty_gap'].fillna(0)

# Merge predictions with stock data to get pct change
df_scratch = pd.read_csv(os.path.join(BASE_DIR, 'data/short_sell_ml_dataset_v5_scratch.csv.gz'), low_memory=False)
df_scratch['clean_stock'] = df_scratch['clean_stock'].astype(str).str.strip().str.upper()
preds['Stock_clean'] = preds['clean_stock'].astype(str).str.strip().str.upper()
preds = preds.merge(df_scratch[['date_str','clean_stock','prev_close']], left_on=['date_str','Stock_clean'], right_on=['date_str','clean_stock'], how='left')
preds = preds.merge(features[['date_str','nifty_gap']], left_on='date_str', right_on='date_str', how='left')
preds['DayOfWeek'] = pd.to_datetime(preds['date_str']).dt.dayofweek

def get_taxes(qty, sell_price, buy_price):
    turnover = (qty * sell_price) + (qty * buy_price)
    stt = round(qty * sell_price * 0.00025)
    txn = turnover * 0.0000322
    sebi = turnover * 0.000001
    stamp = round(qty * buy_price * 0.00003)
    gst = (40.0 + txn + sebi) * 0.18
    return round(40.0 + stt + txn + sebi + stamp + gst, 2)

def audit_trade(args):
    row, entry_min = args
    d = row['date_str']
    s = row['Stock_clean']
    
    conn = pymysql.connect(host='localhost', user='root', password='root', database='markets', cursorclass=pymysql.cursors.DictCursor)
    with conn.cursor() as cur:
        # Exit is 14:45 for the 0940 Hybrid model
        cur.execute(f"SELECT time, price, high FROM scrapdata WHERE date='{d}' AND stockname = '{s}' AND time>='{d} 09:{entry_min}:00' AND time<='{d} 14:48:00' ORDER BY time ASC")
        ticks = cur.fetchall()
    conn.close()
    
    if not ticks: return None
    
    sell_price = float(ticks[0]['price'] or 0)
    sell_time = str(ticks[0]['time'])
    if sell_price <= 0: return None
    
    # 0940 Model uses 3% SL
    qty = int(1000000.0 / sell_price)
    sl_price = round(sell_price * 1.03, 2)
    
    buy_price = None
    buy_time = None
    for t in ticks:
        t_time = str(t['time'])
        if t_time <= sell_time: continue
        
        h = float(t['high'] or t['price'] or 0)
        if h >= sl_price:
            buy_price = sl_price
            buy_time = t_time
            break
        if t_time >= f"{d} 14:45:00":
            buy_price = float(t['price'] or 0)
            buy_time = t_time
            break
            
    if not buy_price:
        buy_price = float(ticks[-1]['price'] or 0)
        buy_time = str(ticks[-1]['time'])
        
    net_pnl = ((sell_price - buy_price) * qty) - get_taxes(qty, sell_price, buy_price)
    
    # Apply Huber Filters logic (r1, r2, r3)
    # 0940 stock percent change is based on entry vs prev_close
    pct = (sell_price - row['prev_close']) / row['prev_close'] * 100
    r1 = pct >= -1.0
    r2 = not (row['nifty_gap'] < -0.5 and pct < -0.5)
    r3 = not (row['DayOfWeek'] == 0 and pct < -0.5)
    
    passed_filters = r1 and r2 and r3
    
    return {
        'Date': d, 'Stock': s, 'Sell_Time': sell_time, 'Sell_Price': sell_price,
        'Buy_Time': buy_time, 'Buy_Price': buy_price, 'Net_PnL': net_pnl,
        'passed_filters': passed_filters
    }

entry_mins = [41, 42, 43, 44, 45, 46, 47, 48, 49, 50]

for em in entry_mins:
    print(f"\nEvaluating exactly 09:{em}:00 Entry for 0940 Model...")
    args_list = [(row, em) for _, row in preds.iterrows()]
    results = []
    with ThreadPoolExecutor(max_workers=25) as ex:
        for res in ex.map(audit_trade, args_list):
            if res is not None:
                results.append(res)
                
    df_res = pd.DataFrame(results)
    df_res = df_res[df_res['passed_filters']]
    
    total_pnl = df_res['Net_PnL'].sum() / 100000.0
    win_rate = (df_res['Net_PnL'] > 0).mean() * 100
    print(f"09:{em}:00 Entry => Total PnL: Rs {total_pnl:6.2f} Lakhs | Win Rate: {win_rate:.1f}% | Trades: {len(df_res)}")

