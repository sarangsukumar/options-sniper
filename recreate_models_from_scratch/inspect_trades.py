import pandas as pd
import lightgbm as lgb
df = pd.read_csv('/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/recreate_models_from_scratch/massive_universe_dataset.csv')
df = df.dropna(subset=['Daily_Volume_Rank', 'Gap_Pct', 'target', 'date'])
df['date_obj'] = pd.to_datetime(df['date'])
df['year'] = df['date_obj'].dt.year

train_df = df[df['year'] < 2026]
test_df = df[df['year'] == 2026].copy()

features = ['open_price', 'morning_volume', 'Gap_Pct', 'morning_return', 'Daily_Volume_Rank', 'Daily_Momentum_Rank']

train_data = lgb.Dataset(train_df[features], label=train_df['target'])
params = {'objective': 'binary', 'metric': 'auc', 'boosting_type': 'gbdt', 'learning_rate': 0.05, 'num_leaves': 15, 'max_depth': 4, 'verbose': -1, 'seed': 42}
model = lgb.train(params, train_data, num_boost_round=100)

test_df['pred_prob'] = model.predict(test_df[features])

# Print Top 10 trades selected
selected = test_df[test_df['pred_prob'] >= 0.50].sort_values('pred_prob', ascending=False).head(10)
print("TOP 10 TRADES THE AI SELECTED FOR 2026:")
print(selected[['date', 'stockname', 'morning_volume', 'Daily_Volume_Rank', 'pred_prob', 'pure_eq_return']])
