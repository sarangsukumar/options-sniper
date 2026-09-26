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

# Load PnL and Stock
pnl = pd.read_csv('0942_verified_pnl_sheet.csv')
pnl['Year'] = pd.to_datetime(pnl['Date']).dt.year
pnl['Stock_clean'] = pnl['Stock'].astype(str).str.strip().str.upper()

df = pd.read_csv('data/short_sell_ml_dataset_v5_scratch.csv', low_memory=False)
df['clean_stock'] = df['clean_stock'].astype(str).str.strip().str.upper()

merged = pnl.merge(df[['date_str', 'clean_stock', 'prev_close']], left_on=['Date', 'Stock_clean'], right_on=['date_str', 'clean_stock'], how='inner')
merged = merged.drop_duplicates(subset=['Date', 'Stock_clean'])
merged['pct'] = (merged['Sell_Price'] - merged['prev_close']) / merged['prev_close'] * 100
merged = merged.merge(features[['date_str', 'nifty_gap']], on='date_str', how='left')

print("=================================================================================================")
print("🛡️ COMBINED STRATEGY: Skip Stock < -1.0% AND Skip Nifty < -0.5%")
print("=================================================================================================")
print(f"{'Year':<5} | {'Base PnL':<15} | {'New PnL':<15} | {'Delta':<13} | {'Total':<6} | {'Skipped':<7} | {'% Skip'}")
print("-" * 97)

total_base = 0
total_new = 0
total_trades = 0
total_skipped = 0

for year in sorted(merged['Year'].unique()):
    yr_data = merged[merged['Year'] == year]
    
    # Absolute Baseline (No filters)
    base_pnl = yr_data['Net_PnL'].sum()
    base_count = len(yr_data)
    
    # Combined Filter
    filt_data = yr_data[(yr_data['pct'] >= -1.0) & (yr_data['nifty_gap'] >= -0.5)]
    new_pnl = filt_data['Net_PnL'].sum()
    new_count = len(filt_data)
    
    delta = new_pnl - base_pnl
    skipped = base_count - new_count
    pct_skip = (skipped / base_count) * 100 if base_count > 0 else 0
    
    total_base += base_pnl
    total_new += new_pnl
    total_trades += base_count
    total_skipped += skipped
    
    delta_str = f"{'+' if delta>0 else ''}₹{delta:>9,.0f}"
    
    print(f"{year:<5} | ₹ {base_pnl:>12,.0f} | ₹ {new_pnl:>12,.0f} | {delta_str:<13} | {base_count:<6} | {skipped:<7} | {pct_skip:>4.1f}%")

total_delta = total_new - total_base
print("=" * 97)
print(f"TOTAL | ₹ {total_base:>12,.0f} | ₹ {total_new:>12,.0f} | {'+' if total_delta>0 else ''}₹{total_delta:>9,.0f} | {total_trades:<6} | {total_skipped:<7} | {(total_skipped/total_trades)*100:>4.1f}%")
