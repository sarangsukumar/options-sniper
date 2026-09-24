import pandas as pd
import yfinance as yf

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
merged = merged[merged['pct'] >= -1.0]

print("==========================================================================")
print("📅 YEAR-WISE PNL FOR NIFTY THRESHOLD (< -0.5%)")
print("==========================================================================")
print(f"{'Year':<5} | {'Base (Stock -1%)':<18} | {'New PnL (+ Nifty)':<18} | {'Delta':<12}")
print("-" * 74)

for year in sorted(merged['Year'].unique()):
    yr_data = merged[merged['Year'] == year]
    base_pnl = yr_data['Net_PnL'].sum()
    filt_data = yr_data[yr_data['nifty_gap'] >= -0.5]
    filt_pnl = filt_data['Net_PnL'].sum()
    delta = filt_pnl - base_pnl
    print(f"{year:<5} | ₹ {base_pnl:>15,.0f} | ₹ {filt_pnl:>15,.0f} | {'+' if delta>0 else ''}₹ {delta:>9,.0f}")
