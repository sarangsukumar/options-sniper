import pandas as pd

pnl = pd.read_csv('0942_verified_pnl_sheet.csv')
pnl['Year'] = pd.to_datetime(pnl['Date']).dt.year
pnl['Stock_clean'] = pnl['Stock'].astype(str).str.strip().str.upper()

df = pd.read_csv('data/short_sell_ml_dataset_v5_scratch.csv', low_memory=False)
df['clean_stock'] = df['clean_stock'].astype(str).str.strip().str.upper()

merged = pnl.merge(df, left_on=['Date', 'Stock_clean'], right_on=['date_str', 'clean_stock'], how='inner')
merged = merged.drop_duplicates(subset=['Date', 'Stock_clean'])
merged['pct'] = (merged['Sell_Price'] - merged['prev_close']) / merged['prev_close'] * 100

print("==========================================================================")
print("🚫 SKIPPED TRADES PER YEAR (NO REPLACEMENTS)")
print("==========================================================================")

for year in sorted(merged['Year'].unique()):
    yr_data = merged[merged['Year'] == year]
    total_trades = len(yr_data)
    
    skipped_10 = len(yr_data[yr_data['pct'] < -1.0])
    skipped_15 = len(yr_data[yr_data['pct'] < -1.5])
    
    print(f"Year {year}: Total Trades: {total_trades:>3} | Skipped by -1.0%: {skipped_10:>3} ({skipped_10/total_trades*100:.1f}%) | Skipped by -1.5%: {skipped_15:>3} ({skipped_15/total_trades*100:.1f}%)")

# Compare PnL
print("\n==========================================================================")
print("💰 PNL COMPARISON (NO REPLACEMENTS)")
print("==========================================================================")

is_df = merged[merged['Year'] <= 2025]
oos_df = merged[merged['Year'] == 2026]

base_is = is_df['Net_PnL'].sum()
base_oos = oos_df['Net_PnL'].sum()

for thresh in [-1.0, -1.5]:
    is_f = is_df[is_df['pct'] >= thresh]
    oos_f = oos_df[oos_df['pct'] >= thresh]
    
    is_pnl = is_f['Net_PnL'].sum()
    oos_pnl = oos_f['Net_PnL'].sum()
    
    is_delta = is_pnl - base_is
    oos_delta = oos_pnl - base_oos
    
    print(f"Filter >= {thresh}%:")
    print(f"  IS (2020-25) PnL: ₹{is_pnl:>10,.0f} (Delta: +₹{is_delta:,.0f}) | Trades skipped: {len(is_df) - len(is_f)}")
    print(f"  OOS (2026)   PnL: ₹{oos_pnl:>10,.0f} (Delta: +₹{oos_delta:,.0f}) | Trades skipped: {len(oos_df) - len(oos_f)}")
    print("-" * 74)

