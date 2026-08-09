#!/usr/bin/env python3
import os
import pickle
import pandas as pd
import numpy as np

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(_THIS_DIR, "output")

FILES = {
    "Daily": "wf_predictions_cache_daily_da_standard_dl_3.0_nf.pkl",
    "Weekly": "wf_predictions_cache_weekly_da_standard_dl_3.0_nf.pkl",
    "Monthly": "wf_predictions_cache_monthly_da_standard_dl_3.0_nf.pkl",
    "Quarterly": "wf_predictions_cache_quarterly_da_standard_dl_3.0_nf.pkl",
    "Yearly": "wf_predictions_cache_yearly_da_standard_dl_3.0_nf.pkl"
}

def main():
    print("[*] Loading caches...")
    caches = {}
    for name, filename in FILES.items():
        with open(os.path.join(OUTPUT_DIR, filename), 'rb') as f:
            caches[name] = pickle.load(f)
            
    all_dates_sets = [set(cache.keys()) for cache in caches.values()]
    common_dates = sorted(list(set.intersection(*all_dates_sets)))
    
    historical_trades = []
    regimes_2026 = []
    
    for dt in common_dates:
        yearly_entry = caches["Yearly"][dt]
        if isinstance(yearly_entry, dict) and yearly_entry.get('status') == 'SKIPPED':
            continue
            
        base_df = yearly_entry.copy()
        
        # Determine State Gate
        if len(historical_trades) >= 15:
            recent_trades = historical_trades[-15:]
            wins = sum(1 for p in recent_trades if p > 0)
            trailing_wr = wins / 15.0
            trailing_avg_pnl = sum(recent_trades) / 15.0
        else:
            trailing_wr = 0.75
            trailing_avg_pnl = 1500.0
            
        if trailing_wr >= 0.75 or trailing_avg_pnl >= 1500.0:
            regime = 'trimmed'
        elif trailing_wr < 0.60 and trailing_avg_pnl < 500.0:
            regime = 'defensive'
        else:
            regime = 'adaptive'
            
        # If the date is in 2026, record the state
        dt_parsed = pd.to_datetime(dt)
        if dt_parsed.year == 2026:
            regimes_2026.append({
                'date': dt_parsed,
                'regime': regime,
                'trailing_wr': trailing_wr * 100,
                'trailing_avg_pnl': trailing_avg_pnl
            })
            
        # Update trailing list with top 4 predicted trades (or actual head(4))
        # Wait, the simulator selects trades where pred_pnl exceeds the dynamic threshold!
        # Let's read from the actual trades csv to see which trades were actually executed!
    
    trades_path = os.path.join(OUTPUT_DIR, "trades_dynamic_threshold_ensemble.csv")
    if os.path.exists(trades_path):
        df_trades = pd.read_csv(trades_path)
        df_trades['date'] = pd.to_datetime(df_trades['date'])
        
        # Let's reconstruct lookahead-free trailing states from actual trades
        df_trades = df_trades.sort_values('date').reset_index(drop=True)
        
        historical_trades = []
        regimes_by_date = {}
        
        # We will loop day-by-day based on unique trade dates
        unique_dates = sorted(df_trades['date'].unique())
        
        for u_dt in unique_dates:
            if len(historical_trades) >= 15:
                recent_trades = historical_trades[-15:]
                wins = sum(1 for p in recent_trades if p > 0)
                trailing_wr = wins / 15.0
                trailing_avg_pnl = sum(recent_trades) / 15.0
            else:
                trailing_wr = 0.75
                trailing_avg_pnl = 1500.0
                
            if trailing_wr >= 0.75 or trailing_avg_pnl >= 1500.0:
                regime = 'trimmed'
            elif trailing_wr < 0.60 and trailing_avg_pnl < 500.0:
                regime = 'defensive'
            else:
                regime = 'adaptive'
                
            regimes_by_date[u_dt] = {
                'regime': regime,
                'trailing_wr': trailing_wr * 100,
                'trailing_avg_pnl': trailing_avg_pnl
            }
            
            # Append today's actual trades to history
            day_trades = df_trades[df_trades['date'] == u_dt]['actual_pnl'].tolist()
            historical_trades.extend(day_trades)
            
        # Filter for 2026
        regimes_2026 = []
        for d, info in regimes_by_date.items():
            if d.year == 2026:
                regimes_2026.append({
                    'date': d,
                    'regime': info['regime'],
                    'trailing_wr': info['trailing_wr'],
                    'trailing_avg_pnl': info['trailing_avg_pnl']
                })
                
        df_reg_2026 = pd.DataFrame(regimes_2026)
        print("\n" + "="*80)
        print("                  2026 DUAL-METRIC STATE REGIME REPORT")
        print("="*80)
        print(f"Total Trading Days with Completed Trades: {len(df_reg_2026)}")
        
        counts = df_reg_2026['regime'].value_counts()
        for reg in ['trimmed', 'adaptive', 'defensive']:
            c = counts.get(reg, 0)
            pct = (c / len(df_reg_2026) * 100) if len(df_reg_2026) > 0 else 0
            print(f"  • {reg.capitalize():10} Days : {c} days ({pct:.1f}%)")
            
        print("\n[+] Day-by-Day State Evolution in 2026:")
        print("  Date       | Regime    | Trailing Win Rate | Trailing Avg PnL ")
        print("  -----------|-----------|-------------------|------------------")
        for idx, row in df_reg_2026.head(20).iterrows():
            print(f"  {row['date'].strftime('%Y-%m-%d')} | {row['regime']:9} | {row['trailing_wr']:17.1f}% | Rs {row['trailing_avg_pnl']:14,.2f}")
        if len(df_reg_2026) > 20:
            print("  ... [Output Truncated for Brevity] ...")
            for idx, row in df_reg_2026.tail(10).iterrows():
                print(f"  {row['date'].strftime('%Y-%m-%d')} | {row['regime']:9} | {row['trailing_wr']:17.1f}% | Rs {row['trailing_avg_pnl']:14,.2f}")
                
    else:
        print("[!] No trades file found.")

if __name__ == "__main__":
    main()
