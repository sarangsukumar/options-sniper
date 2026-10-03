import pandas as pd
import numpy as np
import lightgbm as lgb
import warnings
warnings.filterwarnings('ignore')

print("Loading dataset...")
df = pd.read_csv('/home/ubuntu/v5_from_scratch/data/short_sell_ml_dataset_v5_scratch.csv', low_memory=False)

# Full day short: Entry at 09:15 (morning_open), Exit at 14:45 (short_exit_price)
df['full_day_short_pnl'] = df['morning_open'] - df['short_exit_price']
df['target'] = (df['full_day_short_pnl'] > 0).astype(int)

# Features: ONLY prev_intraday_* and gap_0907_pct (or Gap_Pct)
features = [c for c in df.columns if c.startswith('prev_intraday_')]
if 'gap_0907_pct' in df.columns:
    features.append('gap_0907_pct')
elif 'Gap_Pct' in df.columns:
    features.append('Gap_Pct')

df = df.dropna(subset=features + ['target', 'full_day_short_pnl', 'morning_open', 'short_exit_price'])
df['date_dt'] = pd.to_datetime(df['short_sell_date'])
df = df.sort_values('date_dt').reset_index(drop=True)

start_year = 2020
print(f"Training Model 09:15 to 14:45 with {len(features)} Look-Ahead Free Features...")

results = []
for year in range(start_year, 2027):
    train = df[df['date_dt'].dt.year < year]
    test = df[df['date_dt'].dt.year == year]
    if test.empty: continue
    
    X_train, y_train = train[features], train['target']
    X_test = test[features]
    
    model = lgb.LGBMClassifier(n_estimators=100, learning_rate=0.05, max_depth=5, random_state=42)
    model.fit(X_train, y_train)
    
    test = test.copy()
    test['prob'] = model.predict_proba(X_test)[:, 1]
    
    daily_picks = test.sort_values(['short_sell_date', 'prob'], ascending=[True, False]).groupby('short_sell_date').head(4)
    
    for _, row in daily_picks.iterrows():
        cap = 100000.0 * 5.0
        en = row['morning_open']
        ex = row['short_exit_price']
        if pd.isna(en) or pd.isna(ex) or en <= 0: continue
        qty = int(cap // en)
        gross = (en - ex) * qty
        # approximate strict charges: 0 brokerage, 0.025% STT, 0.003% Txn, 18% GST -> approx ~0.035% of turnover
        turnover = (en + ex) * qty
        charges = turnover * 0.00035 
        net = gross - charges
        results.append({'date': row['short_sell_date'], 'stock': row['stockname'], 'gross': gross, 'net': net})
        
res_df = pd.DataFrame(results)
res_df['year'] = pd.to_datetime(res_df['date']).dt.year

print("\n| Year | Trades | Win Rate | Gross PnL | NET PnL |")
print("|------|--------|----------|-----------|---------|")
for y, grp in res_df.groupby('year'):
    wins = len(grp[grp['net'] > 0])
    trd = len(grp)
    wr = (wins/trd)*100
    gr = grp['gross'].sum() / 100000
    nt = grp['net'].sum() / 100000
    print(f"| {y} | {trd} | {wr:.1f}% | ₹{gr:.2f}L | ₹{nt:.2f}L |")

wins = len(res_df[res_df['net'] > 0])
trd = len(res_df)
wr = (wins/trd)*100
gr = res_df['gross'].sum() / 100000
nt = res_df['net'].sum() / 100000
print(f"| TOTAL | {trd} | {wr:.1f}% | ₹{gr:.2f}L | ₹{nt:.2f}L |")
