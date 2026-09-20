#!/usr/bin/env python3
import os
import pandas as pd

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(_THIS_DIR, "output")

def main():
    trades_path = os.path.join(OUTPUT_DIR, "trades_dynamic_threshold_ensemble.csv")
    if not os.path.exists(trades_path):
        print(f"[!] Trades file not found: {trades_path}")
        return
        
    df = pd.read_csv(trades_path)
    df['date'] = pd.to_datetime(df['date'])
    df['year'] = df['date'].dt.year
    df['month'] = df['date'].dt.month
    
    # Filter for 2026 trades (Adaptive version is currently active in the csv because we just restored it in side-by-side comparison)
    df_2026 = df[df['year'] == 2026].copy()
    
    if len(df_2026) == 0:
        print("[!] No trades found in 2026.")
        return
        
    total_trades = len(df_2026)
    win_rate = (df_2026['actual_pnl'] > 0).mean() * 100
    total_pnl = df_2026['actual_pnl'].sum()
    avg_pnl = df_2026['actual_pnl'].mean()
    
    print("\n" + "="*80)
    print("                     2026 PERFORMANCE DIAGNOSTIC REPORT")
    print("="*80)
    print(f"  • Total Completed Trades : {total_trades}")
    print(f"  • Overall Win Rate       : {win_rate:.1f}%")
    print(f"  • Average PnL per Trade  : Rs {avg_pnl:,.2f}")
    print(f"  • Total Realized Profit  : Rs {total_pnl:,.2f}")
    print("="*80)
    
    # Monthly breakdown
    print("\n  [+] MONTHLY BREAKDOWN FOR 2026:")
    print("  Month | Trades | Win Rate |  Avg PnL/Trade  |   Total PnL   ")
    print("  ------|--------|----------|-----------------|---------------")
    for m in sorted(df_2026['month'].unique()):
        m_df = df_2026[df_2026['month'] == m]
        m_trades = len(m_df)
        m_win = (m_df['actual_pnl'] > 0).mean() * 100
        m_avg = m_df['actual_pnl'].mean()
        m_tot = m_df['actual_pnl'].sum()
        print(f"  {m:5} | {m_trades:6} | {m_win:7.1f}% | Rs {m_avg:13,.2f} | Rs {m_tot:11,.2f}")
        
    # Top 10 most profitable trades
    print("\n  [+] TOP 10 MOST PROFITABLE TRADES IN 2026:")
    print("  Stock Name     | Date       | Actual PnL   | Predicted PnL ")
    print("  ---------------|------------|--------------|---------------")
    top_10 = df_2026.sort_values(by='actual_pnl', ascending=False).head(10)
    for idx, r in top_10.iterrows():
        dt_str = r['date'].strftime('%Y-%m-%d')
        print(f"  {r['stock']:14} | {dt_str} | Rs {r['actual_pnl']:10,.2f} | Rs {r['pred_pnl']:10,.2f}")
        
    # Bottom 5 biggest losses
    print("\n  [+] BOTTOM 5 BIGGEST LOSSES IN 2026:")
    print("  Stock Name     | Date       | Actual PnL   | Predicted PnL ")
    print("  ---------------|------------|--------------|---------------")
    bottom_5 = df_2026.sort_values(by='actual_pnl', ascending=True).head(5)
    for idx, r in bottom_5.iterrows():
        dt_str = r['date'].strftime('%Y-%m-%d')
        print(f"  {r['stock']:14} | {dt_str} | Rs {r['actual_pnl']:10,.2f} | Rs {r['pred_pnl']:10,.2f}")

if __name__ == "__main__":
    main()
