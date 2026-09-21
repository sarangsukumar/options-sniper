import pandas as pd
import numpy as np

df = pd.read_csv('/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/R1_R3_1x_Dual_Confirmed_2x/USER_R1_R3_DUAL_SHEET.csv')
df['year'] = pd.to_datetime(df['date']).dt.year

records = []
for _, row in df.iterrows():
    y = row['year']
    
    # Trade 1
    if pd.notna(row['stock1']) and row['lot1'] > 0:
        records.append({
            'year': y,
            'pnl': row['pnl1']
        })
        
    # Trade 2
    if pd.notna(row['stock2']) and row['lot2'] > 0:
        records.append({
            'year': y,
            'pnl': row['pnl2']
        })

trades_df = pd.DataFrame(records)

yoy = trades_df.groupby('year').agg(
    Trades=('pnl', 'count'),
    Win_Rate=('pnl', lambda x: (x > 0).mean() * 100),
    Net_PnL=('pnl', 'sum'),
    Avg_PnL=('pnl', 'mean')
).reset_index()

# Add totals
total_trades = yoy['Trades'].sum()
total_pnl = yoy['Net_PnL'].sum()
avg_pnl = total_pnl / total_trades if total_trades > 0 else 0
win_rate = (trades_df['pnl'] > 0).mean() * 100

total_row = pd.DataFrame([{
    'year': 'TOTAL',
    'Trades': total_trades,
    'Win_Rate': win_rate,
    'Net_PnL': total_pnl,
    'Avg_PnL': avg_pnl
}])

yoy = pd.concat([yoy, total_row], ignore_index=True)

print("| Year | Win Rate % | Avg PnL/Trade (Rs) | Total PnL (Rs) | Trades |")
print("|------|-----------|--------------------|----------------|--------|")
for _, row in yoy.iterrows():
    yr = row['year']
    wr = f"{row['Win_Rate']:.1f}%"
    avg = f"₹{row['Avg_PnL']:,.0f}"
    tot = f"₹{row['Net_PnL']:,.0f}"
    trd = int(row['Trades'])
    print(f"| {yr} | {wr} | {avg} | {tot} | {trd} |")

