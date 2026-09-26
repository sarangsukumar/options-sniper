import pandas as pd
import yfinance as yf
import os

print("Fetching Nifty Gap data...")
tickers = {'NIFTY': '^NSEI'}
data = yf.download(list(tickers.values()), start='2018-01-01', end='2026-12-31', progress=False)

df_close = data['Close'].reset_index()
df_open = data['Open'].reset_index()

dates = pd.date_range(start='2018-01-01', end='2026-12-31', freq='B')
features = pd.DataFrame({'date': dates})
features['date_str'] = features['date'].dt.strftime('%Y-%m-%d')

nifty_c = df_close[['Date', '^NSEI']].rename(columns={'Date': 'date', '^NSEI': 'nifty_close'})
nifty_o = df_open[['Date', '^NSEI']].rename(columns={'Date': 'date', '^NSEI': 'nifty_open'})
features = features.merge(nifty_c, on='date', how='left').merge(nifty_o, on='date', how='left')
features['nifty_gap'] = ((features['nifty_open'] / features['nifty_close'].shift(1)) - 1) * 100
features['nifty_gap'] = features['nifty_gap'].fillna(0)

macro = features[['date_str', 'nifty_gap']]

# Load PnL and Stock Data
pnl = pd.read_csv('0942_verified_pnl_sheet.csv')
pnl['Year'] = pd.to_datetime(pnl['Date']).dt.year
pnl['Stock_clean'] = pnl['Stock'].astype(str).str.strip().str.upper()

df = pd.read_csv('data/short_sell_ml_dataset_v5_scratch.csv', low_memory=False)
df['clean_stock'] = df['clean_stock'].astype(str).str.strip().str.upper()

merged = pnl.merge(df[['date_str', 'clean_stock', 'prev_close']], left_on=['Date', 'Stock_clean'], right_on=['date_str', 'clean_stock'], how='inner')
merged = merged.drop_duplicates(subset=['Date', 'Stock_clean'])
merged['pct'] = (merged['Sell_Price'] - merged['prev_close']) / merged['prev_close'] * 100

# Merge Macro
merged = merged.merge(macro, on='date_str', how='left')

is_df = merged[merged['Year'] <= 2025]
oos_df = merged[merged['Year'] == 2026]

print("\n==========================================================================================")
print("📊 NIFTY GAP RELATIONSHIP WITH STOCK PERCENTAGE (-1.0% FILTER)")
print("==========================================================================================")

# Apply the -1.0% stock filter first
filt_is = is_df[is_df['pct'] >= -1.0]
filt_oos = oos_df[oos_df['pct'] >= -1.0]

for condition, name in [(filt_is['nifty_gap'] >= 0, "Nifty Gap UP (>= 0%)"), 
                        (filt_is['nifty_gap'] < 0, "Nifty Gap DOWN (< 0%)")]:
    
    subset = filt_is[condition]
    print(f"\n[{name}] - In-Sample (2020-2025)")
    print(f"Total Trades : {len(subset)}")
    print(f"Total PnL    : ₹ {subset['Net_PnL'].sum():>10,.0f}")
    if len(subset) > 0:
        print(f"Avg PnL/Trade: ₹ {subset['Net_PnL'].mean():>10,.0f}")

print("\n------------------------------------------------------------------------------------------")

for condition, name in [(filt_oos['nifty_gap'] >= 0, "Nifty Gap UP (>= 0%)"), 
                        (filt_oos['nifty_gap'] < 0, "Nifty Gap DOWN (< 0%)")]:
    
    subset = filt_oos[condition]
    print(f"\n[{name}] - Out-Of-Sample (2026)")
    print(f"Total Trades : {len(subset)}")
    print(f"Total PnL    : ₹ {subset['Net_PnL'].sum():>10,.0f}")
    if len(subset) > 0:
        print(f"Avg PnL/Trade: ₹ {subset['Net_PnL'].mean():>10,.0f}")

print("==========================================================================================")
