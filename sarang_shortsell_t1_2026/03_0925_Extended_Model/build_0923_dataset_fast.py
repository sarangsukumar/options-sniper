import os
import pymysql
import numpy as np
import pandas as pd
from concurrent.futures import ThreadPoolExecutor
import threading
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_FILE = os.path.join(SCRIPT_DIR, 'data', 'scalp_0925_ml_dataset.csv.gz')
os.makedirs(os.path.join(SCRIPT_DIR, 'data'), exist_ok=True)

VALID_STOCKS = [
    'AARTIIND', 'ABB', 'ABBOTINDIA', 'ABCAPITAL', 'ABFRL', 'ACC', 'ADANIENT', 'ADANIPORTS',
    'ALKEM', 'AMBUJACEM', 'APOLLOHOSP', 'APOLLOTYRE', 'ASHOKLEY', 'ASIANPAINT', 'ASTRAL',
    'ATUL', 'AUBANK', 'AUROPHARMA', 'AXISBANK', 'BAJAJ-AUTO', 'BAJAJFINSV', 'BAJFINANCE',
    'BALKRISIND', 'BALRAMCHIN', 'BANDHANBNK', 'BANKBARODA', 'BATAINDIA', 'BEL', 'BERGEPAINT',
    'BHARATFORG', 'BHARTIARTL', 'BHEL', 'BIOCON', 'BOSCHLTD', 'BPCL', 'BRITANNIA', 'BSOFT',
    'CANBK', 'CANFINHOME', 'CHAMBLFERT', 'CHOLAFIN', 'CIPLA', 'COALINDIA', 'COFORGE',
    'COLPAL', 'CONCOR', 'COROMANDEL', 'CROMPTON', 'CUB', 'CUMMINSIND', 'DABUR', 'DALBHARAT',
    'DEEPAKNTR', 'DIVISLAB', 'DIXON', 'DLF', 'DRREDDY', 'EICHERMOT', 'ESCORTS', 'EXIDEIND',
    'FEDERALBNK', 'GAIL', 'GLENMARK', 'GMRINFRA', 'GNFC', 'GODREJCP', 'GODREJPROP',
    'GRANULES', 'GRASIM', 'GUJGASLTD', 'HAL', 'HAVELLS', 'HCLTECH', 'HDFCAMC', 'HDFCBANK',
    'HDFCLIFE', 'HEROMOTOCO', 'HINDALCO', 'HINDCOPPER', 'HINDPETRO', 'HINDUNILVR',
    'ICICIBANK', 'ICICIGI', 'ICICIPRULI', 'IDEA', 'IDFCFIRSTB', 'IEX', 'IGL', 'INDHOTEL',
    'INDIACEM', 'INDIAMART', 'INDIGO', 'INDUSINDBK', 'INDUSTOWER', 'INFY', 'INTELLECT',
    'IOC', 'IPCALAB', 'IRCTC', 'ITC', 'JINDALSTEL', 'JKCEMENT', 'JSWSTEEL', 'JUBLFOOD',
    'KOTAKBANK', 'LALPATHLAB', 'LAURUSLABS', 'LICHSGFIN', 'LT', 'LTIM', 'LTTS', 'LUPIN',
    'M&M', 'M&MFIN', 'MANAPPURAM', 'MARICO', 'MARUTI', 'MCDOWELL-N', 'MCX', 'METROPOLIS',
    'MFSL', 'MGL', 'MOTHERSON', 'MPHASIS', 'MRF', 'MUTHOOTFIN', 'NATIONALUM', 'NAUKRI',
    'NAVINFLUOR', 'NESTLEIND', 'NMDC', 'NTPC', 'OBEROIRLTY', 'OFSS', 'ONGC', 'PAGEIND',
    'PEL', 'PERSISTENT', 'PETRONET', 'PFC', 'PIDILITIND', 'PIIND', 'PNB', 'POLYCAB',
    'POWERGRID', 'PVRINOX', 'RAMCOCEM', 'RBLBANK', 'RECLTD', 'RELIANCE', 'SAIL',
    'SBICARD', 'SBILIFE', 'SBIN', 'SHREECEM', 'SHRIRAMFIN', 'SIEMENS', 'SRF', 'SUNTV',
    'SYNGENE', 'TATACHEM', 'TATACOMM', 'TATACONSUM', 'TATAMOTORS', 'TATAPOWER', 'TATASTEEL',
    'TCS', 'TECHM', 'TITAN', 'TORNTPHARM', 'TORNTPOWER', 'TRENT', 'TVSMOTOR', 'UBL',
    'ULTRACEMCO', 'UPL', 'VEDL', 'VOLTAS', 'WIPRO', 'ZEEL', 'ZYDUSLIFE'
]
VALID_SET = set(VALID_STOCKS)

thread_local = threading.local()

def get_db_connection():
    if not hasattr(thread_local, "conn"):
        thread_local.conn = pymysql.connect(
            host='localhost', user='root', password='root', 
            database='markets', cursorclass=pymysql.cursors.DictCursor
        )
    return thread_local.conn

def calc_arc_features(prices):
    if len(prices) < 3: return 0.0
    p = np.array(prices)
    norm_p = (p - p[0]) / (p[0] + 1e-9)
    changes = np.diff(norm_p)
    pos_arcs = np.sum(changes > 0)
    total_arcs = len(changes)
    return float(pos_arcs / total_arcs) if total_arcs > 0 else 0.0

def get_kotak_charges(qty, sell_price, buy_price):
    turnover = (qty * sell_price) + (qty * buy_price)
    stt      = round(qty * sell_price * 0.00025)
    txn      = turnover * 0.0000322
    sebi     = turnover * 0.000001
    stamp    = round(qty * buy_price * 0.00003)
    gst      = (40.0 + txn + sebi) * 0.18
    return round(40.0 + stt + txn + sebi + stamp + gst, 2)

def process_date(target_date):
    conn = get_db_connection()
    with conn.cursor() as cur:
        cur.execute(f"SELECT MAX(date) as pd FROM scrapdata WHERE date < '{target_date}'")
        r = cur.fetchone()
        prev_date = str(r['pd']) if r and r['pd'] else None
        if not prev_date: return []

        cur.execute(f"SELECT stockname, time, price, volume FROM scrapdata WHERE date = '{prev_date}' AND TIME(time) >= '09:15:00' AND TIME(time) <= '15:30:00' ORDER BY stockname, time ASC")
        prev_rows = cur.fetchall()

        cur.execute(f"SELECT stockname, time, price FROM scrapdata WHERE date = '{target_date}' AND TIME(time) >= '09:07:00' AND TIME(time) <= '09:23:59' ORDER BY stockname, time ASC")
        morn_rows = cur.fetchall()

        cur.execute(f"SELECT stockname, time, price FROM scrapdata WHERE date = '{target_date}' AND TIME(time) >= '09:25:00' AND TIME(time) <= '09:40:59' ORDER BY stockname, time ASC")
        pnl_rows = cur.fetchall()

    prev_dict = {}
    for r in prev_rows:
        s = r['stockname'].strip().upper()
        if s not in prev_dict: prev_dict[s] = []
        prev_dict[s].append(r)

    morn_dict = {}
    for r in morn_rows:
        s = r['stockname'].strip().upper()
        if s not in morn_dict: morn_dict[s] = []
        morn_dict[s].append(r)

    pnl_dict = {}
    for r in pnl_rows:
        s = r['stockname'].strip().upper()
        if s not in pnl_dict: pnl_dict[s] = []
        pnl_dict[s].append(r)

    records = []
    for stock, mticks in morn_dict.items():
        if stock not in VALID_SET: continue
        if stock not in prev_dict or len(prev_dict[stock]) < 10: continue

        pticks   = prev_dict[stock]
        p_prices = [float(x['price']) for x in pticks]
        p_vols   = [float(x['volume']) if x.get('volume') is not None else 1.0 for x in pticks]
        p_times  = [str(x['time']).split()[-1] for x in pticks]

        p_open  = p_prices[0]
        p_close = p_prices[-1]

        cum_pv = sum(p * v for p, v in zip(p_prices, p_vols))
        cum_v  = sum(p_vols)
        vwap   = cum_pv / cum_v if cum_v > 0 else p_close
        prev_intraday_vwap_gap = ((p_close - vwap) / vwap) * 100.0

        lh_prices = [p for t, p in zip(p_times, p_prices) if t >= '14:30:00']
        p_1430 = lh_prices[0] if lh_prices else p_close
        prev_intraday_roc_last_hour = ((p_close - p_1430) / p_1430) * 100.0

        prev_intraday_return = ((p_close - p_open) / p_open) * 100.0

        p_0907_ticks = [float(x['price']) for x in mticks if str(x['time']).split()[-1] < '09:15:00']
        p_0915_ticks = [float(x['price']) for x in mticks if str(x['time']).split()[-1] >= '09:15:00']

        if not p_0915_ticks: continue

        open_0915  = p_0915_ticks[0]
        close_0923 = p_0915_ticks[-1]
        high_0923  = max(p_0915_ticks)
        low_0923   = min(p_0915_ticks)

        if close_0923 < 50: continue

        Gap_Pct = ((open_0915 - p_close) / p_close) * 100.0
        if p_0907_ticks:
            p_0907 = p_0907_ticks[0]
            gap_0907_pct = ((p_0907 - p_close) / p_close) * 100.0
        else:
            gap_0907_pct = Gap_Pct

        morn_range_pct = (high_0923 - low_0923) / (open_0915 + 1e-9)
        rejection_wick = (high_0923 - close_0923) / (high_0923 - low_0923 + 1e-9)
        pos_arc_ratio  = calc_arc_features(p_0915_ticks)

        stock_pnl_ticks = pnl_dict.get(stock, [])
        if not stock_pnl_ticks: continue

        entry_ticks = [x for x in stock_pnl_ticks if str(x['time']).split()[-1] >= '09:25:00']
        exit_ticks  = [x for x in stock_pnl_ticks if str(x['time']).split()[-1] <= '09:40:59']

        if not entry_ticks or not exit_ticks: continue

        entry_price = float(entry_ticks[0]['price'])
        exit_price  = float(exit_ticks[-1]['price'])

        if entry_price <= 0 or exit_price <= 0: continue

        qty     = int(1000000.0 / entry_price)
        charges = get_kotak_charges(qty, entry_price, exit_price)
        pnl_net = ((entry_price - exit_price) * qty) - charges

        records.append({
            'short_date'                : target_date,
            'clean_stock'               : stock,
            'morn_range_pct'            : round(morn_range_pct, 8),
            'pnl_net'                   : round(pnl_net, 2),
            'prev_intraday_vwap_gap'    : round(prev_intraday_vwap_gap, 6),
            'prev_intraday_roc_last_hour': round(prev_intraday_roc_last_hour, 6),
            'prev_intraday_return'      : round(prev_intraday_return, 6),
            'positive_arc_ratio'        : round(pos_arc_ratio, 6),
            'Gap_Pct'                   : round(Gap_Pct, 6),
            'gap_0907_pct'              : round(gap_0907_pct, 6),
            'rejection_wick'            : round(rejection_wick, 8),
            'entry_price'               : round(entry_price, 2),
            'exit_price'                : round(exit_price, 2),
        })
    return records

if __name__ == '__main__':
    conn = pymysql.connect(host='localhost', user='root', password='root', database='markets', cursorclass=pymysql.cursors.DictCursor)
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT date FROM scrapdata WHERE date >= '2020-01-01' ORDER BY date ASC")
        all_dates = [str(r['date']) for r in cur.fetchall()]
    conn.close()

    print(f"Found {len(all_dates)} trading dates.")
    start = time.time()
    
    all_records = []
    with ThreadPoolExecutor(max_workers=30) as ex:
        for idx, res in enumerate(ex.map(process_date, all_dates)):
            all_records.extend(res)
            if (idx+1) % 50 == 0:
                print(f"Processed {idx+1}/{len(all_dates)} dates... ({(time.time()-start):.1f}s)")
                
    df = pd.DataFrame(all_records)
    df = df.drop_duplicates(subset=['short_date', 'clean_stock'])
    df.to_csv(OUT_FILE, index=False, compression='gzip')
    print(f"\n✅ Dataset rebuilt: {len(df)} rows saved to {OUT_FILE}")

