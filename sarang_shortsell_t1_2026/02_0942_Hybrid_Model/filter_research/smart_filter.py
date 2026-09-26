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

# Original Base -1% Filter
base_filtered = merged[merged['pct'] >= -1.0]

# Smart Filter:
# 1. pct >= -1.0 ALWAYS
# 2. IF nifty < -0.5, THEN pct >= -0.5
def apply_smart_filter(row):
    if row['pct'] < -1.0: return False
    if row['nifty_gap'] < -0.5 and row['pct'] < -0.5: return False
    return True

smart_filtered = merged[merged.apply(apply_smart_filter, axis=1)]

print("=================================================================================================")
print("🧠 SMART FILTER: Dynamic Threshold Based on Nifty")
print("=================================================================================================")
print("Rule: Normally skip stock < -1.0%. But if Nifty < -0.5%, tighten rule to skip stock < -0.5%.")
print("-------------------------------------------------------------------------------------------------")
print(f"{'Year':<5} | {'Base (Stock -1%)':<16} | {'New PnL':<15} | {'Delta':<13} | {'Trades':<6} | {'Skipped'}")
print("-" * 97)

total_base = 0
total_new = 0
total_skipped = 0
total_trades = 0

for year in sorted(merged['Year'].unique()):
    b_data = base_filtered[base_filtered['Year'] == year]
    s_data = smart_filtered[smart_filtered['Year'] == year]
    
    b_pnl = b_data['Net_PnL'].sum()
    s_pnl = s_data['Net_PnL'].sum()
    
    delta = s_pnl - b_pnl
    skip = len(b_data) - len(s_data)
    
    total_base += b_pnl
    total_new += s_pnl
    total_skipped += skip
    total_trades += len(b_data)
    
    delta_str = f"{'+' if delta>0 else ''}₹{delta:>9,.0f}"
    
    print(f"{year:<5} | ₹ {b_pnl:>13,.0f} | ₹ {s_pnl:>12,.0f} | {delta_str:<13} | {len(b_data):<6} | {skip:<7}")

total_delta = total_new - total_base
print("=" * 97)
print(f"TOTAL | ₹ {total_base:>13,.0f} | ₹ {total_new:>12,.0f} | {'+' if total_delta>0 else ''}₹{total_delta:>9,.0f} | {total_trades:<6} | {total_skipped:<7}")
