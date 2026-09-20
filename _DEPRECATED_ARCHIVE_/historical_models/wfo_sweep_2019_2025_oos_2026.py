#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════╗
║  WALK-FORWARD PARAMETER OPTIMIZER (Audit-Clean Version)            ║
║                                                                    ║
║  • In-Sample Sweep:   2019 – 2025                                  ║
║  • Out-of-Sample Test: 2026                                        ║
║                                                                    ║
║  2-Stage Grid Search:                                              ║
║    Stage 1: Sweep K_adaptive × K_defensive  (6 combos)             ║
║    Stage 2: Sweep WR_thresh × PnL_thresh    (6 combos)             ║
║                                                                    ║
║  Selection criterion: Sharpe Ratio (risk-adjusted)                 ║
║                                                                    ║
║  Audit fixes applied:                                              ║
║    ✓ No parameters from full-period optimization                   ║
║    ✓ Conservative warm-up defaults (WR=0.50, PnL=0.0)             ║
║    ✓ No negative K_base (no rewarding disagreement)                ║
║    ✓ K_dyn clamped [0.0, 1.5] (bounded both sides)                ║
║    ✓ 3-state regime (removed hand-tuned super-trimmed)             ║
╚══════════════════════════════════════════════════════════════════════╝
"""
import os
import sys
import time
import pickle
import subprocess
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

# ─── Conservative warm-up defaults (audit fix #4) ──────────────────────
DEFAULT_WR  = 0.50   # Neutral: no assumption about win rate
DEFAULT_PNL = 0.0    # Neutral: no assumption about profitability


def load_caches():
    caches = {}
    for name, filename in FILES.items():
        path = os.path.join(OUTPUT_DIR, filename)
        if not os.path.exists(path):
            print(f"[!] Missing cache: {path}")
            sys.exit(1)
        with open(path, 'rb') as f:
            caches[name] = pickle.load(f)
    return caches


def build_hybrid_cache(caches, k_adaptive, k_defensive, wr_thresh, pnl_thresh,
                       rolling_window=30):
    """
    Build ensemble prediction cache with a clean 3-state regime switcher.
    
    States:
        Trimmed   (k=0.00): trailing WR ≥ wr_thresh OR trailing AvgPnL ≥ pnl_thresh
        Defensive (k=k_def): trailing WR < 0.60 AND trailing AvgPnL < 500
        Adaptive  (k=k_ad):  everything else
    """
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

        # ── 3-State Regime Gate ──────────────────────────────────────
        if len(historical_trades) >= 10:
            recent_trades = historical_trades[-10:]
            wins = sum(1 for p in recent_trades if p > 0)
            trailing_wr = wins / 10.0
            trailing_avg_pnl = sum(recent_trades) / 10.0
        else:
            trailing_wr = DEFAULT_WR
            trailing_avg_pnl = DEFAULT_PNL

        if trailing_wr >= wr_thresh or trailing_avg_pnl >= pnl_thresh:
            k_base = 0.00               # Trimmed: no penalty
        elif trailing_wr < 0.60 and trailing_avg_pnl < 500.0:
            k_base = k_defensive         # Defensive
        else:
            k_base = k_adaptive          # Adaptive

        # ── Baseline std from prediction disagreement ────────────────
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

        # ── Combine predictions with noise penalty ───────────────────
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
            K_dyn = max(0.0, min(1.5, K_dyn))  # Audit fix: clamp both sides

            combined = trimmed_mean_val - K_dyn * std_dev
            combined_preds.append(combined)

        base_df["pred_pnl"] = combined_preds
        ensemble_cache[dt] = base_df

        # Track top-4 actual trades for state gate
        base_df_sorted = base_df.sort_values(by="pred_pnl", ascending=False)
        top_4_actuals = base_df_sorted.head(4)["pnl"].dropna().values
        for p in top_4_actuals:
            historical_trades.append(p)

    # Save ensemble cache
    cache_path = os.path.join(OUTPUT_DIR,
                              "wf_predictions_cache_ensemble_da_standard_dl_3.0_nf.pkl")
    with open(cache_path, 'wb') as f:
        pickle.dump(ensemble_cache, f, protocol=pickle.HIGHEST_PROTOCOL)


def run_simulation(start_year, end_year, max_trades=4, capital=600000.0):
    cmd = [sys.executable, "dynamic_threshold.py", "ensemble"]
    env = os.environ.copy()
    env["START_YEAR"]    = str(start_year)
    env["END_YEAR"]      = str(end_year)
    env["DISABLE_PDF"]   = "True"
    env["REMOVE_EXTREME_TRAINING_LOSSES"] = "True"
    env["DYN_MAX_TRADES"]       = str(max_trades)
    env["DYN_INITIAL_CAPITAL"]  = str(capital)
    env["ENABLE_DYNAMIC_STEPS"] = "True"
    env["ENABLE_DYNAMIC_BOUNDS"] = "True"
    process = subprocess.run(cmd, env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
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
    daily_pnl['equity']  = capital + daily_pnl['cum_pnl']
    daily_pnl['peak']    = daily_pnl['equity'].cummax()
    daily_pnl['drawdown'] = (daily_pnl['equity'] - daily_pnl['peak']) / daily_pnl['peak']
    mdd = daily_pnl['drawdown'].min() * 100

    start_date = df['date'].min()
    end_date   = df['date'].max()
    years_span = max((end_date - start_date).days / 365.25, 0.1)
    final_equity = capital + df['actual_pnl'].sum()
    cagr = ((final_equity / capital) ** (1.0 / years_span) - 1.0) * 100

    daily_pnl['daily_ret'] = daily_pnl['actual_pnl'] / capital
    mean_ret = daily_pnl['daily_ret'].mean()
    std_ret  = daily_pnl['daily_ret'].std()
    sharpe = (mean_ret / std_ret * np.sqrt(252)) if std_ret > 0 else 0.0

    total_trades = len(df)
    wins = (df['actual_pnl'] > 0).sum()
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0
    avg_pnl  = df['actual_pnl'].mean()
    total_pnl = df['actual_pnl'].sum()

    # Year-over-year breakdown
    yoy = {}
    for yr in sorted(df['year'].unique()):
        yr_df = df[df['year'] == yr]
        t = len(yr_df)
        w = (yr_df['actual_pnl'] > 0).sum()
        yoy[yr] = {
            "Trades": t,
            "WinRate": (w / t * 100) if t > 0 else 0.0,
            "AvgPnL": yr_df['actual_pnl'].mean() if t > 0 else 0.0,
            "TotalPnL": yr_df['actual_pnl'].sum()
        }

    return {
        "CAGR": cagr, "MaxDD": mdd, "Sharpe": sharpe,
        "WinRate": win_rate, "AvgPnL": avg_pnl,
        "TotalPnL": total_pnl, "Trades": total_trades,
        "YoY": yoy
    }


def print_row(label_vals, metrics):
    """Helper to print a results table row."""
    parts = " | ".join(f"{v}" for v in label_vals)
    print(f"  {parts} | {metrics['CAGR']:<9.2f}% | {metrics['MaxDD']:<9.2f}% | "
          f"{metrics['Sharpe']:<8.2f} | {metrics['WinRate']:<8.1f}% | "
          f"{metrics['Trades']:<8} | Rs {metrics['TotalPnL']:>12,.2f}")


def main():
    t0 = time.time()

    print("=" * 110)
    print("   WALK-FORWARD PARAMETER OPTIMIZER — AUDIT-CLEAN VERSION")
    print("   In-Sample: 2019–2025  |  Out-of-Sample: 2026")
    print("   Selection Criterion: Sharpe Ratio")
    print("=" * 110)

    print("\n[*] Loading prediction caches...")
    caches = load_caches()
    print("[✓] Caches loaded.\n")

    # ═══════════════════════════════════════════════════════════════════
    #  STAGE 1: Sweep K_adaptive × K_defensive
    #  (regime thresholds fixed at middle-of-range: WR≥0.70, PnL≥1000)
    # ═══════════════════════════════════════════════════════════════════
    print("─" * 110)
    print("  STAGE 1: K-Value Sweep   (regime fixed: WR≥0.70, AvgPnL≥Rs 1000)")
    print("─" * 110)

    k_candidates = [
        (0.00, 0.00),   # No penalty at all
        (0.10, 0.20),
        (0.20, 0.40),
        (0.30, 0.60),
        (0.40, 0.80),
        (0.60, 1.20),   # Heavy penalty
    ]

    fixed_wr  = 0.70
    fixed_pnl = 1000.0

    header = (f"  {'K_ad':<6} | {'K_def':<6} | {'CAGR':<10} | {'MaxDD':<10} | "
              f"{'Sharpe':<8} | {'WinRate':<9} | {'Trades':<8} | {'TotalPnL':<14}")
    sep    = (f"  {'─'*6}─┼─{'─'*6}─┼─{'─'*10}─┼─{'─'*10}─┼─"
              f"{'─'*8}─┼─{'─'*9}─┼─{'─'*8}─┼─{'─'*14}")
    print(header)
    print(sep)

    stage1_results = []

    for k_ad, k_def in k_candidates:
        build_hybrid_cache(caches, k_ad, k_def, fixed_wr, fixed_pnl)
        success = run_simulation(2019, 2025)
        if success:
            m = extract_metrics(year_filter=(2019, 2025))
            if m:
                print_row([f"{k_ad:<6.2f}", f"{k_def:<6.2f}"], m)
                stage1_results.append({'k_ad': k_ad, 'k_def': k_def, **m})
            else:
                print(f"  {k_ad:<6.2f} | {k_def:<6.2f} | [no trades]")
        else:
            print(f"  {k_ad:<6.2f} | {k_def:<6.2f} | [FAILED]")

    if not stage1_results:
        print("\n[!] All Stage 1 runs failed. Aborting.")
        return

    best_s1 = max(stage1_results, key=lambda x: x['Sharpe'])
    best_k_ad  = best_s1['k_ad']
    best_k_def = best_s1['k_def']
    print(sep)
    print(f"  ► STAGE 1 WINNER: K_ad={best_k_ad:.2f}, K_def={best_k_def:.2f}  "
          f"(Sharpe={best_s1['Sharpe']:.2f}, CAGR={best_s1['CAGR']:.2f}%)\n")

    # ═══════════════════════════════════════════════════════════════════
    #  STAGE 2: Sweep Regime Boundaries
    #  (K values fixed to Stage 1 winner)
    # ═══════════════════════════════════════════════════════════════════
    print("─" * 110)
    print(f"  STAGE 2: Regime Boundary Sweep   (K_ad={best_k_ad:.2f}, K_def={best_k_def:.2f} fixed)")
    print("─" * 110)

    regime_candidates = [
        (0.50, 400.0),   # Very relaxed → more time in trimmed state
        (0.55, 600.0),
        (0.60, 800.0),
        (0.65, 1000.0),
        (0.70, 1200.0),
        (0.75, 1500.0),  # Strict → less time in trimmed state
    ]

    header2 = (f"  {'WR_thr':<6} | {'PnL_thr':<9} | {'CAGR':<10} | {'MaxDD':<10} | "
               f"{'Sharpe':<8} | {'WinRate':<9} | {'Trades':<8} | {'TotalPnL':<14}")
    sep2    = (f"  {'─'*6}─┼─{'─'*9}─┼─{'─'*10}─┼─{'─'*10}─┼─"
               f"{'─'*8}─┼─{'─'*9}─┼─{'─'*8}─┼─{'─'*14}")
    print(header2)
    print(sep2)

    stage2_results = []

    for wr, pnl in regime_candidates:
        build_hybrid_cache(caches, best_k_ad, best_k_def, wr, pnl)
        success = run_simulation(2019, 2025)
        if success:
            m = extract_metrics(year_filter=(2019, 2025))
            if m:
                print_row([f"{wr:<6.2f}", f"Rs {pnl:<6.0f}"], m)
                stage2_results.append({'wr_thresh': wr, 'pnl_thresh': pnl, **m})
            else:
                print(f"  {wr:<6.2f} | Rs {pnl:<6.0f} | [no trades]")
        else:
            print(f"  {wr:<6.2f} | Rs {pnl:<6.0f} | [FAILED]")

    if not stage2_results:
        print("\n[!] All Stage 2 runs failed. Aborting.")
        return

    best_s2    = max(stage2_results, key=lambda x: x['Sharpe'])
    best_wr    = best_s2['wr_thresh']
    best_pnl_t = best_s2['pnl_thresh']
    print(sep2)
    print(f"  ► STAGE 2 WINNER: WR≥{best_wr:.2f}, AvgPnL≥Rs {best_pnl_t:.0f}  "
          f"(Sharpe={best_s2['Sharpe']:.2f}, CAGR={best_s2['CAGR']:.2f}%)\n")

    # ═══════════════════════════════════════════════════════════════════
    #  FINAL: Apply Best Parameters — Full 2019–2026 Run
    #  2026 = TRUE Out-of-Sample
    # ═══════════════════════════════════════════════════════════════════
    print("=" * 110)
    print("  FINAL: APPLYING BEST PARAMETERS TO 2026 (TRUE OUT-OF-SAMPLE)")
    print(f"  Parameters found on 2019–2025:")
    print(f"    K_adaptive  = {best_k_ad:.2f}")
    print(f"    K_defensive = {best_k_def:.2f}")
    print(f"    WR_thresh   = {best_wr:.2f}")
    print(f"    PnL_thresh  = Rs {best_pnl_t:.0f}")
    print("=" * 110)

    build_hybrid_cache(caches, best_k_ad, best_k_def, best_wr, best_pnl_t)
    success = run_simulation(2019, 2026)
    if not success:
        print("[!] Final simulation failed.")
        return

    m_is   = extract_metrics(year_filter=(2019, 2025))
    m_oos  = extract_metrics(year_filter=(2026, 2026))
    m_full = extract_metrics(year_filter=(2019, 2026))

    # ── Summary table ────────────────────────────────────────────────
    print(f"\n  {'Period':<20} | {'CAGR':<10} | {'MaxDD':<10} | {'Sharpe':<8} | "
          f"{'WinRate':<9} | {'Trades':<8} | {'AvgPnL':<14} | {'TotalPnL':<14}")
    sum_sep = (f"  {'─'*20}─┼─{'─'*10}─┼─{'─'*10}─┼─{'─'*8}─┼─"
               f"{'─'*9}─┼─{'─'*8}─┼─{'─'*14}─┼─{'─'*14}")
    print(sum_sep)

    for label, m in [("IN-SAMPLE 2019-25", m_is),
                     ("▶ OOS 2026 ◀", m_oos),
                     ("FULL 2019-26", m_full)]:
        if m:
            print(f"  {label:<20} | {m['CAGR']:<9.2f}% | {m['MaxDD']:<9.2f}% | "
                  f"{m['Sharpe']:<8.2f} | {m['WinRate']:<8.1f}% | "
                  f"{m['Trades']:<8} | Rs {m['AvgPnL']:<11,.2f} | Rs {m['TotalPnL']:>12,.2f}")
    print(sum_sep)

    # ── Year-over-year breakdown ─────────────────────────────────────
    if m_full and 'YoY' in m_full:
        print(f"\n  YEAR-OVER-YEAR BREAKDOWN:")
        print(f"  {'Year':<6} | {'Trades':<8} | {'WinRate':<9} | {'AvgPnL':<14} | {'TotalPnL':<14} | {'Label'}")
        yoy_sep = f"  {'─'*6}─┼─{'─'*8}─┼─{'─'*9}─┼─{'─'*14}─┼─{'─'*14}─┼─{'─'*14}"
        print(yoy_sep)
        for yr in sorted(m_full['YoY'].keys()):
            r = m_full['YoY'][yr]
            tag = "  ◀ OOS" if yr == 2026 else ""
            print(f"  {yr:<6} | {r['Trades']:<8} | {r['WinRate']:<8.1f}% | "
                  f"Rs {r['AvgPnL']:<11,.2f} | Rs {r['TotalPnL']:>12,.2f} | {tag}")
        print(yoy_sep)

    elapsed = time.time() - t0
    print(f"\n  Total runtime: {elapsed/60:.1f} minutes")
    print(f"\n  ★ The 2026 row above is TRUE OUT-OF-SAMPLE.")
    print(f"  ★ Parameters were selected BEFORE seeing any 2026 data.")
    print(f"  ★ Compare 2026 metrics against in-sample to check for overfitting.")
    print("=" * 110)


if __name__ == "__main__":
    main()
