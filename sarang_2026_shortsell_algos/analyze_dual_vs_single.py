import pandas as pd
import numpy as np

df = pd.read_csv('/home/ubuntu/sarang_2026_shortsell_algos/rebuild_model2_strict_db_ledger.csv')

def calc_stats(sub_df):
    if len(sub_df) == 0:
        return 0, 0, 0, 0
    
    # We will use eq_net (Cash Net) for this edge comparison
    nets = sub_df['eq_net'].values
    mults = sub_df['lots_multiplier'].values
    
    wins = (nets > 0).sum()
    win_rate = wins / len(nets) * 100
    
    gross_profits = nets[nets > 0].sum()
    gross_losses = abs(nets[nets < 0].sum())
    pf = gross_profits / gross_losses if gross_losses > 0 else float('inf')
    
    # Normalized average profit per LOT (divide by multiplier)
    norm_nets = nets / mults
    avg_norm_profit = norm_nets.mean()
    
    return len(nets), win_rate, pf, avg_norm_profit

print("================================================================================")
print(" DUAL CONFIRMED vs SINGLE CONFIRMED — STATISTICAL EDGE ANALYSIS (Equity Cash)")
print("================================================================================\n")

years = sorted(df['year'].unique())
print(f"{'Year':<6} | {'Cohort':<18} | {'Trades':<6} | {'Win Rate':<8} | {'PF':<5} | {'Avg Net Per Lot'}")
print("-" * 80)

total_single = df[df['lots_multiplier'] == 1]
total_dual = df[df['lots_multiplier'] == 2]

for y in years:
    ydf = df[df['year'] == y]
    s_df = ydf[ydf['lots_multiplier'] == 1]
    d_df = ydf[ydf['lots_multiplier'] == 2]
    
    s_cnt, s_wr, s_pf, s_avg = calc_stats(s_df)
    d_cnt, d_wr, d_pf, d_avg = calc_stats(d_df)
    
    print(f"{y:<6} | {'Single Confirmed':<18} | {s_cnt:<6} | {s_wr:>5.1f}%   | {s_pf:.2f}  | Rs {s_avg:>6.0f}")
    print(f"{'':<6} | {'Dual Confirmed':<18} | {d_cnt:<6} | {d_wr:>5.1f}%   | {d_pf:.2f}  | Rs {d_avg:>6.0f}")
    
    # Edge comparison
    wr_diff = d_wr - s_wr
    pf_diff = d_pf - s_pf
    print(f"{'':<6} | {'EDGE DIFFERENCE':<18} | {'':<6} | {wr_diff:>+5.1f}%   | {pf_diff:>+.2f}  |")
    print("-" * 80)

# Totals
s_cnt, s_wr, s_pf, s_avg = calc_stats(total_single)
d_cnt, d_wr, d_pf, d_avg = calc_stats(total_dual)

print(f"{'TOTAL':<6} | {'Single Confirmed':<18} | {s_cnt:<6} | {s_wr:>5.1f}%   | {s_pf:.2f}  | Rs {s_avg:>6.0f}")
print(f"{'TOTAL':<6} | {'Dual Confirmed':<18} | {d_cnt:<6} | {d_wr:>5.1f}%   | {d_pf:.2f}  | Rs {d_avg:>6.0f}")

wr_diff = d_wr - s_wr
pf_diff = d_pf - s_pf
print(f"{'':<6} | {'OVERALL EDGE':<18} | {'':<6} | {wr_diff:>+5.1f}%   | {pf_diff:>+.2f}  |")
print("================================================================================")
