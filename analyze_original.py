import pandas as pd
df = pd.read_csv('/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/historical_models/output/trades_dynamic_threshold.csv')
df['year'] = pd.to_datetime(df['date']).dt.year
yoy = df.groupby('year').agg(
    Trades=('actual_pnl', 'count'),
    Win_Rate=('actual_pnl', lambda x: (x > 0).mean() * 100),
    Net_PnL=('actual_pnl', 'sum'),
    Avg_PnL=('actual_pnl', 'mean')
)
print("ORIGINAL DYNAMIC THRESHOLD RESULTS (R1+R3, no 2x lot multipliers, just pure dynamic threshold filter)")
print(yoy.to_string(formatters={'Win_Rate': '{:.1f}%'.format, 'Net_PnL': 'Rs {:,.0f}'.format, 'Avg_PnL': 'Rs {:,.0f}'.format}))
print("\nTOTAL PNL:", df['actual_pnl'].sum())
print("TOTAL TRADES:", len(df))
print("AVG PNL:", df['actual_pnl'].mean())
print("WIN RATE:", (df['actual_pnl'] > 0).mean() * 100)
