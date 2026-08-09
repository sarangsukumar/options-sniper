#!/usr/bin/env python3
"""
Compare ALL parameter combos from both sweep stages on 2026 OOS.
Runs each combo on 2019-2026 and extracts 2026-only metrics.
"""
import os, sys, time, pickle, subprocess
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

    cache_path = os.path.join(OUTPUT_DIR, "wf_predictions_cache_ensemble_da_standard_dl_3.0_nf.pkl")
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

def extract_metrics(capital=600000.0, year_filter=None):
    trades_path = os.path.join(OUTPUT_DIR, "trades_dynamic_threshold_ensemble.csv")
    if not os.path.exists(trades_path):
        return None
    df = pd.read_csv(trades_path)
    df['date'] = pd.to_datetime(df['date'])
    df['year'] = df['date'].dt.year
    if year_filter:
        df = df[df['year'].between(year_filter[0], year_filter[1])].copy()
    if len(df) == 0:
        return None

    df_sorted = df.sort_values('date')
    daily_pnl = df_sorted.groupby(df_sorted['date'].dt.date)['actual_pnl'].sum().reset_index()
    daily_pnl = daily_pnl.sort_values('date')
    daily_pnl['cum_pnl'] = daily_pnl['actual_pnl'].cumsum()
    daily_pnl['equity'] = capital + daily_pnl['cum_pnl']
    daily_pnl['peak'] = daily_pnl['equity'].cummax()
    daily_pnl['drawdown'] = (daily_pnl['equity'] - daily_pnl['peak']) / daily_pnl['peak']
    mdd = daily_pnl['drawdown'].min() * 100

    total_trades = len(df)
    wins = (df['actual_pnl'] > 0).sum()
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0
    avg_pnl = df['actual_pnl'].mean()
    total_pnl = df['actual_pnl'].sum()

    daily_pnl['daily_ret'] = daily_pnl['actual_pnl'] / capital
    mean_ret = daily_pnl['daily_ret'].mean()
    std_ret = daily_pnl['daily_ret'].std()
    sharpe = (mean_ret / std_ret * np.sqrt(252)) if std_ret > 0 else 0.0

    return {
        "Trades": total_trades, "WinRate": win_rate, "AvgPnL": avg_pnl,
        "TotalPnL": total_pnl, "MaxDD": mdd, "Sharpe": sharpe
    }

def main():
    t0 = time.time()
    print("=" * 140)
    print("   ALL PARAMETER COMBOS — IN-SAMPLE (2019-2025) vs OOS (2026) COMPARISON")
    print("=" * 140)

    caches = load_caches()

    # All combos to test:
    # Stage 1: K-value pairs with fixed regime (WR=0.70, PnL=1000)
    # Stage 2: Regime boundary pairs with fixed K (K_ad=0.60, K_def=1.20)
    combos = []

    # Stage 1 combos
    for k_ad, k_def in [(0.00, 0.00), (0.10, 0.20), (0.20, 0.40),
                         (0.30, 0.60), (0.40, 0.80), (0.60, 1.20)]:
        combos.append({
            'label': f"K({k_ad:.2f},{k_def:.2f}) R(0.70,1000)",
            'k_ad': k_ad, 'k_def': k_def, 'wr': 0.70, 'pnl': 1000.0,
            'stage': 'S1-Kval'
        })

    # Stage 2 combos
    for wr, pnl in [(0.50, 400.0), (0.55, 600.0), (0.60, 800.0),
                     (0.65, 1000.0), (0.70, 1200.0), (0.75, 1500.0)]:
        combos.append({
            'label': f"K(0.60,1.20) R({wr:.2f},{pnl:.0f})",
            'k_ad': 0.60, 'k_def': 1.20, 'wr': wr, 'pnl': pnl,
            'stage': 'S2-Regime'
        })

    results = []

    print(f"\n  Running {len(combos)} combos on full 2019-2026...\n")

    for i, c in enumerate(combos, 1):
        print(f"  [{i:2d}/{len(combos)}] {c['label']} ...", end=" ", flush=True)
        build_hybrid_cache(caches, c['k_ad'], c['k_def'], c['wr'], c['pnl'])
        success = run_simulation(2019, 2026)
        if success:
            m_is  = extract_metrics(year_filter=(2019, 2025))
            m_oos = extract_metrics(year_filter=(2026, 2026))
            if m_is and m_oos:
                results.append({**c, 'is': m_is, 'oos': m_oos})
                print(f"OK  (IS Sharpe={m_is['Sharpe']:.2f}, OOS Sharpe={m_oos['Sharpe']:.2f})")
            else:
                print("NO DATA")
        else:
            print("FAILED")

    if not results:
        print("[!] No results. Aborting.")
        return

    # ═══════════════════════════════════════════════════════════════════
    #  IN-SAMPLE TABLE (2019-2025)
    # ═══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 140)
    print("  IN-SAMPLE PERFORMANCE (2019-2025) — All Combos")
    print("=" * 140)
    print(f"  {'#':<3} | {'Stage':<10} | {'K_ad':<5} | {'K_def':<5} | {'WR_t':<5} | {'PnL_t':<7} | "
          f"{'Trades':<7} | {'WinRate':<9} | {'Avg PnL':<13} | {'Total PnL':<15} | {'MaxDD':<10} | {'Sharpe':<7}")
    sep = f"  {'─'*3}─┼─{'─'*10}─┼─{'─'*5}─┼─{'─'*5}─┼─{'─'*5}─┼─{'─'*7}─┼─{'─'*7}─┼─{'─'*9}─┼─{'─'*13}─┼─{'─'*15}─┼─{'─'*10}─┼─{'─'*7}"
    print(sep)
    for i, r in enumerate(results, 1):
        m = r['is']
        print(f"  {i:<3} | {r['stage']:<10} | {r['k_ad']:<5.2f} | {r['k_def']:<5.2f} | {r['wr']:<5.2f} | "
              f"Rs{r['pnl']:<5.0f} | {m['Trades']:<7} | {m['WinRate']:<8.1f}% | "
              f"Rs {m['AvgPnL']:<10,.2f} | Rs {m['TotalPnL']:>12,.2f} | {m['MaxDD']:<9.2f}% | {m['Sharpe']:<7.2f}")
    print(sep)

    # ═══════════════════════════════════════════════════════════════════
    #  OOS TABLE (2026 ONLY)
    # ═══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 140)
    print("  ▶▶▶ OUT-OF-SAMPLE 2026 PERFORMANCE — All Combos ◀◀◀")
    print("=" * 140)
    print(f"  {'#':<3} | {'Stage':<10} | {'K_ad':<5} | {'K_def':<5} | {'WR_t':<5} | {'PnL_t':<7} | "
          f"{'Trades':<7} | {'WinRate':<9} | {'Avg PnL':<13} | {'Total PnL':<15} | {'MaxDD':<10} | {'Sharpe':<7}")
    print(sep)
    for i, r in enumerate(results, 1):
        m = r['oos']
        print(f"  {i:<3} | {r['stage']:<10} | {r['k_ad']:<5.2f} | {r['k_def']:<5.2f} | {r['wr']:<5.2f} | "
              f"Rs{r['pnl']:<5.0f} | {m['Trades']:<7} | {m['WinRate']:<8.1f}% | "
              f"Rs {m['AvgPnL']:<10,.2f} | Rs {m['TotalPnL']:>12,.2f} | {m['MaxDD']:<9.2f}% | {m['Sharpe']:<7.2f}")
    print(sep)

    # ═══════════════════════════════════════════════════════════════════
    #  SIDE-BY-SIDE COMPARISON — Sorted by OOS Sharpe
    # ═══════════════════════════════════════════════════════════════════
    results_sorted = sorted(results, key=lambda x: x['oos']['Sharpe'], reverse=True)

    print("\n" + "=" * 140)
    print("  RANKED BY OOS 2026 SHARPE (Best → Worst)")
    print("=" * 140)
    print(f"  {'Rank':<5} | {'Parameters':<32} | {'IS Sharpe':<10} | {'OOS Sharpe':<11} | "
          f"{'OOS Trades':<11} | {'OOS WinRate':<12} | {'OOS AvgPnL':<13} | {'OOS TotPnL':<15} | {'OOS MaxDD':<10}")
    sep2 = f"  {'─'*5}─┼─{'─'*32}─┼─{'─'*10}─┼─{'─'*11}─┼─{'─'*11}─┼─{'─'*12}─┼─{'─'*13}─┼─{'─'*15}─┼─{'─'*10}"
    print(sep2)
    for rank, r in enumerate(results_sorted, 1):
        marker = " ◀ BEST" if rank == 1 else ""
        print(f"  {rank:<5} | {r['label']:<32} | {r['is']['Sharpe']:<10.2f} | {r['oos']['Sharpe']:<11.2f} | "
              f"{r['oos']['Trades']:<11} | {r['oos']['WinRate']:<11.1f}% | "
              f"Rs {r['oos']['AvgPnL']:<10,.2f} | Rs {r['oos']['TotalPnL']:>12,.2f} | "
              f"{r['oos']['MaxDD']:<9.2f}%{marker}")
    print(sep2)

    # Best OOS
    best = results_sorted[0]
    print(f"\n  ★ BEST OOS 2026 COMBO: {best['label']}")
    print(f"    OOS Sharpe: {best['oos']['Sharpe']:.2f}  |  OOS WinRate: {best['oos']['WinRate']:.1f}%  |  "
          f"OOS Total PnL: Rs {best['oos']['TotalPnL']:,.2f}  |  OOS MaxDD: {best['oos']['MaxDD']:.2f}%")
    print(f"    IS  Sharpe: {best['is']['Sharpe']:.2f}  |  IS  WinRate: {best['is']['WinRate']:.1f}%  |  "
          f"IS  Total PnL: Rs {best['is']['TotalPnL']:,.2f}  |  IS  MaxDD: {best['is']['MaxDD']:.2f}%")

    # Worst OOS
    worst = results_sorted[-1]
    print(f"\n  ✗ WORST OOS 2026 COMBO: {worst['label']}")
    print(f"    OOS Sharpe: {worst['oos']['Sharpe']:.2f}  |  OOS WinRate: {worst['oos']['WinRate']:.1f}%  |  "
          f"OOS Total PnL: Rs {worst['oos']['TotalPnL']:,.2f}  |  OOS MaxDD: {worst['oos']['MaxDD']:.2f}%")

    # Check if IS best = OOS best
    is_best = max(results, key=lambda x: x['is']['Sharpe'])
    oos_best = results_sorted[0]
    if is_best['label'] == oos_best['label']:
        print(f"\n  ✓ IN-SAMPLE BEST = OOS BEST — good parameter stability")
    else:
        print(f"\n  ⚠ IN-SAMPLE BEST ≠ OOS BEST:")
        print(f"    IS  best: {is_best['label']} (IS Sharpe={is_best['is']['Sharpe']:.2f}, OOS Sharpe={is_best['oos']['Sharpe']:.2f})")
        print(f"    OOS best: {oos_best['label']} (IS Sharpe={oos_best['is']['Sharpe']:.2f}, OOS Sharpe={oos_best['oos']['Sharpe']:.2f})")

    elapsed = time.time() - t0
    print(f"\n  Total runtime: {elapsed/60:.1f} minutes")
    print("=" * 140)

if __name__ == "__main__":
    main()
