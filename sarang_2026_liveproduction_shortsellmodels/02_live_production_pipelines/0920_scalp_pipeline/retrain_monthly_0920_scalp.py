import os, pickle
import pandas as pd
import yfinance as yf
import lightgbm as lgb
import warnings

warnings.filterwarnings('ignore')

DIR = os.path.dirname(os.path.abspath(__file__))
DATASET_PATH = os.path.join(DIR, 'data/scalp_0920_ml_dataset.csv.gz')
MODEL_OUTPUT_PATH = os.path.join(DIR, 'lgb_0920_scalp_model.txt')

print("======================================================================")
print("  HALF-YEARLY RETRAINING ENGINE: 09:20 SCALP V1 MODEL (JAN 1 & JUL 1)")
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
df, df_lots = pd.read_csv(DATASET_PATH), pd.read_csv(os.path.join(DIR, 'data/historical_lotsize_new.csv'), low_memory=False)
# [UPDATE 1] Filter training data to Point-in-Time Active F&O universe
df_lots['ym'], df['ym'] = pd.to_datetime(df_lots['expdate'], format='%d/%m/%Y', errors='coerce').dt.to_period('M'), pd.to_datetime(df['short_date']).dt.to_period('M')
active_by_ym = {ym: (set(df_lots[(df_lots['ym'] >= ym) & (df_lots['ym'] <= ym + 2)]['stockname'].str.strip().str.upper()) or set(df_lots[df_lots['ym'] >= df_lots['ym'].max() - 1]['stockname'].str.strip().str.upper())) for ym in df['ym'].unique()}
df = df[[st.strip().upper() in active_by_ym.get(ym, set()) for st, ym in zip(df['clean_stock'], df['ym'])]].copy()
df['short_ret'] = (((df['entry_price'] - df['exit_price']) / df['entry_price']) * 100.0).fillna(((df['pnl_net'] / 1000000.0) + 0.0004) * 100.0).fillna(0.0)
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

# Step 3: Train Half-Yearly Expanding Window production model & save model binary
now = pd.Timestamp.now()
hy_cutoff = f"{now.year}-07-01" if now.month >= 7 else f"{now.year}-01-01"
df_train = df[df['short_date'] < hy_cutoff].copy()
if len(df_train) == 0:
    df_train = df.copy()

print(f"3. Retraining Half-Yearly Model on {len(df_train):,} Historical Samples (short_date < {hy_cutoff}, min={df_train['short_date'].min()}, max={df_train['short_date'].max()})...")
train_data = lgb.Dataset(df_train[features_920], label=df_train['target'])
model = lgb.train(params_920, train_data, num_boost_round=300)

model.save_model(MODEL_OUTPUT_PATH)
# [UPDATE 2] Train & save 4-Checkpoint Multi-Temporal Regression Ensemble (day, week, month, year)
tr_d, p_nb = sorted(df_train['short_date'].unique()), {**params_920, 'objective': 'regression', 'metric': 'rmse', 'learning_rate': 0.08}
pickle.dump({k: lgb.train(p_nb, lgb.Dataset(df_train[df_train['short_date'] <= cd][features_920], label=df_train[df_train['short_date'] <= cd]['short_ret']), num_boost_round=60) for k, cd in {'day': tr_d[-1], 'week': tr_d[max(0, len(tr_d)-5)], 'month': tr_d[max(0, len(tr_d)-21)], 'year': tr_d[max(0, len(tr_d)-126)]}.items()}, open(os.path.join(DIR, 'lgb_0920_ens_checkpoints.pkl'), 'wb'))
# [UPDATE 3] Daily Evening Rolling 4-Frequency Ensemble (day, week, month + half-yearly year anchor) + Downside Sortino Weighting (w=1.5 on losses)
import numpy as np
ens_cut = (pd.Timestamp.now(tz='Asia/Kolkata') + pd.Timedelta(days=1 if pd.Timestamp.now(tz='Asia/Kolkata').hour >= 10 else 0)).strftime('%Y-%m-%d')
df_ens, tr_d = df[df['short_date'] < ens_cut], sorted(df[df['short_date'] < ens_cut]['short_date'].unique())
pickle.dump({k: lgb.train(p_nb, lgb.Dataset(df_ens[df_ens['short_date'] <= cd][features_920], label=df_ens[df_ens['short_date'] <= cd]['short_ret'], weight=np.where(df_ens[df_ens['short_date'] <= cd]['short_ret'] < 0, 1.5, 1.0)), num_boost_round=60) for k, cd in {'day': tr_d[-1], 'week': tr_d[max(0, len(tr_d)-5)], 'month': ([d for d in tr_d if d < ens_cut[:8] + '01'] or tr_d)[-1], 'year': df_train['short_date'].max()}.items()}, open(os.path.join(DIR, 'lgb_0920_ens_checkpoints.pkl'), 'wb'))
print(f"✅ Success! Half-Yearly Retrained model (< {hy_cutoff}) saved to: {MODEL_OUTPUT_PATH}")
print("======================================================================")
