import pandas as pd

# Load the verified tick-by-tick ledger (which has the correct 2L Neo Margin PnL)
ledger = pd.read_csv('/home/ubuntu/942_regime_shift_model/final_verified_ledger_2L_Neo.csv')

# Load the original ML simulation trades to get the signal tag
ml_trades = pd.read_csv('/home/ubuntu/942_regime_shift_model/longer_window_trades_futures_and_eq.csv')

# Merge them on date and stockname
merged = pd.merge(
    ledger, 
    ml_trades[['date', 'stockname', 'signal_type']], 
    on=['date', 'stockname'], 
    how='inner'
)

# Filter ONLY Dual or Quad Confirmed
duals = merged[merged['signal_type'].isin(['DUAL_CONFIRMED', 'QUAD_CONFIRMED'])].copy()

duals['year'] = pd.to_datetime(duals['date']).dt.year.astype(int)

yoy = duals.groupby('year').agg(
    trades=('stockname', 'count'),
    winning_trades=('net_pnl', lambda x: (x > 0).sum()),
    net_pnl=('net_pnl', 'sum')
).reset_index()

yoy['win_rate_pct'] = (yoy['winning_trades'] / yoy['trades']) * 100

for index, row in yoy.iterrows():
    print(f"{int(row['year'])} | {int(row['trades'])} Trades | {row['win_rate_pct']:.1f}% Win | + Rs {row['net_pnl']/100000:.2f} Lakhs")
    
total_net = yoy['net_pnl'].sum()
print(f"Total: + Rs {total_net/100000:.2f} Lakhs")
