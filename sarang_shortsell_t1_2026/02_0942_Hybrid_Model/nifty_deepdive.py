import pandas as pd
import yfinance as yf

# Load Nifty
tickers = {'NIFTY': '^NSEI'}
data = yf.download(list(tickers.values()), start='2018-01-01', end='2026-12-31', progress=False)
df_close = data['Close'].reset_index()
df_open = data['Open'].reset_index()
dates = pd.date_range(start='2018-01-01', end='2026-12-31', freq='B')
features = pd.DataFrame({'date': dates})
features['date_str'] = features['date'].dt.strftime('%Y-%m-%d')
features = features.merge(df_close[['Date', '^NSEI']].rename(columns={'Date': 'date', '^NSEI': 'nifty_close'}), on='date', how='left')
features = features.merge(df_open[['Date', '^NSEI']].rename(columns={'Date': 'date', '^NSEI': 'nifty_open'}), on='date', how='left')
features['nifty_gap'] = ((features['nifty_open'] / features['nifty_close'].shift(1)) - 1) * 100
features['nifty_gap'] = features['nifty_gap'].fillna(0)

# Load PnL and Stock Data
pnl = pd.read_csv('0942_verified_pnl_sheet.csv')
pnl['Year'] = pd.to_datetime(pnl['Date']).dt.year
pnl['Stock_clean'] = pnl['Stock'].astype(str).str.strip().str.upper()

df = pd.read_csv('data/short_sell_ml_dataset_v5_scratch.csv', low_memory=False)
df['clean_stock'] = df['clean_stock'].astype(str).str.strip().str.upper()

merged = pnl.merge(df[['date_str', 'clean_stock', 'prev_close']], left_on=['Date', 'Stock_clean'], right_on=['date_str', 'clean_stock'], how='inner')
merged = merged.drop_duplicates(subset=['Date', 'Stock_clean'])
merged['pct'] = (merged['Sell_Price'] - merged['prev_close']) / merged['prev_close'] * 100
merged = merged.merge(features[['date_str', 'nifty_gap']], on='date_str', how='left')

# Base -1% Stock filter is applied
merged = merged[merged['pct'] >= -1.0]

# Add a Rank column for each day
# Since pnl dataframe has them in order (assuming they were logged in rank order, but let's re-rank by Net_PnL or just order of appearance)
# Actually, the original dataset has `pred`. We need `pred` to get the true rank!
preds = pd.read_csv('0942_predictions.csv')
preds['clean_stock'] = preds['clean_stock'].astype(str).str.strip().str.upper()
merged = merged.merge(preds, on=['date_str', 'clean_stock'], how='left')

# Rank by prediction score per day
merged['Rank'] = merged.groupby('date_str')['pred'].rank(ascending=False, method='first')

# Isolate ONLY the "Dangerous" days (Nifty < -0.5%)
danger_days = merged[merged['nifty_gap'] < -0.5]

print("==========================================================================")
print("🔍 DEEP DIVE: TRADES ON NIFTY < -0.5% DAYS (2020 - 2026)")
print("==========================================================================")
print(f"Total Trades on these days: {len(danger_days)}")
print(f"Total PnL on these days   : ₹ {danger_days['Net_PnL'].sum():,.0f}")
print("--------------------------------------------------------------------------")

# Hypothesis 1: PnL by Rank
print("📊 1. PERFORMANCE BY PREDICTION RANK (1 to 4)")
ranks = danger_days.groupby('Rank')['Net_PnL'].agg(['sum', 'count', 'mean']).reset_index()
for _, r in ranks.iterrows():
    print(f"Rank {int(r['Rank'])}: Trades: {r['count']:<4} | PnL: ₹ {r['sum']:>10,.0f} | Avg/Trade: ₹ {r['mean']:>6,.0f}")

# Hypothesis 2: PnL by Individual Stock % (Relative Strength/Weakness)
print("\n📊 2. PERFORMANCE BY INDIVIDUAL STOCK GAP (Relative to Market)")
bins = [-1.0, -0.5, 0, 0.5, 1.0, 100]
labels = ['-1% to -0.5%', '-0.5% to 0%', '0% to +0.5%', '+0.5% to +1.0%', '> +1.0%']
danger_days['Stock_Bin'] = pd.cut(danger_days['pct'], bins=bins, labels=labels)
stk_bins = danger_days.groupby('Stock_Bin')['Net_PnL'].agg(['sum', 'count', 'mean']).reset_index()
for _, r in stk_bins.iterrows():
    print(f"Gap {r['Stock_Bin']:<15}: Trades: {r['count']:<4} | PnL: ₹ {r['sum']:>10,.0f} | Avg/Trade: ₹ {r['mean']:>6,.0f}")

print("==========================================================================")
