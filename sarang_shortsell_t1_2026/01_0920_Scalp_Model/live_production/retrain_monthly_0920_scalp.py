import os
import pandas as pd
import yfinance as yf
import lightgbm as lgb
import warnings

warnings.filterwarnings('ignore')

DIR = os.path.dirname(os.path.abspath(__file__))
DATASET_PATH = os.path.join(DIR, 'data/scalp_0920_ml_dataset.csv.gz')
MODEL_OUTPUT_PATH = os.path.join(DIR, 'lgb_0920_scalp_model.txt')

print("======================================================================")
print("  MONTHLY RETRAINING ENGINE: 09:20 SCALP V1 MODEL")
print("======================================================================")

# Step 1: Fetch macro features
print("1. Fetching Global Macro Data (Yahoo Finance)...")
tickers = {'NIFTY': '^NSEI', 'SP500': '^GSPC', 'NIKKEI': '^N225'}
data = yf.download(list(tickers.values()), start='2018-01-01', progress=False)

if isinstance(data.columns, pd.MultiIndex):
    df_close = data['Close'].reset_index()
    df_open = data['Open'].reset_index()
else:
    df_close = pd.DataFrame(data['Close'], columns=['^NSEI']).reset_index()
    df_open = pd.DataFrame(data['Open'], columns=['^NSEI']).reset_index()

dates = pd.date_range(start='2018-01-01', end=pd.Timestamp.now() + pd.Timedelta(days=30), freq='B')
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

# Step 2: Load historical base features
print("2. Loading Historical Base Dataset...")
df = pd.read_csv(DATASET_PATH)
df = df.merge(global_macro, left_on='short_date', right_on='date_str', how='left')

features_920 = [
    'morn_range_pct', 'prev_intraday_vwap_gap', 'prev_intraday_roc_last_hour',
    'prev_intraday_return', 'positive_arc_ratio', 'Gap_Pct', 'gap_0907_pct',
    'rejection_wick', 'nifty_gap', 'sp500_overnight_ret', 'nikkei_gap',
    'nifty_vs_sp500_gap', 'nifty_vs_nikkei_gap'
]

df[features_920] = df[features_920].fillna(0)
df['target'] = (df['pnl_net'] > 0).astype(int)

params_920 = {
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

# Step 3: Train full production model & save model binary
print(f"3. Retraining Full Model on {len(df)} Historical Samples...")
train_data = lgb.Dataset(df[features_920], label=df['target'])
model = lgb.train(params_920, train_data, num_boost_round=300)

model.save_model(MODEL_OUTPUT_PATH)
print(f"✅ Success! Retrained model saved to: {MODEL_OUTPUT_PATH}")
print("======================================================================")
