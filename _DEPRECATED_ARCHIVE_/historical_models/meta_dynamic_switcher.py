import os
import pandas as pd
import numpy as np

OUTPUT_DIR = "/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/historical_models/output"
freqs = ['daily', 'weekly', 'monthly', 'quarterly', 'yearly', 'ensemble']
dfs = {}

for freq in freqs:
    path = os.path.join(OUTPUT_DIR, f"trades_dynamic_threshold_{freq}.csv")
    if os.path.exists(path):
        df = pd.read_csv(path)
        df['date'] = pd.to_datetime(df['date'])
        dfs[freq] = df

all_dates = set()
for df in dfs.values():
    all_dates.update(df['date'].unique())
all_dates = sorted(list(all_dates))

for N_DAYS in [7, 14, 30, 60, 90]:
    daily_pnl = {freq: pd.Series(0.0, index=all_dates) for freq in freqs}
    for freq, df in dfs.items():
        dp = df.groupby('date')['actual_pnl'].sum()
        daily_pnl[freq].update(dp)
    
    pnl_df = pd.DataFrame(daily_pnl)
    rolling_pnl = pnl_df.rolling(window=N_DAYS, min_periods=1).sum().shift(1)
    
    # Fill NAs
    if rolling_pnl.isna().all(axis=1).any():
        # Fallback to ensemble
        best_freqs = rolling_pnl.fillna(0).idxmax(axis=1)
    else:
        best_freqs = rolling_pnl.idxmax(axis=1)
        
    meta_trades = []
    for date in all_dates:
        best_freq = best_freqs.loc[date]
        if pd.isna(best_freq):
            best_freq = 'ensemble'
        
        day_trades = dfs[best_freq][dfs[best_freq]['date'] == date]
        if not day_trades.empty:
            meta_trades.append(day_trades)
    
    meta_df = pd.concat(meta_trades, ignore_index=True)
    meta_df['year'] = meta_df['date'].dt.year
    meta_df = meta_df[meta_df['year'].between(2019, 2026)]
    
    total_pnl = meta_df['actual_pnl'].sum()
    print(f"Meta-Switcher ({N_DAYS} days lookback) PnL: Rs {total_pnl:,.2f}")
meta_df = pd.concat(meta_trades, ignore_index=True)
meta_df['year'] = meta_df['date'].dt.year
meta_df = meta_df[meta_df['year'].between(2019, 2026)]

print("="*90)
print(f"   LOOKAHEAD-FREE META-SWITCHER (Dynamically choosing best of 6 models based on past {N_DAYS} days)")
print("="*90)
print(f"{'Year':<6} | {'Trades':<8} | {'Win Rate (%)':<15} | {'Total PnL (Rs)':<20}")
print("-" * 65)

total_pnl = 0
total_trades = 0
total_wins = 0

for year in sorted(meta_df['year'].unique()):
    y_df = meta_df[meta_df['year'] == year]
    t = len(y_df)
    w = (y_df['actual_pnl'] > 0).sum()
    wr = (w / t * 100) if t > 0 else 0
    p = y_df['actual_pnl'].sum()
    
    print(f"{year:<6} | {t:<8} | {wr:<15.1f} | Rs {p:,.2f}")
    total_pnl += p
    total_trades += t
    total_wins += w

ovr_wr = (total_wins / total_trades * 100) if total_trades > 0 else 0
print("-" * 65)
print(f"{'OVRAL':<6} | {total_trades:<8} | {ovr_wr:<15.1f} | Rs {total_pnl:,.2f}")
print("==========================================================================================")

# Also print the ensemble and daily baseline
ensemble_df = dfs['ensemble']
ensemble_df = ensemble_df[ensemble_df['date'].dt.year.between(2019, 2026)]
print(f"\n[Baseline] ENSEMBLE Total PnL : Rs {ensemble_df['actual_pnl'].sum():,.2f}  (Win Rate: {(ensemble_df['actual_pnl']>0).mean()*100:.1f}%)")

daily_df = dfs['daily']
daily_df = daily_df[daily_df['date'].dt.year.between(2019, 2026)]
print(f"[Baseline] DAILY Total PnL    : Rs {daily_df['actual_pnl'].sum():,.2f}  (Win Rate: {(daily_df['actual_pnl']>0).mean()*100:.1f}%)")
