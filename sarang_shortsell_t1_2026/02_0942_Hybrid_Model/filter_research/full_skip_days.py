import pandas as pd
import yfinance as yf
import pymysql

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
merged['DayOfWeek'] = pd.to_datetime(merged['Date']).dt.dayofweek

def apply_rules(row):
    spct = row['pct']
    if spct < -1.0: return False
    if row['nifty_gap'] < -0.5 and spct < -0.5: return False
    if row['DayOfWeek'] == 0 and spct < -0.5: return False
    return True

merged['passes'] = merged.apply(apply_rules, axis=1)

# Per day: count total trades and how many passed
day_summary = merged.groupby('Date').agg(
    total=('passes', 'count'),
    passed=('passes', 'sum'),
    day_pnl=('Net_PnL', 'sum')
).reset_index()

day_summary['passed'] = day_summary['passed'].astype(int)
day_summary['blocked'] = day_summary['total'] - day_summary['passed']

# Days where ALL trades were blocked
full_skip_days = day_summary[day_summary['passed'] == 0]
partial_days   = day_summary[(day_summary['passed'] > 0) & (day_summary['passed'] < day_summary['total'])]
full_trade_days = day_summary[day_summary['passed'] == day_summary['total']]

print("==========================================================================")
print("📊 HOW OFTEN DOES THE FILTER BLOCK TRADES?")
print("==========================================================================")
print(f"Total trading days           : {len(day_summary)}")
print(f"Days with ALL trades passing : {len(full_trade_days)} ({len(full_trade_days)/len(day_summary)*100:.1f}%)")
print(f"Days with SOME blocked       : {len(partial_days)} ({len(partial_days)/len(day_summary)*100:.1f}%)")
print(f"Days with ALL blocked (skip) : {len(full_skip_days)} ({len(full_skip_days)/len(day_summary)*100:.1f}%)")

print(f"\n📅 FULL SKIP DAYS BY YEAR:")
full_skip_days['Year'] = pd.to_datetime(full_skip_days['Date']).dt.year
skip_yr = full_skip_days.groupby('Year').agg(days=('Date','count'), pnl=('day_pnl','sum')).reset_index()
for _, r in skip_yr.iterrows():
    total_yr = len(day_summary[pd.to_datetime(day_summary['Date']).dt.year == r['Year']])
    print(f"  Year {int(r['Year'])}: {int(r['days'])} full-skip days out of {total_yr} | PnL avoided: ₹{r['pnl']:,.0f}")

print(f"\n📌 PNL ON FULLY SKIPPED DAYS (negative = we saved money, positive = we missed profit):")
print(f"  Total PnL we avoided by skipping: ₹{full_skip_days['day_pnl'].sum():,.0f}")
print(f"  Avg PnL per skipped day          : ₹{full_skip_days['day_pnl'].mean():,.0f}")

# Show today's blocked stocks PnL for context
print(f"\n🔍 TODAY'S SPECIFICALLY - Blocked stocks actual PnL:")
today_blocked = ['ANGELONE','ADANIENSOL','PNBHOUSING','INOXWIND']
today_pnl = merged[(merged['Date']=='2026-09-24') & (merged['Stock_clean'].isin(today_blocked))]
for _, r in today_pnl.iterrows():
    status = "✅ Profit" if r['Net_PnL'] > 0 else "❌ Loss"
    print(f"  {r['Stock_clean']:<14} pct: {r['pct']:+.2f}% | PnL: ₹{r['Net_PnL']:,.0f} | {status}")
