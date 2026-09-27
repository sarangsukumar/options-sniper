import os
import pandas as pd
import lightgbm as lgb
import warnings
import numpy as np
import yfinance as yf
from dateutil.relativedelta import relativedelta

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
df = pd.read_csv(os.path.join(BASE_DIR, 'data/scalp_0925_ml_dataset.csv.gz'))
df['year'] = pd.to_datetime(df['short_date']).dt.year
df = df.merge(global_macro, left_on='short_date', right_on='date_str', how='left')

FEATURES = [
    'morn_range_pct', 'prev_intraday_vwap_gap', 'prev_intraday_roc_last_hour',
    'prev_intraday_return', 'positive_arc_ratio', 'Gap_Pct', 'gap_0907_pct',
    'rejection_wick', 'nifty_gap', 'sp500_overnight_ret', 'nikkei_gap',
    'nifty_vs_sp500_gap', 'nifty_vs_nikkei_gap'
]

df[FEATURES] = df[FEATURES].fillna(0)
df['target'] = (df['pnl_net'] > 0).astype(int)
df['date_obj'] = pd.to_datetime(df['short_date'])

PARAMS = {
    'objective': 'binary',
    'metric': 'auc',
    'boosting_type': 'gbdt',
    'learning_rate': 0.05,
    'max_depth': 5,
    'num_leaves': 31,
    'feature_fraction': 0.8,
    'verbose': -1,
    'random_state': 42
}

print("3. Training Monthly Walk-Forward Model (09:23 Extended Features)...")
all_oos = []
start_date = pd.to_datetime('2020-01-01')
end_date = pd.to_datetime(df['date_obj'].max())
months = pd.date_range(start=start_date, end=end_date, freq='MS')

for i, test_start in enumerate(months):
    test_end = test_start + relativedelta(months=1) - relativedelta(days=1)
    
    tr = df[df['date_obj'] < test_start].copy()
    te = df[(df['date_obj'] >= test_start) & (df['date_obj'] <= test_end)].copy()
    if len(tr) == 0 or len(te) == 0: continue
    
    current_year = test_start.year
    tr['weight'] = np.exp((tr['year'] - current_year) * 0.5)
    
    mod = lgb.train(
        PARAMS,
        lgb.Dataset(tr[FEATURES], label=tr['target'], weight=tr['weight']),
        num_boost_round=300
    )
    te['prob'] = mod.predict(te[FEATURES])
    all_oos.append(te)

oos = pd.concat(all_oos).sort_values(['short_date', 'prob'], ascending=[True, False])
top4 = oos.groupby('short_date').head(4).reset_index(drop=True)

out_file = os.path.join(BASE_DIR, '0925_predictions.csv')
top4[['short_date', 'clean_stock', 'prob', 'pnl_net']].to_csv(out_file, index=False)
print(f"✅ Success! Predictions saved to {out_file}")

print("\n==========================================================")
print(" 🏆 NEW 09:23 EXTENDED MODEL (09:25 ENTRY PNL)")
print("==========================================================")
for y in sorted(top4['year'].unique()):
    sub = top4[top4['year'] == y]
    print(f"  {y}: Rs {sub['pnl_net'].sum()/100000:6.2f} L | {(sub['pnl_net']>0).mean()*100:.1f}% Win | {len(sub)} trades")
print("----------------------------------------------------------")
print(f"  TOTAL: Rs {top4['pnl_net'].sum()/100000:.2f} Lakhs")
print("==========================================================")
