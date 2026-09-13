#!/usr/bin/env python3
"""
🏆 SARANG 2026 SHORT-SELL ALGORITHMS - MASTER SUITE BENCHMARK
===================================================================================
100% PURE MYSQL DATABASE | ZERO YAHOO FINANCE | VERIFIED CONTRACT LOT SIZES
===================================================================================
Master Benchmark Suite comparing:
1. Best Shorter Window (09:20 -> 09:40 AM) - Evaluated on Equity & Futures
2. Best Longer Window (09:42 -> 14:45 PM, 3% SL) - Evaluated on Futures & Equity
3. Sequential Zero-Overlap Master Portfolio (Shorter on EQ -> Longer on Futures)
===================================================================================
"""

import os
import pandas as pd
import numpy as np

BASE_DIR = '/home/ubuntu/sarang_2026_shortsell_algos'

MODELS_CONFIG = [
    {
        'id': 'best_shorter_eq',
        'name': 'Model 1 (Shorter Window): Equity (09:20 -> 09:40)',
        'file': os.path.join(BASE_DIR, '01_Best_Shorter_Window_0920_0940', 'shorter_window_trades_eq_and_futures.csv'),
        'date_col': 'date_str',
        'pnl_col': 'eq_net_pnl'
    },
    {
        'id': 'best_shorter_f1',
        'name': 'Model 1 (Shorter Window): Futures (09:20 -> 09:40)',
        'file': os.path.join(BASE_DIR, '01_Best_Shorter_Window_0920_0940', 'shorter_window_trades_eq_and_futures.csv'),
        'date_col': 'date_str',
        'pnl_col': 'f1_net_pnl'
    },
    {
        'id': 'best_longer_f1',
        'name': 'Model 2 (Longer Window): Futures (09:42 -> 14:45, 3% SL)',
        'file': os.path.join(BASE_DIR, '02_Best_Longer_Window_0942_1445', 'longer_window_trades_futures_and_eq.csv'),
        'date_col': 'date_str',
        'pnl_col': 'f1_net_pnl'
    },
    {
        'id': 'best_longer_eq',
        'name': 'Model 2 (Longer Window): Equity (09:42 -> 14:45, 3% SL)',
        'file': os.path.join(BASE_DIR, '02_Best_Longer_Window_0942_1445', 'longer_window_trades_futures_and_eq.csv'),
        'date_col': 'date_str',
        'pnl_col': 'eq_net_pnl'
    }
]

def main():
    print("=" * 105)
    print("🏆 SARANG 2026 DEFINITIVE TWO SHORT-SELL MODELS: DUAL-TABLE BENCHMARK REPORT")
    print("=" * 105)

    loaded = []
    daily_pnls = {}

    for cfg in MODELS_CONFIG:
        if not os.path.exists(cfg['file']):
            print(f"⚠️ Warning: File not found: {cfg['file']}")
            continue

        df = pd.read_csv(cfg['file'])
        df['trade_date'] = pd.to_datetime(df[cfg['date_col']])
        df['year'] = df['trade_date'].dt.year

        total_trades = len(df)
        net_pnl_tot = df[cfg['pnl_col']].sum()
        win_rate = (df[cfg['pnl_col']] > 0).mean() * 100
        avg_trade = df[cfg['pnl_col']].mean()
        wins = df[df[cfg['pnl_col']] > 0][cfg['pnl_col']].sum()
        losses = abs(df[df[cfg['pnl_col']] < 0][cfg['pnl_col']].sum())
        profit_factor = (wins / losses) if losses > 0 else np.nan

        daily = df.groupby('trade_date')[cfg['pnl_col']].sum()
        daily_pnls[cfg['id']] = daily
        sharpe = (daily.mean() / daily.std()) * np.sqrt(252) if daily.std() > 0 else np.nan

        loaded.append({
            'Model': cfg['name'],
            'Trades': total_trades,
            'Net PnL (₹ L)': net_pnl_tot / 1e5,
            'Win Rate (%)': win_rate,
            'Avg/Trade (₹)': avg_trade,
            'Profit Factor': profit_factor,
            'Daily Sharpe': sharpe
        })

    summary_df = pd.DataFrame(loaded).round(2)
    print("\n📈 OVERALL PERFORMANCE SUMMARY:")
    print(summary_df.to_string(index=False))

    # Year-by-Year breakdown
    print("\n" + "=" * 105)
    print("📅 YEAR-BY-YEAR NET PNL BREAKDOWN (₹ IN LAKHS):")
    print("=" * 105)

    year_dfs = []
    for cfg in MODELS_CONFIG:
        if not os.path.exists(cfg['file']):
            continue
        df = pd.read_csv(cfg['file'])
        df['year'] = pd.to_datetime(df[cfg['date_col']]).dt.year
        y_pnl = df.groupby('year')[cfg['pnl_col']].sum() / 1e5
        y_pnl.name = cfg['name']
        year_dfs.append(y_pnl)

    master_year_df = pd.concat(year_dfs, axis=1).fillna(0.0).round(2)
    print(master_year_df.to_string())

    # Combined Sequential Portfolio: Shorter Window (EQ) -> Longer Window (Futures)
    if 'best_shorter_eq' in daily_pnls and 'best_longer_f1' in daily_pnls:
        print("\n" + "=" * 105)
        print("💎 MASTER SEQUENTIAL PORTFOLIO (ZERO MARGIN OVERLAP):")
        print("   09:20 -> 09:40 AM: Best Shorter Window on Equity Cash")
        print("   09:42 -> 14:45 PM: Best Longer Window on Near-Month Futures (3% SL)")
        print("   -> 100% Margin Recycled (09:40 exit precedes 09:42 entry)")
        print("=" * 105)

        s_pnl = daily_pnls['best_shorter_eq']
        l_pnl = daily_pnls['best_longer_f1']
        all_dates = sorted(list(set(s_pnl.index).union(set(l_pnl.index))))

        comb_daily = pd.DataFrame(index=all_dates)
        comb_daily['shorter_eq'] = s_pnl
        comb_daily['longer_f1'] = l_pnl
        comb_daily = comb_daily.fillna(0.0)
        comb_daily['total_pnl'] = comb_daily['shorter_eq'] + comb_daily['longer_f1']
        comb_daily['year'] = comb_daily.index.year

        tot_pnl = comb_daily['total_pnl'].sum() / 1e5
        tot_sharpe = (comb_daily['total_pnl'].mean() / comb_daily['total_pnl'].std()) * np.sqrt(252)
        pos_days = (comb_daily['total_pnl'] > 0).mean() * 100

        print(f"Total Master Portfolio Net PnL: +₹{tot_pnl:.2f} Lakhs (+₹{tot_pnl/100:.2f} CRORE)")
        print(f"Daily Win Rate:                {pos_days:.2f}%")
        print(f"Annualized Sharpe Ratio:       {tot_sharpe:.2f}")

        print("\nYear-by-Year Master Portfolio PnL (₹ Lakhs):")
        y_comb = (comb_daily.groupby('year')['total_pnl'].sum() / 1e5).round(2)
        for y, p in y_comb.items():
            print(f"  {y}: +₹{p:6.2f} Lakhs")
        print("=" * 105)

if __name__ == '__main__':
    main()
