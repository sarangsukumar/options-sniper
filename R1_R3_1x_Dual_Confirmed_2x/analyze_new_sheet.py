import pandas as pd

df = pd.read_csv('/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/R1_R3_1x_Dual_Confirmed_2x/USER_R1_R3_DUAL_SHEET.csv')
total_pnl = df['daily_total_pnl'].sum()
win_rate = (df['daily_total_pnl'] > 0).mean() * 100
avg_trade = df['daily_total_pnl'].mean()
print(f"Total Days Traded: {len(df)}")
print(f"Total Net PnL: Rs {total_pnl:,.2f}")
print(f"Win Rate: {win_rate:.1f}%")
print(f"Average PnL/Day: Rs {avg_trade:,.2f}")
