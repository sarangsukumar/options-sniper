import pandas as pd
df = pd.read_csv('0920_monthly_verified_pnl_0921.csv')
df['year'] = pd.to_datetime(df['Date']).dt.year

print("\n==========================================================")
print(" 🏆 09:20 SCALP (09:21 ENTRY VERIFIED) FILTERED RESULTS")
print("==========================================================")
for y in sorted(df['year'].unique()):
    sub = df[df['year'] == y]
    print(f"  {y}: Rs {sub['Net_PnL'].sum()/100000:6.2f} L | {(sub['Net_PnL']>0).mean()*100:.1f}% Win | {len(sub)} trades")
print("----------------------------------------------------------")
print(f"  TOTAL: Rs {df['Net_PnL'].sum()/100000:.2f} Lakhs")
print("==========================================================")
