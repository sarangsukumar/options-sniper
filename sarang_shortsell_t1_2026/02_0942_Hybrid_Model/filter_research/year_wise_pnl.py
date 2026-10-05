import pandas as pd

pnl = pd.read_csv('0942_verified_pnl_sheet.csv')
pnl['Year'] = pd.to_datetime(pnl['Date']).dt.year
pnl['Stock_clean'] = pnl['Stock'].astype(str).str.strip().str.upper()

df = pd.read_csv('data/short_sell_ml_dataset_v5_scratch.csv', low_memory=False)
df['clean_stock'] = df['clean_stock'].astype(str).str.strip().str.upper()

merged = pnl.merge(df, left_on=['Date', 'Stock_clean'], right_on=['date_str', 'clean_stock'], how='inner')
merged = merged.drop_duplicates(subset=['Date', 'Stock_clean'])
merged['pct'] = (merged['Sell_Price'] - merged['prev_close']) / merged['prev_close'] * 100

print("==========================================================================================")
print("📅 YEAR-WISE PNL: BASELINE vs -1.0% FILTER (NO REPLACEMENTS)")
print("==========================================================================================")
print(f"{'Year':<5} | {'Baseline PnL':<15} | {'Filtered PnL':<15} | {'Delta':<12} | {'Total':<6} | {'Skipped':<7}")
print("-" * 90)

total_base = 0
total_filt = 0
total_skipped = 0

for year in sorted(merged['Year'].unique()):
    yr_data = merged[merged['Year'] == year]
    
    base_pnl = yr_data['Net_PnL'].sum()
    
    filt_data = yr_data[yr_data['pct'] >= -1.0]
    filt_pnl = filt_data['Net_PnL'].sum()
    
    delta = filt_pnl - base_pnl
    
    total_trades = len(yr_data)
    skipped = total_trades - len(filt_data)
    
    total_base += base_pnl
    total_filt += filt_pnl
    total_skipped += skipped
    
    # Formatting
    base_str = f"₹ {base_pnl:>10,.0f}"
    filt_str = f"₹ {filt_pnl:>10,.0f}"
    delta_str = f"{'+' if delta > 0 else ''}₹ {delta:>8,.0f}"
    
    print(f"{year:<5} | {base_str:<15} | {filt_str:<15} | {delta_str:<12} | {total_trades:<6} | {skipped:<7}")

print("=" * 90)
print(f"TOTAL | ₹ {total_base:>10,.0f}    | ₹ {total_filt:>10,.0f}    | +₹ {total_filt-total_base:>8,.0f} | {len(merged):<6} | {total_skipped:<7}")
