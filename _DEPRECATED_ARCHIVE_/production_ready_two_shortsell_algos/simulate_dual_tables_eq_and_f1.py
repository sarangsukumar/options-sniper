#!/usr/bin/env python3
"""
simulate_dual_tables_eq_and_f1.py
==================================
Simulates Model 1 and Model 2 across BOTH:
1. NSE Equity Cash Table (`markets.scrapdata`) with Kotak MIS Calculator (+Rs 50 buffer)
2. Near-Month Futures Table (`markets.scrapdata_F1`) with Flat Rs 600 per lot

Covers:
- Model 1: 09:20 -> 09:40 Quick Scalp
- Model 2: 09:42 -> 14:45 Hybrid Intraday (with 3% tick-by-tick continuous Stop Loss)
- Year-by-Year comparison tables (2020 - 2026)
- Combined Multi-Asset Portfolios: Pure Equity, Pure Futures, and Optimal Hybrid
- Realistic Rs 7.5L Capital Constrained execution
"""

import os, sys
import pandas as pd
import numpy as np

sys.path.insert(0, '/home/ubuntu/sarang_2026_shortsell_algos')
from kotak_mis_calculator import calculate_kotak_charges, calculate_kotak_margin

BASE_DIR = '/home/ubuntu/sarang_2026_shortsell_algos'
M1_FILE = os.path.join(BASE_DIR, '01_Best_Shorter_Window_0920_0940', 'm1_dual_table_all_trades.csv')
M1_BENCH_FILE = os.path.join(BASE_DIR, '01_Best_Shorter_Window_0920_0940', 'shorter_window_trades_eq_and_futures.csv')
M2_FILE = os.path.join(BASE_DIR, '02_Best_Longer_Window_0942_1445', 'm2_equity_ticks_cache.csv')

def compute_drawdown(series_pnl):
    cum = series_pnl.cumsum()
    peak = cum.cummax()
    dd = cum - peak
    return dd.min()

def run_simulation():
    print("=" * 95)
    print("🏆 MASTER DUAL-TABLE SIMULATION: EQUITY CASH (`scrapdata`) vs FUTURES (`scrapdata_F1`)")
    print("   • Equity Cash Engine : Exact Kotak Securities MIS Calculator (5x leverage + Rs 50 safety buffer)")
    print("   • Futures F1 Engine  : Flat Rs 600.00 Commission per lot traded")
    print("=" * 95)

    # -------------------------------------------------------------
    # 1. MODEL 1 (09:20 -> 09:40 SCALP)
    # -------------------------------------------------------------
    print("\n" + "#" * 95)
    print("⚡ PART 1: MODEL 1 (09:20 -> 09:40 AM SCALP)")
    print("#" * 95)
    
    df1 = pd.read_csv(M1_BENCH_FILE)
    # df1 has: date_str, clean_stock, year, lotsize, eq_entry, eq_exit, f1_entry, f1_exit
    df1['eq_gross'] = (df1['eq_entry'] - df1['eq_exit']) * df1['lotsize']
    df1['eq_charges'] = [calculate_kotak_charges(en, ex, q)['total_charges'] for en, ex, q in zip(df1['eq_entry'], df1['eq_exit'], df1['lotsize'])]
    df1['eq_net'] = df1['eq_gross'] - df1['eq_charges']
    
    df1['f1_gross'] = (df1['f1_entry'] - df1['f1_exit']) * df1['lotsize']
    df1['f1_charges'] = 600.0  # Flat Rs 600 per lot
    df1['f1_net'] = df1['f1_gross'] - df1['f1_charges']
    
    # Save ledger
    m1_out = os.path.join(BASE_DIR, 'model1_equity_kotak_vs_f1_flat600.csv')
    df1.to_csv(m1_out, index=False)
    
    print(f"Total Trades Evaluated: {len(df1):,} (Top 3 Ranks, Tue-Fri 2021-2026)")
    print("-" * 95)
    print(f"{'Metric':<30} | {'Equity (`scrapdata`) [Kotak MIS]':<30} | {'Futures (`scrapdata_F1`) [Flat 600]':<30}")
    print("-" * 95)
    print(f"{'Gross Profit':<30} | +Rs {df1['eq_gross'].sum()/1e5:>10.2f} L (+Rs {df1['eq_gross'].sum()/1e7:>5.3f} Cr)  | +Rs {df1['f1_gross'].sum()/1e5:>10.2f} L (+Rs {df1['f1_gross'].sum()/1e7:>5.3f} Cr)")
    print(f"{'Total Charges':<30} | -Rs {df1['eq_charges'].sum()/1e5:>10.2f} L (Avg Rs {df1['eq_charges'].mean():>6.2f})  | -Rs {df1['f1_charges'].sum()/1e5:>10.2f} L (Flat Rs 600.00)")
    print(f"{'Net Profit':<30} | 👑 +Rs {df1['eq_net'].sum()/1e5:>8.2f} L (+Rs {df1['eq_net'].sum()/1e7:>5.3f} Cr)  | +Rs {df1['f1_net'].sum()/1e5:>10.2f} L (+Rs {df1['f1_net'].sum()/1e7:>5.3f} Cr)")
    print(f"{'Trade Win Rate':<30} | {(df1['eq_net']>0).mean()*100:>26.2f}% | {(df1['f1_net']>0).mean()*100:>26.2f}%")
    print(f"{'Max Drawdown':<30} | -Rs {abs(compute_drawdown(df1['eq_net']))/1e5:>10.2f} L              | -Rs {abs(compute_drawdown(df1['f1_net']))/1e5:>10.2f} L")
    
    # Year by Year M1
    print("\n📅 MODEL 1: YEAR-BY-YEAR COMPARISON")
    print("-" * 95)
    print(f"{'Year':<6} | {'Trades':<8} | {'EQ Gross (L)':<13} | {'EQ Net (L)':<13} | {'EQ WR %':<10} | {'F1 Gross (L)':<13} | {'F1 Net (L)':<13} | {'F1 WR %':<10}")
    print("-" * 95)
    for y, g in df1.groupby('year'):
        print(f"{y:<6} | {len(g):<8} | +Rs {g['eq_gross'].sum()/1e5:>7.2f} L | +Rs {g['eq_net'].sum()/1e5:>7.2f} L | {(g['eq_net']>0).mean()*100:>8.2f}% | +Rs {g['f1_gross'].sum()/1e5:>7.2f} L | +Rs {g['f1_net'].sum()/1e5:>7.2f} L | {(g['f1_net']>0).mean()*100:>8.2f}%")
    print("-" * 95)

    # -------------------------------------------------------------
    # 2. MODEL 2 (09:42 -> 14:45 HYBRID)
    # -------------------------------------------------------------
    print("\n" + "#" * 95)
    print("👑 PART 2: MODEL 2 (09:42 -> 14:45 PM HYBRID WITH 3% STOP LOSS)")
    print("#" * 95)
    
    df2 = pd.read_csv(M2_FILE)
    df2 = df2[df2['status'] == 'COMPLETED'].copy()
    df2['year'] = pd.to_datetime(df2['date']).dt.year
    
    # 1. Futures F1 with Flat Rs 600 per lot
    df2['f1_gross'] = (df2['entry_price'] - df2['exit_price']) * df2['total_quantity']
    df2['f1_charges'] = 600.0 * df2['lots_to_trade']
    df2['f1_net'] = df2['f1_gross'] - df2['f1_charges']
    
    # 2. Equity with Kotak MIS charges
    df2['eq_gross'] = (df2['eq_entry_price'] - df2['eq_exit_price']) * df2['total_quantity']
    df2['eq_charges'] = [calculate_kotak_charges(float(en), float(ex), int(q))['total_charges'] for en, ex, q in zip(df2['eq_entry_price'], df2['eq_exit_price'], df2['total_quantity'])]
    df2['eq_net'] = df2['eq_gross'] - df2['eq_charges']
    
    # Save ledger
    m2_out = os.path.join(BASE_DIR, 'model2_equity_kotak_vs_f1_flat600.csv')
    df2.to_csv(m2_out, index=False)
    
    print(f"Total Trades Evaluated: {len(df2):,} (2020-2026 Dual Confirmed 2x + 50/50 Remainder)")
    print("-" * 95)
    print(f"{'Metric':<30} | {'Equity (`scrapdata`) [Kotak MIS]':<30} | {'Futures (`scrapdata_F1`) [Flat 600]':<30}")
    print("-" * 95)
    print(f"{'Gross Profit':<30} | +Rs {df2['eq_gross'].sum()/1e5:>10.2f} L (+Rs {df2['eq_gross'].sum()/1e7:>5.3f} Cr)  | +Rs {df2['f1_gross'].sum()/1e5:>10.2f} L (+Rs {df2['f1_gross'].sum()/1e7:>5.3f} Cr)")
    print(f"{'Total Charges':<30} | -Rs {df2['eq_charges'].sum()/1e5:>10.2f} L (Avg Rs {df2['eq_charges'].mean():>6.2f})  | -Rs {df2['f1_charges'].sum()/1e5:>10.2f} L (Flat Rs 600/lot)")
    print(f"{'Net Profit':<30} | +Rs {df2['eq_net'].sum()/1e5:>10.2f} L (+Rs {df2['eq_net'].sum()/1e7:>5.3f} Cr)  | 👑 +Rs {df2['f1_net'].sum()/1e5:>8.2f} L (+Rs {df2['f1_net'].sum()/1e7:>5.3f} Cr)")
    print(f"{'Trade Win Rate':<30} | {(df2['eq_net']>0).mean()*100:>26.2f}% | {(df2['f1_net']>0).mean()*100:>26.2f}%")
    print(f"{'Max Drawdown':<30} | -Rs {abs(compute_drawdown(df2['eq_net']))/1e5:>10.2f} L              | -Rs {abs(compute_drawdown(df2['f1_net']))/1e5:>10.2f} L")
    
    # Year by Year M2
    print("\n📅 MODEL 2: YEAR-BY-YEAR COMPARISON")
    print("-" * 95)
    print(f"{'Year':<6} | {'Trades':<8} | {'EQ Gross (L)':<13} | {'EQ Net (L)':<13} | {'EQ WR %':<10} | {'F1 Gross (L)':<13} | {'F1 Net (L)':<13} | {'F1 WR %':<10}")
    print("-" * 95)
    for y, g in df2.groupby('year'):
        print(f"{y:<6} | {len(g):<8} | +Rs {g['eq_gross'].sum()/1e5:>7.2f} L | +Rs {g['eq_net'].sum()/1e5:>7.2f} L | {(g['eq_net']>0).mean()*100:>8.2f}% | +Rs {g['f1_gross'].sum()/1e5:>7.2f} L | +Rs {g['f1_net'].sum()/1e5:>7.2f} L | {(g['f1_net']>0).mean()*100:>8.2f}%")
    print("-" * 95)

    # -------------------------------------------------------------
    # 3. COMBINED DUAL ENGINE PORTFOLIOS
    # -------------------------------------------------------------
    print("\n" + "#" * 95)
    print("🏛️ PART 3: COMBINED PORTFOLIO MULTI-ASSET SCENARIOS (MODEL 1 + MODEL 2)")
    print("#" * 95)
    
    # Filter Model 2 to 2021-2026 to align with Model 1 for apples-to-apples comparison
    df2_sync = df2[df2['year'] >= 2021].copy()
    
    # Scenario A: All-Equity Execution (Both on scrapdata with Kotak MIS)
    tot_trades = len(df1) + len(df2_sync)
    p_eq_gross = df1['eq_gross'].sum() + df2_sync['eq_gross'].sum()
    p_eq_charges = df1['eq_charges'].sum() + df2_sync['eq_charges'].sum()
    p_eq_net = df1['eq_net'].sum() + df2_sync['eq_net'].sum()
    p_eq_wr = ((df1['eq_net'] > 0).sum() + (df2_sync['eq_net'] > 0).sum()) / tot_trades * 100
    
    # Scenario B: All-Futures Execution (Both on scrapdata_F1 with Flat Rs 600)
    p_f1_gross = df1['f1_gross'].sum() + df2_sync['f1_gross'].sum()
    p_f1_charges = df1['f1_charges'].sum() + df2_sync['f1_charges'].sum()
    p_f1_net = df1['f1_net'].sum() + df2_sync['f1_net'].sum()
    p_f1_wr = ((df1['f1_net'] > 0).sum() + (df2_sync['f1_net'] > 0).sum()) / tot_trades * 100
    
    # Scenario C: Optimal Hybrid Production Execution (M1 on Equity Kotak MIS + M2 on Futures F1 Flat 600)
    p_hyb_gross = df1['eq_gross'].sum() + df2_sync['f1_gross'].sum()
    p_hyb_charges = df1['eq_charges'].sum() + df2_sync['f1_charges'].sum()
    p_hyb_net = df1['eq_net'].sum() + df2_sync['f1_net'].sum()
    p_hyb_wr = ((df1['eq_net'] > 0).sum() + (df2_sync['f1_net'] > 0).sum()) / tot_trades * 100

    print(f"{'Combined Portfolio Scenario':<42} | {'Gross Profit':<16} | {'Charges':<14} | {'Net Profit':<18} | {'Win Rate':<9}")
    print("-" * 95)
    print(f"{'1. All-Equity (`scrapdata` + Kotak MIS)':<42} | +Rs {p_eq_gross/1e5:>7.2f} L   | -Rs {p_eq_charges/1e5:>5.2f} L   | +Rs {p_eq_net/1e5:>7.2f} L (+{p_eq_net/1e7:.2f}Cr) | {p_eq_wr:>6.2f}%")
    print(f"{'2. All-Futures (`scrapdata_F1` + Flat 600)':<42} | +Rs {p_f1_gross/1e5:>7.2f} L   | -Rs {p_f1_charges/1e5:>5.2f} L   | +Rs {p_f1_net/1e5:>7.2f} L (+{p_f1_net/1e7:.2f}Cr) | {p_f1_wr:>6.2f}%")
    print(f"{'3. 👑 Optimal Hybrid (M1 Equity + M2 F1)':<42} | +Rs {p_hyb_gross/1e5:>7.2f} L   | -Rs {p_hyb_charges/1e5:>5.2f} L   | +Rs {p_hyb_net/1e5:>7.2f} L (+{p_hyb_net/1e7:.2f}Cr) | {p_hyb_wr:>6.2f}%")
    print("-" * 95)
    
    # Yearly summary for Optimal Hybrid
    print("\n📅 OPTIMAL HYBRID (M1 Equity + M2 Futures F1) YEAR-BY-YEAR (2021-2026):")
    print("-" * 95)
    print(f"{'Year':<6} | {'Trades':<8} | {'M1 Net (EQ)':<14} | {'M2 Net (F1)':<14} | {'Combined Net (Rs L)':<20} | {'Combined WR %':<12}")
    print("-" * 95)
    for y in sorted(df1['year'].unique()):
        m1_y = df1[df1['year'] == y]
        m2_y = df2_sync[df2_sync['year'] == y]
        n_tr = len(m1_y) + len(m2_y)
        m1_net_y = m1_y['eq_net'].sum() / 1e5
        m2_net_y = m2_y['f1_net'].sum() / 1e5
        comb_net_y = m1_net_y + m2_net_y
        comb_wr = ((m1_y['eq_net'] > 0).sum() + (m2_y['f1_net'] > 0).sum()) / n_tr * 100
    for y in sorted(df1['year'].unique()):
        m1_y = df1[df1['year'] == y]
        m2_y = df2_sync[df2_sync['year'] == y]
        n_tr = len(m1_y) + len(m2_y)
        m1_net_y = m1_y['eq_net'].sum() / 1e5
        m2_net_y = m2_y['f1_net'].sum() / 1e5
        comb_net_y = m1_net_y + m2_net_y
        comb_wr = ((m1_y['eq_net'] > 0).sum() + (m2_y['f1_net'] > 0).sum()) / n_tr * 100
        print(f"{y:<6} | {n_tr:<8} | +Rs {m1_net_y:>6.2f} L     | +Rs {m2_net_y:>6.2f} L     | 👑 +Rs {comb_net_y:>6.2f} Lakhs     | {comb_wr:>8.2f}%")
    print("-" * 95)
    
    # -------------------------------------------------------------
    # 4. REALISTIC Rs 7.5 LAKHS CAPITAL CONSTRAINED PORTFOLIO
    # -------------------------------------------------------------
    print("\n" + "#" * 95)
    print("🛡️ PART 4: REALISTIC Rs 7.5 LAKHS DAILY CAPITAL CONSTRAINED PORTFOLIO")
    print("   • Fixed Rs 7,50,000 cash balance every morning")
    print("   • 5.0x leverage (20% margin required per position)")
    print("   • Trades prioritized by model confidence rank; skips trade if cash is insufficient")
    print("#" * 95)
    
    CAPITAL = 750000.0
    
    # Model 1 Constrained (Equity Kotak vs Futures Flat 600)
    m1_eq_75 = []
    m1_f1_75 = []
    for dt, grp in df1.groupby('date_str'):
        avail_eq = CAPITAL
        avail_f1 = CAPITAL
        for _, r in grp.iterrows():
            qty = int(r['lotsize'])
            # EQ
            eq_margin = (float(r['eq_entry']) * qty) / 5.0
            if eq_margin <= avail_eq:
                avail_eq -= eq_margin
                m1_eq_75.append({'year': r['year'], 'net': r['eq_net']})
            # F1
            f1_margin = (float(r['f1_entry']) * qty) / 5.0
            if f1_margin <= avail_f1:
                avail_f1 -= f1_margin
                m1_f1_75.append({'year': r['year'], 'net': r['f1_net']})
                
    m1_eq_75_df = pd.DataFrame(m1_eq_75)
    m1_f1_75_df = pd.DataFrame(m1_f1_75)
    
    # Model 2 Constrained (Equity Kotak vs Futures Flat 600)
    m2_eq_75 = []
    m2_f1_75 = []
    for dt, grp in df2.groupby('date'):
        avail_eq = CAPITAL
        avail_f1 = CAPITAL
        for _, r in grp.sort_values('rank').iterrows():
            qty = int(r['total_quantity'])
            mult = int(r['lots_to_trade'])
            # EQ
            eq_margin = (float(r['eq_entry_price']) * qty) / 5.0
            if eq_margin <= avail_eq:
                avail_eq -= eq_margin
                m2_eq_75.append({'year': r['year'], 'net': r['eq_net']})
            # F1
            f1_margin = (float(r['entry_price']) * qty) / 5.0
            if f1_margin <= avail_f1:
                avail_f1 -= f1_margin
                m2_f1_75.append({'year': r['year'], 'net': r['f1_net']})
                
    m2_eq_75_df = pd.DataFrame(m2_eq_75)
    m2_f1_75_df = pd.DataFrame(m2_f1_75)
    
    print(f"{'Strategy / Engine':<35} | {'Executed Trades':<16} | {'Net PnL (Rs Lakhs)':<20} | {'Win Rate %':<12}")
    print("-" * 95)
    print(f"{'Model 1 (Equity Cash + Kotak MIS)':<35} | {len(m1_eq_75_df):<16} | +Rs {m1_eq_75_df['net'].sum()/1e5:>7.2f} Lakhs        | {(m1_eq_75_df['net']>0).mean()*100:>6.2f}%")
    print(f"{'Model 1 (Futures F1 + Flat Rs 600)':<35} | {len(m1_f1_75_df):<16} | +Rs {m1_f1_75_df['net'].sum()/1e5:>7.2f} Lakhs        | {(m1_f1_75_df['net']>0).mean()*100:>6.2f}%")
    print("-" * 95)
    print(f"{'Model 2 (Equity Cash + Kotak MIS)':<35} | {len(m2_eq_75_df):<16} | +Rs {m2_eq_75_df['net'].sum()/1e5:>7.2f} Lakhs (+{m2_eq_75_df['net'].sum()/1e7:.2f}Cr) | {(m2_eq_75_df['net']>0).mean()*100:>6.2f}%")
    print(f"{'Model 2 (Futures F1 + Flat Rs 600)':<35} | {len(m2_f1_75_df):<16} | 👑 +Rs {m2_f1_75_df['net'].sum()/1e5:>7.2f} Lakhs (+{m2_f1_75_df['net'].sum()/1e7:.2f}Cr) | {(m2_f1_75_df['net']>0).mean()*100:>6.2f}%")
    print("-" * 95)
    
    # Combined Hybrid 7.5L
    comb_75_net = (m1_eq_75_df['net'].sum() + m2_f1_75_df[m2_f1_75_df['year']>=2021]['net'].sum()) / 1e5
    comb_75_trades = len(m1_eq_75_df) + len(m2_f1_75_df[m2_f1_75_df['year']>=2021])
    comb_75_wr = ((m1_eq_75_df['net']>0).sum() + (m2_f1_75_df[m2_f1_75_df['year']>=2021]['net']>0).sum()) / comb_75_trades * 100
    print(f"{'👑 Combined Optimal (M1 EQ + M2 F1)':<35} | {comb_75_trades:<16} | 👑 +Rs {comb_75_net:>7.2f} Lakhs (+{comb_75_net/100:.2f}Cr) | {comb_75_wr:>6.2f}%")
    print("=" * 95)

if __name__ == '__main__':
    run_simulation()

