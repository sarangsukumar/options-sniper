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

# SUPREME FILTER:
def apply_supreme_filter(row):
    # Rule 1: If market is crashing (< -0.5%), be extremely strict (stock must be > -0.5%)
    if row['nifty_gap'] < -0.5:
        return row['pct'] >= -0.5
        
    # Rule 2: If market is slightly red (-0.5% to 0%), allow EVERYTHING
    # The tailwind is perfect, even heavily gapping down stocks work well here
    if -0.5 <= row['nifty_gap'] < 0:
        return True
        
    # Rule 3: If market is GREEN (>= 0%), use standard strict rule (stock must be > -1.0%)
    if row['nifty_gap'] >= 0:
        return row['pct'] >= -1.0

supreme_filtered = merged[merged.apply(apply_supreme_filter, axis=1)]

print("=================================================================================================")
print("👑 SUPREME FILTER: The Perfect Matrix")
print("=================================================================================================")
print(f"{'Year':<5} | {'Raw Baseline PnL':<18} | {'Supreme Filter PnL':<18} | {'Total Profit Gained':<20}")
print("-" * 85)

total_base = 0
total_new = 0
total_skipped = 0
total_trades = 0

for year in sorted(merged['Year'].unique()):
    b_data = merged[merged['Year'] == year]
    s_data = supreme_filtered[supreme_filtered['Year'] == year]
    
    b_pnl = b_data['Net_PnL'].sum()
    s_pnl = s_data['Net_PnL'].sum()
    
    delta = s_pnl - b_pnl
    skip = len(b_data) - len(s_data)
    
    total_base += b_pnl
    total_new += s_pnl
    total_skipped += skip
    total_trades += len(b_data)
    
    delta_str = f"{'+' if delta>0 else ''}₹{delta:>9,.0f}"
    
    print(f"{year:<5} | ₹ {b_pnl:>15,.0f} | ₹ {s_pnl:>15,.0f} | {delta_str:<20} (Skipped {skip})")

total_delta = total_new - total_base
print("=" * 85)
print(f"TOTAL | ₹ {total_base:>15,.0f} | ₹ {total_new:>15,.0f} | {'+' if total_delta>0 else ''}₹{total_delta:>9,.0f} (Total Skipped {total_skipped})")
