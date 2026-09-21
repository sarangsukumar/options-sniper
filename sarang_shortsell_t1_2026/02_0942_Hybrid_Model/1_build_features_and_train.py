import os
import pandas as pd
import yfinance as yf
import lightgbm as lgb
import warnings

warnings.filterwarnings('ignore')
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

print("1. Fetching Global Macro Data (Yahoo Finance)...")
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

for c in ['sp500_overnight_ret', 'nikkei_gap', 'nifty_gap']: 
    features[c] = features[c].fillna(0)

features['nifty_vs_sp500_gap'] = features['nifty_gap'] - features['sp500_overnight_ret']
features['nifty_vs_nikkei_gap'] = features['nifty_gap'] - features['nikkei_gap']

global_macro = features[['date_str', 'nifty_gap', 'sp500_overnight_ret', 'nikkei_gap', 'nifty_vs_sp500_gap', 'nifty_vs_nikkei_gap']]

print("2. Loading Historical Base Features...")
df_942 = pd.read_csv(os.path.join(BASE_DIR, 'data/short_sell_ml_dataset_v5_scratch.csv'), low_memory=False)
df_942['clean_stock'] = df_942['clean_stock'].astype(str).str.strip().str.upper()
df_942['year'] = pd.to_datetime(df_942['date_str']).dt.year
df_942 = df_942.merge(global_macro, on='date_str', how='left')

features_942 = [
    'gap_0907_pct', 'gap_fade_0907_to_940_pct', 'prev_intraday_vwap_gap',
    'prev_intraday_return', 'prev_intraday_roc_last_hour', 'morn_range_pct',
    'rejection_wick', 'prev_1450_to_1519_pct', 'Gap_Pct', 'nifty_gap',
    'sp500_overnight_ret', 'nikkei_gap', 'nifty_vs_sp500_gap', 'nifty_vs_nikkei_gap'
]

df_942[features_942] = df_942[features_942].apply(pd.to_numeric, errors='coerce').fillna(0)
df_942['target'] = df_942['short_pct_return']

params_942 = {
    'objective': 'regression',
    'metric': 'rmse',
    'boosting_type': 'gbdt',
    'learning_rate': 0.05,
    'max_depth': 5,
    'num_leaves': 31,
    'verbose': -1,
    'random_state': 42
}

print("3. Training Walk-Forward Expanding Window Model...")
all_oos_942 = []
for y in range(2021, 2027):
    tr = df_942[df_942['year'] < y]
    te = df_942[df_942['year'] == y].copy()
    if len(tr) == 0 or len(te) == 0: continue
    
    mod = lgb.train(
        params_942,
        lgb.Dataset(tr[features_942], label=tr['target']),
        num_boost_round=100
    )
    te['pred'] = mod.predict(te[features_942])
    all_oos_942.append(te)

oos_942 = pd.concat(all_oos_942).sort_values(['date_str', 'pred'], ascending=[True, False])
top4_942 = oos_942.groupby('date_str').head(4).reset_index(drop=True)

out_file = os.path.join(BASE_DIR, '0942_predictions.csv')
top4_942[['date_str', 'clean_stock', 'pred']].to_csv(out_file, index=False)
print(f"✅ Success! Predictions saved to {out_file}")
