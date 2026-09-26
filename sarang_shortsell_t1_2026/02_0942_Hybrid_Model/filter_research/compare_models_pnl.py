import pandas as pd
import lightgbm as lgb
import warnings
warnings.filterwarnings('ignore')

# 1. Load Data
df = pd.read_csv('data/short_sell_ml_dataset_v5_scratch.csv', low_memory=False)
df['clean_stock'] = df['clean_stock'].astype(str).str.strip().str.upper()
df = df.drop_duplicates(subset=['date_str', 'clean_stock'])
df['short_pct_return'] = df['short_pct_return'].clip(-15, 15)
df = df[df['short_entry_price'] >= 50].reset_index(drop=True)
df['year'] = pd.to_datetime(df['date_str']).dt.year

# 2. Add New Features
df['day_of_week'] = pd.to_datetime(df['date_str']).dt.dayofweek
df['stock_940_pct'] = df['gap_0907_pct'] + df['gap_fade_0907_to_940_pct']

nifty_df = pd.read_csv('data/nifty_940_pct_historical.csv')
nifty_df['date_str'] = nifty_df['date_str'].astype(str)
df = df.merge(nifty_df, on='date_str', how='left')
df['nifty_940_pct'] = df['nifty_940_pct'].fillna(0)

# 3. Features
ORIGINAL_FEATURES = [
    'gap_0907_pct', 'gap_fade_0907_to_940_pct', 'prev_intraday_vwap_gap',
    'prev_intraday_return', 'prev_intraday_roc_last_hour', 'morn_range_pct',
    'rejection_wick', 'prev_1450_to_1519_pct', 'Gap_Pct'
]
NEW_FEATURES = ORIGINAL_FEATURES + ['stock_940_pct', 'nifty_940_pct', 'day_of_week']

for f in NEW_FEATURES:
    df[f] = pd.to_numeric(df[f], errors='coerce').fillna(0)
df['target'] = df['short_pct_return']

is_df = df[df['year'] <= 2025].copy()

# 4. Train Models
params = {
    'objective': 'regression', 'metric': 'rmse', 'boosting_type': 'gbdt',
    'learning_rate': 0.05, 'max_depth': 5, 'num_leaves': 31,
    'verbose': -1, 'random_state': 42
}
orig_model = lgb.train(params, lgb.Dataset(is_df[ORIGINAL_FEATURES], label=is_df['target']), num_boost_round=100)
new_model = lgb.train(params, lgb.Dataset(is_df[NEW_FEATURES], label=is_df['target']), num_boost_round=100)

# 5. Predict
df['pred_orig'] = orig_model.predict(df[ORIGINAL_FEATURES])
df['pred_new'] = new_model.predict(df[NEW_FEATURES])

# 6. Calculate PnL (Top 4 per day, assuming ₹10L capital per trade to match your baseline)
# 1% return on 10L = ₹10,000
CAPITAL_PER_TRADE = 10_000_00

def get_pnl(grp, pred_col):
    top4 = grp.nlargest(4, pred_col)
    # PnL = (return / 100) * Capital
    return (top4['short_pct_return'] / 100.0 * CAPITAL_PER_TRADE).sum()

print("==========================================================================================")
print("🏆 RAW ML MODELS COMPARISON (NO HARD FILTERS APPLIED)")
print("==========================================================================================")
print(f"{'Year':<5} | {'Old Model PnL':<15} | {'New Model PnL':<15} | {'Delta (New - Old)'}")
print("-" * 75)

total_orig = 0
total_new = 0

# Limit to 2020-2026 to match our earlier baseline comparison
df_recent = df[df['year'] >= 2020]

for year in sorted(df_recent['year'].unique()):
    yr_df = df_recent[df_recent['year'] == year]
    
    orig_pnl = yr_df.groupby('date_str').apply(lambda g: get_pnl(g, 'pred_orig')).sum()
    new_pnl = yr_df.groupby('date_str').apply(lambda g: get_pnl(g, 'pred_new')).sum()
    
    total_orig += orig_pnl
    total_new += new_pnl
    
    delta = new_pnl - orig_pnl
    tag = "(OOS)" if year == 2026 else ""
    print(f"{year:<5} | ₹ {orig_pnl:>12,.0f} | ₹ {new_pnl:>12,.0f} | {'+' if delta>0 else ''}₹ {delta:>10,.0f} {tag}")

print("=" * 75)
total_delta = total_new - total_orig
print(f"TOTAL | ₹ {total_orig:>12,.0f} | ₹ {total_new:>12,.0f} | {'+' if total_delta>0 else ''}₹ {total_delta:>10,.0f}")
