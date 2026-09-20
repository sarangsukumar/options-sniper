import os
import pandas as pd
import numpy as np

# Import the backtest function from the champion strategy
from dynamic_threshold_ml_adaptive_dampener import run_backtest

print("Running Champion Strategy to calculate Year-over-Year metrics...")
df_res = run_backtest()
df_res['year'] = df_res['date'].dt.year

def get_stats(df):
    t = len(df)
    w = (df['actual_pnl'] > 0).sum()
    wr = (w/t*100) if t>0 else 0
    p = df['actual_pnl'].sum()
    avg = p/t if t>0 else 0
    return wr, avg, p, t

test_years = range(2020, 2027)

print("==========================================================================================")
print(f"{'Year':<5} | {'WIN RATE (%)':<15} | {'AVG PnL/DAY (Rs)':<18} | {'SUM PnL (Rs)':<18} | {'DAYS TRADED'}")
print("-" * 90)

for y in test_years:
    wr, avg, p, t = get_stats(df_res[df_res['year'] == y])
    year_str = f"{y}*" if y == 2026 else str(y)
    print(f"{year_str:<5} | {wr:<15.1f} | Rs {avg:<15.0f} | Rs {p:<15,.0f} | {t}")

print("-" * 90)
wr_total, avg_total, p_total, t_total = get_stats(df_res[df_res['year'].isin(test_years)])
print(f"{'TOTAL':<5} | {wr_total:<15.1f} | Rs {avg_total:<15.0f} | Rs {p_total:<15,.0f} | {t_total}")
print("==========================================================================================")
print("* 2026 is strictly OUT OF SAMPLE")
