import pandas as pd
import numpy as np

pnl = pd.read_csv('0942_verified_pnl_sheet.csv')
pnl['Year'] = pd.to_datetime(pnl['Date']).dt.year
pnl['Stock'] = pnl['Stock'].astype(str).str.strip().str.upper()

df = pd.read_csv('data/short_sell_ml_dataset_v5_scratch.csv', low_memory=False)
df['clean_stock'] = df['clean_stock'].astype(str).str.strip().str.upper()
df = df[['date_str', 'clean_stock', 'prev_close', 'short_entry_price']]

merged = pnl.merge(df, left_on=['Date', 'Stock'], right_on=['date_str', 'clean_stock'], how='inner')
merged = merged.drop_duplicates(subset=['Date', 'Stock'])
merged['pct'] = (merged['Sell_Price'] - merged['prev_close']) / merged['prev_close'] * 100

is_df = merged[merged['Year'] <= 2025]
oos_df = merged[merged['Year'] == 2026]

base_is = is_df['Net_PnL'].sum()
base_oos = oos_df['Net_PnL'].sum()

results = []
for min_pct in [-5, -3, -2, -1.5, -1, -0.5, 0]:
    for max_pct in [1, 1.5, 2, 2.5, 3, 5, 10, 100]:
        if min_pct >= max_pct: continue
        
        is_f = is_df[(is_df['pct'] >= min_pct) & (is_df['pct'] <= max_pct)]
        oos_f = oos_df[(oos_df['pct'] >= min_pct) & (oos_df['pct'] <= max_pct)]
        
        results.append({
            'min': min_pct,
            'max': max_pct,
            'is_pnl': is_f['Net_PnL'].sum(),
            'oos_pnl': oos_f['Net_PnL'].sum(),
            'is_trades': len(is_f),
            'oos_trades': len(oos_f)
        })

res = pd.DataFrame(results)
res['is_delta'] = res['is_pnl'] - base_is
res['oos_delta'] = res['oos_pnl'] - base_oos

# Sort by in-sample improvement
top = res.sort_values('is_delta', ascending=False).head(10)
print("🏆 TOP 10 FILTER STRATEGIES (Ranked by In-Sample 2020-2025 Improvement)")
print("==========================================================================================")
print(f"{'Condition':<25} | {'IS PnL':<10} | {'IS Delta':<10} | {'OOS PnL':<10} | {'OOS Delta':<10}")
print("------------------------------------------------------------------------------------------")
for _, r in top.iterrows():
    cond = f"{r['min']:>4} to {r['max']:<4} %"
    print(f"{cond:<25} | {r['is_pnl']:>10,.0f} | {r['is_delta']:>10,.0f} | {r['oos_pnl']:>10,.0f} | {r['oos_delta']:>10,.0f}")
