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

def build_hybrid_cache_and_simulate(caches, k_super_grid, k_trimmed_grid, k_adaptive_grid, k_defensive_grid, objective_metric='sharpe', rolling_window=30):
    all_dates_sets = [set(cache.keys()) for cache in caches.values()]
    common_dates = sorted(list(set.intersection(*all_dates_sets)))
    
    # Helper to resolve stockname and actual PnL
    def row_name_lookup(df, idx):
        return df.iloc[idx]['stockname'] if idx < len(df) else ""
        
    def row_pnl_lookup(df, idx):
        return df.iloc[idx]['pnl'] if idx < len(df) else 0.0

    # 1. Pre-compute and cache all daily statistics
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

    # Fast switcher simulation for lookahead-free optimization
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
                trailing_wr = 0.65
                trailing_avg_pnl = 800.0
                
            if trailing_wr >= 0.85 and trailing_avg_pnl >= 2500.0:
                k_base = k_super
            elif trailing_wr >= 0.70 or trailing_avg_pnl >= 1000.0:
                k_base = k_trimmed
            elif trailing_wr < 0.60 and trailing_avg_pnl < 500.0:
                k_base = k_defensive
            else:
                k_base = k_adaptive
                
            day_preds = []
            for feat in day['stock_features']:
                K_dyn = k_base * (feat['std_dev'] / day['baseline_std'])
                K_dyn = max(0.0, min(1.5, K_dyn))
                
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
            
        if objective_metric == 'sharpe':
            mean_pnl = np.mean(sim_trades)
            std_pnl = np.std(sim_trades)
            return (mean_pnl / std_pnl) if std_pnl > 0 else -999.0
        elif objective_metric == 'avg_pnl':
            return np.mean(sim_trades)
        elif objective_metric == 'profit_factor':
            pos_sum = sum(p for p in sim_trades if p > 0)
            neg_sum = abs(sum(p for p in sim_trades if p < 0))
            return (pos_sum / neg_sum) if neg_sum > 0 else 999.0
        else: # net_pnl
            return sum(sim_trades)

    def optimize_parameters_for_year(historical_precomputed):
        best_score = -999.0
        best_params = (k_super_grid[0], k_trimmed_grid[0], k_adaptive_grid[0], k_defensive_grid[0])
        
        for k_sup in k_super_grid:
            for k_tri in k_trimmed_grid:
                for k_ada in k_adaptive_grid:
                    for k_def in k_defensive_grid:
                        score = run_fast_switcher_sim(historical_precomputed, k_sup, k_tri, k_ada, k_def)
                        if score > best_score:
                            best_score = score
                            best_params = (k_sup, k_tri, k_ada, k_def)
                            
        return best_params

    # Run the walk-forward simulation
    ensemble_cache = {}
    historical_trades = []
    current_params = (0.10, 0.30, 0.60, 1.20)
    last_optimized_year = None
    
    for day in precomputed_data:
        dt = day['date']
        yr = day['year']
        
        if day['status'] == 'SKIPPED':
            ensemble_cache[dt] = {'status': 'SKIPPED', 'reason': day.get('reason', 'Skipped')}
            continue
            
        if yr >= 2021 and yr != last_optimized_year:
            history_subset = [d for d in precomputed_data if d['year'] < yr and d['status'] == 'ACTIVE']
            current_params = optimize_parameters_for_year(history_subset)
            last_optimized_year = yr
            
        k_sup, k_tri, k_ada, k_def = current_params
        
        if len(historical_trades) >= 10:
            recent_trades = historical_trades[-10:]
            wins = sum(1 for p in recent_trades if p > 0)
            trailing_wr = wins / 10.0
            trailing_avg_pnl = sum(recent_trades) / 10.0
        else:
            trailing_wr = 0.65
            trailing_avg_pnl = 800.0
            
        if trailing_wr >= 0.85 and trailing_avg_pnl >= 2500.0:
            k_base = k_sup
        elif trailing_wr >= 0.70 or trailing_avg_pnl >= 1000.0:
            k_base = k_tri
        elif trailing_wr < 0.60 and trailing_avg_pnl < 500.0:
            k_base = k_def
        else:
            k_base = k_ada
            
        base_df = day['base_df']
        combined_preds = []
        
        for feat in day['stock_features']:
            K_dyn = k_base * (feat['std_dev'] / day['baseline_std'])
            K_dyn = max(0.0, min(1.5, K_dyn))
            
            comb = feat['trimmed_mean_val'] - K_dyn * feat['std_dev']
            combined_preds.append(comb)
            
        base_df["pred_pnl"] = combined_preds
        ensemble_cache[dt] = base_df
        
        base_df_sorted = base_df.sort_values(by="pred_pnl", ascending=False)
        top_4_actuals = base_df_sorted.head(4)["pnl"].dropna().values
        for p in top_4_actuals:
            historical_trades.append(p)
            
    # Save cache
    ensemble_cache_path = os.path.join(OUTPUT_DIR, "wf_predictions_cache_ensemble_da_standard_dl_3.0_nf.pkl")
    with open(ensemble_cache_path, 'wb') as f:
        pickle.dump(ensemble_cache, f, protocol=pickle.HIGHEST_PROTOCOL)

def run_simulation(max_trades=4, capital=600000.0):
    cmd = [sys.executable, "dynamic_threshold.py", "ensemble"]
    env = os.environ.copy()
    env["START_YEAR"] = "2019"
    env["END_YEAR"] = "2026"
    env["DISABLE_PDF"] = "True"
    env["REMOVE_EXTREME_TRAINING_LOSSES"] = "True"
    env["DYN_MAX_TRADES"] = str(max_trades)
    env["DYN_INITIAL_CAPITAL"] = str(capital)
    env["ENABLE_DYNAMIC_STEPS"] = "True"
    env["ENABLE_DYNAMIC_BOUNDS"] = "True"
    process = subprocess.run(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return process.returncode == 0

def extract_yoy_metrics(capital=600000.0):
    trades_path = os.path.join(OUTPUT_DIR, "trades_dynamic_threshold_ensemble.csv")
    if not os.path.exists(trades_path):
        return None
    df = pd.read_csv(trades_path)
    df['date'] = pd.to_datetime(df['date'])
    df['year'] = df['date'].dt.year
    df = df[df['year'].between(2019, 2026)].copy()
    
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
        "TotalPnL": df['actual_pnl'].sum()
    }
    return yoy_records

def main():
    print("[*] Loading noise-filtered caches...")
    caches = load_caches()
    
    # Define various lookahead-free configurations to test!
    scenarios = [
        {
            "name": "Scenario 1: Baseline Sharpe (Strict Bounds)",
            "k_super_grid": [0.00, 0.10, 0.20],
            "k_trimmed_grid": [0.20, 0.30, 0.40],
            "k_adaptive_grid": [0.50, 0.60, 0.70],
            "k_defensive_grid": [1.00, 1.20, 1.40],
            "objective_metric": "sharpe"
        },
        {
            "name": "Scenario 2: Relaxed Disagreement Penalty (Direct Avg PnL Objective)",
            "k_super_grid": [0.00, 0.10],
            "k_trimmed_grid": [0.10, 0.20],
            "k_adaptive_grid": [0.20, 0.30, 0.40],
            "k_defensive_grid": [0.50, 0.60, 0.80],
            "objective_metric": "avg_pnl"
        },
        {
            "name": "Scenario 3: Relaxed Disagreement Penalty (Sharpe Objective)",
            "k_super_grid": [0.00, 0.10],
            "k_trimmed_grid": [0.10, 0.20],
            "k_adaptive_grid": [0.20, 0.30, 0.40],
            "k_defensive_grid": [0.50, 0.60, 0.80],
            "objective_metric": "sharpe"
        },
        {
            "name": "Scenario 4: Gentle Linear Penalty Grid (Avg PnL Objective)",
            "k_super_grid": [0.00],
            "k_trimmed_grid": [0.05, 0.10],
            "k_adaptive_grid": [0.15, 0.20],
            "k_defensive_grid": [0.30, 0.40],
            "objective_metric": "avg_pnl"
        },
        {
            "name": "Scenario 5: Pure Zero-Penalty (Standard Trimmed Mean)",
            "k_super_grid": [0.00],
            "k_trimmed_grid": [0.00],
            "k_adaptive_grid": [0.00],
            "k_defensive_grid": [0.00],
            "objective_metric": "sharpe"
        }
    ]
    
    results = []
    
    for sc in scenarios:
        print(f"\nEvaluating {sc['name']}...")
        build_hybrid_cache_and_simulate(
            caches, 
            sc['k_super_grid'], 
            sc['k_trimmed_grid'], 
            sc['k_adaptive_grid'], 
            sc['k_defensive_grid'], 
            sc['objective_metric']
        )
        
        success = run_simulation()
        if not success:
            print(f"[!] Simulation failed for {sc['name']}")
            continue
            
        m = extract_yoy_metrics()
        if m is not None:
            ov = m["OVERALL"]
            y2026 = m.get(2026, {"Trades": 0, "WinRate": 0, "AvgPnL": 0, "TotalPnL": 0})
            results.append({
                "name": sc['name'],
                "overall_trades": ov['Trades'],
                "overall_pnl": ov['TotalPnL'],
                "overall_avg_pnl": ov['AvgPnL'],
                "y2026_trades": y2026['Trades'],
                "y2026_winrate": y2026['WinRate'],
                "y2026_avg_pnl": y2026['AvgPnL'],
                "y2026_total_pnl": y2026['TotalPnL']
            })
            
            print(f"--> [2026 OUT-OF-SAMPLE] Avg PnL: Rs {y2026['AvgPnL']:,.2f} | Trades: {y2026['Trades']} | Win Rate: {y2026['WinRate']:.1f}%")
            print(f"--> [OVERALL] Total PnL: Rs {ov['TotalPnL']:,.2f} | Avg PnL: Rs {ov['AvgPnL']:,.2f}")
            
    print("\n" + "="*90)
    print("                      COMPARATIVE CONFIGURATION SWEEP SUMMARY")
    print("="*90)
    print(f"{'Scenario Name':<50} | {'2026 Avg PnL':<15} | {'2026 Trades':<12} | {'Overall PnL':<15}")
    print("-"*97)
    for r in results:
        print(f"{r['name'][:48]:<50} | Rs {r['y2026_avg_pnl']:<12,.2f} | {r['y2026_trades']:<11} | Rs {r['overall_pnl']:<15,.2f}")
    print("="*90)

if __name__ == "__main__":
    main()
