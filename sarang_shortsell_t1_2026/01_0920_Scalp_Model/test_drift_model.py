import os
import pandas as pd
import yfinance as yf
import lightgbm as lgb
import warnings
import numpy as np
from datetime import timedelta
warnings.filterwarnings('ignore')
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

print("Loading Global Macro Data...")
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


print("Loading Dataset with new Drift feature...")
df = pd.read_csv(os.path.join(BASE_DIR, 'data/scalp_0920_ml_dataset_with_drift.csv.gz'), low_memory=False)
df['date_obj'] = pd.to_datetime(df['short_date'])
df['year'] = df['date_obj'].dt.year
df['target'] = (df['pnl_net'] > 0).astype(int)

df = df.merge(global_macro, left_on='short_date', right_on='date_str', how='left')


FEATURES = [
    'morn_range_pct', 'prev_intraday_vwap_gap', 'prev_intraday_roc_last_hour',
    'prev_intraday_return', 'positive_arc_ratio', 'Gap_Pct', 'gap_0907_pct',
    'rejection_wick', 'nifty_gap', 'sp500_overnight_ret', 'nikkei_gap',
    'nifty_vs_sp500_gap', 'nifty_vs_nikkei_gap',
    'drift_0919_to_0923_pct' # The new feature!
]
df[FEATURES] = df[FEATURES].fillna(0)

PARAMS = {
    'objective': 'binary', 'metric': 'auc', 'learning_rate': 0.05,
    'max_depth': 5, 'num_leaves': 31, 'feature_fraction': 0.8,
    'verbose': -1, 'random_state': 42
}

print("Training Monthly Walk-Forward with Drift...")
all_oos = []
start_date = pd.to_datetime('2020-01-01')
end_date = pd.to_datetime(df['date_obj'].max())
months = pd.date_range(start=start_date, end=end_date, freq='MS')

from dateutil.relativedelta import relativedelta
for i, test_start in enumerate(months):
    test_end = test_start + relativedelta(months=1) - relativedelta(days=1)

    tr = df[df['date_obj'] < test_start].copy()
    te = df[(df['date_obj'] >= test_start) & (df['date_obj'] <= test_end)].copy()
    if len(tr) == 0 or len(te) == 0: continue

    current_year = test_start.year
    tr['weight'] = np.exp((tr['year'] - current_year) * 0.5)

    dtrain = lgb.Dataset(tr[FEATURES], label=tr['target'], weight=tr['weight'])
    mod = lgb.train(PARAMS, dtrain, num_boost_round=300)

    te['prob'] = mod.predict(te[FEATURES])
    all_oos.append(te)

oos = pd.concat(all_oos).sort_values(['short_date', 'prob'], ascending=[True, False])
top4 = oos.groupby('short_date').head(4).reset_index(drop=True)

out_file = os.path.join(BASE_DIR, '0920_drift_predictions.csv')
top4[['short_date', 'clean_stock', 'prob']].to_csv(out_file, index=False)
print(f"Predictions saved to {out_file}")
