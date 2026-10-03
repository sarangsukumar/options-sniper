import pandas as pd
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

df1 = pd.read_csv(os.path.join(BASE_DIR, 'output', 'model1_cash_audited_pnl.csv'))
df2 = pd.read_csv(os.path.join(BASE_DIR, 'output', 'model2_cash_audited_pnl.csv'))

df1 = df1[df1['exit_reason'].str.startswith('SKIPPED') == False].copy()
df2 = df2[df2['exit_reason'].str.startswith('SKIPPED') == False].copy()

df1['date'] = pd.to_datetime(df1['date'])
df2['date'] = pd.to_datetime(df2['date'])

def get_stats(df, name):
    df['year_week'] = df['date'].dt.strftime('%Y-%U')
    df['year_month'] = df['date'].dt.strftime('%Y-%m')
    
    weekly_pnl = df.groupby('year_week')['net_pnl'].sum()
    monthly_pnl = df.groupby('year_month')['net_pnl'].sum()
    
    total_weeks = len(weekly_pnl)
    winning_weeks = len(weekly_pnl[weekly_pnl > 0])
    
    total_months = len(monthly_pnl)
    winning_months = len(monthly_pnl[monthly_pnl > 0])
    
    print(f"\n--- {name} ---")
    print(f"Weeks Positive: {winning_weeks}/{total_weeks} ({winning_weeks/total_weeks*100:.2f}%)")
    print(f"Months Positive: {winning_months}/{total_months} ({winning_months/total_months*100:.2f}%)")

get_stats(df1, "09:20 Model Alone")
get_stats(df2, "09:42 Model Alone")

# Combined sequentially
df_combined = pd.concat([df1, df2])
get_stats(df_combined, "Combined Sequentially (09:20 + 09:42)")

