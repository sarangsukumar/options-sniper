import os
import pandas as pd
import numpy as np
import yfinance as yf
import lightgbm as lgb
from dateutil.relativedelta import relativedelta
import warnings
warnings.filterwarnings('ignore')

BASE_DIR = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_shortsell_t1_2026/02_0942_Hybrid_Model'

print("1. Fetching Global Macro Data (Yahoo Finance)...")
tickers = {'NIFTY': '^NSEI', 'SP500': '^GSPC', 'NIKKEI': '^N225'}
data = yf.download(list(tickers.values()), start='2018-01-01', end='2026-12-31', progress=False)

if isinstance(data.columns, pd.MultiIndex):
    df_close = data['Close'].reset_index()
    df_open  = data['Open'].reset_index()
else:
    df_close = pd.DataFrame(data['Close']).reset_index()
    df_open  = pd.DataFrame(data['Open']).reset_index()

dates = pd.date_range(start='2018-01-01', end='2026-12-31', freq='B')
features = pd.DataFrame({'date': dates})
features['date_str'] = features['date'].dt.strftime('%Y-%m-%d')

nifty_c = df_close[['Date', '^NSEI']].rename(columns={'Date': 'date', '^NSEI': 'nifty_close'})
nifty_o = df_open[['Date',  '^NSEI']].rename(columns={'Date': 'date', '^NSEI': 'nifty_open'})
features = features.merge(nifty_c, on='date', how='left').merge(nifty_o, on='date', how='left')
features['nifty_gap'] = (features['nifty_open'] / features['nifty_close'].shift(1)) - 1

sp_c  = df_close[['Date', '^GSPC']].rename(columns={'Date': 'date', '^GSPC': 'sp500_close'})
nik_c = df_close[['Date', '^N225']].rename(columns={'Date': 'date', '^N225': 'nikkei_close'})
nik_o = df_open[['Date',  '^N225']].rename(columns={'Date': 'date', '^N225': 'nikkei_open'})
features = features.merge(sp_c, on='date', how='left').merge(nik_c, on='date', how='left').merge(nik_o, on='date', how='left')
features['sp500_overnight_ret'] = features['sp500_close'] / features['sp500_close'].shift(1) - 1
features['nikkei_gap']          = features['nikkei_open'] / features['nikkei_close'].shift(1) - 1
features['nifty_vs_sp500_gap']  = features['nifty_gap'] - features['sp500_overnight_ret']
features['nifty_vs_nikkei_gap'] = features['nifty_gap'] - features['nikkei_gap']
features = features.fillna(0)

print("2. Loading Historical Base Features and PURGING F1 DATA...")
df = pd.read_csv(os.path.join(BASE_DIR, 'data/short_sell_ml_dataset_v5_scratch.csv.gz'), low_memory=False)

# PURGE F1 DATA CONTAMINATION:
df['price_0907_eq'] = pd.to_numeric(df['price_0907_eq'], errors='coerce')
df['prev_close'] = pd.to_numeric(df['prev_close'], errors='coerce')
df['morning_close'] = pd.to_numeric(df['morning_close'], errors='coerce')
df['Gap_Pct'] = pd.to_numeric(df['Gap_Pct'], errors='coerce').fillna(0.0)

# Re-engineer gap_0907_pct purely on EQ:
df['gap_0907_pct'] = np.where(
    df['price_0907_eq'].notna() & df['prev_close'].notna() & (df['prev_close'] > 0),
    ((df['price_0907_eq'] - df['prev_close']) / df['prev_close']) * 100.0,
    df['Gap_Pct']
)

# Re-engineer gap_fade_0907_to_940_pct purely on EQ:
df['gap_fade_0907_to_940_pct'] = np.where(
    df['price_0907_eq'].notna() & (df['price_0907_eq'] > 0) & df['morning_close'].notna(),
    ((df['morning_close'] - df['price_0907_eq']) / df['price_0907_eq']) * 100.0,
    0.0
)

df['date_obj'] = pd.to_datetime(df['date_str'])
df['year']     = df['date_obj'].dt.year
df = df.merge(features, on='date_str', how='left')

df['target'] = (df['short_exit_price'] - df['short_entry_price']) / df['short_entry_price'] * -100

FEATURES = [
    'gap_abs', 'vol_gap_combo', 'stock_ret_940', 'morn_range_pct', 'rejection_wick',
    'gap_0907_pct', 'gap_fade_0907_to_940_pct', 'prev_intraday_return', 'prev_intraday_vwap_gap',
    'morning_momentum', 'morning_vol_trend', 'nifty_gap', 'sp500_overnight_ret',
    'nikkei_gap', 'nifty_vs_sp500_gap', 'nifty_vs_nikkei_gap'
]
df[FEATURES] = df[FEATURES].fillna(0)

PARAMS = {
    'objective':        'huber',
    'alpha':             0.9,
    'learning_rate':     0.05,
    'max_depth':         4,
    'num_leaves':        15,
    'feature_fraction':  0.8,
    'verbose':          -1,
    'random_state':      42,
    'n_jobs':           -1
}

print("3. Training PURE EQ Huber Model...")
all_oos = []
for y in range(2020, 2027):
    test_start  = pd.to_datetime(f"{y}-01-01")
    train_start = test_start - relativedelta(years=4)

    tr = df[(df['date_obj'] >= train_start) & (df['date_obj'] < test_start)].copy()
    te = df[df['year'] == y].copy()
    if len(tr) == 0 or len(te) == 0:
        continue

    tr['weight'] = np.exp((tr['year'] - y) * 0.5)

    dtrain = lgb.Dataset(tr[FEATURES], label=tr['target'], weight=tr['weight'])
    mod = lgb.train(PARAMS, dtrain, num_boost_round=100)

    te['pred'] = mod.predict(te[FEATURES])
    all_oos.append(te)
    print(f"   ✔ {y}: trained on {train_start.date()} | {len(te)} test samples")

oos = pd.concat(all_oos).sort_values(['date_str', 'pred'], ascending=[True, False])
top4 = oos.groupby('date_str').head(4).reset_index(drop=True)

out_file = os.path.join(BASE_DIR, '0942_predictions.csv')
top4[['date_str', 'clean_stock', 'pred']].to_csv(out_file, index=False)
print(f"✅ Success! Saved {len(top4)} predictions to {out_file}")
