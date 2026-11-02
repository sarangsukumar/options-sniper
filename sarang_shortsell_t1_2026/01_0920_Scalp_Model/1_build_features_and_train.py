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
df_920 = pd.read_csv(os.path.join(BASE_DIR, 'data/scalp_0920_ml_dataset.csv.gz'))
df_920['year'] = pd.to_datetime(df_920['short_date']).dt.year
df_920 = df_920.merge(global_macro, left_on='short_date', right_on='date_str', how='left')

features_920 = [
    'morn_range_pct', 'prev_intraday_vwap_gap', 'prev_intraday_roc_last_hour',
    'prev_intraday_return', 'positive_arc_ratio', 'Gap_Pct', 'gap_0907_pct',
    'rejection_wick', 'nifty_gap', 'sp500_overnight_ret', 'nikkei_gap',
    'nifty_vs_sp500_gap', 'nifty_vs_nikkei_gap'
]

df_920[features_920] = df_920[features_920].fillna(0)
df_920['target'] = (df_920['pnl_net'] > 0).astype(int)

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

print("3. Training Half-Yearly (6M) Walk-Forward Expanding Window Model (Jan 1 & Jul 1)...")
all_oos_920 = []
latest_mod = None
latest_cutoff = None

for y in range(2020, 2028):
    for h, (start_d, end_d) in enumerate([
        (f"{y}-01-01", f"{y}-06-30"),
        (f"{y}-07-01", f"{y}-12-31")
    ], start=1):
        tr = df_920[df_920['short_date'] < start_d]
        te = df_920[(df_920['short_date'] >= start_d) & (df_920['short_date'] <= end_d)].copy()
        if len(tr) == 0 or len(te) == 0:
            continue

        print(f"   • {y}-H{h} ({start_d} to {end_d}): Training on {len(tr):,} rows (< {start_d}) -> Predicting {len(te):,} rows")
        mod = lgb.train(
            params_920,
            lgb.Dataset(tr[features_920], label=tr['target']),
            num_boost_round=300
        )
        te['prob'] = mod.predict(te[features_920])
        all_oos_920.append(te)
        latest_mod = mod
        latest_cutoff = start_d

oos_920 = pd.concat(all_oos_920).sort_values(['short_date', 'prob'], ascending=[True, False])
top4_920 = oos_920.groupby('short_date').head(4).reset_index(drop=True)

out_file = os.path.join(BASE_DIR, '0920_predictions.csv')
top4_920[['short_date', 'clean_stock', 'prob']].to_csv(out_file, index=False)
print(f"✅ Success! Half-Yearly OOS Predictions saved to {out_file} ({len(top4_920):,} top-4 trades)")

if latest_mod is not None:
    live_model_path = os.path.join(BASE_DIR, 'live_production', 'lgb_0920_scalp_model.txt')
    latest_mod.save_model(live_model_path)
    print(f"✅ Active Half-Yearly Production Model (trained < {latest_cutoff}) saved to {live_model_path}")
