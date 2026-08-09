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

def build_hybrid_cache(caches, k_adaptive=0.10, k_defensive=0.20, rolling_window=30):
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
    subprocess.run(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

def parse_model(filepath):
    if not os.path.exists(filepath):
        return None
    df = pd.read_csv(filepath)
    df['date'] = pd.to_datetime(df['date'])
    df['year'] = df['date'].dt.year
    
    # Yearly stats
    yoy = {}
    for yr in sorted(df['year'].unique()):
        yr_df = df[df['year'] == yr]
        trades = len(yr_df)
        wins = (yr_df['actual_pnl'] > 0).sum()
        wr = (wins / trades * 100) if trades > 0 else 0.0
        avg = yr_df['actual_pnl'].mean() if trades > 0 else 0.0
        yoy[yr] = (wr, avg, trades)
        
    # Overall
    trades = len(df)
    wins = (df['actual_pnl'] > 0).sum()
    wr = (wins / trades * 100) if trades > 0 else 0.0
    avg = df['actual_pnl'].mean() if trades > 0 else 0.0
    yoy['OVERALL'] = (wr, avg, trades)
    return yoy

def main():
    print("[*] Rebuilding ensemble cache with optimal K_base (0.10 / 0.20)...")
    caches = load_caches()
    build_hybrid_cache(caches, k_adaptive=0.10, k_defensive=0.20)
    
    print("[*] Generating optimized ensemble trade file...")
    run_simulation()
    
    # Paths to generated trades CSVs
    paths = {
        "Yearly": os.path.join(OUTPUT_DIR, "trades_dynamic_threshold_yearly.csv"),
        "Weekly": os.path.join(OUTPUT_DIR, "trades_dynamic_threshold_weekly.csv"),
        "Daily": os.path.join(OUTPUT_DIR, "trades_dynamic_threshold_daily.csv"),
        "Opt Ensemble": os.path.join(OUTPUT_DIR, "trades_dynamic_threshold_ensemble.csv")
    }
    
    data = {}
    for name, path in paths.items():
        yoy = parse_model(path)
        if yoy:
            data[name] = yoy
            
    years = [2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026, 'OVERALL']
    
    # Display comparison
    print("\n" + "="*125)
    print("                     YEAR-BY-YEAR DETAILED MULTI-FREQUENCY PERFORMANCE COMPARISON")
    print("="*125)
    print("        |         YEARLY MODEL         |         WEEKLY MODEL         |          DAILY MODEL         |    OPTIMIZED ENSEMBLE (0.10/0.20) ")
    print("  Year  |  Trades | Win Rate | Avg PnL |  Trades | Win Rate | Avg PnL |  Trades | Win Rate | Avg PnL |  Trades | Win Rate | Avg PnL  ")
    print("  ------|---------|----------|---------|---------|----------|---------|---------|----------|---------|---------|----------|----------")
    for yr in years:
        yr_label = f"{yr}" if isinstance(yr, int) else f"{yr:7}"
        
        # Yearly
        y_wr, y_avg, y_tr = data["Yearly"].get(yr, (0.0, 0.0, 0))
        # Weekly
        w_wr, w_avg, w_tr = data["Weekly"].get(yr, (0.0, 0.0, 0))
        # Daily
        d_wr, d_avg, d_tr = data["Daily"].get(yr, (0.0, 0.0, 0))
        # Ensemble
        e_wr, e_avg, e_tr = data["Opt Ensemble"].get(yr, (0.0, 0.0, 0))
        
        print(f"  {yr_label} | {y_tr:<7} | {y_wr:<7.1f}% | Rs {y_avg:<5.0f} | {w_tr:<7} | {w_wr:<7.1f}% | Rs {w_avg:<5.0f} | {d_tr:<7} | {d_wr:<7.1f}% | Rs {d_avg:<5.0f} | {e_tr:<7} | {e_wr:<7.1f}% | Rs {e_avg:<5.0f}")
    print("="*125)

if __name__ == "__main__":
    main()
