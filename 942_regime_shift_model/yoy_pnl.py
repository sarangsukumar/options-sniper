import pandas as pd

df = pd.read_csv('/home/ubuntu/942_regime_shift_model/final_verified_ledger_86L.csv')
df['year'] = pd.to_datetime(df['date']).dt.year

yoy = df.groupby('year').agg(
    trades=('stockname', 'count'),
    winning_trades=('net_pnl', lambda x: (x > 0).sum()),
    gross_pnl=('gross_pnl', 'sum'),
    commission=('commission', 'sum'),
    net_pnl=('net_pnl', 'sum')
).reset_index()

yoy['win_rate_pct'] = (yoy['winning_trades'] / yoy['trades']) * 100

for index, row in yoy.iterrows():
    print(f"20{str(row['year'])[-2:]} | {row['trades']} Trades | {row['win_rate_pct']:.1f}% Win | Rs {row['net_pnl']/100000:.2f} Lakhs")
    
total_net = yoy['net_pnl'].sum()
print(f"Total: Rs {total_net/100000:.2f} Lakhs")
