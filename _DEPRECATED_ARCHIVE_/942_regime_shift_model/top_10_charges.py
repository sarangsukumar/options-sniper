import pandas as pd

df = pd.read_csv('/home/ubuntu/942_regime_shift_model/final_verified_ledger_86L.csv')
top_10 = df.nlargest(10, 'commission')[['date', 'stockname', 'sell_price', 'qty', 'commission', 'net_pnl']]

for index, row in top_10.iterrows():
    print(f"| {row['date']} | {row['stockname']} | Rs {row['sell_price']:,.2f} | {int(row['qty'])} | Rs {row['commission']:,.2f} | Rs {row['net_pnl']:,.2f} |")
