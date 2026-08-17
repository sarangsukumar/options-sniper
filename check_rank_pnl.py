import pandas as pd

df = pd.read_csv('/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/historical_models/output/trades_dynamic_threshold_ensemble.csv')
df['date'] = pd.to_datetime(df['date'])
df_2026 = df[df['date'].dt.year == 2026].copy()

# Sort by date and pred_pnl descending
df_2026 = df_2026.sort_values(by=['date', 'pred_pnl'], ascending=[True, False])

# Assign ranks 1, 2, 3, 4 for each day
df_2026['rank'] = df_2026.groupby('date').cumcount() + 1

# Sum actual_pnl by rank
pnl_by_rank = df_2026.groupby('rank')['actual_pnl'].sum()
print("Raw 2026 PnL by Stock Rank (without ML/Dampener):")
print(pnl_by_rank)
