import pandas as pd

df = pd.read_csv('/home/ubuntu/942_regime_shift_model/final_verified_ledger_2L_Neo.csv')
df['date'] = pd.to_datetime(df['date'])

# Day Level
daily = df.groupby('date')['net_pnl'].sum().reset_index()
days_total = len(daily)
days_won = (daily['net_pnl'] > 0).sum()
day_wr = (days_won / days_total) * 100

# Week Level (Group by Year and Week Number)
df['week'] = df['date'].dt.isocalendar().year.astype(str) + "-" + df['date'].dt.isocalendar().week.astype(str)
weekly = df.groupby('week')['net_pnl'].sum().reset_index()
weeks_total = len(weekly)
weeks_won = (weekly['net_pnl'] > 0).sum()
week_wr = (weeks_won / weeks_total) * 100

# Month Level
df['month'] = df['date'].dt.to_period('M')
monthly = df.groupby('month')['net_pnl'].sum().reset_index()
months_total = len(monthly)
months_won = (monthly['net_pnl'] > 0).sum()
month_wr = (months_won / months_total) * 100

# Quarter Level
df['quarter'] = df['date'].dt.to_period('Q')
quarterly = df.groupby('quarter')['net_pnl'].sum().reset_index()
quarters_total = len(quarterly)
quarters_won = (quarterly['net_pnl'] > 0).sum()
quarter_wr = (quarters_won / quarters_total) * 100

print(f"Daily: {days_won}/{days_total} ({day_wr:.1f}%)")
print(f"Weekly: {weeks_won}/{weeks_total} ({week_wr:.1f}%)")
print(f"Monthly: {months_won}/{months_total} ({month_wr:.1f}%)")
print(f"Quarterly: {quarters_won}/{quarters_total} ({quarter_wr:.1f}%)")

print(f"Avg Daily PnL: Rs {daily['net_pnl'].mean():.2f}")
print(f"Avg Weekly PnL: Rs {weekly['net_pnl'].mean():.2f}")
print(f"Avg Monthly PnL: Rs {monthly['net_pnl'].mean():.2f}")
print(f"Avg Quarterly PnL: Rs {quarterly['net_pnl'].mean():.2f}")
