import pandas as pd
import yfinance as yf

# Fetch Nifty
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
macro = features[['date_str', 'nifty_gap']]

# Load Data
pnl = pd.read_csv('0942_verified_pnl_sheet.csv')
pnl['Year'] = pd.to_datetime(pnl['Date']).dt.year
pnl['Stock_clean'] = pnl['Stock'].astype(str).str.strip().str.upper()

df = pd.read_csv('data/short_sell_ml_dataset_v5_scratch.csv', low_memory=False)
df['clean_stock'] = df['clean_stock'].astype(str).str.strip().str.upper()

merged = pnl.merge(df[['date_str', 'clean_stock', 'prev_close']], left_on=['Date', 'Stock_clean'], right_on=['date_str', 'clean_stock'], how='inner')
merged = merged.drop_duplicates(subset=['Date', 'Stock_clean'])
merged['pct'] = (merged['Sell_Price'] - merged['prev_close']) / merged['prev_close'] * 100
merged = merged.merge(macro, on='date_str', how='left')

# We apply the -1.0% stock filter first because we proved it is unconditionally good
# (We could also test without it, but let's test on the already optimized base)
merged = merged[merged['pct'] >= -1.0]

is_df = merged[merged['Year'] <= 2025]
oos_df = merged[merged['Year'] == 2026]
base_is = is_df['Net_PnL'].sum()
base_oos = oos_df['Net_PnL'].sum()

print("==========================================================================")
print("🔍 SWEEPING NIFTY GAP THRESHOLDS (ON TOP OF -1.0% STOCK FILTER)")
print("==========================================================================")
print(f"{'Condition (Skip if Nifty < X%)':<35} | {'IS Delta':<12} | {'OOS Delta':<12}")
print("-" * 74)

best_threshold = None
best_is_delta = -float('inf')

for thresh in [-2.0, -1.5, -1.0, -0.75, -0.5, -0.25, 0.0, 0.25, 0.5]:
    # Filter: Keep trades where Nifty Gap >= thresh (i.e. Skip if < thresh)
    filt_is = is_df[is_df['nifty_gap'] >= thresh]
    filt_oos = oos_df[oos_df['nifty_gap'] >= thresh]
    
    is_delta = filt_is['Net_PnL'].sum() - base_is
    oos_delta = filt_oos['Net_PnL'].sum() - base_oos
    
    print(f"Skip if Nifty Gap < {thresh:>5.2f}%{' ':>11} | {'+' if is_delta>0 else ''}₹{is_delta:>9,.0f} | {'+' if oos_delta>0 else ''}₹{oos_delta:>9,.0f}")
    
    if is_delta > best_is_delta:
        best_is_delta = is_delta
        best_threshold = thresh

print(f"\n🏆 BEST THRESHOLD: Skip if Nifty < {best_threshold}%")
print("==========================================================================")
print(f"📅 YEAR-WISE PNL FOR BEST NIFTY THRESHOLD (< {best_threshold}%)")
print("==========================================================================")
print(f"{'Year':<5} | {'Base (Stock -1%)':<18} | {'New PnL (+ Nifty)':<18} | {'Delta':<12}")
print("-" * 74)

for year in sorted(merged['Year'].unique()):
    yr_data = merged[merged['Year'] == year]
    base_pnl = yr_data['Net_PnL'].sum()
    
    filt_data = yr_data[yr_data['nifty_gap'] >= best_threshold]
    filt_pnl = filt_data['Net_PnL'].sum()
    
    delta = filt_pnl - base_pnl
    
    print(f"{year:<5} | ₹ {base_pnl:>15,.0f} | ₹ {filt_pnl:>15,.0f} | {'+' if delta>0 else ''}₹ {delta:>9,.0f}")

