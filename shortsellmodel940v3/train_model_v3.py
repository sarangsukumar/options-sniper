import os
import joblib
import pandas as pd
import numpy as np
import lightgbm as lgb
import warnings
warnings.filterwarnings('ignore')

DEST_DIR = '/home/ubuntu/shortsellmodel940v3'
SRC_DIR = '/home/ubuntu/short_sell_simulation_algo/output'

print("1. Loading v3 dataset...")
df = pd.read_csv(f'{DEST_DIR}/short_sell_ml_dataset_v3.csv', low_memory=False)

# Load feature list
adv_features = joblib.load(f'{SRC_DIR}/models/adv_features.pkl')

# Feature list for ML
bank_keywords = ['BANK', 'HDFC', 'ICICI', 'KOTAK', 'AXIS', 'SBI', 'INDUSIND']
df['is_bank'] = df['clean_stock'].apply(lambda x: 1 if any(k in str(x).upper() for k in bank_keywords) else 0)

feature_cols = [c for c in adv_features if c in df.columns]
for c in feature_cols:
    df[c] = df[c].fillna(0.0)

# Binary target: Positive short sell return (>0)
df['target_short'] = (df['short_pct_return'] > 0).astype(int)

# 2. Expanding Monthly Walk-Forward Training (2018 to 2026)
test_months = sorted(df[df['year'] >= 2018]['year_month'].unique())
print(f"2. Running Expanding Monthly Walk-Forward Training over {len(test_months)} months (2018–2026)...")

all_preds = []
for ym in test_months:
    train_mask = df['year_month'] < ym
    test_mask = df['year_month'] == ym
    
    X_train = df[train_mask][feature_cols]
    y_train = df[train_mask]['target_short']
    X_test = df[test_mask][feature_cols]
    
    if len(X_test) == 0: continue
    
    model = lgb.LGBMClassifier(
        n_estimators=100,
        learning_rate=0.03,
        num_leaves=31,
        random_state=42,
        verbose=-1,
        n_jobs=-1
    )
    model.fit(X_train, y_train)
    
    sub = df[test_mask][['short_sell_date', 'clean_stock', 'quantity', 'year']].copy()
    sub['score'] = model.predict_proba(X_test)[:, 1]
    all_preds.append(sub)

preds_df = pd.concat(all_preds)
preds_df['rank'] = preds_df.groupby('short_sell_date')['score'].rank(method='first', ascending=False)

# Filter top 10 stocks per day
top10_df = preds_df[preds_df['rank'] <= 10].copy()
top10_df = top10_df.rename(columns={'short_sell_date': 'date', 'clean_stock': 'stock', 'quantity': 'qty'})

out_preds = f'{DEST_DIR}/predictions_top10_v3.csv'
top10_df[['date', 'stock', 'qty', 'rank']].to_csv(out_preds, index=False)
print(f"3. Saved top 10 walk-forward predictions cleanly to {out_preds} ({len(top10_df):,} rows).")

