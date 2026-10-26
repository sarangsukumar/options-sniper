import os
import pandas as pd
import lightgbm as lgb
import numpy as np
import warnings

warnings.filterwarnings('ignore')

DIR = os.path.dirname(os.path.abspath(__file__))
DATASET_PATH = os.path.join(DIR, 'audited_0940_hybrid_trades.csv')
MODEL_OUTPUT_PATH = os.path.join(DIR, 'lgb_0940_hybrid_huber_model.txt')

print("======================================================================")
print("  MONTHLY RETRAINING ENGINE: 09:40 HYBRID HUBER MODEL")
print("======================================================================")

print("1. Loading Historical Audited Trade Ledger...")
if os.path.exists(DATASET_PATH):
    df = pd.read_csv(DATASET_PATH)
else:
    raise FileNotFoundError(f"Dataset missing at {DATASET_PATH}")

df['date'] = pd.to_datetime(df['date'].astype(str))
df['year'] = df['date'].dt.year

features_huber = [
    'gap_pct', 'morn_range_pct', 'gap_fade_0907_to_940_pct', 'prev_intraday_return',
    'prev_intraday_vwap_gap', 'prev_intraday_roc_last_hour', 'positive_arc_ratio',
    'rejection_wick', 'nifty_gap', 'sp500_overnight_ret', 'nikkei_gap',
    'nifty_vs_sp500_gap', 'nifty_vs_nikkei_gap'
]

# Standardize available numeric columns
existing_cols = [c for c in features_huber if c in df.columns]
if 'target_return' in df.columns:
    df['target'] = df['target_return']
elif 'net_pnl' in df.columns:
    df['target'] = df['net_pnl'] / 750000.0  # Normalized return target (7.5L capital)

df[existing_cols] = df[existing_cols].fillna(0)
df['target'] = df['target'].fillna(0)

params_huber = {
    'objective': 'huber',
    'alpha': 0.9,
    'learning_rate': 0.05,
    'max_depth': 5,
    'num_leaves': 31,
    'feature_fraction': 0.8,
    'verbose': -1,
    'random_state': 42
}

# Apply 4-Year Rolling Window (drop data older than 4 years for recency focus)
max_year = df['year'].max()
cutoff_year = max_year - 4
df_train = df[df['year'] >= cutoff_year].copy()

# Add exponential time-decay weights (giving recent 2025/2026 data 5x higher influence)
max_dt = df_train['date'].max()
df_train['days_old'] = (max_dt - df_train['date']).dt.days
df_train['sample_weight'] = np.exp(-df_train['days_old'] / 730.0)  # 2-year half-life

print(f"2. Retraining Huber Model on {len(df_train)} Samples (Rolling Window {cutoff_year}-{max_year})...")
train_data = lgb.Dataset(
    df_train[existing_cols],
    label=df_train['target'],
    weight=df_train['sample_weight']
)

model = lgb.train(params_huber, train_data, num_boost_round=300)

model.save_model(MODEL_OUTPUT_PATH)
print(f"✅ Success! Retrained Huber Model saved to: {MODEL_OUTPUT_PATH}")
print("======================================================================")
