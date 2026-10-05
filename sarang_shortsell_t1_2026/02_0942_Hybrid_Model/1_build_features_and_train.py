import os
import pandas as pd
import numpy as np
import lightgbm as lgb
from dateutil.relativedelta import relativedelta
import warnings
warnings.filterwarnings('ignore')

BASE_DIR = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_shortsell_t1_2026/02_0942_Hybrid_Model'

print("1. Loading 100% Pure EQ Dataset...")
df = pd.read_csv(os.path.join(BASE_DIR, 'data/short_sell_ml_dataset_v5_scratch.csv.gz'), low_memory=False)

df['date_obj'] = pd.to_datetime(df['date_str'])
df['year']     = df['date_obj'].dt.year

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

print("2. Training PURE EQ Huber Walk-Forward Model...")
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
    print(f"   ✔ {y}: trained on {len(tr)} rows | {len(te)} test samples")

oos = pd.concat(all_oos).sort_values(['date_str', 'pred'], ascending=[True, False])
top4 = oos.groupby('date_str').head(4).reset_index(drop=True)

out_file = os.path.join(BASE_DIR, '0942_predictions.csv')
top4[['date_str', 'clean_stock', 'pred']].to_csv(out_file, index=False)
print(f"✅ Success! Saved {len(top4)} predictions to {out_file}")
