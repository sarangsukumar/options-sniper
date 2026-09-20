import os
import time
import warnings
import numpy as np
import pandas as pd
import lightgbm as lgb
import pymysql
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor

warnings.filterwarnings('ignore')
BASE_DIR = '/home/ubuntu/sarang_shortsell_t1_2026'

tickers = {'NIFTY': '^NSEI', 'SP500': '^GSPC', 'NIKKEI': '^N225'}
data = yf.download(list(tickers.values()), start='2018-01-01', end='2026-12-31', progress=False)

if isinstance(data.columns, pd.MultiIndex):
    df_close = data['Close'].reset_index()
    df_open = data['Open'].reset_index()
else:
    df_close = pd.DataFrame(data['Close'], columns=['^NSEI']).reset_index()
    df_open = pd.DataFrame(data['Open'], columns=['^NSEI']).reset_index()

dates = pd.date_range(start='2018-01-01', end='2026-12-31', freq='B')
features = pd.DataFrame({'date': dates})
features['date_str'] = features['date'].dt.strftime('%Y-%m-%d')

nifty_c = df_close[['Date', '^NSEI']].rename(columns={'Date': 'date', '^NSEI': 'nifty_close'})
nifty_o = df_open[['Date', '^NSEI']].rename(columns={'Date': 'date', '^NSEI': 'nifty_open'})
features = features.merge(nifty_c, on='date', how='left').merge(nifty_o, on='date', how='left')
features['nifty_gap'] = (features['nifty_open'] / features['nifty_close'].shift(1)) - 1
sp_c = df_close[['Date', '^GSPC']].rename(columns={'Date': 'date', '^GSPC': 'sp500_close'})
features = features.merge(sp_c, on='date', how='left')
features['sp500_overnight_ret'] = (features['sp500_close'].shift(1) / features['sp500_close'].shift(2)) - 1
nikkei_c = df_close[['Date', '^N225']].rename(columns={'Date': 'date', '^N225': 'nikkei_close'})
nikkei_o = df_open[['Date', '^N225']].rename(columns={'Date': 'date', '^N225': 'nikkei_open'})
features = features.merge(nikkei_c, on='date', how='left').merge(nikkei_o, on='date', how='left')
features['nikkei_gap'] = (features['nikkei_open'] / features['nikkei_close'].shift(1)) - 1
for c in ['sp500_overnight_ret', 'nikkei_gap', 'nifty_gap']: features[c] = features[c].fillna(0)
features['nifty_vs_sp500_gap'] = features['nifty_gap'] - features['sp500_overnight_ret']
features['nifty_vs_nikkei_gap'] = features['nifty_gap'] - features['nikkei_gap']
global_macro = features[['date_str', 'nifty_gap', 'sp500_overnight_ret', 'nikkei_gap', 'nifty_vs_sp500_gap', 'nifty_vs_nikkei_gap']]

# 920
df_920 = pd.read_csv(os.path.join(BASE_DIR, 'data/scalp_0920_ml_dataset.csv.gz'))
df_920['year'] = pd.to_datetime(df_920['short_date']).dt.year
df_920 = df_920.merge(global_macro, left_on='short_date', right_on='date_str', how='left')
features_920 = ['morn_range_pct', 'prev_intraday_vwap_gap', 'prev_intraday_roc_last_hour', 'prev_intraday_return', 'positive_arc_ratio', 'Gap_Pct', 'gap_0907_pct', 'rejection_wick', 'nifty_gap', 'sp500_overnight_ret', 'nikkei_gap', 'nifty_vs_sp500_gap', 'nifty_vs_nikkei_gap']
df_920[features_920] = df_920[features_920].fillna(0)
df_920['target'] = (df_920['pnl_net'] > 0).astype(int)
params_920 = {'objective': 'binary', 'metric': 'auc', 'boosting_type': 'gbdt', 'learning_rate': 0.05, 'max_depth': 5, 'num_leaves': 31, 'feature_fraction': 0.8, 'verbose': -1, 'random_state': 42}
all_oos_920 = []
for y in range(2021, 2027):
    tr = df_920[df_920['year'] < y]
    te = df_920[df_920['year'] == y].copy()
    if len(tr) == 0 or len(te) == 0: continue
    mod = lgb.train(params_920, lgb.Dataset(tr[features_920], label=tr['target']), num_boost_round=300)
    te['prob'] = mod.predict(te[features_920])
    all_oos_920.append(te)
oos_920 = pd.concat(all_oos_920).sort_values(['short_date', 'prob'], ascending=[True, False])
top4_920 = oos_920.groupby('short_date').head(4).reset_index(drop=True)

# 942
df_942 = pd.read_csv(os.path.join(BASE_DIR, 'data/short_sell_ml_dataset_v5_scratch.csv'), low_memory=False)
df_942['clean_stock'] = df_942['clean_stock'].astype(str).str.strip().str.upper()
df_942['year'] = pd.to_datetime(df_942['date_str']).dt.year
df_942 = df_942.merge(global_macro, on='date_str', how='left')
features_942 = ['gap_0907_pct', 'gap_fade_0907_to_940_pct', 'prev_intraday_vwap_gap', 'prev_intraday_return', 'prev_intraday_roc_last_hour', 'morn_range_pct', 'rejection_wick', 'prev_1450_to_1519_pct', 'Gap_Pct', 'nifty_gap', 'sp500_overnight_ret', 'nikkei_gap', 'nifty_vs_sp500_gap', 'nifty_vs_nikkei_gap']
df_942[features_942] = df_942[features_942].apply(pd.to_numeric, errors='coerce').fillna(0)
df_942['target'] = df_942['short_pct_return']
params_942 = {'objective': 'regression', 'metric': 'rmse', 'boosting_type': 'gbdt', 'learning_rate': 0.05, 'max_depth': 5, 'num_leaves': 31, 'verbose': -1, 'random_state': 42}
all_oos_942 = []
for y in range(2021, 2027):
    tr = df_942[df_942['year'] < y]
    te = df_942[df_942['year'] == y].copy()
    if len(tr) == 0 or len(te) == 0: continue
    mod = lgb.train(params_942, lgb.Dataset(tr[features_942], label=tr['target']), num_boost_round=100)
    te['pred'] = mod.predict(te[features_942])
    all_oos_942.append(te)
oos_942 = pd.concat(all_oos_942).sort_values(['date_str', 'pred'], ascending=[True, False])
top4_942 = oos_942.groupby('date_str').head(4).reset_index(drop=True)

def get_taxes(qty, sell_price, buy_price):
    turnover = (qty * sell_price) + (qty * buy_price)
    stt = round(qty * sell_price * 0.00025)
    txn = turnover * 0.0000322
    sebi = turnover * 0.000001
    stamp = round(qty * buy_price * 0.00003)
    gst = (40.0 + txn + sebi) * 0.18
    return round(40.0 + stt + txn + sebi + stamp + gst, 2)

def audit_920(row):
    d, s, y = row['short_date'], row['clean_stock'], row['year']
    conn = pymysql.connect(host='localhost', user='root', password='root', database='markets', cursorclass=pymysql.cursors.DictCursor)
    with conn.cursor() as cur:
        cur.execute(f"SELECT time, price, high FROM scrapdata WHERE date='{d}' AND stockname LIKE '%{s}%' AND time>='{d} 09:22:00' AND time<='{d} 09:40:00' ORDER BY time ASC")
        ticks = cur.fetchall()
    conn.close()
    if not ticks: return (y, 0)
    sell_price = float(ticks[0]['price'] or 0)
    if sell_price <= 0: return (y, 0)
    qty = int(1000000.0 / sell_price)
    sl_price = round(sell_price * 1.03, 2)
    buy_price = next((float(t['high'] or t['price'] or 0) for t in ticks if float(t['high'] or t['price'] or 0) >= sl_price), float(ticks[-1]['price'] or 0))
    p = ((sell_price - buy_price) * qty) - get_taxes(qty, sell_price, buy_price)
    return (y, p)

def audit_942(row):
    d, s, y = row['date_str'], row['clean_stock'], row['year']
    conn = pymysql.connect(host='localhost', user='root', password='root', database='markets', cursorclass=pymysql.cursors.DictCursor)
    with conn.cursor() as cur:
        cur.execute(f"SELECT time, price, high FROM scrapdata WHERE date='{d}' AND stockname LIKE '%{s}%' AND time>='{d} 09:42:00' AND time<='{d} 14:47:00' ORDER BY time ASC")
        ticks = cur.fetchall()
    conn.close()
    if not ticks: return (y, 0)
    sell_price = float(ticks[0]['price'] or 0)
    if sell_price <= 0: return (y, 0)
    qty = int(1000000.0 / sell_price)
    sl_price = round(sell_price * 1.03, 2)
    buy_price = next((float(t['high'] or t['price'] or 0) for t in ticks if float(t['high'] or t['price'] or 0) >= sl_price), float(ticks[-1]['price'] or 0))
    p = ((sell_price - buy_price) * qty) - get_taxes(qty, sell_price, buy_price)
    return (y, p)

year_pnl = {2021:0, 2022:0, 2023:0, 2024:0, 2025:0, 2026:0}
with ThreadPoolExecutor(max_workers=30) as ex:
    for y, p in ex.map(audit_920, [r for _, r in top4_920.iterrows()]): year_pnl[y] += p
with ThreadPoolExecutor(max_workers=30) as ex:
    for y, p in ex.map(audit_942, [r for _, r in top4_942.iterrows()]): year_pnl[y] += p

for y in sorted(year_pnl.keys()):
    print(f"{y}: Rs {year_pnl[y]/100000.0:.2f} Lakhs")
