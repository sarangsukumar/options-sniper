import pandas as pd
import lightgbm as lgb
import os

print("1. Loading base dataset (short_sell_ml_dataset_v3.csv.gz)...")
df = pd.read_csv('/home/ubuntu/github_repo/shortsellmodel940v3/short_sell_ml_dataset_v3.csv.gz')

# Fix date column
df['date_obj'] = pd.to_datetime(df['short_sell_date'])
df['date_str'] = df['date_obj'].dt.strftime('%Y-%m-%d')
df['year'] = df['date_obj'].dt.year

print("2. Loading Pure EQ Auditor Ledger (verified_ledger_with_margin.csv)...")
df_eq = pd.read_csv('/home/ubuntu/942_regime_shift_model/verified_ledger_with_margin.csv')
df_eq['pure_eq_return'] = (df_eq['sell_price'] - df_eq['buy_price']) / df_eq['sell_price'] * 100.0

# Merge on date and stock
df = df.merge(df_eq[['date', 'stockname', 'pure_eq_return']], left_on=['date_str', 'clean_stock'], right_on=['date', 'stockname'], how='left')

# Drop anything not found in EQ ledger
df = df.dropna(subset=['pure_eq_return'])
df['target'] = (df['pure_eq_return'] > 0).astype(int)

print("3. Merging Global Macro Features...")
global_df = pd.read_csv('/home/ubuntu/942_regime_shift_model/global_macro_features.csv')
df = pd.merge(df, global_df, left_on='date_str', right_on='date_str', how='left')
global_cols = ['nifty_gap', 'sp500_overnight_ret', 'nikkei_gap', 'nifty_vs_sp500_gap', 'nifty_vs_nikkei_gap']
df[global_cols] = df[global_cols].fillna(0)

# These features match the production config
features = [
    'Gap_Pct', 'Volume_Change_Pct', 'prev_intraday_return', 'prev_intraday_rsi_9', 
    'prev_intraday_macd', 'prev_intraday_ema_cross', 'prev_intraday_bb_pct_b', 
    'prev_intraday_vwap_gap', 'prev_intraday_stoch_k', 'prev_intraday_range_pos', 
    'prev_intraday_volume_ratio', 'prev_intraday_high_low_ratio', 'prev_intraday_volatility', 
    'prev_intraday_twap_crosses', 'prev_intraday_roc_last_hour', 'prev_intraday_orb_pos', 
    'prev_first_tick_to_1519_pct', 'prev_1450_to_1519_pct', 'morning_return', 'morning_range', 
    'morning_rsi_9', 'morning_macd', 'morning_vwap_gap', 'morning_momentum', 'morning_vol_trend', 
    'morning_bb_pct_b', 'morning_stoch_k', 'morning_ema_cross', 'morning_range_pos', 
    'morning_volatility', 'gap_abs', 'vol_gap_combo',
    'nifty_gap', 'sp500_overnight_ret', 'nikkei_gap', 'nifty_vs_sp500_gap', 'nifty_vs_nikkei_gap'
]

# Ensure numeric
for f in features:
    if f not in df.columns:
        print(f"MISSING FEATURE: {f}")
    df[f] = pd.to_numeric(df[f], errors='coerce').fillna(0)

print("4. Training Pure EQ LightGBM Model...")
train_data = lgb.Dataset(df[features], label=df['target'])
params = {
    'objective': 'binary',
    'metric': 'auc',
    'boosting_type': 'gbdt',
    'learning_rate': 0.03,
    'num_leaves': 15,
    'max_depth': 4,
    'feature_fraction': 0.8,
    'verbose': -1,
    'seed': 42
}
model = lgb.train(params, train_data, num_boost_round=120)
model_path = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/production_ready_two_shortsell_algos/02_hybrid_0942_1445/lgb_0940_hybrid_model_PURE_EQ.txt'
model.save_model(model_path)
print("✅ SUCCESS! Saved to:", model_path)
print(f"✅ Total Pure EQ trades used for training: {len(df)}")
