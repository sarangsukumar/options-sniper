#!/usr/bin/env python3
import os
import sys
import pickle
import subprocess
import pandas as pd
import numpy as np

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(_THIS_DIR, "output")

is_nf = os.getenv('REMOVE_EXTREME_TRAINING_LOSSES', 'False').lower() == 'true'
suffix = "_nf.pkl" if is_nf else ".pkl"

FILES = {
    "Daily": f"wf_predictions_cache_daily_da_standard_dl_3.0{suffix}",
    "Weekly": f"wf_predictions_cache_weekly_da_standard_dl_3.0{suffix}",
    "Monthly": f"wf_predictions_cache_monthly_da_standard_dl_3.0{suffix}",
    "Quarterly": f"wf_predictions_cache_quarterly_da_standard_dl_3.0{suffix}",
    "Yearly": f"wf_predictions_cache_yearly_da_standard_dl_3.0{suffix}"
}

def load_caches():
    caches = {}
    for name, filename in FILES.items():
        with open(os.path.join(OUTPUT_DIR, filename), 'rb') as f:
            caches[name] = pickle.load(f)
    return caches

def build_hybrid_cache(caches, rolling_window=30):
    all_dates_sets = [set(cache.keys()) for cache in caches.values()]
    common_dates = sorted(list(set.intersection(*all_dates_sets)))
    
    # Helper to resolve stockname and actual PnL
    def row_name_lookup(df, idx):
        return df.iloc[idx]['stockname'] if idx < len(df) else ""
        
    def row_pnl_lookup(df, idx):
        return df.iloc[idx]['pnl'] if idx < len(df) else 0.0

    print(f"\n[*] Starting pre-computation of model features across {len(common_dates)} days...")
    
    # 1. Pre-compute and cache all daily statistics to make the optimizer run at lightning speed
    precomputed_data = []
    historical_daily_medians = []

    
    for dt in common_dates:
        yearly_entry = caches["Yearly"][dt]
        if isinstance(yearly_entry, dict) and yearly_entry.get('status') == 'SKIPPED':
            precomputed_data.append({
                'date': dt,
                'year': dt.year,
                'status': 'SKIPPED',
                'reason': 'Skipped in Yearly cache'
            })
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
            precomputed_data.append({
                'date': dt,
                'year': dt.year,
                'status': 'SKIPPED',
                'reason': 'All models skipped'
            })
            continue
            
        stacked_preds = pd.concat(pred_series_list, axis=1)
        
        # Pre-compute model standard deviation for each stock on this day
        stock_features = []
        daily_std_devs = []
        for idx, row in stacked_preds.iterrows():
            preds = row.dropna().values
            trimmed_mean_val = 0.0
            if len(preds) > 0:
                if len(preds) >= 4:
                    sorted_preds = sorted(preds)
                    trimmed = sorted_preds[1:-1]
                    trimmed_mean_val = np.mean(trimmed)
                else:
                    trimmed_mean_val = np.median(preds)
                    
            std_dev = np.std(preds) if len(preds) > 1 else 0.0
            daily_std_devs.append(std_dev)
            
            stock_features.append({
                'stockname': row_name_lookup(base_df, idx),
                'trimmed_mean_val': trimmed_mean_val,
                'std_dev': std_dev,
                'pnl': row_pnl_lookup(base_df, idx)
            })
            
        median_std_dt = np.median(daily_std_devs) if len(daily_std_devs) > 0 else 0.0
        historical_daily_medians.append(median_std_dt)
        
        recent_medians = historical_daily_medians[-rolling_window:]
        baseline_std = np.mean(recent_medians) if len(recent_medians) > 0 else 1.0
        if baseline_std <= 0:
            baseline_std = 1.0
            
        precomputed_data.append({
            'date': dt,
            'year': dt.year,
            'status': 'ACTIVE',
            'stock_features': stock_features,
            'baseline_std': baseline_std,
            'base_df': base_df
        })
        
    print("✔ Pre-computation complete.")
    



    # 2. Fast lookahead-free simulation function for grid search
    def run_fast_switcher_sim(subset, k_super, k_trimmed, k_adaptive, k_defensive):
        sim_trades = []
        hist_trades = []
        for day in subset:
            if day['status'] == 'SKIPPED':
                continue
                
            # Determine state causally from historical trades
            if len(hist_trades) >= 10:
                recent = hist_trades[-10:]
                wins = sum(1 for p in recent if p > 0)
                trailing_wr = wins / 10.0
                trailing_avg_pnl = sum(recent) / 10.0
            else:
                # Default Neutral state for warm-ups (no aggressive forcing!)
                trailing_wr = 0.65
                trailing_avg_pnl = 800.0
                
            # Regime bounds
            if trailing_wr >= 0.85 and trailing_avg_pnl >= 2500.0:
                k_base = k_super
            elif trailing_wr >= 0.70 or trailing_avg_pnl >= 1000.0:
                k_base = k_trimmed
            elif trailing_wr < 0.60 and trailing_avg_pnl < 500.0:
                k_base = k_defensive
            else:
                k_base = k_adaptive
                
            # Calculate combined predictions
            day_preds = []
            for feat in day['stock_features']:
                K_dyn = k_base * (feat['std_dev'] / day['baseline_std'])
                K_dyn = max(0.0, min(1.5, K_dyn)) # Strictly bound K_dyn to avoid unbounded or negative multipliers
                
                comb = feat['trimmed_mean_val'] - K_dyn * feat['std_dev']
                day_preds.append((comb, feat['pnl']))
                
            day_preds.sort(key=lambda x: x[0], reverse=True)
            top_4 = day_preds[:4]
            
            for score, act_pnl in top_4:
                if not np.isnan(act_pnl):
                    sim_trades.append(act_pnl)
                    hist_trades.append(act_pnl)
                    
        if len(sim_trades) < 10:
            return -999.0
            
        # Calculate Average PnL of this parameter configuration
        return np.mean(sim_trades)

    # 3. Lookahead-Free Grid Search Optimizer
    def optimize_parameters_for_year(historical_precomputed):
        print(f"   • Optimizing parameters on {len(historical_precomputed)} days of historical data...")
        
        # Grid parameters - strictly non-negative to eliminate fragile disagreement rewards!
        grid_k_super = [0.00, 0.10]
        grid_k_trimmed = [0.10, 0.20]
        grid_k_adaptive = [0.20, 0.30, 0.40]
        grid_k_defensive = [0.50, 0.60, 0.80]
        
        best_score = -999.0
        best_params = (0.00, 0.10, 0.30, 0.60) # Balanced defaults
        
        for k_sup in grid_k_super:
            for k_tri in grid_k_trimmed:
                for k_ada in grid_k_adaptive:
                    for k_def in grid_k_defensive:
                        score = run_fast_switcher_sim(historical_precomputed, k_sup, k_tri, k_ada, k_def)
                        if score > best_score:
                            best_score = score
                            best_params = (k_sup, k_tri, k_ada, k_def)
                            
        print(f"   ✔ Winning parameters found (Avg PnL: {best_score:.4f}): K_super={best_params[0]:.2f}, K_trimmed={best_params[1]:.2f}, K_adaptive={best_params[2]:.2f}, K_defensive={best_params[3]:.2f}")
        return best_params

    # 4. Master Walk-Forward Simulation Loop
    ensemble_cache = {}
    historical_trades = []
    
    # Default parameters for bootstrap period (2019-2020)
    current_params = (0.10, 0.30, 0.60, 1.20)
    last_optimized_year = None
    
    state_stats = {'super_trimmed': 0, 'trimmed': 0, 'adaptive': 0, 'defensive': 0}
    
    for day in precomputed_data:
        dt = day['date']
        yr = day['year']
        
        if day['status'] == 'SKIPPED':
            ensemble_cache[dt] = {'status': 'SKIPPED', 'reason': day.get('reason', 'Skipped')}
            continue
            
        # Trigger Walk-Forward Optimization at the start of any new year (from 2021 onwards)
        if yr >= 2021 and yr != last_optimized_year:
            print(f"\n[🔄] Year change detected to {yr}. Triggering lookahead-free hyperparameter tuning...")
            history_subset = [d for d in precomputed_data if d['year'] < yr and d['status'] == 'ACTIVE']
            current_params = optimize_parameters_for_year(history_subset)
            last_optimized_year = yr
            
        k_sup, k_tri, k_ada, k_def = current_params
        
        # Determine State causally
        if len(historical_trades) >= 10:
            recent_trades = historical_trades[-10:]
            wins = sum(1 for p in recent_trades if p > 0)
            trailing_wr = wins / 10.0
            trailing_avg_pnl = sum(recent_trades) / 10.0
        else:
            # Default Neutral state for warm-ups (no aggressive forcing!)
            trailing_wr = 0.65
            trailing_avg_pnl = 800.0
            
        # Select active state
        if trailing_wr >= 0.85 and trailing_avg_pnl >= 2500.0:
            k_base = k_sup
            state_stats['super_trimmed'] = state_stats.get('super_trimmed', 0) + 1
        elif trailing_wr >= 0.70 or trailing_avg_pnl >= 1000.0:
            k_base = k_tri
            state_stats['trimmed'] += 1
        elif trailing_wr < 0.60 and trailing_avg_pnl < 500.0:
            k_base = k_def
            state_stats['defensive'] += 1
        else:
            k_base = k_ada
            state_stats['adaptive'] += 1
            
        # Generate combined predictions for ensemble cache row
        base_df = day['base_df']
        combined_preds = []
        
        for feat in day['stock_features']:
            K_dyn = k_base * (feat['std_dev'] / day['baseline_std'])
            K_dyn = max(0.0, min(1.5, K_dyn)) # Restrict K_dyn bounds to avoid unbounded or negative multipliers
            
            comb = feat['trimmed_mean_val'] - K_dyn * feat['std_dev']
            combined_preds.append(comb)
            
        base_df["pred_pnl"] = combined_preds
        ensemble_cache[dt] = base_df
        
        # Save actual results to trailing tracker (Causal Model Performance Tracker)
        base_df_sorted = base_df.sort_values(by="pred_pnl", ascending=False)
        top_4_actuals = base_df_sorted.head(4)["pnl"].dropna().values
        for p in top_4_actuals:
            historical_trades.append(p)
            
    # Save the ensemble cache with the '_nf' suffix
    ensemble_cache_path = os.path.join(OUTPUT_DIR, "wf_predictions_cache_ensemble_da_standard_dl_3.0_nf.pkl")
    with open(ensemble_cache_path, 'wb') as f:
        pickle.dump(ensemble_cache, f, protocol=pickle.HIGHEST_PROTOCOL)
        
    print(f"\n[+] Lookahead-Free WFHO Hybrid Cache Built Successfully:")
    print(f"    • Super-Trimmed State Days: {state_stats.get('super_trimmed', 0)} days")
    print(f"    • Trimmed State Days      : {state_stats['trimmed']} days")
    print(f"    • Adaptive State Days     : {state_stats['adaptive']} days")
    print(f"    • Defensive State Days    : {state_stats['defensive']} days")

def run_simulation(max_trades, capital):
    cmd = [sys.executable, "dynamic_threshold.py", "ensemble"]
    env = os.environ.copy()
    env["START_YEAR"] = "2019"
    env["END_YEAR"] = "2026"
    env["DISABLE_PDF"] = "True"
    env["REMOVE_EXTREME_TRAINING_LOSSES"] = "True"  # This guarantees it loads the '_nf' ensemble cache!
    env["DYN_MAX_TRADES"] = str(max_trades)
    env["DYN_INITIAL_CAPITAL"] = str(capital)
    env["ENABLE_DYNAMIC_STEPS"] = "True"
    env["ENABLE_DYNAMIC_BOUNDS"] = "True"
    process = subprocess.run(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return process.returncode == 0

def extract_metrics(capital=600000.0):
    # Ensemble trade csv path for noise-removed
    trades_path = os.path.join(OUTPUT_DIR, "trades_dynamic_threshold_ensemble.csv")
    df = pd.read_csv(trades_path)
    df['date'] = pd.to_datetime(df['date'])
    df['year'] = df['date'].dt.year
    df = df[df['year'].between(2019, 2026)].copy()
    
    # Calculate portfolio stats
    df_sorted = df.sort_values('date')
    daily_pnl = df_sorted.groupby(df_sorted['date'].dt.date)['actual_pnl'].sum().reset_index()
    daily_pnl = daily_pnl.sort_values('date')
    daily_pnl['cum_pnl'] = daily_pnl['actual_pnl'].cumsum()
    daily_pnl['equity'] = capital + daily_pnl['cum_pnl']
    daily_pnl['peak'] = daily_pnl['equity'].cummax()
    daily_pnl['drawdown'] = (daily_pnl['equity'] - daily_pnl['peak']) / daily_pnl['peak']
    mdd = daily_pnl['drawdown'].min() * 100
    
    start_date = df['date'].min()
    end_date = df['date'].max()
    years_span = (end_date - start_date).days / 365.25
    final_equity = capital + df['actual_pnl'].sum()
    cagr = ((final_equity / capital) ** (1.0 / years_span) - 1.0) * 100
    
    daily_pnl['daily_ret'] = daily_pnl['actual_pnl'] / capital
    mean_ret = daily_pnl['daily_ret'].mean()
    std_ret = daily_pnl['daily_ret'].std()
    sharpe = (mean_ret / std_ret * np.sqrt(252)) if std_ret > 0 else 0.0
    
    yoy_records = {}
    for yr in sorted(df['year'].unique()):
        yr_df = df[df['year'] == yr]
        trades = len(yr_df)
        wins = (yr_df['actual_pnl'] > 0).sum()
        win_rate = (wins / trades * 100) if trades > 0 else 0.0
        avg_pnl = yr_df['actual_pnl'].mean() if trades > 0 else 0.0
        total_pnl = yr_df['actual_pnl'].sum()
        yoy_records[yr] = {
            "Trades": trades,
            "WinRate": win_rate,
            "AvgPnL": avg_pnl,
            "TotalPnL": total_pnl
        }
    yoy_records["OVERALL"] = {
        "Trades": len(df),
        "WinRate": (df['actual_pnl'] > 0).mean() * 100,
        "AvgPnL": df['actual_pnl'].mean(),
        "TotalPnL": df['actual_pnl'].sum(),
        "CAGR": cagr,
        "MaxDD": mdd,
        "Sharpe": sharpe
    }
    return yoy_records

def main():
    print("[*] Loading noise-filtered caches...")
    caches = load_caches()
    build_hybrid_cache(caches)
    
    print("\n[*] Running backtest simulation (Max Orders = 4, Capital = Rs 6,00,000)...")
    success = run_simulation(4, 600000.0)
    if not success:
        print("[!] Backtest simulation failed.")
        return
        
    m = extract_metrics()
    
    print("\n" + "="*90)
    print("      NOISE-REMOVED DUAL-METRIC HYBRID REGIME SWITCHER — AUDITED PERFORMANCE")
    print("="*90)
    print("  Year  |  Total Trades  |  Win Rate (%)  |  Avg PnL / Trade  |   Total Realized PnL ")
    print("  ------|----------------|----------------|-------------------|----------------------")
    years = [2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026]
    for yr in years:
        r = m[yr]
        print(f"  {yr:<5} | {r['Trades']:<14} | {r['WinRate']:<14.1f}% | Rs {r['AvgPnL']:<17,.2f} | Rs {r['TotalPnL']:,.2f}")
    print("  ------|----------------|----------------|-------------------|----------------------")
    ov = m["OVERALL"]
    print(f"  OVRAL | {ov['Trades']:<14} | {ov['WinRate']:<14.1f}% | Rs {ov['AvgPnL']:<17,.2f} | Rs {ov['TotalPnL']:,.2f}")
    print("  ------|----------------|----------------|-------------------|----------------------")
    print(f"  Sharpe Ratio (Ann):  {ov['Sharpe']:.2f}")
    print(f"  Overall CAGR       :  {ov['CAGR']:.2f}%")
    print(f"  Maximum Drawdown   : {ov['MaxDD']:.2f}%")
    print("="*90)

if __name__ == "__main__":
    main()
