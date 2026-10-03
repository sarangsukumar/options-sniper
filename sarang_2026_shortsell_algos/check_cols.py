import pandas as pd
df = pd.read_csv('/home/ubuntu/v5_from_scratch/data/short_sell_ml_dataset_v5_scratch.csv', low_memory=False)
print("Total:", len(df))
print("Nulls price_0907_unified:", df['price_0907_unified'].isna().sum())
print("Nulls morning_open:", df['morning_open'].isna().sum())
print("Nulls gap_0907_pct:", df['gap_0907_pct'].isna().sum() if 'gap_0907_pct' in df.columns else df['Gap_Pct'].isna().sum())
