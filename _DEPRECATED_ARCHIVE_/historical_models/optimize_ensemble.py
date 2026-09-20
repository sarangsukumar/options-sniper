#!/usr/bin/env python3
import os
import sys
import pickle
import subprocess
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

def build_hybrid_cache(caches, k_adaptive, k_defensive, rolling_window=30):
    all_dates_sets = [set(cache.keys()) for cache in caches.values()]
    common_dates = sorted(list(set.intersection(*all_dates_sets)))
    
    ensemble_cache = {}
    historical_daily_medians = []
    historical_trades = []
    
    for dt in common_dates:
        yearly_entry = caches["Yearly"][dt]
        if isinstance(yearly_entry, dict) and yearly_entry.get('status') == 'SKIPPED':
            ensemble_cache[dt] = yearly_entry
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
            ensemble_cache[dt] = {'status': 'SKIPPED', 'reason': 'All models skipped'}
            continue
            
        stacked_preds = pd.concat(pred_series_list, axis=1)
        
        if len(historical_trades) >= 15:
            recent_trades = historical_trades[-15:]
            wins = sum(1 for p in recent_trades if p > 0)
            trailing_wr = wins / 15.0
            trailing_avg_pnl = sum(recent_trades) / 15.0
        else:
            trailing_wr = 0.75
            trailing_avg_pnl = 1500.0
            
        if trailing_wr >= 0.75 or trailing_avg_pnl >= 1500.0:
            k_base = 0.00
        elif trailing_wr < 0.60 and trailing_avg_pnl < 500.0:
            k_base = k_defensive
        else:
            k_base = k_adaptive
            
        daily_std_devs = []
        for idx, row in stacked_preds.iterrows():
            preds = row.dropna().values
            if len(preds) > 1:
                daily_std_devs.append(np.std(preds))
            else:
                daily_std_devs.append(0.0)
                
        median_std_dt = np.median(daily_std_devs) if len(daily_std_devs) > 0 else 0.0
        historical_daily_medians.append(median_std_dt)
        
        recent_medians = historical_daily_medians[-rolling_window:]
        baseline_std = np.mean(recent_medians) if len(recent_medians) > 0 else 1.0
        if baseline_std <= 0:
            baseline_std = 1.0
            
        combined_preds = []
        for idx, row in stacked_preds.iterrows():
            preds = row.dropna().values
            if len(preds) == 0:
                combined_preds.append(0.0)
                continue
                
            if len(preds) >= 4:
                sorted_preds = sorted(preds)
                trimmed = sorted_preds[1:-1]
                trimmed_mean_val = np.mean(trimmed)
            else:
                trimmed_mean_val = np.median(preds)
                
            std_dev = np.std(preds) if len(preds) > 1 else 0.0
            K_dyn = k_base * (std_dev / baseline_std)
            K_dyn = min(1.5, K_dyn)
            
            combined = trimmed_mean_val - K_dyn * std_dev
            combined_preds.append(combined)
            
        base_df["pred_pnl"] = combined_preds
        ensemble_cache[dt] = base_df
        
        base_df_sorted = base_df.sort_values(by="pred_pnl", ascending=False)
        top_4_actuals = base_df_sorted.head(4)["pnl"].dropna().values
        for p in top_4_actuals:
            historical_trades.append(p)
            
    ensemble_cache_path = os.path.join(OUTPUT_DIR, "wf_predictions_cache_ensemble_da_standard_dl_3.0_nf.pkl")
    with open(ensemble_cache_path, 'wb') as f:
        pickle.dump(ensemble_cache, f, protocol=pickle.HIGHEST_PROTOCOL)

def run_simulation():
    cmd = [sys.executable, "dynamic_threshold.py", "ensemble"]
    env = os.environ.copy()
    env["START_YEAR"] = "2019"
    env["END_YEAR"] = "2026"
    env["DISABLE_PDF"] = "True"
    env["REMOVE_EXTREME_TRAINING_LOSSES"] = "True"
    env["DYN_MAX_TRADES"] = "4"
    env["DYN_INITIAL_CAPITAL"] = "600000.0"
    env["ENABLE_DYNAMIC_STEPS"] = "True"
    env["ENABLE_DYNAMIC_BOUNDS"] = "True"
    process = subprocess.run(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return process.returncode == 0

def extract_metrics():
    trades_path = os.path.join(OUTPUT_DIR, "trades_dynamic_threshold_ensemble.csv")
    if not os.path.exists(trades_path):
        return None
    df = pd.read_csv(trades_path)
    df['date'] = pd.to_datetime(df['date'])
    df['year'] = df['date'].dt.year
    
    df_sorted = df.sort_values('date')
    daily_pnl = df_sorted.groupby(df_sorted['date'].dt.date)['actual_pnl'].sum().reset_index()
    daily_pnl = daily_pnl.sort_values('date')
    daily_pnl['cum_pnl'] = daily_pnl['actual_pnl'].cumsum()
    daily_pnl['equity'] = 600000.0 + daily_pnl['cum_pnl']
    daily_pnl['peak'] = daily_pnl['equity'].cummax()
    daily_pnl['drawdown'] = (daily_pnl['equity'] - daily_pnl['peak']) / daily_pnl['peak']
    mdd = daily_pnl['drawdown'].min() * 100
    
    start_date = df['date'].min()
    end_date = df['date'].max()
    years_span = (end_date - start_date).days / 365.25
    final_equity = 600000.0 + df['actual_pnl'].sum()
    cagr = ((final_equity / 600000.0) ** (1.0 / years_span) - 1.0) * 100
    
    daily_pnl['daily_ret'] = daily_pnl['actual_pnl'] / 600000.0
    mean_ret = daily_pnl['daily_ret'].mean()
    std_ret = daily_pnl['daily_ret'].std()
    sharpe = (mean_ret / std_ret * np.sqrt(252)) if std_ret > 0 else 0.0
    
    df_2026 = df[df['year'] == 2026]
    trades_2026 = len(df_2026)
    avg_pnl_2026 = df_2026['actual_pnl'].mean() if trades_2026 > 0 else 0.0
    tot_pnl_2026 = df_2026['actual_pnl'].sum()
    
    return {
        "CAGR": cagr,
        "MaxDD": mdd,
        "Sharpe": sharpe,
        "AvgPnL_2026": avg_pnl_2026,
        "TotPnL_2026": tot_pnl_2026,
        "Trades_2026": trades_2026
    }

def main():
    print("[*] Loading caches...")
    caches = load_caches()
    
    # Grid of candidate K_base values
    candidates = [
        (0.60, 0.90), # Current baseline
        (0.40, 0.80),
        (0.30, 0.60),
        (0.20, 0.40),
        (0.10, 0.20),
        (0.00, 0.00)  # Pure unpenalized ensemble!
    ]
    
    results = []
    
    print("\n" + "="*95)
    print("                     ENSEMBLE OPTIMIZATION HYPERPARAMETER GRID SEARCH")
    print("="*95)
    print("  Adaptive K | Defensive K | Overall CAGR | Max Drawdown | Sharpe | 2026 Trades | 2026 Avg PnL | 2026 Tot PnL ")
    print("  -----------|-------------|--------------|--------------|--------|-------------|--------------|--------------")
    
    for k_ad, k_def in candidates:
        build_hybrid_cache(caches, k_ad, k_def)
        success = run_simulation()
        if success:
            metrics = extract_metrics()
            if metrics:
                print(f"  {k_ad:<10.2f} | {k_def:<11.2f} | {metrics['CAGR']:<12.2f}% | {metrics['MaxDD']:<12.2f}% | {metrics['Sharpe']:<6.2f} | {metrics['Trades_2026']:<11} | Rs {metrics['AvgPnL_2026']:<10,.2f} | Rs {metrics['TotPnL_2026']:,.2f}")
                results.append({
                    'k_adaptive': k_ad,
                    'k_defensive': k_def,
                    **metrics
                })
        else:
            print(f"  Failed for K_ad={k_ad}, K_def={k_def}")
            
    print("="*95)

if __name__ == "__main__":
    main()
