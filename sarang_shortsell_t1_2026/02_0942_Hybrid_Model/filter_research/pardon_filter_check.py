import pandas as pd
import yfinance as yf

# Load Data
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

pnl = pd.read_csv('0942_verified_pnl_sheet.csv')
pnl['Year'] = pd.to_datetime(pnl['Date']).dt.year
pnl['Stock_clean'] = pnl['Stock'].astype(str).str.strip().str.upper()

df = pd.read_csv('data/short_sell_ml_dataset_v5_scratch.csv', low_memory=False)
df['clean_stock'] = df['clean_stock'].astype(str).str.strip().str.upper()

merged = pnl.merge(df[['date_str', 'clean_stock', 'prev_close']], left_on=['Date', 'Stock_clean'], right_on=['date_str', 'clean_stock'], how='inner')
merged = merged.drop_duplicates(subset=['Date', 'Stock_clean'])
merged['pct'] = (merged['Sell_Price'] - merged['prev_close']) / merged['prev_close'] * 100
merged = merged.merge(features[['date_str', 'nifty_gap']], on='date_str', how='left')

# Isolate ONLY the trades we currently THROW AWAY (Stock < -1.0%)
trashed_trades = merged[merged['pct'] < -1.0]

print("=================================================================================================")
print("🕵️ EXAMINING TRASHED TRADES (Stock < -1.0%)")
print("=================================================================================================")
print(f"Total trades normally thrown away: {len(trashed_trades)}")
print(f"Total PnL of these trashed trades: ₹ {trashed_trades['Net_PnL'].sum():,.0f} (Negative means throwing them away saved money)")
print("-------------------------------------------------------------------------------------------------")

print("\nWhat if Nifty is POSITIVE vs NEGATIVE on these days?")

bins = [-100, -0.5, 0, 0.5, 100]
labels = ['Nifty < -0.5% (Very Red)', 'Nifty -0.5% to 0% (Red)', 'Nifty 0% to +0.5% (Green)', 'Nifty > +0.5% (Very Green)']
trashed_trades['Nifty_Bin'] = pd.cut(trashed_trades['nifty_gap'], bins=bins, labels=labels)
nifty_bins = trashed_trades.groupby('Nifty_Bin')['Net_PnL'].agg(['sum', 'count', 'mean']).reset_index()

for _, r in nifty_bins.iterrows():
    print(f"{r['Nifty_Bin']:<26} | Trades: {r['count']:<4} | PnL: ₹ {r['sum']:>10,.0f} | Avg/Trade: ₹ {r['mean']:>6,.0f}")

print("\n=================================================================================================")
print("📅 Let's see year-by-year if we 'PARDON' trades where Nifty >= 0")
print("=================================================================================================")

pardon_condition = trashed_trades['nifty_gap'] >= 0
pardoned_trades = trashed_trades[pardon_condition]

print(f"Total Pardoned Trades: {len(pardoned_trades)}")
print(f"Total Pardoned PnL   : ₹ {pardoned_trades['Net_PnL'].sum():,.0f}")
print("-" * 50)

for year in sorted(trashed_trades['Year'].unique()):
    yr_pardoned = pardoned_trades[pardoned_trades['Year'] == year]
    pnl_val = yr_pardoned['Net_PnL'].sum()
    print(f"Year {year}: {len(yr_pardoned):<3} trades pardoned | PnL: {'+' if pnl_val>0 else ''}₹ {pnl_val:>9,.0f}")

