import pandas as pd
import lightgbm as lgb
import pymysql

print("1. Re-running ML Model to get exact 2026 trades...")
csv_path = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/recreate_models_from_scratch/massive_universe_dataset.csv'
df = pd.read_csv(csv_path)
df = df.dropna(subset=['Daily_Volume_Rank', 'Gap_Pct', 'target', 'date'])
df['date_obj'] = pd.to_datetime(df['date'])
df['year'] = df['date_obj'].dt.year

df['morning_turnover'] = df['morning_volume'] * df['morning_close']
features = ['open_price', 'morning_volume', 'Gap_Pct', 'morning_return', 'Daily_Volume_Rank', 'Daily_Momentum_Rank']

train_df = df[df['year'] < 2026]
test_df = df[df['year'] == 2026].copy()

train_data = lgb.Dataset(train_df[features], label=train_df['target'])
params = {'objective': 'binary', 'metric': 'auc', 'boosting_type': 'gbdt', 'learning_rate': 0.05, 'num_leaves': 15, 'max_depth': 4, 'verbose': -1, 'seed': 42}
model = lgb.train(params, train_data, num_boost_round=100)
test_df['pred_prob'] = model.predict(test_df[features])

def get_kotak_neo_charges(qty, sell_price, buy_price):
    turnover = (qty * sell_price) + (qty * buy_price)
    brokerage = 40.0
    stt = round(qty * sell_price * 0.00025)
    txn = turnover * 0.0000322
    sebi = turnover * 0.000001
    stamp = round(qty * buy_price * 0.00003)
    gst = (brokerage + txn + sebi) * 0.18
    return round(brokerage + stt + txn + sebi + stamp + gst, 2)

out_trades = []
for d, group in test_df.groupby('date'):
    liquid_group = group[group['morning_turnover'] >= 100000000]
    selected = liquid_group[liquid_group['pred_prob'] >= 0.50].sort_values('pred_prob', ascending=False).head(5)
    for _, row in selected.iterrows():
        sp = row['entry_price']
        bp = row['exit_price']
        qty = int(1000000.0 / sp)
        gross = (sp - bp) * qty
        net = gross - get_kotak_neo_charges(qty, sp, bp)
        out_trades.append({'date': d, 'stock': row['stockname'], 'sp': sp, 'bp': bp, 'qty': qty, 'net': net})

res_df = pd.DataFrame(out_trades)
print(f"Total 2026 PnL Calculated: Rs {res_df['net'].sum():,.2f}")

print("\n2. Picking 3 Random Trades from 2026 to cross-verify directly against MySQL scrapdata...")
sample = res_df.sample(3, random_state=42)

db = pymysql.connect(host='localhost', user='root', password='root', database='markets', cursorclass=pymysql.cursors.DictCursor)
cur = db.cursor()

for _, row in sample.iterrows():
    d = row['date']
    s = row['stock']
    print(f"\n--- VERIFYING {s} on {d} ---")
    print(f"CSV RECORD SAYS: Sell at {row['sp']}, Buy at {row['bp']}, Qty: {row['qty']}, Net PnL: Rs {row['net']:,.2f}")
    
    # Query Database
    cur.execute(f"SELECT time, price FROM scrapdata WHERE date='{d}' AND stockname='{s}' AND time >= '{d} 09:42:00' LIMIT 1")
    sp_db = cur.fetchone()
    
    cur.execute(f"SELECT time, price FROM scrapdata WHERE date='{d}' AND stockname='{s}' AND time >= '{d} 14:45:00' LIMIT 1")
    bp_db = cur.fetchone()
    
    if sp_db and bp_db:
        print(f"MYSQL PHYSICAL DB: 09:42 tick = {sp_db['price']}, 14:45 tick = {bp_db['price']}")
        qty_check = int(1000000.0 / sp_db['price'])
        gross = (sp_db['price'] - bp_db['price']) * qty_check
        net_check = gross - get_kotak_neo_charges(qty_check, sp_db['price'], bp_db['price'])
        print(f"MYSQL PHYSICAL MATH: Qty: {qty_check}, Net PnL: Rs {net_check:,.2f}")
    else:
        print("Missing ticks in DB.")
db.close()
