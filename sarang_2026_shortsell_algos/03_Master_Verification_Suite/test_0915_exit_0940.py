import os, pymysql, time
import pandas as pd
import lightgbm as lgb
from concurrent.futures import ThreadPoolExecutor

print("1. Generating 09:15 Trades via Walk-Forward...")
df = pd.read_csv('/home/ubuntu/v5_from_scratch/data/master_dual_timeline_dataset.csv', low_memory=False)

features_0915 = ['Gap_Pct', 'gap_0907_pct', 'prev_intraday_return', 'prev_intraday_rsi_9',
                 'prev_intraday_macd', 'prev_intraday_ema_cross', 'prev_intraday_bb_pct_b',
                 'prev_intraday_vwap_gap', 'prev_intraday_stoch_k', 'prev_intraday_range_pos',
                 'prev_first_tick_to_1519_pct']

df['month'] = pd.to_datetime(df['date_str']).dt.to_period('M')
df['year'] = pd.to_datetime(df['date_str']).dt.year
months = sorted(df['month'].unique())
eval_start = pd.Period('2021-01', 'M')
df['target'] = (df['pnl_0915_net'] > 0).astype(int)
results = []

for m in months:
    if m < eval_start: continue
    train_df = df[(df['month'] >= pd.Period('2018-01', 'M')) & (df['month'] < m)]
    test_df = df[df['month'] == m]
    if len(train_df) == 0 or len(test_df) == 0: continue
    
    X_train = train_df[features_0915]
    y_train = train_df['target']
    X_test = test_df[features_0915]
    
    model = lgb.LGBMClassifier(n_estimators=100, learning_rate=0.05, max_depth=4, random_state=42, n_jobs=-1, verbose=-1)
    model.fit(X_train, y_train)
    
    test_out = test_df[['date_str', 'year', 'clean_stock', 'target']].copy()
    test_out['prob_win'] = model.predict_proba(X_test)[:, 1]
    results.append(test_out)
    
res_df = pd.concat(results)
top4 = res_df.sort_values(['date_str', 'prob_win'], ascending=[True, False]).groupby('date_str').head(4)
print(f"Total trades isolated: {len(top4)}.")

def get_kotak_mis_charges(qty, sell_price, buy_price):
    sell_value = qty * sell_price
    buy_value = qty * buy_price
    turnover = sell_value + buy_value
    stt = round(sell_value * 0.00025)
    txn = turnover * 0.0000322
    sebi = turnover * 0.000001
    stamp = round(buy_value * 0.00003)
    gst = (txn + sebi) * 0.18
    return round(stt + txn + sebi + stamp + gst, 2)

def process_trade(row):
    d = row['date_str']
    s = row['clean_stock']
    base_capital = 100000.0
    leveraged_capital = base_capital * 5.0
    
    conn = pymysql.connect(host='localhost', user='root', password='root', database='markets', autocommit=True)
    cur = conn.cursor(pymysql.cursors.DictCursor)
    
    cur.execute(f"SELECT time, price, high, low, close FROM scrapdata WHERE date = '{d}' AND stockname IN ('{s}', '\"{s}\"', '{s} ') AND time >= '{d} 09:15:00' AND time <= '{d} 09:16:59' ORDER BY time ASC LIMIT 1")
    entry_tick = cur.fetchone()
    
    if not entry_tick or not float(entry_tick['price'] or entry_tick['close'] or 0) > 0:
        conn.close()
        return {'net_pnl': 0.0, 'valid': False}
        
    en = float(entry_tick['price'] or entry_tick['close'])
    en_time = entry_tick['time']
    qty = int(leveraged_capital // en)
    
    cur.execute(f"SELECT time, price, high, low, close FROM scrapdata WHERE date = '{d}' AND stockname IN ('{s}', '\"{s}\"', '{s} ') AND time >= '{en_time}' AND time <= '{d} 09:41:59' ORDER BY time ASC")
    ticks = cur.fetchall()
    
    sl = round(en * 1.03, 2)
    tp = round(en * 0.95, 2) # Adding 5% TP just in case!
    hit, ex = False, None
    
    for t in ticks:
        if float(t['high'] or t['price'] or 0) >= sl:
            hit, ex = True, sl
            break
        if float(t['low'] or t['price'] or 0) <= tp:
            hit, ex = True, tp
            break
            
    if not hit:
        cur.execute(f"SELECT time, price, high, low, close FROM scrapdata WHERE date = '{d}' AND stockname IN ('{s}', '\"{s}\"', '{s} ') AND time >= '{d} 09:40:00' AND time <= '{d} 09:41:59' ORDER BY time DESC LIMIT 1")
        exit_tick = cur.fetchone()
        if not exit_tick:
            conn.close()
            return {'net_pnl': 0.0, 'valid': False}
        ex = float(exit_tick['close'] or exit_tick['price'])
        
    gross = (en - ex) * qty
    taxes = get_kotak_mis_charges(qty, en, ex)
    net = round(gross - taxes, 2)
    conn.close()
    return {'year': row['year'], 'net_pnl': net, 'valid': True}

print("2. Querying exact 09:15 to 09:40 ticks from Cash EQ Database...")
results_arr = []
with ThreadPoolExecutor(max_workers=20) as executor:
    futures = [executor.submit(process_trade, r) for _, r in top4.iterrows()]
    for f in futures:
        res = f.result()
        if res['valid']: results_arr.append(res)

valid_df = pd.DataFrame(results_arr)
win_rate = len(valid_df[valid_df['net_pnl'] > 0]) / len(valid_df) * 100
total_pnl = valid_df['net_pnl'].sum()

print("\n=========================================")
print(" 09:15 MODEL WITH 09:40 SQUARE OFF (Cash) ")
print("=========================================")
yoy = valid_df.groupby('year')['net_pnl'].sum()
for yr, pnl in yoy.items():
    print(f"{yr} | Profit: Rs {pnl:,.2f}")
print("=========================================")
print(f"Total Valid Trades: {len(valid_df)}")
print(f"Win Rate: {win_rate:.2f}%")
print(f"TOTAL EXACT PROFIT: ₹ {total_pnl:,.2f}")
