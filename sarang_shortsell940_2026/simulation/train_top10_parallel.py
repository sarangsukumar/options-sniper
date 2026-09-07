import pandas as pd
import numpy as np
import lightgbm as lgb
import os
import multiprocessing
import warnings

warnings.filterwarnings('ignore')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
OUTPUT_DIR = os.path.join(BASE_DIR, 'output')

print("Loading datasets...")
df_path = os.path.join(OUTPUT_DIR, 'short_sell_ml_dataset_v2.csv')
df = pd.read_csv(df_path, low_memory=False)
df['short_sell_date'] = pd.to_datetime(df['short_sell_date'], format='mixed')
df['year'] = df['short_sell_date'].dt.year
df['month'] = df['short_sell_date'].dt.month
df['day_of_week'] = df['short_sell_date'].dt.day_name()

df = df[df['day_of_week'] != 'Monday']
df = df[df['Gap_Pct'] <= 5.0]

nifty_path = os.path.join(DATA_DIR, 'nifty_morning_features.csv')
nifty_df = pd.read_csv(nifty_path)
nifty_df['date'] = pd.to_datetime(nifty_df['date'])
df = pd.merge(df, nifty_df, left_on='short_sell_date', right_on='date', how='left')

global_path = os.path.join(DATA_DIR, 'global_gaps_combined (1).csv')
if os.path.exists(global_path):
    global_df = pd.read_csv(global_path)
    global_df['date'] = pd.to_datetime(global_df['date'], format='mixed')
    df = pd.merge(df, global_df, left_on='short_sell_date', right_on='date', how='left')

bank_keywords = ['BANK', 'HDFC', 'ICICI', 'KOTAK', 'AXIS', 'SBI', 'INDUSIND']
df['is_bank'] = df['clean_stock'].apply(lambda x: 1 if any(k in str(x).upper() for k in bank_keywords) else 0)

# Regime prep
df['global_gap'] = df['^GSPC'].fillna(0) * 0.5 + df['^NSEI'].fillna(0) * 0.5
df['regime_global'] = pd.cut(df['global_gap'], bins=[-np.inf, -1.0, 0, 1.0, np.inf], labels=[0, 1, 2, 3])
df['regime_global'] = df['regime_global'].astype(float).fillna(1.0).astype(int)
df['gap_divergence'] = (np.sign(df['Gap_Pct']) != np.sign(df['global_gap'])).astype(int)

global_df_sorted = df[['short_sell_date', 'global_gap']].drop_duplicates().sort_values('short_sell_date')
global_df_sorted['rolling_global_gap_3d'] = global_df_sorted['global_gap'].rolling(3, min_periods=1).mean()
global_df_sorted['rolling_global_gap_7d'] = global_df_sorted['global_gap'].rolling(7, min_periods=1).mean()

df = pd.merge(df, global_df_sorted[['short_sell_date', 'rolling_global_gap_3d', 'rolling_global_gap_7d']], on='short_sell_date', how='left')

df['regime_composite'] = (df['Gap_Pct'] > 0).astype(int) * 10 + (df['global_gap'] > 0).astype(int)
df['target'] = (df['short_pnl_net'] > 0).astype(int)

adv_features = [c for c in df.columns if c.startswith('prev_') or c.startswith('morning_') or c.startswith('nifty_')]
adv_features += ['Gap_Pct', 'Volume_Change_Pct', 'gap_abs', 'vol_gap_combo', 'is_bank']
for idx in ['^GSPC', '^DJI', '^IXIC', '^RUT', '^STOXX', '^FTSE', '^GDAXI', '^FCHI', '^N225', '^HSI', '^KS11', '^STI', '^BSESN', '^NSEI', '^MXX', '^BVSP', '^SSMI', '^AORD']:
    if idx in df.columns: adv_features.append(idx)
adv_features = list(set([c for c in adv_features if 'pnl' not in c and c != 'target']))

reg_features = adv_features + ['regime_global', 'gap_divergence', 'rolling_global_gap_3d', 'rolling_global_gap_7d', 'regime_composite', 'global_gap']
reg_features = list(set(reg_features))

df.sort_values('short_sell_date', inplace=True)
df.reset_index(drop=True, inplace=True)

months = df[['year', 'month']].drop_duplicates().sort_values(['year', 'month'])
month_args = [(row['year'], row['month']) for _, row in months.iterrows() if row['year'] >= 2018]

params1 = {'objective': 'binary', 'metric': 'auc', 'boosting_type': 'gbdt', 'n_estimators': 150, 'learning_rate': 0.03, 'num_leaves': 31, 'random_state': 42, 'verbose': -1, 'n_jobs': 1}
params2 = {'objective': 'binary', 'metric': 'auc', 'boosting_type': 'gbdt', 'n_estimators': 100, 'learning_rate': 0.05, 'num_leaves': 15, 'random_state': 123, 'verbose': -1, 'n_jobs': 1}

def train_month(args):
    ty, tm = args
    test_date = pd.Timestamp(year=ty, month=tm, day=1)
    train_start_date = test_date - pd.DateOffset(years=3)

    train_mask = (df['short_sell_date'] >= train_start_date) & (df['short_sell_date'] < test_date)
    test_mask = (df['year'] == ty) & (df['month'] == tm)

    if train_mask.sum() < 500 or test_mask.sum() == 0:
        return None

    train_data = df[train_mask].copy()
    test_data = df[test_mask].copy()

    # ADVANCED MODEL
    train_data_adv, test_data_adv = train_data.copy(), test_data.copy()
    for c in adv_features:
        med = train_data_adv[c].median()
        train_data_adv[c] = train_data_adv[c].fillna(med)
        test_data_adv[c] = test_data_adv[c].fillna(med)

    m1_adv = lgb.LGBMClassifier(**params1).fit(train_data_adv[adv_features], train_data_adv['target'])
    p1_adv = m1_adv.predict_proba(test_data_adv[adv_features])[:, 1]
    m2_adv = lgb.LGBMClassifier(**params2).fit(train_data_adv[adv_features], train_data_adv['target'])
    p2_adv = m2_adv.predict_proba(test_data_adv[adv_features])[:, 1]
    test_data_adv['ml_score_adv'] = (p1_adv + p2_adv) / 2.0

    # REGIME MODEL
    train_data_reg, test_data_reg = train_data.copy(), test_data.copy()
    for c in reg_features:
        med = train_data_reg[c].median()
        train_data_reg[c] = train_data_reg[c].fillna(med)
        test_data_reg[c] = test_data_reg[c].fillna(med)

    m1_reg = lgb.LGBMClassifier(**params1).fit(train_data_reg[reg_features], train_data_reg['target'], categorical_feature=['regime_global', 'regime_composite'])
    p1_reg = m1_reg.predict_proba(test_data_reg[reg_features])[:, 1]
    m2_reg = lgb.LGBMClassifier(**params2).fit(train_data_reg[reg_features], train_data_reg['target'], categorical_feature=['regime_global', 'regime_composite'])
    p2_reg = m2_reg.predict_proba(test_data_reg[reg_features])[:, 1]
    test_data_reg['ml_score_reg'] = (p1_reg + p2_reg) / 2.0

    res_adv = test_data_adv[['short_sell_date', 'clean_stock', 'quantity', 'ml_score_adv']]
    res_reg = test_data_reg[['short_sell_date', 'clean_stock', 'quantity', 'ml_score_reg']]

    return res_adv, res_reg

if __name__ == '__main__':
    print(f"Training across {len(month_args)} windows using multiprocessing...")
    with multiprocessing.Pool(processes=10) as pool:
        results = pool.map(train_month, month_args)

    results = [r for r in results if r is not None]
    adv_dfs = [r[0] for r in results]
    reg_dfs = [r[1] for r in results]

    adv_full = pd.concat(adv_dfs, ignore_index=True)
    adv_full = adv_full.sort_values(['short_sell_date', 'ml_score_adv'], ascending=[True, False])
    adv_full['daily_rank'] = adv_full.groupby('short_sell_date').cumcount() + 1
    adv_top10 = adv_full[adv_full['daily_rank'] <= 10].copy()
    adv_top10 = adv_top10.rename(columns={'short_sell_date': 'date', 'clean_stock': 'stock', 'quantity': 'qty', 'daily_rank': 'rank'})
    adv_top10[['date', 'stock', 'qty', 'rank']].to_csv(os.path.join(OUTPUT_DIR, 'predictions_advanced_top10.csv'), index=False)

    reg_full = pd.concat(reg_dfs, ignore_index=True)
    reg_full = reg_full.sort_values(['short_sell_date', 'ml_score_reg'], ascending=[True, False])
    reg_full['daily_rank'] = reg_full.groupby('short_sell_date').cumcount() + 1
    reg_top10 = reg_full[reg_full['daily_rank'] <= 10].copy()
    reg_top10 = reg_top10.rename(columns={'short_sell_date': 'date', 'clean_stock': 'stock', 'quantity': 'qty', 'daily_rank': 'rank'})
    reg_top10[['date', 'stock', 'qty', 'rank']].to_csv(os.path.join(OUTPUT_DIR, 'predictions_regime_top10.csv'), index=False)

    print("Done saving Top 10 predictions!")
