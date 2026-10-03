import pandas as pd
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

df1 = pd.read_csv(os.path.join(BASE_DIR, 'output', 'model1_cash_audited_pnl.csv'))
df2 = pd.read_csv(os.path.join(BASE_DIR, 'output', 'model2_cash_audited_pnl.csv'))

df1 = df1[df1['exit_reason'].str.startswith('SKIPPED') == False].copy()
df2 = df2[df2['exit_reason'].str.startswith('SKIPPED') == False].copy()

df = pd.concat([df1, df2])
df['date'] = pd.to_datetime(df['date'])
df['month'] = df['date'].dt.to_period('M')

# 1. Per Trade Winrate
total_trades = len(df)
winning_trades = len(df[df['net_pnl'] > 0])
trade_winrate = (winning_trades / total_trades) * 100

# 2. Per Day Winrate
daily_pnl = df.groupby(df['date'].dt.date)['net_pnl'].sum().reset_index()
total_days = len(daily_pnl)
winning_days = len(daily_pnl[daily_pnl['net_pnl'] > 0])
day_winrate = (winning_days / total_days) * 100

# 3. Per Month Winrate
monthly_pnl = df.groupby('month')['net_pnl'].sum().reset_index()
total_months = len(monthly_pnl)
winning_months = len(monthly_pnl[monthly_pnl['net_pnl'] > 0])
month_winrate = (winning_months / total_months) * 100

print(f"Per Trade: {trade_winrate:.2f}% ({winning_trades}/{total_trades})")
print(f"Per Day:   {day_winrate:.2f}% ({winning_days}/{total_days})")
print(f"Per Month: {month_winrate:.2f}% ({winning_months}/{total_months})")
