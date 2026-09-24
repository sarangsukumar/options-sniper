import pandas as pd
import numpy as np

# Load verified PnL sheet (contains Date, Stock, Net_PnL, etc.)
pnl = pd.read_csv('0942_verified_pnl_sheet.csv')
pnl['Year'] = pd.to_datetime(pnl['Date']).dt.year
pnl['Stock'] = pnl['Stock'].astype(str).str.strip().str.upper()

# Load features dataset to get prev_close
df = pd.read_csv('data/short_sell_ml_dataset_v5_scratch.csv', low_memory=False)
df['clean_stock'] = df['clean_stock'].astype(str).str.strip().str.upper()
df = df[['date_str', 'clean_stock', 'prev_close', 'short_entry_price']]

# Merge
merged = pnl.merge(df, left_on=['Date', 'Stock'], right_on=['date_str', 'clean_stock'], how='inner')
merged = merged.drop_duplicates(subset=['Date', 'Stock'])

# Calculate % change from prev_close to 09:40 entry
merged['pct_from_prev_close'] = (merged['Sell_Price'] - merged['prev_close']) / merged['prev_close'] * 100

in_sample = merged[merged['Year'] <= 2025].copy()
oos = merged[merged['Year'] == 2026].copy()

baseline_is = in_sample['Net_PnL'].sum()
baseline_oos = oos['Net_PnL'].sum()

print("==========================================================================")
print("🔍 0942 HYBRID: PERCENTAGE CHANGE FILTERING EXPERIMENT")
print("==========================================================================")
print(f"BASELINE In-Sample (2020-2025): ₹{baseline_is:>10,.2f} | Trades: {len(in_sample)}")
print(f"BASELINE Out-Of-Sample (2026) : ₹{baseline_oos:>10,.2f} | Trades: {len(oos)}")
print("--------------------------------------------------------------------------")

# Let's test different threshold buckets to see where the profits/losses come from
# We'll split the pct_from_prev_close into bins:
bins = [-np.inf, -3, -2, -1, 0, 1, 2, 3, np.inf]
labels = ['<-3%', '-3% to -2%', '-2% to -1%', '-1% to 0%', '0% to 1%', '1% to 2%', '2% to 3%', '>3%']

in_sample['bin'] = pd.cut(in_sample['pct_from_prev_close'], bins=bins, labels=labels)
grouped = in_sample.groupby('bin')['Net_PnL'].agg(['sum', 'count']).reset_index()
grouped.rename(columns={'sum': 'Net_PnL', 'count': 'Trades'}, inplace=True)
grouped['Avg_PnL'] = grouped['Net_PnL'] / grouped['Trades']

print("\n📊 IN-SAMPLE (2020-2025) PNL CONTRIBUTION BY % CHANGE BUCKET:")
for _, row in grouped.iterrows():
    print(f"Bucket {row['bin']:<12}: PnL: ₹{row['Net_PnL']:>11,.2f} | Trades: {row['Trades']:>4} | Avg: ₹{row['Avg_PnL']:>7,.2f}")

# Now let's try some specific filters
filters = [
    ("Exclude stocks DOWN more than -1%", lambda x: x >= -1),
    ("Exclude stocks DOWN more than -2%", lambda x: x >= -2),
    ("Exclude stocks UP more than +2%", lambda x: x <= 2),
    ("Only take stocks UP (+0% to +3%)", lambda x: (x >= 0) & (x <= 3)),
    ("Exclude extreme gaps (<-2% and >2%)", lambda x: (x >= -2) & (x <= 2))
]

print("\n🎯 FILTER STRATEGY TESTS:")
for name, cond in filters:
    is_filtered = in_sample[cond(in_sample['pct_from_prev_close'])]
    oos_filtered = oos[cond(oos['pct_from_prev_close'])]
    
    is_pnl = is_filtered['Net_PnL'].sum()
    oos_pnl = oos_filtered['Net_PnL'].sum()
    
    is_improvement = is_pnl - baseline_is
    oos_improvement = oos_pnl - baseline_oos
    
    print(f"\n{name}:")
    print(f"  In-Sample (20-25) : ₹{is_pnl:>11,.2f} (Delta: ₹{is_improvement:>10,.2f}) | Trades: {len(is_filtered)}/{len(in_sample)}")
    print(f"  Out-Of-Sample (26): ₹{oos_pnl:>11,.2f} (Delta: ₹{oos_improvement:>10,.2f}) | Trades: {len(oos_filtered)}/{len(oos)}")

print("==========================================================================")
