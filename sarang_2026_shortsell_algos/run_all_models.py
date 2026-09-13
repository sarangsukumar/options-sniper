#!/usr/bin/env python3
"""
🏆 SARANG 2026 SHORT-SELL ALGORITHMS - MASTER SUITE BENCHMARK
===================================================================================
100% PURE MYSQL DATABASE | ZERO YAHOO FINANCE | VERIFIED CONTRACT LOT SIZES
===================================================================================
This script loads and compares the audited performance of all 4 short-sell models:
1. Model V8: Morning Momentum Scalp (09:20 -> 09:40 AM)
2. Model B: Extended Morning Ticks Hold (09:20 -> 14:45 PM)
3. Model V6: Single Reversion Engine (09:42 -> 14:45 PM with 3% SL)
4. Model V6/V7 Hybrid: Dual-Engine Titan (09:42 -> 14:45 PM with 3% SL)
===================================================================================
"""

import os
import pandas as pd
import numpy as np

BASE_DIR = '/home/ubuntu/sarang_2026_shortsell_algos'

MODELS_CONFIG = [
    {
        'id': 'v8_scalp',
        'name': 'Model 1: V8 Scalp (09:20 -> 09:40)',
        'file': os.path.join(BASE_DIR, '01_Model_V8_Scalp_0920_0940', 'trades_log.csv'),
        'date_col': 'date_str',
        'pnl_col': 'net_pnl_rupees'
    },
    {
        'id': 'model_b',
        'name': 'Model 2: Model B Hold (09:20 -> 14:45)',
        'file': os.path.join(BASE_DIR, '02_Model_B_Extended_0920_1445', 'trades_log.csv'),
        'date_col': 'short_date',
        'pnl_col': 'net_pnl'
    },
    {
        'id': 'v6_single',
        'name': 'Model 3: V6 Single (09:42 -> 14:45, 3% SL)',
        'file': os.path.join(BASE_DIR, '03_Model_V6_Single_0942_1445', 'trades_log.csv'),
        'date_col': 'date_str',
        'pnl_col': 'net_pnl_rupees'
    },
    {
        'id': 'v6_v7_hybrid',
        'name': 'Model 4: V6/V7 Hybrid (09:42 -> 14:45, 3% SL)',
        'file': os.path.join(BASE_DIR, '04_Model_V6_V7_Hybrid_0942_1445', 'trades_log.csv'),
        'date_col': 'date_str',
        'pnl_col': 'net_pnl'
    }
]

def main():
    print("=" * 95)
    print("🏆 SARANG 2026 SHORT-SELL ALGORITHMIC PORTFOLIO: AUDIT & COMPARISON SUITE")
    print("=" * 95)

    loaded = []
    daily_pnls = {}

    for cfg in MODELS_CONFIG:
        if not os.path.exists(cfg['file']):
            print(f"Warning: File not found: {cfg['file']}")
            continue
        df = pd.read_csv(cfg['file'])
        df['date'] = pd.to_datetime(df[cfg['date_col']], errors='coerce').dt.strftime('%Y-%m-%d')
        df['net'] = pd.to_numeric(df[cfg['pnl_col']], errors='coerce').fillna(0.0)
        df['year'] = pd.to_datetime(df['date']).dt.year
        loaded.append((cfg, df))
        
        # Calculate daily aggregate
        daily = df.groupby('date')['net'].sum().rename(cfg['id'])
        daily_pnls[cfg['id']] = daily

    print("\n--- 1. INSTITUTIONAL METRICS SUMMARY ---")
    summary_rows = []
    for cfg, df in loaded:
        trades = len(df)
        net_tot = df['net'].sum()
        wr = (df['net'] > 0).mean() * 100
        avg_t = df['net'].mean()
        wins = df[df['net'] > 0]['net'].sum()
        losses = abs(df[df['net'] < 0]['net'].sum())
        pf = wins / losses if losses > 0 else np.nan

        daily = daily_pnls[cfg['id']].reset_index()
        daily['cum'] = daily[cfg['id']].cumsum()
        daily['peak'] = daily['cum'].cummax()
        daily['dd'] = daily['cum'] - daily['peak']
        max_dd = daily['dd'].min()
        sharpe = (daily[cfg['id']].mean() / daily[cfg['id']].std()) * np.sqrt(252) if daily[cfg['id']].std() > 0 else 0

        summary_rows.append({
            'Model Name': cfg['name'],
            'Trades': f"{trades:,}",
            'Win Rate': f"{wr:.2f}%",
            'Profit Factor': f"{pf:.2f}",
            'Avg Net/Trade': f"₹{avg_t:,.2f}",
            'Daily Sharpe': f"{sharpe:.2f}",
            'Max Drawdown': f"₹{max_dd/1e5:,.2f} L",
            'Total Net PnL': f"₹{net_tot/1e5:,.2f} L (₹{net_tot/1e7:.2f} Cr)"
        })

    print(pd.DataFrame(summary_rows).to_string(index=False))

    print("\n--- 2. YEAR-BY-YEAR NET PnL (₹ LAKHS) ---")
    years = [2020, 2021, 2022, 2023, 2024, 2025, 2026]
    year_rows = []
    for y in years:
        row = {'Year': y}
        for cfg, df in loaded:
            sub = df[df['year'] == y]
            pnl_l = sub['net'].sum() / 1e5 if len(sub) > 0 else 0.0
            row[cfg['id']] = f"₹{pnl_l:7.2f} L"
        year_rows.append(row)
    print(pd.DataFrame(year_rows).to_string(index=False))

    print("\n--- 3. CORRELATION MATRIX (DAILY PnL DIVERSIFICATION) ---")
    daily_df = pd.DataFrame(daily_pnls).fillna(0.0)
    print(daily_df.corr().round(4).to_string())

    print("\n--- 4. THE GOLDEN SEQUENTIAL PAIR: MODEL 1 (V8 Scalp) + MODEL 4 (V6/V7 Hybrid) ---")
    seq_tot = daily_df['v8_scalp'] + daily_df['v6_v7_hybrid']
    seq_l = seq_tot.sum() / 1e5
    seq_wr = (seq_tot > 0).mean() * 100
    seq_sharpe = (seq_tot.mean() / seq_tot.std()) * np.sqrt(252)
    seq_cum = seq_tot.cumsum()
    seq_dd = (seq_cum - seq_cum.cummax()).min() / 1e5

    print(f"Total Combined Net PnL:  ₹{seq_l:,.2f} Lakhs (₹{seq_l/100:.2f} CRORE)")
    print(f"Daily Win Rate:          {seq_wr:.2f}%")
    print(f"Daily Sharpe Ratio:      {seq_sharpe:.2f}")
    print(f"Max Peak-to-Trough DD:   ₹{seq_dd:,.2f} Lakhs")
    print(f"Capital Requirement:     1x Margin (09:20-09:40 exits before 09:42 entry)")
    print("=" * 95)

if __name__ == '__main__':
    main()
