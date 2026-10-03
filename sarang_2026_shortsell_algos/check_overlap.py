import pandas as pd

df_a = pd.read_csv('/home/ubuntu/v5_from_scratch/data/short_sell_ml_dataset_v5_scratch.csv', low_memory=False)
df_b = pd.read_csv('/home/ubuntu/sarang_2026_shortsell_algos/01_Best_Shorter_Window_0920_0940/data/scalp_0920_ml_dataset.csv.gz')

df_a['date'] = pd.to_datetime(df_a['short_sell_date'])
df_b['date'] = pd.to_datetime(df_b['short_date'])

df_a['stock'] = df_a['stockname'].str.strip().str.upper()
df_b['stock'] = df_b['clean_stock'].str.strip().str.upper()

merged = pd.merge(df_a, df_b, on=['date', 'stock'], how='inner')
print(f"Dataset A: {len(df_a)}, Dataset B: {len(df_b)}, Merged: {len(merged)}")
