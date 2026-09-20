import pandas as pd

df = pd.read_csv('/home/ubuntu/942_regime_shift_model/day_wise_pnl_86L.csv')
df['date'] = pd.to_datetime(df['date'])
df['weekday'] = df['date'].dt.day_name()

# Sort days logically
days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']

grouped = df.groupby('weekday').agg(
    total_days=('date', 'count'),
    winning_days=('net_pnl', lambda x: (x > 0).sum()),
    total_net_pnl=('net_pnl', 'sum'),
    avg_pnl_per_day=('net_pnl', 'mean')
).reindex(days)

grouped['win_rate_pct'] = (grouped['winning_days'] / grouped['total_days']) * 100

for index, row in grouped.iterrows():
    print(f"{index}: {row['total_days']} days | Win Rate: {row['win_rate_pct']:.1f}% | Total PnL: Rs {row['total_net_pnl']/100000:.2f} L | Avg per day: Rs {row['avg_pnl_per_day']:,.0f}")
