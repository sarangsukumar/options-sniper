import pandas as pd, lightgbm as lgb
df = pd.read_csv('model2_features.csv').dropna(subset=['Daily_Volume_Rank', 'Gap_Pct', 'target', 'date'])
df['year'] = pd.to_datetime(df['date']).dt.year
df['turnover'] = df['morning_volume'] * df['morning_close']
features = ['open_price', 'morning_volume', 'Gap_Pct', 'morning_return', 'Daily_Volume_Rank', 'Daily_Momentum_Rank']
oos = []
for ty in sorted(df['year'].unique()):
    if ty < 2020: continue 
    tr, te = df[df['year'] < ty], df[df['year'] == ty].copy()
    if len(tr) == 0 or len(te) == 0: continue
    model = lgb.train({'objective': 'binary', 'metric': 'auc', 'boosting_type': 'gbdt', 'learning_rate': 0.05, 'num_leaves': 15, 'max_depth': 4, 'verbose': -1, 'seed': 42}, lgb.Dataset(tr[features], label=tr['target']), 100)
    te['pred_prob'] = model.predict(te[features])
    oos.append(te)
out = []
for d, g in pd.concat(oos).groupby('date'):
    for _, r in g[g['turnover'] >= 30000000][g['pred_prob'] >= 0.50].sort_values('pred_prob', ascending=False).head(5).iterrows():
        out.append({'date': d, 'stock': r['stockname']})
pd.DataFrame(out).to_csv('model2_raw_trades.csv', index=False)
