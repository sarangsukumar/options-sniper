import pandas as pd
import numpy as np
import lightgbm as lgb
import warnings
warnings.filterwarnings('ignore')

print("1. Loading existing dataset...")
df = pd.read_csv('data/short_sell_ml_dataset_v5_scratch.csv', low_memory=False)
df['clean_stock'] = df['clean_stock'].astype(str).str.strip().str.upper()
df = df.drop_duplicates(subset=['date_str', 'clean_stock'])
df['short_pct_return'] = df['short_pct_return'].clip(-15, 15)
df = df[df['short_entry_price'] >= 50].reset_index(drop=True)
df['year'] = pd.to_datetime(df['date_str']).dt.year

print("2. Adding new features...")
df['day_of_week']    = pd.to_datetime(df['date_str']).dt.dayofweek
df['stock_940_pct']  = df['gap_0907_pct'] + df['gap_fade_0907_to_940_pct']

print("3. Loading pre-fetched Nifty 09:40 historical prices from CSV...")
nifty_df = pd.read_csv('data/nifty_940_pct_historical.csv')
nifty_df['date_str'] = nifty_df['date_str'].astype(str)
print(f"   Loaded {len(nifty_df)} dates of Nifty 09:40 data")

print("4. Merging new features into dataset...")
df = df.merge(nifty_df, on='date_str', how='left')
df['nifty_940_pct'] = df['nifty_940_pct'].fillna(0)

print(f"\nSample new features:")
print(df[['date_str','clean_stock','stock_940_pct','nifty_940_pct','day_of_week']].head(5).to_string())

# --- FEATURE SETS ---
ORIGINAL_FEATURES = [
    'gap_0907_pct', 'gap_fade_0907_to_940_pct', 'prev_intraday_vwap_gap',
    'prev_intraday_return', 'prev_intraday_roc_last_hour', 'morn_range_pct',
    'rejection_wick', 'prev_1450_to_1519_pct', 'Gap_Pct'
]

NEW_FEATURES = ORIGINAL_FEATURES + ['stock_940_pct', 'nifty_940_pct', 'day_of_week']

# Prepare data
for f in NEW_FEATURES:
    df[f] = pd.to_numeric(df[f], errors='coerce').fillna(0)
df['target'] = df['short_pct_return']

is_df  = df[df['year'] <= 2025].copy()
oos_df = df[df['year'] == 2026].copy()

params = {
    'objective': 'regression', 'metric': 'rmse', 'boosting_type': 'gbdt',
    'learning_rate': 0.05, 'max_depth': 5, 'num_leaves': 31,
    'verbose': -1, 'random_state': 42
}

print("\n5. Training ORIGINAL model (14 features)...")
orig_model = lgb.train(
    params,
    lgb.Dataset(is_df[ORIGINAL_FEATURES], label=is_df['target']),
    num_boost_round=100
)

print("6. Training NEW model (17 features: + stock_940_pct, nifty_940_pct, day_of_week)...")
new_model = lgb.train(
    params,
    lgb.Dataset(is_df[NEW_FEATURES], label=is_df['target']),
    num_boost_round=100
)

# Predictions on OOS
oos_df['pred_orig'] = orig_model.predict(oos_df[ORIGINAL_FEATURES])
oos_df['pred_new']  = new_model.predict(oos_df[NEW_FEATURES])

print("\n7. Feature Importances — NEW MODEL (Top 12):")
fi = pd.Series(new_model.feature_importance(importance_type='gain'), index=NEW_FEATURES).sort_values(ascending=False)
for feat, val in fi.head(12).items():
    marker = "🆕" if feat in ['stock_940_pct', 'nifty_940_pct', 'day_of_week'] else "  "
    bar = "█" * int(val / fi.max() * 30)
    print(f"  {marker} {feat:<35}: {bar} ({val:,.0f})")

# OOS PnL comparison — top4 per day
print("\n8. OOS (2026) PERFORMANCE — does new model self-filter bad stocks?")

# Check if new model naturally de-ranks blocked stocks
bad_mask = (
    (oos_df['stock_940_pct'] < -1.0) |
    ((oos_df['nifty_940_pct'] < -0.5) & (oos_df['stock_940_pct'] < -0.5))
)
blocked = oos_df[bad_mask]
passed  = oos_df[~bad_mask]

print(f"\n   Stocks our RULE would BLOCK ({len(blocked)} trades):")
print(f"     Avg pred score ORIGINAL model : {blocked['pred_orig'].mean():+.4f}")
print(f"     Avg pred score NEW model      : {blocked['pred_new'].mean():+.4f}")
print(f"     Actual avg return             : {blocked['short_pct_return'].mean():+.4f}%")

print(f"\n   Stocks our RULE would PASS ({len(passed)} trades):")
print(f"     Avg pred score ORIGINAL model : {passed['pred_orig'].mean():+.4f}")
print(f"     Avg pred score NEW model      : {passed['pred_new'].mean():+.4f}")
print(f"     Actual avg return             : {passed['short_pct_return'].mean():+.4f}%")

print("\n   ✅ KEY: If new model correctly learns the rules,")
print("          blocked stocks should have LOWER scores than passed stocks")
print(f"          Gap in new model : {passed['pred_new'].mean() - blocked['pred_new'].mean():+.4f}")
print(f"          Gap in orig model: {passed['pred_orig'].mean() - blocked['pred_orig'].mean():+.4f}")

# Year-by-year PnL from top4 by each model
print("\n9. YEAR-BY-YEAR: Does new model improve PnL?")
print(f"{'Year':<5} | {'Orig top4 avg ret':<20} | {'New top4 avg ret':<20} | {'Delta'}")
print("-" * 75)

for year in sorted(df['year'].unique()):
    yr = df[df['year'] == year].copy()
    yr['pred_orig'] = orig_model.predict(yr[ORIGINAL_FEATURES])
    yr['pred_new']  = new_model.predict(yr[NEW_FEATURES])

    orig_ret = yr.groupby('date_str').apply(lambda g: g.nlargest(4,'pred_orig')['short_pct_return'].mean()).mean()
    new_ret  = yr.groupby('date_str').apply(lambda g: g.nlargest(4,'pred_new')['short_pct_return'].mean()).mean()
    delta = new_ret - orig_ret
    tag = "(OOS)" if year == 2026 else ""
    print(f"{year:<5} | {orig_ret:>+18.4f}%   | {new_ret:>+18.4f}%   | {'+' if delta>0 else ''}{delta:.4f}% {tag}")
