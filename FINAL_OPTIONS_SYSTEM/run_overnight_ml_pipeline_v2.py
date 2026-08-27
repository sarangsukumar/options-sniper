import mysql.connector, pandas as pd, numpy as np, os, time
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.metrics import classification_report
from datetime import datetime, timedelta

print("Loading Database...")
db = mysql.connector.connect(host='localhost', user='root', password='root', database='markets')
c = db.cursor(dictionary=True)

print("Loading Futures...")
fut = pd.read_csv('/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/historical_models/output/trades_dynamic_threshold.csv')
fut['rank'] = fut.groupby('date').cumcount() + 1
r13 = fut[(pd.to_datetime(fut['date']).dt.year >= 2024) & (fut['rank'].isin([1, 3]))].copy()
stocks = "', '".join(r13['stock'].unique())

print("Loading Options from MySQL (PE & CE Batch Query)...")
# First find all valid dates
c.execute(f"SELECT DISTINCT DATE(datetime) as dt FROM scrapdata_options WHERE stock_code IN ('{stocks}')")
all_db_dates = sorted([str(r['dt']) for r in c.fetchall()])

stk_days = {}
for s in r13['stock'].unique(): stk_days[s] = all_db_dates # Approx for fast lookup

valid_trades = []
req_dates = set()
for _, r in r13.iterrows():
    s, d = r['stock'], r['date']
    days = [x for x in all_db_dates if x > d]
    if not days: continue
    d1 = days[0]
    valid_trades.append((s, d, d1))
    req_dates.add(d)
    req_dates.add(d1)

dates_str = "', '".join(req_dates)
c.execute(f"SELECT stock_code, DATE(datetime) as dt, TIME(datetime) as tm, strike_price, `close`, `open`, `right` FROM scrapdata_options WHERE stock_code IN ('{stocks}') AND DATE(datetime) IN ('{dates_str}') AND ( (TIME(datetime) BETWEEN '15:16:00' AND '15:36:00') OR (TIME(datetime) BETWEEN '09:15:00' AND '09:35:00') )")
opt_data = c.fetchall()
c.close()
db.close()

pe_map, ce_map = {}, {}
for r in opt_data:
    stk, d, sp = r['stock_code'], str(r['dt']), float(r['strike_price'])
    t_str = str(r['tm'])
    if len(t_str) == 7: t_str = "0" + t_str
    px = float(r['close']) if r['close'] else float(r['open']) if r['open'] else 0
    if px > 0:
        if r['right'] == 'Put': pe_map[(stk, d, t_str, sp)] = px
        else: ce_map[(stk, d, t_str, sp)] = px

def get_strike_step(price):
    if price > 2500: return 50
    if price > 1000: return 20
    if price > 500: return 10
    if price > 100: return 5
    if price > 50: return 2.5
    return 1

print("Generating Labels (Relaxed ±10 min)...")
results = []
for stk, d, d1 in valid_trades:
    # Use CE map to find ATM price
    splist = [sp for (s, dt, t, sp) in ce_map.keys() if s==stk and dt==d and t=="15:26:00"]
    if not splist:
        # Relaxed lookup for median price
        splist = [sp for (s, dt, t, sp) in ce_map.keys() if s==stk and dt==d and "15:16" <= t <= "15:36"]
    if not splist: continue
    
    price = np.median(splist)
    step = get_strike_step(price)
    atm = round(price/step)*step
    
    def lookup(tmap, date, strike, target_time_str):
        target_dt = datetime.strptime(f"{date} {target_time_str}", "%Y-%m-%d %H:%M:%S")
        for delta in range(0, 11): # Check exact, then +/- up to 10
            for sign in [1, -1]:
                if delta == 0 and sign == -1: continue
                curr_dt = target_dt + timedelta(minutes=delta*sign)
                t_str = curr_dt.strftime("%H:%M:%S")
                if len(t_str) == 7: t_str = "0" + t_str
                if (stk, date, t_str, float(strike)) in tmap:
                    return tmap[(stk, date, t_str, float(strike))]
        return None
        
    pe_s, pe_b = atm + step, atm - (3*step)
    pe_se, pe_be = lookup(pe_map, d, pe_s, "15:26:00"), lookup(pe_map, d, pe_b, "15:26:00")
    pe_sx, pe_bx = lookup(pe_map, d1, pe_s, "09:25:00"), lookup(pe_map, d1, pe_b, "09:25:00")
    
    pe_pnl = 0
    if None not in [pe_se, pe_be, pe_sx, pe_bx]:
        pe_pnl = ((pe_se - pe_be) - (pe_sx - pe_bx)) * 1000 # Proxy relative scale
        
    ce_b, ce_s = atm - step, atm + step
    ce_be, ce_se = lookup(ce_map, d, ce_b, "15:26:00"), lookup(ce_map, d, ce_s, "15:26:00")
    ce_bx, ce_sx = lookup(ce_map, d1, ce_b, "09:25:00"), lookup(ce_map, d1, ce_s, "09:25:00")
    
    ce_pnl = 0
    if None not in [ce_be, ce_se, ce_bx, ce_sx]:
        ce_pnl = ((ce_bx - ce_sx) - (ce_be - ce_se)) * 1000
        
    if pe_pnl != 0 or ce_pnl != 0:
        results.append({'Date': d, 'Stock': stk, 'pe_pnl': pe_pnl, 'ce_pnl': ce_pnl})

labels = pd.DataFrame(results)
print(f"Generated {len(labels)} Trade Labels.")

print("Loading Intraday ML Features...")
feat = pd.read_csv('/home/ubuntu/ML/best ML/data/f11_intraday_features_all.csv')
feat.rename(columns={'Date': 'Date', 'Stock': 'Stock'}, inplace=True)
# Convert DD-MM-YYYY to YYYY-MM-DD
feat['Date'] = pd.to_datetime(feat['Date'], format='%d-%m-%Y', errors='coerce').dt.strftime('%Y-%m-%d')
merged = pd.merge(labels, feat, on=['Date', 'Stock'], how='inner')

merged['hybrid_pnl'] = merged['pe_pnl'] + merged['ce_pnl']
merged['target'] = (merged['ce_pnl'] > 0).astype(int)

fcols = ['intraday_return', 'intraday_rsi_9', 'intraday_macd', 'intraday_ema_cross', 'intraday_volatility', 'first_tick_to_1515_pct', 'intraday_bb_pct_b']
merged = merged.dropna(subset=fcols)
merged = merged.sort_values('Date')

print("Running Walk-Forward ML Backtest...")
months = pd.to_datetime(merged['Date']).dt.to_period('M').unique()

ml_pnl = 0
hybrid_pnl = 0
base_put_pnl = 0
total_trades = 0

for i in range(3, len(months)):
    train_months = months[:i]
    test_month = months[i]
    
    train = merged[pd.to_datetime(merged['Date']).dt.to_period('M').isin(train_months)]
    test = merged[pd.to_datetime(merged['Date']).dt.to_period('M') == test_month]
    
    if len(train) < 50 or len(test) == 0: continue
    
    rf = GradientBoostingClassifier(n_estimators=100, max_depth=3, random_state=42)
    rf.fit(train[fcols], train['target'])
    preds = rf.predict(test[fcols])
    
    for idx, (_, row) in enumerate(test.iterrows()):
        pred_is_ce = preds[idx]
        actual_ml = row['pe_pnl'] + (row['ce_pnl'] if pred_is_ce else 0)
        ml_pnl += actual_ml
        hybrid_pnl += row['hybrid_pnl']
        base_put_pnl += row['pe_pnl']
        total_trades += 1

print("=============================================================")
print("  ML DYNAMIC SPREAD SELECTOR vs PURE HYBRID (OUT OF SAMPLE)  ")
print("=============================================================")
print(f"Total OOS Test Trades Evaluated: {total_trades}")
print(f"1. Base Put Spread Only PnL:   ₹{base_put_pnl:,.2f}")
print(f"2. Static Dual Hybrid PnL:     ₹{hybrid_pnl:,.2f}")
print(f"3. 🤖 ML Selected Hybrid PnL:  ₹{ml_pnl:,.2f}")
print("-------------------------------------------------------------")
if ml_pnl > hybrid_pnl:
    print(f"✅ ML MODEL ADDED +₹{ml_pnl - hybrid_pnl:,.2f} ALPHA by avoiding bad CE days!")
else:
    print(f"❌ ML MODEL UNDERPERFORMED Hybrid by ₹{hybrid_pnl - ml_pnl:,.2f}.")
print("=============================================================")
