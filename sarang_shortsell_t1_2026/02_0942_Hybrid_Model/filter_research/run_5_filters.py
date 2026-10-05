import pandas as pd
import yfinance as yf

# Macro Nifty
tickers = {'NIFTY': '^NSEI'}
data = yf.download(list(tickers.values()), start='2018-01-01', end='2026-12-31', progress=False)
df_close = data['Close'].reset_index()
df_open = data['Open'].reset_index()
dates = pd.date_range(start='2018-01-01', end='2026-12-31', freq='B')
features = pd.DataFrame({'date': dates})
features['date_str'] = features['date'].dt.strftime('%Y-%m-%d')
features = features.merge(df_close[['Date', '^NSEI']].rename(columns={'Date':'date','^NSEI':'nifty_close'}), on='date', how='left')
features = features.merge(df_open[['Date', '^NSEI']].rename(columns={'Date':'date','^NSEI':'nifty_open'}), on='date', how='left')
features['nifty_gap'] = ((features['nifty_open'] / features['nifty_close'].shift(1)) - 1) * 100
features['nifty_gap'] = features['nifty_gap'].fillna(0)

pnl = pd.read_csv('../0942_verified_pnl_sheet.csv')
pnl['Year'] = pd.to_datetime(pnl['Date']).dt.year
pnl['Stock_clean'] = pnl['Stock'].astype(str).str.strip().str.upper()

df = pd.read_csv('../data/short_sell_ml_dataset_v5_scratch.csv.gz', low_memory=False)
df['clean_stock'] = df['clean_stock'].astype(str).str.strip().str.upper()

# Merge
merged = pnl.merge(df[['date_str','clean_stock','prev_close', 'prev_intraday_vwap_gap']], left_on=['Date','Stock_clean'], right_on=['date_str','clean_stock'], how='inner')
merged = merged.drop_duplicates(subset=['Date','Stock_clean'])
merged['pct'] = (merged['Sell_Price'] - merged['prev_close']) / merged['prev_close'] * 100
merged = merged.merge(features[['date_str','nifty_gap']], on='date_str', how='left')
merged['DayOfWeek'] = pd.to_datetime(merged['Date']).dt.dayofweek

r1_mask = merged['pct'] >= -1.0
r2_mask = ~((merged['nifty_gap'] < -0.5) & (merged['pct'] < -0.5))
r3_mask = ~((merged['DayOfWeek'] == 0) & (merged['pct'] < -0.5))
r5_mask = merged['prev_intraday_vwap_gap'] >= -0.52

baseline = merged
after_3f = merged[r1_mask & r2_mask & r3_mask]
after_5f = merged[r1_mask & r2_mask & r3_mask & r5_mask]

print("Year  | Baseline (0F) | After 3 Filters | After 4 Filters (+VWAP) ")
print("-" * 65)
tot_base, tot_3f, tot_5f = 0, 0, 0
for year in sorted(merged['Year'].unique()):
    b  = baseline[baseline['Year'] == year]['Net_PnL'].sum()
    f3 = after_3f[after_3f['Year'] == year]['Net_PnL'].sum()
    f5 = after_5f[after_5f['Year'] == year]['Net_PnL'].sum()
    tot_base += b; tot_3f += f3; tot_5f += f5
    print(f"{year}  | ₹ {b:>11,.0f} | ₹ {f3:>13,.0f} | ₹ {f5:>13,.0f}")
print("=" * 65)
print(f"TOTAL | ₹ {tot_base:>11,.0f} | ₹ {tot_3f:>13,.0f} | ₹ {tot_5f:>13,.0f}")
