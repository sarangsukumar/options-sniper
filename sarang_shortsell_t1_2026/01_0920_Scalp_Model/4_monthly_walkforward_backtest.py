import os
import pandas as pd
import numpy as np
import yfinance as yf
import lightgbm as lgb
import warnings
from dateutil.relativedelta import relativedelta

warnings.filterwarnings('ignore')
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

print("1. Fetching Global Macro Data...")
data = yf.download(['^NSEI', '^GSPC', '^N225'], start='2018-01-01', end='2026-12-31', progress=False)
df_close = data['Close'].reset_index()
df_open  = data['Open'].reset_index()

dates = pd.date_range(start='2018-01-01', end='2026-12-31', freq='B')
mac = pd.DataFrame({'date': dates})
mac['date_str'] = mac['date'].dt.strftime('%Y-%m-%d')

mac = mac.merge(df_close[['Date', '^NSEI']].rename(columns={'Date': 'date', '^NSEI': 'nifty_close'}), on='date', how='left')
mac = mac.merge(df_open[['Date',  '^NSEI']].rename(columns={'Date': 'date', '^NSEI': 'nifty_open'}), on='date', how='left')
mac['nifty_gap'] = (mac['nifty_open'] / mac['nifty_close'].shift(1)) - 1

mac = mac.merge(df_close[['Date', '^GSPC']].rename(columns={'Date': 'date', '^GSPC': 'sp500_close'}), on='date', how='left')
mac['sp500_overnight_ret'] = mac['sp500_close'] / mac['sp500_close'].shift(1) - 1

mac = mac.merge(df_close[['Date', '^N225']].rename(columns={'Date': 'date', '^N225': 'nikkei_close'}), on='date', how='left')
mac = mac.merge(df_open[['Date',  '^N225']].rename(columns={'Date': 'date', '^N225': 'nikkei_open'}), on='date', how='left')
mac['nikkei_gap'] = mac['nikkei_open'] / mac['nikkei_close'].shift(1) - 1

mac['nifty_vs_sp500_gap'] = mac['nifty_gap'] - mac['sp500_overnight_ret']
mac['nifty_vs_nikkei_gap'] = mac['nifty_gap'] - mac['nikkei_gap']
mac = mac.fillna(0)

print("2. Loading Base Features...")
df = pd.read_csv(os.path.join(BASE_DIR, 'data/scalp_0920_ml_dataset.csv.gz'), low_memory=False)
df['date_obj'] = pd.to_datetime(df['short_date'])
df['year']     = df['date_obj'].dt.year
df = df.merge(mac[['date_str','nifty_gap','sp500_overnight_ret','nikkei_gap','nifty_vs_sp500_gap','nifty_vs_nikkei_gap']], left_on='short_date', right_on='date_str', how='left')
df['target'] = (df['pnl_net'] > 0).astype(int)

FEATURES = [
    'morn_range_pct', 'prev_intraday_vwap_gap', 'prev_intraday_roc_last_hour',
    'prev_intraday_return', 'positive_arc_ratio', 'Gap_Pct', 'gap_0907_pct',
    'rejection_wick', 'nifty_gap', 'sp500_overnight_ret', 'nikkei_gap',
    'nifty_vs_sp500_gap', 'nifty_vs_nikkei_gap'
]
df[FEATURES] = df[FEATURES].fillna(0)

PARAMS = {
    'objective': 'binary', 'metric': 'auc', 'learning_rate': 0.05,
    'max_depth': 5, 'num_leaves': 31, 'feature_fraction': 0.8,
    'verbose': -1, 'random_state': 42
}

print("3. Training: MONTHLY Retraining (Binary + Expanding Window + Decay)...")
all_oos = []

# Generate a list of all Month Starts
start_date = pd.to_datetime('2020-01-01')
end_date = pd.to_datetime(df['date_obj'].max())
months = pd.date_range(start=start_date, end=end_date, freq='MS')

for i, test_start in enumerate(months):
    test_end = test_start + relativedelta(months=1) - relativedelta(days=1)

    # Expanding window: use all data prior to the 1st of the month
    tr = df[df['date_obj'] < test_start].copy()
    te = df[(df['date_obj'] >= test_start) & (df['date_obj'] <= test_end)].copy()
    
    if len(tr) == 0 or len(te) == 0:
        continue

    # Exponential time-decay relative to the testing year
    current_year = test_start.year
    tr['weight'] = np.exp((tr['year'] - current_year) * 0.5)

    dtrain = lgb.Dataset(tr[FEATURES], label=tr['target'], weight=tr['weight'])
    mod = lgb.train(PARAMS, dtrain, num_boost_round=300)

    te['prob'] = mod.predict(te[FEATURES])
    all_oos.append(te)
    
    if i % 12 == 0:
        print(f"   [{i}/{len(months)}] Trained up to {test_start.date()}... ({(i/len(months))*100:.1f}%)")

oos = pd.concat(all_oos).sort_values(['short_date', 'prob'], ascending=[True, False])
top4 = oos.groupby('short_date').head(4).reset_index(drop=True)

out_file = os.path.join(BASE_DIR, '0920_monthly_predictions.csv')
top4[['short_date', 'clean_stock', 'prob']].to_csv(out_file, index=False)
print(f"\n✅ Success! Saved {len(top4)} predictions to {out_file}")
