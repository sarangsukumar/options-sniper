import pandas as pd

df = pd.read_csv('/home/ubuntu/942_regime_shift_model/final_verified_ledger_2L_Neo.csv')
df['year'] = pd.to_datetime(df['date']).dt.year.astype(int)

yoy = df.groupby('year').agg(
    trades=('stockname', 'count'),
    winning_trades=('net_pnl', lambda x: (x > 0).sum()),
    gross_pnl=('gross_pnl', 'sum'),
    commission=('commission', 'sum'),
    net_pnl=('net_pnl', 'sum')
).reset_index()

yoy['win_rate_pct'] = (yoy['winning_trades'] / yoy['trades']) * 100

for index, row in yoy.iterrows():
    print(f"{int(row['year'])} | {int(row['trades'])} Trades | {row['win_rate_pct']:.1f}% Win | + Rs {row['net_pnl']/100000:.2f} Lakhs")
    
total_net = yoy['net_pnl'].sum()
print(f"Total: + Rs {total_net/100000:.2f} Lakhs")
print(f"Avg Charge per Trade: Rs {df['commission'].mean():.2f}")
