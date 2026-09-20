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

def load_caches():
    caches = {}
    for name, filename in FILES.items():
        with open(os.path.join(OUTPUT_DIR, filename), 'rb') as f:
            caches[name] = pickle.load(f)
    return caches

def main():
    print("[*] Loading caches...")
    caches = load_caches()
    
    all_dates_sets = [set(cache.keys()) for cache in caches.values()]
    common_dates = sorted(list(set.intersection(*all_dates_sets)))
    
    records = []
    
    for dt in common_dates:
        yearly_entry = caches["Yearly"][dt]
        if isinstance(yearly_entry, dict) and yearly_entry.get('status') == 'SKIPPED':
            continue
            
        base_df = yearly_entry.copy()
        pred_series_list = []
        for name in FILES.keys():
            freq_entry = caches[name][dt]
            if isinstance(freq_entry, pd.DataFrame):
                freq_clean = freq_entry.drop_duplicates(subset=["stockname"])
                mapped_pred = freq_clean.set_index("stockname")["pred_pnl"]
                pred_series_list.append(base_df["stockname"].map(mapped_pred))
                
        if len(pred_series_list) == 0:
            continue
            
        stacked_preds = pd.concat(pred_series_list, axis=1)
        
        # Calculate trimmed mean for each row
        trimmed_means = []
        for idx, row in stacked_preds.iterrows():
            preds = row.dropna().values
            if len(preds) == 0:
                trimmed_means.append(0.0)
                continue
            if len(preds) >= 4:
                sorted_preds = sorted(preds)
                trimmed_mean_val = np.mean(sorted_preds[1:-1])
            else:
                trimmed_mean_val = np.median(preds)
            trimmed_means.append(trimmed_mean_val)
            
        base_df["trimmed_mean_pnl"] = trimmed_means
        
        # Collect all candidates with their actual PnL
        for idx, row in base_df.iterrows():
            if pd.notna(row['pnl']):
                records.append({
                    'stockname': row['stockname'],
                    'date': dt,
                    'trimmed_mean_pnl': row['trimmed_mean_pnl'],
                    'actual_pnl': row['pnl']
                })
                
    df_all = pd.DataFrame(records)
    
    thresholds = [2000, 2500, 3000, 3500, 4000, 4500, 5000, 6000]
    
    print("\n" + "="*85)
    print("           HISTORICAL PERFORMANCE OF HIGH-CONVICTION PREDICTED PNL CANDIDATES")
    print("="*85)
    print("  Trimmed Mean Threshold | Candidate Count | Win Rate (%) |  Avg Actual PnL  |  Total Actual PnL")
    print("  -----------------------|-----------------|--------------|------------------|------------------")
    for thr in thresholds:
        sub = df_all[df_all['trimmed_mean_pnl'] >= thr]
        count = len(sub)
        if count > 0:
            wins = (sub['actual_pnl'] > 0).sum()
            wr = wins / count * 100
            avg_pnl = sub['actual_pnl'].mean()
            tot_pnl = sub['actual_pnl'].sum()
            print(f"  Rs {thr:<19,} | {count:<15} | {wr:<12.1f}% | Rs {avg_pnl:<14,.2f} | Rs {tot_pnl:,.2f}")
        else:
            print(f"  Rs {thr:<19,} | 0               | N/A          | N/A              | N/A")
    print("="*85)

if __name__ == "__main__":
    main()
