import pandas as pd

df = pd.read_csv('/home/ubuntu/942_regime_shift_model/final_verified_ledger_86L.csv')
daily = df.groupby('date').agg(
    trades=('stockname', 'count'),
    gross_pnl=('gross_pnl', 'sum'),
    commission=('commission', 'sum'),
    net_pnl=('net_pnl', 'sum')
).reset_index()

daily['cumulative_pnl'] = daily['net_pnl'].cumsum()

daily.to_csv('/home/ubuntu/942_regime_shift_model/day_wise_pnl_86L.csv', index=False)
print(f"Generated {len(daily)} days of PnL.")
