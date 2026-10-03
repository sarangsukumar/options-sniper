import pandas as pd
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

df1 = pd.read_csv(os.path.join(BASE_DIR, 'output', 'model1_cash_audited_pnl.csv'))
df2 = pd.read_csv(os.path.join(BASE_DIR, 'output', 'model2_cash_audited_pnl.csv'))

# Filter valid trades only
df1 = df1[df1['exit_reason'].str.startswith('SKIPPED') == False].copy()
df2 = df2[df2['exit_reason'].str.startswith('SKIPPED') == False].copy()

df1['model'] = 'Model 1 (09:20)'
df2['model'] = 'Model 2 (09:42)'

df = pd.concat([df1, df2])
df['year'] = pd.to_datetime(df['date']).dt.year

yoy = df.groupby('year')['net_pnl'].sum().reset_index()

print("===================================")
print("  COMBINED YEAR-OVER-YEAR PNL")
print("===================================")
total = 0
for _, row in yoy.iterrows():
    yr = int(row['year'])
    pnl = row['net_pnl']
    total += pnl
    print(f"{yr} | Profit: Rs {pnl:,.2f}")
print("===================================")
print(f"TOTAL: Rs {total:,.2f}")
