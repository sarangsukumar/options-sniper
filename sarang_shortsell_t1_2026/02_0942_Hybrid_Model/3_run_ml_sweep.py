import os
import pandas as pd
import numpy as np
import lightgbm as lgb
from dateutil.relativedelta import relativedelta
import warnings

warnings.filterwarnings('ignore')
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 1. Load Data
df_942 = pd.read_csv(os.path.join(BASE_DIR, 'data/short_sell_ml_dataset_v5_scratch.csv.gz'), low_memory=False)
df_942['date_obj'] = pd.to_datetime(df_942['date_str'])
df_942['year'] = df_942['date_obj'].dt.year

import yfinance as yf
tickers = {'NIFTY': '^NSEI', 'SP500': '^GSPC', 'NIKKEI': '^N225'}
data = yf.download(list(tickers.values()), start='2018-01-01', end='2026-12-31', progress=False)
df_close = data['Close'].reset_index() if not isinstance(data.columns, pd.MultiIndex) else data['Close'].reset_index()
df_open = data['Open'].reset_index() if not isinstance(data.columns, pd.MultiIndex) else data['Open'].reset_index()
dates = pd.date_range(start='2018-01-01', end='2026-12-31', freq='B')
features = pd.DataFrame({'date': dates})
features['date_str'] = features['date'].dt.strftime('%Y-%m-%d')
nifty_c = df_close[['Date', '^NSEI']].rename(columns={'Date': 'date', '^NSEI': 'nifty_close'})
nifty_o = df_open[['Date', '^NSEI']].rename(columns={'Date': 'date', '^NSEI': 'nifty_open'})
features = features.merge(nifty_c, on='date', how='left').merge(nifty_o, on='date', how='left')
features['nifty_gap'] = (features['nifty_open'] / features['nifty_close'].shift(1)) - 1
sp_c = df_close[['Date', '^GSPC']].rename(columns={'Date': 'date', '^GSPC': 'sp500_close'})
nik_c = df_close[['Date', '^N225']].rename(columns={'Date': 'date', '^N225': 'nikkei_close'})
features = features.merge(sp_c, on='date', how='left').merge(nik_c, on='date', how='left')
features['sp500_overnight_ret'] = features['sp500_close'] / features['sp500_close'].shift(1) - 1
features['nikkei_gap'] = features['nikkei_close'] / features['nikkei_close'].shift(1) - 1
features['nifty_vs_sp500_gap'] = features['nifty_gap'] - features['sp500_overnight_ret']
features['nifty_vs_nikkei_gap'] = features['nifty_gap'] - features['nikkei_gap']
features = features.fillna(0)

df_942 = df_942.merge(features, on='date_str', how='left')
df_942['target'] = (df_942['short_exit_price'] - df_942['short_entry_price']) / df_942['short_entry_price'] * -100
df_942['target_bin'] = (df_942['target'] > 0.5).astype(int)

features_942 = [
    'gap_abs', 'vol_gap_combo', 'stock_ret_940', 'morn_range_pct', 'rejection_wick', 
    'gap_0907_pct', 'gap_fade_0907_to_940_pct', 'prev_intraday_return', 'prev_intraday_vwap_gap',
    'morning_momentum', 'morning_vol_trend', 'nifty_gap', 'sp500_overnight_ret', 
    'nikkei_gap', 'nifty_vs_sp500_gap', 'nifty_vs_nikkei_gap'
]
df_942[features_942] = df_942[features_942].fillna(0)

# EXPERIMENT A: Huber Loss + Time Decay Weights
def run_exp_A():
    all_oos = []
    p = {'objective': 'huber', 'learning_rate': 0.05, 'max_depth': 4, 'verbose': -1, 'random_state': 42}
    for y in range(2020, 2027):
        test_s = pd.to_datetime(f"{y}-01-01")
        tr_s = test_s - relativedelta(years=4)
        tr = df_942[(df_942['date_obj'] >= tr_s) & (df_942['date_obj'] < test_s)].copy()
        te = df_942[df_942['year'] == y].copy()
        if len(tr)==0 or len(te)==0: continue
        
        tr['weight'] = np.exp((tr['year'] - y) * 0.5) # Time decay
        dtrain = lgb.Dataset(tr[features_942], label=tr['target'], weight=tr['weight'])
        mod = lgb.train(p, dtrain, num_boost_round=100)
        te['pred'] = mod.predict(te[features_942])
        all_oos.append(te)
    top4 = pd.concat(all_oos).sort_values(['date_str', 'pred'], ascending=[True, False]).groupby('date_str').head(4)
    top4[['date_str', 'clean_stock', 'pred']].to_csv('preds_A.csv', index=False)

# EXPERIMENT B: Binary Classification (Probability Ranking)
def run_exp_B():
    all_oos = []
    p = {'objective': 'binary', 'metric': 'auc', 'learning_rate': 0.05, 'max_depth': 4, 'verbose': -1, 'random_state': 42}
    for y in range(2020, 2027):
        test_s = pd.to_datetime(f"{y}-01-01")
        tr_s = test_s - relativedelta(years=4)
        tr = df_942[(df_942['date_obj'] >= tr_s) & (df_942['date_obj'] < test_s)]
        te = df_942[df_942['year'] == y].copy()
        if len(tr)==0 or len(te)==0: continue
        
        dtrain = lgb.Dataset(tr[features_942], label=tr['target_bin'])
        mod = lgb.train(p, dtrain, num_boost_round=100)
        te['pred'] = mod.predict(te[features_942])
        all_oos.append(te)
    top4 = pd.concat(all_oos).sort_values(['date_str', 'pred'], ascending=[True, False]).groupby('date_str').head(4)
    top4[['date_str', 'clean_stock', 'pred']].to_csv('preds_B.csv', index=False)

# EXPERIMENT C: Heavy L1 Regularization
def run_exp_C():
    all_oos = []
    p = {'objective': 'regression', 'reg_alpha': 2.0, 'learning_rate': 0.05, 'max_depth': 3, 'verbose': -1, 'random_state': 42}
    for y in range(2020, 2027):
        test_s = pd.to_datetime(f"{y}-01-01")
        tr_s = test_s - relativedelta(years=4)
        tr = df_942[(df_942['date_obj'] >= tr_s) & (df_942['date_obj'] < test_s)]
        te = df_942[df_942['year'] == y].copy()
        if len(tr)==0 or len(te)==0: continue
        
        dtrain = lgb.Dataset(tr[features_942], label=tr['target'])
        mod = lgb.train(p, dtrain, num_boost_round=100)
        te['pred'] = mod.predict(te[features_942])
        all_oos.append(te)
    top4 = pd.concat(all_oos).sort_values(['date_str', 'pred'], ascending=[True, False]).groupby('date_str').head(4)
    top4[['date_str', 'clean_stock', 'pred']].to_csv('preds_C.csv', index=False)

print("Running Exp A...")
run_exp_A()
print("Running Exp B...")
run_exp_B()
print("Running Exp C...")
run_exp_C()
print("Done!")
