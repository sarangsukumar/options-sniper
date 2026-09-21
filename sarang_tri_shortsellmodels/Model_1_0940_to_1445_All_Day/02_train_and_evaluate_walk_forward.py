import pandas as pd
import lightgbm as lgb
import os

csv_path = 'massive_universe_dataset.csv'
if not os.path.exists(csv_path):
    print("Please run 01_build_massive_dataset.py first.")
    exit()
    
df = pd.read_csv(csv_path)
df = df.dropna(subset=['Daily_Volume_Rank', 'Gap_Pct', 'target', 'date'])
df['date_obj'] = pd.to_datetime(df['date'])
df['year'] = df['date_obj'].dt.year
df['morning_turnover'] = df['morning_volume'] * df['morning_close']

features = ['open_price', 'morning_volume', 'Gap_Pct', 'morning_return', 'Daily_Volume_Rank', 'Daily_Momentum_Rank']

def get_kotak_neo_charges(qty, sell_price, buy_price):
    turnover = (qty * sell_price) + (qty * buy_price)
    brokerage = 40.0
    stt = round(qty * sell_price * 0.00025)
    txn = turnover * 0.0000322
    sebi = turnover * 0.000001
    stamp = round(qty * buy_price * 0.00003)
    gst = (brokerage + txn + sebi) * 0.18
    return round(brokerage + stt + txn + sebi + stamp + gst, 2)

years = sorted(df['year'].unique())
oos_predictions = []

for test_year in years:
    if test_year < 2020: continue 
    train_df = df[df['year'] < test_year]
    test_df = df[df['year'] == test_year].copy()
    if len(train_df) == 0 or len(test_df) == 0: continue
    
    train_data = lgb.Dataset(train_df[features], label=train_df['target'])
    params = {'objective': 'binary', 'metric': 'auc', 'boosting_type': 'gbdt', 'learning_rate': 0.05, 'num_leaves': 15, 'max_depth': 4, 'verbose': -1, 'seed': 42}
    model = lgb.train(params, train_data, num_boost_round=100)
    
    test_df['pred_prob'] = model.predict(test_df[features])
    oos_predictions.append(test_df)

full_oos = pd.concat(oos_predictions)

out_trades = []
for d, group in full_oos.groupby('date'):
    liquid_group = group[group['morning_turnover'] >= 100000000] # 10 Crore Minimum Turnover
    selected = liquid_group[liquid_group['pred_prob'] >= 0.50].sort_values('pred_prob', ascending=False).head(5)
    
    for _, row in selected.iterrows():
        sp = row['entry_price']
        bp = row['exit_price']
        qty = int(1000000.0 / sp)
        gross = (sp - bp) * qty
        net = gross - get_kotak_neo_charges(qty, sp, bp)
        out_trades.append({'date': d, 'year': row['year'], 'stock': row['stockname'], 'sp': sp, 'bp': bp, 'qty': qty, 'net_pnl': net, 'pred_prob': row['pred_prob']})

res_df = pd.DataFrame(out_trades)
res_df.to_csv('03_final_pnl_verification_ledger.csv', index=False)
print("Saved all trades to 03_final_pnl_verification_ledger.csv")

for yr in sorted(res_df['year'].unique()):
    yr_df = res_df[res_df['year'] == yr]
    print(f"Year {yr}: Trades: {len(yr_df)} | Net PnL: Rs {yr_df['net_pnl'].sum():,.2f}")
print(f"TOTAL OOS NET PNL: Rs {res_df['net_pnl'].sum():,.2f}")
