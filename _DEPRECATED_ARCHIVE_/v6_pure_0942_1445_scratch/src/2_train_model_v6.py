#!/usr/bin/env python3
"""
2_train_model_v6.py
---------------------
Trains LightGBM Classifier on Model v6 dataset using Expanding Walk-Forward Validation.

Features used (till 09:40 AM ONLY, no yfinance volume):
  - `gap_0907_pct`
  - `gap_fade_0907_to_940_pct`
  - `stock_ret_940`
  - `morn_range_pct`
  - `rejection_wick`
  - `Gap_Pct`
  - `dist_from_high_pct`
  - `dist_from_low_pct`
  - `rsi_14`
  - `macd`

Out-of-Sample Predictions: 2021 to 2026
Outputs:
  /home/ubuntu/daily_prediction_sytem_Dynamic_threshold/v6_pure_0942_1445_scratch/output/predictions_v6.csv
"""

import os
import pandas as pd
import numpy as np
import lightgbm as lgb
import warnings
warnings.filterwarnings('ignore')

BASE_DIR = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/v6_pure_0942_1445_scratch'
DATA_FILE = os.path.join(BASE_DIR, 'data', 'short_sell_ml_dataset_v6.csv')
OUT_DIR = os.path.join(BASE_DIR, 'output')
os.makedirs(OUT_DIR, exist_ok=True)
OUT_FILE = os.path.join(OUT_DIR, 'predictions_v6.csv')

FEATURE_COLS = [
    'positive_arc_ratio',
    'prev_intraday_vwap_gap',
    'prev_intraday_return',
    'Gap_Pct',
    'gap_0907_pct',
    'morn_range_pct',
    'rejection_wick',
    'prev_intraday_roc_last_hour',
    'stock_weekday_win_rate'
]

def main():
    print("===================================================================================")
    print("🚀 STEP 2: EXPANDING WALK-FORWARD LIGHTGBM TRAINING (MODEL v6)")
    print("===================================================================================\n")

    if not os.path.exists(DATA_FILE):
        raise FileNotFoundError(f"Dataset missing! Run 1_build_dataset_v6.py first.")

    df = pd.read_csv(DATA_FILE)
    df['date'] = pd.to_datetime(df['date_str'])
    df['year'] = df['date'].dt.year

    # Filter features that exist in df
    avail_features = [c for c in FEATURE_COLS if c in df.columns]
    print(f"Features used for training ({len(avail_features)} features):")
    for f in avail_features:
        print(f"  • {f}")

    # Fill NaNs in feature columns
    for f in avail_features:
        df[f] = pd.to_numeric(df[f], errors='coerce').fillna(0.0)

    test_years = [2021, 2022, 2023, 2024, 2025, 2026]
    all_preds = []

    print("\nStarting Expanding Walk-Forward Training across 2021–2026...")
    for test_y in test_years:
        train_df = df[df['year'] < test_y].copy()
        test_df = df[df['year'] == test_y].copy()

        if len(test_df) == 0:
            print(f"  ⚠️ No test data for {test_y}, skipping.")
            continue

        X_train = train_df[avail_features]
        y_train = train_df['target']

        X_test = test_df[avail_features]

        params = {
            'objective': 'binary',
            'metric': 'binary_logloss',
            'boosting_type': 'gbdt',
            'learning_rate': 0.03,
            'num_leaves': 15,
            'max_depth': 4,
            'min_child_samples': 20,
            'subsample': 0.8,
            'colsample_bytree': 0.8,
            'random_state': 42,
            'verbose': -1
        }

        model = lgb.LGBMClassifier(**params, n_estimators=100)
        model.fit(X_train, y_train)

        probs = model.predict_proba(X_test)[:, 1]
        test_df['prob_win'] = probs
        all_preds.append(test_df)

        print(f"  • {test_y}: Train Rows = {len(train_df):,}, Test Rows = {len(test_df):,}, Mean Prob = {probs.mean():.4f}")

    df_preds = pd.concat(all_preds, ignore_index=True)
    df_preds['rank'] = df_preds.groupby('date_str')['prob_win'].rank(ascending=False, method='first').astype(int)

    print(f"\nSaving predictions to: {OUT_FILE}...")
    df_preds.to_csv(OUT_FILE, index=False)
    print(f"✅ Step 2 complete! Generated {len(df_preds):,} out-of-sample predictions across 2021–2026.")

if __name__ == '__main__':
    main()
