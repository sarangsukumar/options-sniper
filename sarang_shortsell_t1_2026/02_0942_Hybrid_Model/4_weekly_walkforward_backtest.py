import os
import pandas as pd
import numpy as np
import yfinance as yf
import lightgbm as lgb
import warnings
from dateutil.relativedelta import relativedelta
from datetime import timedelta

warnings.filterwarnings('ignore')
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

print("1. Fetching Global Macro Data...")
data = yf.download(['^NSEI', '^GSPC', '^N225'], start='2018-01-01', end='2026-12-31', progress=False)
df_close = data['Close'].reset_index()
df_open  = data['Open'].reset_index()

dates = pd.date_range(start='2018-01-01', end='2026-12-31', freq='B')
features = pd.DataFrame({'date': dates})
features['date_str'] = features['date'].dt.strftime('%Y-%m-%d')

features = features.merge(df_close[['Date', '^NSEI']].rename(columns={'Date': 'date', '^NSEI': 'nifty_close'}), on='date', how='left')
features = features.merge(df_open[['Date',  '^NSEI']].rename(columns={'Date': 'date', '^NSEI': 'nifty_open'}), on='date', how='left')
features['nifty_gap'] = (features['nifty_open'] / features['nifty_close'].shift(1)) - 1

features = features.merge(df_close[['Date', '^GSPC']].rename(columns={'Date': 'date', '^GSPC': 'sp500_close'}), on='date', how='left')
features['sp500_overnight_ret'] = features['sp500_close'] / features['sp500_close'].shift(1) - 1

features = features.merge(df_close[['Date', '^N225']].rename(columns={'Date': 'date', '^N225': 'nikkei_close'}), on='date', how='left')
features = features.merge(df_open[['Date',  '^N225']].rename(columns={'Date': 'date', '^N225': 'nikkei_open'}), on='date', how='left')
features['nikkei_gap'] = features['nikkei_open'] / features['nikkei_close'].shift(1) - 1

features['nifty_vs_sp500_gap'] = features['nifty_gap'] - features['sp500_overnight_ret']
features['nifty_vs_nikkei_gap'] = features['nifty_gap'] - features['nikkei_gap']
features = features.fillna(0)

print("2. Loading Base Features...")
df = pd.read_csv(os.path.join(BASE_DIR, 'data/short_sell_ml_dataset_v5_scratch.csv.gz'), low_memory=False)
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
    'objective': 'huber', 'alpha': 0.9, 'learning_rate': 0.05,
    'max_depth': 4, 'num_leaves': 15, 'feature_fraction': 0.8,
    'verbose': -1, 'random_state': 42, 'n_jobs': -1
}

print("3. Training: WEEKLY Retraining (Huber + 4-Yr Rolling + Decay)...")
all_oos = []

# Generate a list of all Mondays from Jan 2020 to Sep 2026
start_date = pd.to_datetime('2020-01-01')
end_date = pd.to_datetime(df['date_obj'].max())
weeks = pd.date_range(start=start_date, end=end_date, freq='W-MON')

for i, test_start in enumerate(weeks):
    test_end = test_start + timedelta(days=6) # Sunday
    train_start = test_start - relativedelta(years=4)

    tr = df[(df['date_obj'] >= train_start) & (df['date_obj'] < test_start)].copy()
    te = df[(df['date_obj'] >= test_start) & (df['date_obj'] <= test_end)].copy()
    
    if len(tr) == 0 or len(te) == 0:
        continue

    # Exponential time-decay relative to the testing year
    current_year = test_start.year
    tr['weight'] = np.exp((tr['year'] - current_year) * 0.5)

    dtrain = lgb.Dataset(tr[FEATURES], label=tr['target'], weight=tr['weight'])
    mod = lgb.train(PARAMS, dtrain, num_boost_round=100)

    te['pred'] = mod.predict(te[FEATURES])
    all_oos.append(te)
    
    if i % 50 == 0:
        print(f"   [{i}/{len(weeks)}] Trained up to {test_start.date()}... ({(i/len(weeks))*100:.1f}%)")

oos = pd.concat(all_oos).sort_values(['date_str', 'pred'], ascending=[True, False])
top4 = oos.groupby('date_str').head(4).reset_index(drop=True)

out_file = os.path.join(BASE_DIR, '0942_weekly_predictions.csv')
top4[['date_str', 'clean_stock', 'pred']].to_csv(out_file, index=False)
print(f"\n✅ Success! Saved {len(top4)} predictions to {out_file}")
