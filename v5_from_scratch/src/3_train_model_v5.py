#!/usr/bin/env python3
"""
3_train_model_v5.py
-------------------
Executes expanding monthly walk-forward LightGBM training (2021–2026) using
100% leak-free pre-market and morning features.

Outputs:
  • Predictions: /home/ubuntu/v5_from_scratch/output/predictions_top10_v5_scratch.csv
  • Model Booster: /home/ubuntu/v5_from_scratch/models/model_v5_lgb_scratch.txt
"""

import pandas as pd
import numpy as np
import lightgbm as lgb
import os
import time
import warnings
warnings.filterwarnings('ignore')

BASE_DIR = '/home/ubuntu/v5_from_scratch'
DATASET_PATH = os.path.join(BASE_DIR, 'data', 'short_sell_ml_dataset_v5_scratch.csv')
PREDS_OUT = os.path.join(BASE_DIR, 'output', 'predictions_top10_v5_scratch.csv')
MODEL_OUT = os.path.join(BASE_DIR, 'models', 'model_v5_lgb_scratch.txt')

def main():
    print("==================================================================")
    print("STEP 3: WALK-FORWARD LIGHTGBM TRAINING (MODEL v5 FROM SCRATCH)")
    print("==================================================================")
    
    print("1. Loading Model v5 dataset...")
    df = pd.read_csv(DATASET_PATH, low_memory=False)
    df['date_str'] = pd.to_datetime(df['short_sell_date'], format='mixed').dt.strftime('%Y-%m-%d')
    df['month'] = pd.to_datetime(df['date_str']).dt.to_period('M')
    
    df['target_pnl_positive'] = (df['short_pnl_net'] > 0).astype(int)
    
    # 15 Strictly Leak-Free Features
    feature_cols = [
        'Gap_Pct',
        'gap_0907_pct', 'gap_fade_0907_to_940_pct',
        'stock_ret_940', 'morn_range_pct', 'rejection_wick'
    ]
    
    opt_feats = [
        'prev_intraday_return', 'prev_intraday_rsi_9', 'prev_intraday_macd',
        'prev_intraday_ema_cross', 'prev_intraday_bb_pct_b', 'prev_intraday_vwap_gap',
        'prev_intraday_stoch_k', 'prev_intraday_range_pos', 'prev_first_tick_to_1519_pct'
    ]
    for f in opt_feats:
        if f in df.columns:
            feature_cols.append(f)
            
    for col in feature_cols:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)
        
    print(f" Loaded {len(df):,} trades across {df['date_str'].nunique()} dates.")
    print(f" Features ({len(feature_cols)} total): {feature_cols}")
    
    months = sorted(df['month'].unique())
    train_start_month = pd.Period('2018-01', 'M')
    eval_start_month = pd.Period('2021-01', 'M')
    
    print("\n2. Executing Expanding Monthly Walk-Forward Training...")
    preds_list = []
    params = {
        'objective': 'binary',
        'metric': 'auc',
        'boosting_type': 'gbdt',
        'learning_rate': 0.03,
        'num_leaves': 15,
        'max_depth': 4,
        'min_child_samples': 50,
        'subsample': 0.8,
        'colsample_bytree': 0.8,
        'random_state': 42,
        'n_jobs': -1,
        'verbose': -1
    }
    
    final_model = None
    
    for m in months:
        if m < eval_start_month:
            continue
            
        train_mask = (df['month'] >= train_start_month) & (df['month'] < m)
        test_mask = (df['month'] == m)
        
        X_train = df.loc[train_mask, feature_cols]
        y_train = df.loc[train_mask, 'target_pnl_positive']
        
        X_test = df.loc[test_mask, feature_cols]
        test_df = df.loc[test_mask, ['date_str', 'clean_stock', 'short_entry_price', 'short_exit_price', 'quantity', 'short_pnl_net', 'short_pct_return', 'Gap_Pct', 'gap_0907_pct', 'gap_fade_0907_to_940_pct']].copy()
        
        if len(X_train) < 500 or len(X_test) == 0:
            continue
            
        dtrain = lgb.Dataset(X_train, label=y_train)
        final_model = lgb.train(params, dtrain, num_boost_round=100)
        
        test_df['prob_win'] = final_model.predict(X_test)
        preds_list.append(test_df)
        
    all_preds = pd.concat(preds_list, ignore_index=True)
    top10_preds = all_preds.sort_values(['date_str', 'prob_win'], ascending=[True, False]).groupby('date_str').head(10).reset_index(drop=True)
    
    top10_preds.to_csv(PREDS_OUT, index=False)
    print(f"\n Saved walk-forward predictions: {PREDS_OUT}")
    
    # Save final trained booster model for live production deployment
    if final_model is not None:
        final_model.save_model(MODEL_OUT)
        print(f" Saved production model booster: {MODEL_OUT}")
        
    importances = final_model.feature_importance(importance_type='gain')
    fi_df = pd.DataFrame({'feature': feature_cols, 'importance_gain': importances}).sort_values('importance_gain', ascending=False)
    print("\n📊 Model v5 Feature Importance (Gain):")
    print(fi_df.to_string(index=False))
    
    print("\n✅ Step 3 complete!")

if __name__ == '__main__':
    main()
