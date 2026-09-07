import pandas as pd
import subprocess
import os

df = pd.read_csv('/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_shortsell940_2026/data/short_sell_ml_dataset_v2.csv', low_memory=False)
df['date_str'] = pd.to_datetime(df['short_sell_date']).dt.strftime('%Y-%m-%d')
ban = pd.read_csv('/home/ubuntu/banlist/fo_ban_list_historical.csv')
ban['date_str'] = pd.to_datetime(ban['date'], format='%d-%m-%Y').dt.strftime('%Y-%m-%d')
ban = ban.rename(columns={'stock_name': 'clean_stock'})
ban['is_banned'] = 1
df = df.merge(ban[['date_str', 'clean_stock', 'is_banned']], on=['date_str', 'clean_stock'], how='left')
df = df[df['is_banned'] != 1].copy()

# Just a dummy way to get R1 targets if we don't want to re-run 2 mins of LGBM.
# Wait, I DO need to re-run LGBM to know which one was R1. 
