#!/usr/bin/env python3
"""
run_frozen_reference_backtest.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
LIVE REFERENCE BACKTESTER — SNIPER v3.0 (R1 + R3)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

This script reads from output/trades_dynamic_threshold.csv — the live
growing tracker that started as the Aug-12 frozen baseline and is
auto-extended every evening by predict_today.py (4 baseline rows
appended at actual_pnl=0.0) and healed every morning by
merge_actuals.py (actual_pnl filled from real DB results).

Because ML predictions and thresholds are preserved in the CSV,
this backtester is reproducible and free of re-training drift.
It applies the R1+R3 sniper filter as a post-processing step, exactly
how the Golden Target was originally produced.

Usage:
    python3 run_frozen_reference_backtest.py

Output:
    Full metrics: Sharpe, Sortino, CAGR, Max Drawdown, Win Rate
    Year-by-year breakdown
    Comparison vs Golden Target

"""

import os
import numpy as np
import pandas as pd

# ── Configuration ────────────────────────────────────────────────────
SCRIPT_DIR    = os.path.dirname(os.path.abspath(__file__))
# Live growing tracker — same historical data as CLEAN_REFERENCE but
# auto-extended every day by predict_today.py + merge_actuals.py
REF_CSV       = os.path.join(SCRIPT_DIR, 'output', 'trades_dynamic_threshold.csv')
ASSUMED_CAPITAL = 600_000.0
TRADING_DAYS_PER_YEAR = 252

# ── Golden Target for comparison ─────────────────────────────────────
GOLDEN = {
    2019: {'trades': 103,  'win_pct': 76.7, 'avg_pnl': 1363},
    2020: {'trades': 210,  'win_pct': 67.6, 'avg_pnl': 2514},
    2021: {'trades': 282,  'win_pct': 75.9, 'avg_pnl': 4547},
    2022: {'trades': 286,  'win_pct': 71.0, 'avg_pnl': 1835},
    2023: {'trades': 222,  'win_pct': 77.0, 'avg_pnl': 1375},
    2024: {'trades': 285,  'win_pct': 76.1, 'avg_pnl': 2109},
    2025: {'trades': 172,  'win_pct': 70.9, 'avg_pnl': 1283},
    2026: {'trades': 95,   'win_pct': 64.2, 'avg_pnl': 1552},
}

def compute_metrics(daily_pnl_series, capital=ASSUMED_CAPITAL):
    """Compute Sharpe, Sortino, CAGR, Max Drawdown from a daily PnL series."""
    arr = np.array(daily_pnl_series)
    n_days = len(arr)

    # Returns as fraction of capital
    daily_ret = arr / capital
    mean_ret  = daily_ret.mean()
    std_ret   = daily_ret.std()

    # Sharpe (annualised)
    sharpe = (mean_ret / std_ret * np.sqrt(TRADING_DAYS_PER_YEAR)) if std_ret > 0 else 0.0

    # Sortino (annualised, downside only)
    downside = daily_ret[daily_ret < 0]
    downside_std = downside.std() if len(downside) > 1 else 1e-9
    sortino = (mean_ret / downside_std * np.sqrt(TRADING_DAYS_PER_YEAR)) if downside_std > 0 else 0.0

    # CAGR
    total_return = arr.sum() / capital
    years = n_days / TRADING_DAYS_PER_YEAR
    cagr = ((1 + total_return) ** (1 / years) - 1) * 100 if years > 0 else 0.0

    # Max Drawdown (on cumulative PnL)
    cum = np.cumsum(arr)
    peak = np.maximum.accumulate(cum)
    drawdown = (cum - peak) / (capital + peak)
    max_dd = drawdown.min() * 100  # as percentage

    return sharpe, sortino, cagr, max_dd


def main():
    print("\n" + "="*80)
    print("  LIVE REFERENCE BACKTESTER — SNIPER v3.0 R1+R3")
    print("  Source: output/trades_dynamic_threshold.csv (live growing tracker)")
    print("="*80)

    if not os.path.exists(REF_CSV):
        print(f"\n❌ ERROR: Reference CSV not found at:\n   {REF_CSV}")
        return

    # ── Load & prepare ────────────────────────────────────────────────
    df = pd.read_csv(REF_CSV)
    df['date'] = pd.to_datetime(df['date'])
    df['year'] = df['date'].dt.year

    # Daily trade count and rank within each day
    df['daily_count'] = df.groupby('date')['stock'].transform('count')
    df['rank']        = df.groupby('date').cumcount() + 1

    # ── Apply R1+R3 Sniper Filter ─────────────────────────────────────
    # Normal days (3+ candidates): keep Rank 1 and Rank 3
    # Scarce days (1-2 candidates): keep Rank 1 only
    mask_r1r3   = (df['daily_count'] >= 3) & (df['rank'].isin([1, 3]))
    mask_r1only = (df['daily_count'] <  3) & (df['rank'] == 1)
    trades      = df[mask_r1r3 | mask_r1only].copy()

    # ── Build daily PnL series (sum of actual_pnl per trading day) ────
    # Include ALL days that had baseline candidates (even if 0 sniper picks)
    all_dates     = df['date'].unique()
    daily_pnl_map = trades.groupby('date')['actual_pnl'].sum()

    daily_series = pd.Series(0.0, index=sorted(all_dates))
    daily_series.update(daily_pnl_map)
    daily_pnl_list = daily_series.values

    # ── Overall metrics ───────────────────────────────────────────────
    sharpe, sortino, cagr, max_dd = compute_metrics(daily_pnl_list)

    total_trades = len(trades)
    wins         = (trades['actual_pnl'] > 0).sum()
    win_rate     = wins / total_trades * 100 if total_trades > 0 else 0
    avg_pnl      = trades['actual_pnl'].mean() if total_trades > 0 else 0
    total_pnl    = trades['actual_pnl'].sum()

    print(f"\n{'='*80}")
    print(f"  OVERALL RESULTS (2019 – {trades['date'].dt.year.max()})")
    print(f"{'='*80}")
    print(f"  Total Trades       : {total_trades:,}")
    print(f"  Overall Win Rate   : {win_rate:.1f}%")
    print(f"  Average PnL/Trade  : Rs {avg_pnl:,.2f}")
    print(f"  Total Realized PnL : Rs {total_pnl:,.2f}")
    print(f"  Assumed Capital    : Rs {ASSUMED_CAPITAL:,.0f}")
    print(f"  Overall CAGR       : {cagr:.2f}%")
    print(f"  Max Drawdown       : {max_dd:.2f}%")
    print(f"  Sharpe Ratio (Ann) : {sharpe:.2f}")
    print(f"  Sortino Ratio (Ann): {sortino:.2f}")
    print(f"{'='*80}")

    # ── Year-by-year breakdown ────────────────────────────────────────
    print(f"\n{'YEAR-BY-YEAR BREAKDOWN vs GOLDEN TARGET':^80}")
    print("-"*80)
    print(f"{'Year':<6} | {'Trades':>7} | {'G.Trades':>8} | {'Win%':>6} | {'G.Win%':>7} | {'AvgPnL':>10} | {'G.AvgPnL':>10} | {'TotalPnL':>12}")
    print("-"*80)

    for year, grp in trades.groupby('year'):
        t   = len(grp)
        wr  = (grp['actual_pnl'] > 0).sum() / t * 100 if t > 0 else 0
        ap  = grp['actual_pnl'].mean() if t > 0 else 0
        tp  = grp['actual_pnl'].sum()
        g   = GOLDEN.get(year, {})
        gt  = g.get('trades', '-')
        gw  = f"{g.get('win_pct', '-')}%" if g else '-'
        gap = f"Rs {g.get('avg_pnl', 0):,}" if g else '-'
        match = "✅" if g and abs(t - g.get('trades', 0)) <= 5 else "⚠️"
        print(f"{year:<6} | {t:>7} | {str(gt):>8} | {wr:>5.1f}% | {gw:>7} | Rs {ap:>8,.0f} | {gap:>10} | Rs {tp:>10,.0f} {match}")

    print("-"*80)
    print(f"\n✅ = Within 5 trades of Golden Target  |  ⚠️ = Divergence detected\n")


if __name__ == '__main__':
    main()
