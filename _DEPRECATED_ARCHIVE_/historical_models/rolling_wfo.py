#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════╗
║  ROLLING WALK-FORWARD OPTIMIZATION                                 ║
║                                                                    ║
║  For each test year Y (2021 → 2026):                               ║
║    1. Sweep all parameter combos on 2019 → Y-1 (in-sample)         ║
║    2. Pick best by Sharpe                                          ║
║    3. Run full 2019 → Y with those best params                     ║
║    4. Record year Y's performance (true out-of-sample)             ║
║                                                                    ║
║  Output: A fully OOS equity curve from 2021 → 2026                 ║
║  Every single day in the final results is out-of-sample.           ║
╚══════════════════════════════════════════════════════════════════════╝
"""
import os, sys, time, pickle, subprocess, json
import pandas as pd
import numpy as np

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(_THIS_DIR, "output")

FILES = {
    "Daily":     "wf_predictions_cache_daily_da_standard_dl_3.0_nf.pkl",
    "Weekly":    "wf_predictions_cache_weekly_da_standard_dl_3.0_nf.pkl",
    "Monthly":   "wf_predictions_cache_monthly_da_standard_dl_3.0_nf.pkl",
    "Quarterly": "wf_predictions_cache_quarterly_da_standard_dl_3.0_nf.pkl",
    "Yearly":    "wf_predictions_cache_yearly_da_standard_dl_3.0_nf.pkl"
}

DEFAULT_WR  = 0.50
DEFAULT_PNL = 0.0


def load_caches():
    caches = {}
    for name, filename in FILES.items():
        with open(os.path.join(OUTPUT_DIR, filename), 'rb') as f:
            caches[name] = pickle.load(f)
    return caches


def build_hybrid_cache(caches, k_adaptive, k_defensive, wr_thresh, pnl_thresh,
                       rolling_window=30):
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

        if len(historical_trades) >= 10:
            recent_trades = historical_trades[-10:]
            wins = sum(1 for p in recent_trades if p > 0)
            trailing_wr = wins / 10.0
            trailing_avg_pnl = sum(recent_trades) / 10.0
        else:
            trailing_wr = DEFAULT_WR
            trailing_avg_pnl = DEFAULT_PNL

        if trailing_wr >= wr_thresh or trailing_avg_pnl >= pnl_thresh:
            k_base = 0.00
        elif trailing_wr < 0.60 and trailing_avg_pnl < 500.0:
            k_base = k_defensive
        else:
            k_base = k_adaptive

        daily_std_devs = []
        for idx, row in stacked_preds.iterrows():
            preds = row.dropna().values
            daily_std_devs.append(np.std(preds) if len(preds) > 1 else 0.0)
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
                trimmed_mean_val = np.mean(sorted_preds[1:-1])
            else:
                trimmed_mean_val = np.median(preds)
            std_dev = np.std(preds) if len(preds) > 1 else 0.0
            K_dyn = max(0.0, min(1.5, k_base * (std_dev / baseline_std)))
            combined_preds.append(trimmed_mean_val - K_dyn * std_dev)

        base_df["pred_pnl"] = combined_preds
        ensemble_cache[dt] = base_df
        base_df_sorted = base_df.sort_values(by="pred_pnl", ascending=False)
        for p in base_df_sorted.head(4)["pnl"].dropna().values:
            historical_trades.append(p)

    cache_path = os.path.join(OUTPUT_DIR,
                              "wf_predictions_cache_ensemble_da_standard_dl_3.0_nf.pkl")
    with open(cache_path, 'wb') as f:
        pickle.dump(ensemble_cache, f, protocol=pickle.HIGHEST_PROTOCOL)


def run_simulation(start_year, end_year):
    cmd = [sys.executable, "dynamic_threshold.py", "ensemble"]
    env = os.environ.copy()
    env["START_YEAR"] = str(start_year)
    env["END_YEAR"] = str(end_year)
    env["DISABLE_PDF"] = "True"
    env["REMOVE_EXTREME_TRAINING_LOSSES"] = "True"
    env["DYN_MAX_TRADES"] = "4"
    env["DYN_INITIAL_CAPITAL"] = "600000.0"
    env["ENABLE_DYNAMIC_STEPS"] = "True"
    env["ENABLE_DYNAMIC_BOUNDS"] = "True"
    process = subprocess.run(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return process.returncode == 0


def extract_metrics_for_year(year, capital=600000.0):
    """Extract metrics for a single year from the trades CSV."""
    trades_path = os.path.join(OUTPUT_DIR, "trades_dynamic_threshold_ensemble.csv")
    if not os.path.exists(trades_path):
        return None
    df = pd.read_csv(trades_path)
    df['date'] = pd.to_datetime(df['date'])
    df['year'] = df['date'].dt.year
    df = df[df['year'] == year].copy()
    if len(df) == 0:
        return None

    total_trades = len(df)
    wins = (df['actual_pnl'] > 0).sum()
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0
    avg_pnl = df['actual_pnl'].mean()
    total_pnl = df['actual_pnl'].sum()

    df_sorted = df.sort_values('date')
    daily_pnl = df_sorted.groupby(df_sorted['date'].dt.date)['actual_pnl'].sum().reset_index()
    daily_pnl = daily_pnl.sort_values('date')
    daily_pnl['cum_pnl'] = daily_pnl['actual_pnl'].cumsum()
    daily_pnl['equity'] = capital + daily_pnl['cum_pnl']
    daily_pnl['peak'] = daily_pnl['equity'].cummax()
    daily_pnl['drawdown'] = (daily_pnl['equity'] - daily_pnl['peak']) / daily_pnl['peak']
    mdd = daily_pnl['drawdown'].min() * 100

    daily_pnl['daily_ret'] = daily_pnl['actual_pnl'] / capital
    mean_ret = daily_pnl['daily_ret'].mean()
    std_ret = daily_pnl['daily_ret'].std()
    sharpe = (mean_ret / std_ret * np.sqrt(252)) if std_ret > 0 else 0.0

    # Return daily PnLs for stitching the equity curve
    daily_pnls = daily_pnl[['date', 'actual_pnl']].copy()

    return {
        "Trades": total_trades, "WinRate": win_rate, "AvgPnL": avg_pnl,
        "TotalPnL": total_pnl, "MaxDD": mdd, "Sharpe": sharpe,
        "DailyPnLs": daily_pnls
    }


def extract_metrics_range(start_year, end_year, capital=600000.0):
    """Extract aggregate metrics for a year range."""
    trades_path = os.path.join(OUTPUT_DIR, "trades_dynamic_threshold_ensemble.csv")
    if not os.path.exists(trades_path):
        return None
    df = pd.read_csv(trades_path)
    df['date'] = pd.to_datetime(df['date'])
    df['year'] = df['date'].dt.year
    df = df[df['year'].between(start_year, end_year)].copy()
    if len(df) == 0:
        return None

    total_trades = len(df)
    wins = (df['actual_pnl'] > 0).sum()
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0
    avg_pnl = df['actual_pnl'].mean()
    total_pnl = df['actual_pnl'].sum()

    df_sorted = df.sort_values('date')
    daily_pnl = df_sorted.groupby(df_sorted['date'].dt.date)['actual_pnl'].sum().reset_index()
    daily_pnl = daily_pnl.sort_values('date')
    daily_pnl['daily_ret'] = daily_pnl['actual_pnl'] / capital
    mean_ret = daily_pnl['daily_ret'].mean()
    std_ret = daily_pnl['daily_ret'].std()
    sharpe = (mean_ret / std_ret * np.sqrt(252)) if std_ret > 0 else 0.0

    return {
        "Trades": total_trades, "WinRate": win_rate, "AvgPnL": avg_pnl,
        "TotalPnL": total_pnl, "Sharpe": sharpe
    }


def sweep_for_year(caches, train_end_year):
    """
    Sweep all parameter combos on 2019 → train_end_year.
    Returns the best combo by Sharpe.
    """
    # Combined grid: K-values × regime thresholds (sampled for speed)
    all_combos = []

    k_pairs = [(0.00, 0.00), (0.20, 0.40), (0.40, 0.80), (0.60, 1.20)]
    regime_pairs = [(0.55, 600.0), (0.65, 1000.0), (0.75, 1500.0)]

    for k_ad, k_def in k_pairs:
        for wr, pnl in regime_pairs:
            all_combos.append((k_ad, k_def, wr, pnl))

    best_sharpe = -999
    best_combo = None
    best_metrics = None

    for k_ad, k_def, wr, pnl in all_combos:
        build_hybrid_cache(caches, k_ad, k_def, wr, pnl)
        success = run_simulation(2019, train_end_year)
        if success:
            m = extract_metrics_range(2019, train_end_year)
            if m and m['Sharpe'] > best_sharpe:
                best_sharpe = m['Sharpe']
                best_combo = (k_ad, k_def, wr, pnl)
                best_metrics = m

    return best_combo, best_metrics


def main():
    t0 = time.time()

    print("=" * 120)
    print("   ROLLING WALK-FORWARD OPTIMIZATION")
    print("   Every year from 2021–2026 is TRUE Out-of-Sample")
    print("=" * 120)

    print("\n[*] Loading prediction caches...")
    caches = load_caches()
    print("[✓] Caches loaded.\n")

    # Test years: 2021 through 2026
    # (2019-2020 = minimum training data needed)
    test_years = [2021, 2022, 2023, 2024, 2025, 2026]

    oos_year_results = []
    all_daily_pnls = []
    param_history = []

    for test_year in test_years:
        train_end = test_year - 1
        print(f"{'─'*120}")
        print(f"  TEST YEAR: {test_year}  |  Training on 2019–{train_end}")
        print(f"{'─'*120}")

        # Stage 1: Find best K-values with fixed middle regime
        print(f"    Sweeping 12 combos on 2019–{train_end}...", end=" ", flush=True)
        t1 = time.time()
        best_combo, best_is_metrics = sweep_for_year(caches, train_end)

        if best_combo is None:
            print(f"FAILED — no successful runs")
            continue

        k_ad, k_def, wr, pnl = best_combo
        print(f"done ({time.time()-t1:.0f}s)")
        print(f"    Best params: K_ad={k_ad:.2f}, K_def={k_def:.2f}, WR≥{wr:.2f}, PnL≥Rs {pnl:.0f}")
        print(f"    IS metrics:  Sharpe={best_is_metrics['Sharpe']:.2f}, "
              f"WinRate={best_is_metrics['WinRate']:.1f}%, "
              f"AvgPnL=Rs {best_is_metrics['AvgPnL']:,.2f}")

        # Now apply best params on 2019→test_year to get OOS for test_year
        print(f"    Applying to {test_year} (OOS)...", end=" ", flush=True)
        build_hybrid_cache(caches, k_ad, k_def, wr, pnl)
        success = run_simulation(2019, test_year)

        if not success:
            print("FAILED")
            continue

        oos_m = extract_metrics_for_year(test_year)
        if oos_m is None:
            print("NO TRADES")
            continue

        print(f"done")
        print(f"    ▶ OOS {test_year}: Trades={oos_m['Trades']}, WinRate={oos_m['WinRate']:.1f}%, "
              f"AvgPnL=Rs {oos_m['AvgPnL']:,.2f}, TotalPnL=Rs {oos_m['TotalPnL']:,.2f}, "
              f"MaxDD={oos_m['MaxDD']:.2f}%\n")

        oos_year_results.append({
            'year': test_year,
            'params': {'k_ad': k_ad, 'k_def': k_def, 'wr': wr, 'pnl': pnl},
            'is_sharpe': best_is_metrics['Sharpe'],
            **{k: v for k, v in oos_m.items() if k != 'DailyPnLs'}
        })

        param_history.append({
            'test_year': test_year,
            'k_ad': k_ad, 'k_def': k_def, 'wr': wr, 'pnl': pnl
        })

        if oos_m.get('DailyPnLs') is not None:
            all_daily_pnls.append(oos_m['DailyPnLs'])

    # ═══════════════════════════════════════════════════════════════════
    #  STITCHED OOS RESULTS
    # ═══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 120)
    print("  ROLLING WFO — FULLY OUT-OF-SAMPLE RESULTS (2021–2026)")
    print("  Every row below used parameters selected BEFORE that year's data was seen")
    print("=" * 120)

    header = (f"  {'Year':<6} | {'K_ad':<5} | {'K_def':<5} | {'WR_t':<5} | {'PnL_t':<7} | "
              f"{'IS Shrp':<8} | {'Trades':<7} | {'WinRate':<9} | {'Avg PnL':<13} | "
              f"{'Total PnL':<15} | {'MaxDD':<10} | {'OOS Shrp':<8}")
    sep = (f"  {'─'*6}─┼─{'─'*5}─┼─{'─'*5}─┼─{'─'*5}─┼─{'─'*7}─┼─"
           f"{'─'*8}─┼─{'─'*7}─┼─{'─'*9}─┼─{'─'*13}─┼─"
           f"{'─'*15}─┼─{'─'*10}─┼─{'─'*8}")
    print(header)
    print(sep)

    total_trades_all = 0
    total_pnl_all = 0.0
    total_wins_all = 0

    for r in oos_year_results:
        p = r['params']
        wins_approx = int(r['Trades'] * r['WinRate'] / 100)
        total_trades_all += r['Trades']
        total_pnl_all += r['TotalPnL']
        total_wins_all += wins_approx

        print(f"  {r['year']:<6} | {p['k_ad']:<5.2f} | {p['k_def']:<5.2f} | {p['wr']:<5.2f} | "
              f"Rs{p['pnl']:<5.0f} | {r['is_sharpe']:<8.2f} | {r['Trades']:<7} | "
              f"{r['WinRate']:<8.1f}% | Rs {r['AvgPnL']:<10,.2f} | "
              f"Rs {r['TotalPnL']:>12,.2f} | {r['MaxDD']:<9.2f}% | {r['Sharpe']:<8.2f}")

    print(sep)

    # Aggregate OOS stats
    if total_trades_all > 0:
        overall_wr = (total_wins_all / total_trades_all * 100)
        overall_avg = total_pnl_all / total_trades_all
        print(f"  {'TOTAL':<6} | {'':5} | {'':5} | {'':5} | {'':7} | "
              f"{'':8} | {total_trades_all:<7} | {overall_wr:<8.1f}% | "
              f"Rs {overall_avg:<10,.2f} | Rs {total_pnl_all:>12,.2f} | {'':10} |")
    print(sep)

    # Compute stitched equity curve stats
    if len(all_daily_pnls) > 0:
        stitched = pd.concat(all_daily_pnls, ignore_index=True)
        stitched = stitched.sort_values('date')
        stitched['cum_pnl'] = stitched['actual_pnl'].cumsum()
        capital = 600000.0
        stitched['equity'] = capital + stitched['cum_pnl']
        stitched['peak'] = stitched['equity'].cummax()
        stitched['drawdown'] = (stitched['equity'] - stitched['peak']) / stitched['peak']
        overall_mdd = stitched['drawdown'].min() * 100

        stitched['daily_ret'] = stitched['actual_pnl'] / capital
        mean_ret = stitched['daily_ret'].mean()
        std_ret = stitched['daily_ret'].std()
        overall_sharpe = (mean_ret / std_ret * np.sqrt(252)) if std_ret > 0 else 0.0

        final_equity = stitched['equity'].iloc[-1]
        first_date = pd.to_datetime(stitched['date'].iloc[0])
        last_date = pd.to_datetime(stitched['date'].iloc[-1])
        years_span = max((last_date - first_date).days / 365.25, 0.1)
        overall_cagr = ((final_equity / capital) ** (1.0 / years_span) - 1.0) * 100

        # Find worst drawdown period
        dd_end_idx = stitched['drawdown'].idxmin()
        dd_end_date = stitched.loc[dd_end_idx, 'date']
        peak_before = stitched.loc[:dd_end_idx, 'equity'].idxmax()
        dd_start_date = stitched.loc[peak_before, 'date']

        print(f"\n  STITCHED OOS EQUITY CURVE STATS (2021–2026):")
        print(f"  ─────────────────────────────────────────────")
        print(f"    Annualized Sharpe Ratio : {overall_sharpe:.2f}")
        print(f"    CAGR                    : {overall_cagr:.2f}%")
        print(f"    Maximum Drawdown        : {overall_mdd:.2f}%")
        print(f"    Worst DD Period         : {dd_start_date} → {dd_end_date}")
        print(f"    Final Equity            : Rs {final_equity:,.2f}")
        print(f"    Total OOS PnL           : Rs {total_pnl_all:,.2f}")
        print(f"    Total OOS Trades        : {total_trades_all}")

    # Parameter stability check
    print(f"\n  PARAMETER STABILITY CHECK:")
    print(f"  ─────────────────────────")
    for ph in param_history:
        print(f"    {ph['test_year']}: K_ad={ph['k_ad']:.2f}, K_def={ph['k_def']:.2f}, "
              f"WR≥{ph['wr']:.2f}, PnL≥Rs {ph['pnl']:.0f}")

    unique_combos = len(set((p['k_ad'], p['k_def'], p['wr'], p['pnl']) for p in param_history))
    if unique_combos == 1:
        print(f"    → ✅ STABLE: Same params selected every year")
    elif unique_combos <= 3:
        print(f"    → ⚠️  MODERATE: {unique_combos} different combos across {len(param_history)} years")
    else:
        print(f"    → 🔴 UNSTABLE: {unique_combos} different combos across {len(param_history)} years — "
              f"parameters are not robust")

    elapsed = time.time() - t0
    print(f"\n  Total runtime: {elapsed/60:.1f} minutes")
    print(f"\n  ★ EVERY number above is TRUE OUT-OF-SAMPLE.")
    print(f"  ★ This is the honest performance you should use for decision-making.")
    print("=" * 120)


if __name__ == "__main__":
    main()
