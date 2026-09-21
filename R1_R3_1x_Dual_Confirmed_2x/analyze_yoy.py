import pandas as pd

df = pd.read_csv('/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/R1_R3_1x_Dual_Confirmed_2x/USER_R1_R3_DUAL_SHEET.csv')
df['year'] = pd.to_datetime(df['date']).dt.year
yoy = df.groupby('year').agg(
    Trades=('date', 'count'),
    Win_Rate=('daily_total_pnl', lambda x: (x > 0).mean() * 100),
    Net_PnL=('daily_total_pnl', 'sum'),
    Max_Drawdown=('daily_total_pnl', lambda x: x.min())
)
print(yoy.to_string(formatters={'Win_Rate': '{:.1f}%'.format, 'Net_PnL': 'Rs {:,.0f}'.format, 'Max_Drawdown': 'Rs {:,.0f}'.format}))
