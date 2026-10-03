import pandas as pd

# Load Model 1 (Cash EQ)
df1 = pd.read_csv('/home/ubuntu/sarang_2026_shortsell_algos/01_Best_Shorter_Window_0920_0940/rebuilt_model1_strict_pnl.csv')
df1 = df1[~df1['exit_reason'].str.startswith('SKIPPED')]
df1['model'] = 'M1_EQ'

# Load Model 2 (Futures F1)
df2 = pd.read_csv('/home/ubuntu/sarang_2026_shortsell_algos/02_Best_Longer_Window_0942_1445/rebuilt_model2_f1_pnl.csv')
df2 = df2[~df2['exit_reason'].str.startswith('SKIPPED')]
df2['model'] = 'M2_F1'

# Combine
df = pd.concat([df1, df2])
df['date'] = pd.to_datetime(df['date'])
df['year'] = df['date'].dt.year
df['month'] = df['date'].dt.to_period('M')

# 1. Per Trade Win Rate
total_trades = len(df)
winning_trades = len(df[df['net_pnl'] > 0])
trade_win_rate = (winning_trades / total_trades) * 100

# 2. Per Month Win Rate
monthly_pnl = df.groupby('month')['net_pnl'].sum()
total_months = len(monthly_pnl)
winning_months = len(monthly_pnl[monthly_pnl > 0])
month_win_rate = (winning_months / total_months) * 100

# 3. Yearly Performance
yearly_pnl = df.groupby('year')['net_pnl'].sum()

print("--- COMBINED PERFORMANCE ---")
print(f"Total Trades: {total_trades}")
print(f"Trade Win Rate: {trade_win_rate:.2f}%")
print(f"Total Months: {total_months}")
print(f"Winning Months: {winning_months}")
print(f"Month Win Rate: {month_win_rate:.2f}%")

print("\n--- YEARLY BREAKDOWN ---")
for y, pnl in yearly_pnl.items():
    print(f"{y}: ₹ {pnl/100000:,.2f}L")

print("\n--- INDIVIDUAL MONTH WIN RATES ---")
m1_monthly = df1.copy()
m1_monthly['month'] = pd.to_datetime(m1_monthly['date']).dt.to_period('M')
m1_pnl = m1_monthly.groupby('month')['net_pnl'].sum()
m1_win_months = len(m1_pnl[m1_pnl > 0])

m2_monthly = df2.copy()
m2_monthly['month'] = pd.to_datetime(m2_monthly['date']).dt.to_period('M')
m2_pnl = m2_monthly.groupby('month')['net_pnl'].sum()
m2_win_months = len(m2_pnl[m2_pnl > 0])

print(f"Model 1 (EQ) Month Win Rate: {m1_win_months}/{len(m1_pnl)} ({(m1_win_months/len(m1_pnl))*100:.1f}%)")
print(f"Model 2 (F1) Month Win Rate: {m2_win_months}/{len(m2_pnl)} ({(m2_win_months/len(m2_pnl))*100:.1f}%)")


overlap = df[df['year'] >= 2021]
ov_monthly_pnl = overlap.groupby('month')['net_pnl'].sum()
ov_win = len(ov_monthly_pnl[ov_monthly_pnl > 0])
print(f"Overlap (2021-2026) Combined Month Win Rate: {ov_win}/{len(ov_monthly_pnl)} ({(ov_win/len(ov_monthly_pnl))*100:.1f}%)")
