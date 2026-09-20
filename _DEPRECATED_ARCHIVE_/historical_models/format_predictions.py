#!/usr/bin/env python3
import os
import pandas as pd

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
trades_path = os.path.join(_THIS_DIR, "output", "trades_dynamic_threshold_ensemble.csv")
output_dir = os.path.join(_THIS_DIR, "output", "simulation_results")
os.makedirs(output_dir, exist_ok=True)
output_path = os.path.join(output_dir, "ensemble_predictions_yyyymmdd.csv")

if not os.path.exists(trades_path):
    print(f"[!] Trades file not found: {trades_path}")
    exit(1)

df = pd.read_csv(trades_path)
df['date'] = pd.to_datetime(df['date'])
df['formatted_date'] = df['date'].dt.strftime('%Y%m%d')

# Keep only formatted_date and stock, with no headers
out_df = df[['formatted_date', 'stock']].copy()
out_df.to_csv(output_path, header=False, index=False)

print(f"[+] Clean predictions formatted and saved successfully to: {output_path}")
print(f"    • Total Rows: {len(out_df)}")
