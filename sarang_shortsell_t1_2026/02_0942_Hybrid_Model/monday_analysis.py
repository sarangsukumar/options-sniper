import pandas as pd
import yfinance as yf

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

df = pd.read_csv('data/short_sell_ml_dataset_v5_scratch.csv', low_memory=False)
df['clean_stock'] = df['clean_stock'].astype(str).str.strip().str.upper()

merged = pnl.merge(df[['date_str','clean_stock','prev_close']], left_on=['Date','Stock_clean'], right_on=['date_str','clean_stock'], how='inner')
merged = merged.drop_duplicates(subset=['Date','Stock_clean'])
merged['pct'] = (merged['Sell_Price'] - merged['prev_close']) / merged['prev_close'] * 100
merged = merged.merge(features[['date_str','nifty_gap']], on='date_str', how='left')
merged['DayOfWeek'] = pd.to_datetime(merged['Date']).dt.dayofweek  # 0=Mon

base_is = merged[merged['Year'] <= 2025]['Net_PnL'].sum()
base_oos = merged[merged['Year'] == 2026]['Net_PnL'].sum()

mondays = merged[merged['DayOfWeek'] == 0]
non_mondays = merged[merged['DayOfWeek'] != 0]

print("==========================================================================================")
print("📅 MONDAY DEEP DIVE")
print("==========================================================================================")
print(f"Total Trades      : {len(merged)}")
print(f"Monday Trades     : {len(mondays)} ({len(mondays)/len(merged)*100:.1f}%)")
print(f"Non-Monday Trades : {len(non_mondays)}")
print("==========================================================================================")

# OPTION 1: Skip ALL Mondays
skip_all_mon = merged[merged['DayOfWeek'] != 0]
o1_is = skip_all_mon[skip_all_mon['Year'] <= 2025]['Net_PnL'].sum()
o1_oos = skip_all_mon[skip_all_mon['Year'] == 2026]['Net_PnL'].sum()

print(f"\n⛔ OPTION 1: Skip ALL Monday trades")
print(f"   Trades Skipped : {len(mondays)}")
print(f"   IS  (20-25) Delta: {'+' if o1_is-base_is > 0 else ''}₹{o1_is-base_is:>9,.0f}")
print(f"   OOS (2026)  Delta: {'+' if o1_oos-base_oos > 0 else ''}₹{o1_oos-base_oos:>9,.0f}")

# Break down Monday PnL by stock gap bucket
print(f"\n   📊 Monday PnL breakdown by Stock % gap:")
bins = [-100, -1.5, -1.0, -0.5, 0, 0.5, 1.0, 100]
labels = ['<-1.5%','-1.5 to -1%','-1% to -0.5%','-0.5% to 0%','0% to 0.5%','0.5% to 1%','>1%']
mondays_copy = mondays.copy()
mondays_copy['bin'] = pd.cut(mondays_copy['pct'], bins=bins, labels=labels)
mon_bins = mondays_copy.groupby('bin', observed=False)['Net_PnL'].agg(['sum','count','mean']).reset_index()
for _, r in mon_bins.iterrows():
    verdict = "❌ LOSERS" if r['sum'] < 0 else "✅ WINNERS"
    print(f"   {r['bin']:<15} : Trades: {int(r['count']):<4} | PnL: ₹{r['sum']:>9,.0f} | Avg: ₹{r['mean']:>6,.0f} | {verdict}")

# OPTION 2: Specific Monday Rule (skip only when stock < -0.5%)
specific_mon = merged[~((merged['DayOfWeek'] == 0) & (merged['pct'] < -0.5))]
o2_is = specific_mon[specific_mon['Year'] <= 2025]['Net_PnL'].sum()
o2_oos = specific_mon[specific_mon['Year'] == 2026]['Net_PnL'].sum()

print(f"\n🎯 OPTION 2: Specific Monday Rule — Skip ONLY if Stock < -0.5% on Monday")
print(f"   Trades Skipped : {len(merged) - len(specific_mon)}")
print(f"   IS  (20-25) Delta: {'+' if o2_is-base_is > 0 else ''}₹{o2_is-base_is:>9,.0f}")
print(f"   OOS (2026)  Delta: {'+' if o2_oos-base_oos > 0 else ''}₹{o2_oos-base_oos:>9,.0f}")

# OPTION 3: Monday vs Other days -- is Monday genuinely worse?
print("\n==========================================================================================")
print("📊 MONDAY vs OTHER DAYS: AVG PNL PER TRADE")
print("==========================================================================================")
for dow_num, dow_name in [(0,'Monday'),(1,'Tuesday'),(2,'Wednesday'),(3,'Thursday'),(4,'Friday')]:
    day_data = merged[merged['DayOfWeek'] == dow_num]
    avg = day_data['Net_PnL'].mean()
    total = day_data['Net_PnL'].sum()
    print(f"{dow_name:<10}: Trades: {len(day_data):<4} | Total PnL: ₹{total:>10,.0f} | Avg/Trade: ₹{avg:>6,.0f}")

