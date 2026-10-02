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

pnl = pd.read_csv('0942_verified_pnl_sheet.csv')
pnl['Year'] = pd.to_datetime(pnl['Date']).dt.year
pnl['Stock_clean'] = pnl['Stock'].astype(str).str.strip().str.upper()

df = pd.read_csv('data/short_sell_ml_dataset_v5_scratch.csv.gz', low_memory=False)
df['clean_stock'] = df['clean_stock'].astype(str).str.strip().str.upper()

# Merge
merged = pnl.merge(df[['date_str','clean_stock','prev_close']], left_on=['Date','Stock_clean'], right_on=['date_str','clean_stock'], how='inner')
merged = merged.drop_duplicates(subset=['Date','Stock_clean'])
merged['pct'] = (merged['Sell_Price'] - merged['prev_close']) / merged['prev_close'] * 100
merged = merged.merge(features[['date_str','nifty_gap']], on='date_str', how='left')
merged['DayOfWeek'] = pd.to_datetime(merged['Date']).dt.dayofweek

r1_mask = merged['pct'] >= -1.0
r2_mask = ~((merged['nifty_gap'] < -0.5) & (merged['pct'] < -0.5))
r3_mask = ~((merged['DayOfWeek'] == 0) & (merged['pct'] < -0.5))

filtered = merged[r1_mask & r2_mask & r3_mask]

print("\n==========================================================")
print(" 🏆 09:40 HUBER (MONTHLY RETRAINING) FILTERED RESULTS")
print("==========================================================")
for year in sorted(filtered['Year'].unique()):
    sub = filtered[filtered['Year'] == year]
    print(f"  {year}: Rs {sub['Net_PnL'].sum()/100000:6.2f} L | {(sub['Net_PnL']>0).mean()*100:.1f}% Win | {len(sub)} trades")
print("----------------------------------------------------------")
print(f"  TOTAL: Rs {filtered['Net_PnL'].sum()/100000:.2f} Lakhs")
print("==========================================================")
