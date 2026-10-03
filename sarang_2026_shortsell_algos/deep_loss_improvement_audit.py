#!/usr/bin/env python3
"""
deep_loss_improvement_audit.py
==============================
Rigorous loss-side and risk-adjusted comparison:
Baseline vs With Rules on Master F1 (+Rs 2.27 Cr) & Equity (+Rs 2.37 Cr) Engines.
"""

import os, sys, pymysql
import pandas as pd
import numpy as np

M2_CSV = '/home/ubuntu/sarang_2026_shortsell_algos/model2_equity_kotak_vs_f1_flat600.csv'
HIST_DATASET = '/home/ubuntu/v5_from_scratch/data/short_sell_ml_dataset_v5_scratch.csv'

def load_prev_closes():
    df_h = pd.read_csv(HIST_DATASET, usecols=['clean_stock', 'short_sell_date', 'prev_close'], low_memory=False)
    df_h = df_h.dropna(subset=['clean_stock', 'short_sell_date', 'prev_close'])
    df_h['clean_stock'] = df_h['clean_stock'].astype(str).str.strip().str.upper()
    df_h['date'] = df_h['short_sell_date'].astype(str).str.strip()
    df_h = df_h.drop_duplicates(subset=['clean_stock', 'date'])
    return dict(zip(zip(df_h['clean_stock'], df_h['date']), df_h['prev_close'].astype(float)))

def main():
    prev_map = load_prev_closes()
    df = pd.read_csv(M2_CSV)
    
    # We already have the simulated pattern exits from audit_patterns_on_master_f1.py
    # Let's import check_pattern_triggers
    from audit_patterns_on_master_f1 import check_pattern_triggers
    from concurrent.futures import ThreadPoolExecutor
    from kotak_mis_calculator import calculate_kotak_charges
    
    trades = df.to_dict('records')
    with ThreadPoolExecutor(max_workers=24) as ex:
        results = [r for r in ex.map(check_pattern_triggers, trades) if r is not None]
    rdf = pd.DataFrame(results)
    
    rdf['prev_close'] = [prev_map.get((str(s).strip().upper().replace('\"', '').strip(), str(d).strip()[:10])) for s, d in zip(rdf['stockname'], rdf['date'])]
    valid = rdf[rdf['prev_close'].notna() & (rdf['prev_close'] > 0)].copy()
    valid['stock_gain_pct'] = ((valid['en'] - valid['prev_close']) / valid['prev_close']) * 100.0
    valid['passed_filter'] = (valid['stock_gain_pct'] >= -1.5) & ~((valid['stock_gain_pct'] >= 2.0) & (valid['stock_gain_pct'] < 3.0))
    
    # Futures F1 PnLs
    valid['f1_base_net'] = (valid['en'] - valid['ex_aud']) * valid['qty'] - (600.0 * valid['lots'])
    valid['f1_pat_net']  = (valid['en'] - valid['ex_pat']) * valid['qty'] - (600.0 * valid['lots'])
    
    # Equity Cash PnLs
    chg_base = [calculate_kotak_charges(en, ex, q)['total_charges'] for en, ex, q in zip(valid['en'], valid['ex_aud'], valid['qty'])]
    chg_pat  = [calculate_kotak_charges(en, ex, q)['total_charges'] for en, ex, q in zip(valid['en'], valid['ex_pat'], valid['qty'])]
    valid['eq_base_net'] = (valid['en'] - valid['ex_aud']) * valid['qty'] - pd.Series(chg_base, index=valid.index)
    valid['eq_pat_net']  = (valid['en'] - valid['ex_pat']) * valid['qty'] - pd.Series(chg_pat, index=valid.index)
    
    # Function to compute loss metrics
    def compute_loss_profile(series, name):
        total_pnl = series.sum() / 1e5
        trades = len(series)
        wins = series[series > 0]
        losses = series[series < 0]
        
        wr = (len(wins) / trades) * 100
        tot_loss_val = abs(losses.sum()) / 1e5
        tot_win_val = wins.sum() / 1e5
        pf = tot_win_val / tot_loss_val if tot_loss_val > 0 else np.nan
        
        avg_loss = losses.mean() if len(losses) > 0 else 0
        avg_win = wins.mean() if len(wins) > 0 else 0
        max_loss = losses.min() if len(losses) > 0 else 0
        p95_loss = losses.quantile(0.05) if len(losses) > 0 else 0
        
        return {
            'name': name,
            'trades': trades,
            'net_lakhs': total_pnl,
            'wr': wr,
            'tot_loss_lakhs': tot_loss_val,
            'tot_win_lakhs': tot_win_val,
            'pf': pf,
            'avg_loss': avg_loss,
            'avg_win': avg_win,
            'max_loss': max_loss,
            'p95_loss': p95_loss,
            'loss_trades_count': len(losses)
        }
        
    f1_base_prof = compute_loss_profile(valid['f1_base_net'], "Futures F1 Baseline")
    f1_filt_prof = compute_loss_profile(valid[valid['passed_filter']]['f1_base_net'], "Futures F1 Filter Only")
    f1_pat_prof  = compute_loss_profile(valid[valid['passed_filter']]['f1_pat_net'], "Futures F1 Filter + Patterns")
    
    eq_base_prof = compute_loss_profile(valid['eq_base_net'], "Equity Baseline")
    eq_filt_prof = compute_loss_profile(valid[valid['passed_filter']]['eq_base_net'], "Equity Filter Only")
    eq_pat_prof  = compute_loss_profile(valid[valid['passed_filter']]['eq_pat_net'], "Equity Filter + Patterns")
    
    print("=" * 115)
    print("🔬 COMPREHENSIVE LOSS PROFILE & RISK AUDIT")
    print("=" * 115)
    
    profiles = [f1_base_prof, f1_filt_prof, f1_pat_prof, eq_base_prof, eq_filt_prof, eq_pat_prof]
    
    print(f"{'System Variant':<32} | {'Trades':<8} | {'Net PnL':<14} | {'Win Rate':<9} | {'Avg Loss':<12} | {'Max Single Loss':<16} | {'Total Gross Loss'}")
    print("-" * 115)
    for p in profiles:
        print(f"{p['name']:<32} | {p['trades']:<8} | Rs {p['net_lakhs']:>7.2f} L  | {p['wr']:>6.2f}%   | Rs {p['avg_loss']:>8.2f} | Rs {p['max_loss']:>12.2f}   | -Rs {p['tot_loss_lakhs']:>6.2f} L")
    print("=" * 115)
    
    # Analyze the 227 filtered trades specifically
    cut_trades = valid[~valid['passed_filter']]
    print(f"\n🔍 WHAT HAPPENED TO THE 227 FILTERED TRADES?")
    print(f"  • Total Filtered Trades: {len(cut_trades)}")
    print(f"  • F1 Net PnL of cut trades:     Rs {cut_trades['f1_base_net'].sum()/1e5:.2f} Lakhs")
    print(f"  • Equity Net PnL of cut trades: Rs {cut_trades['eq_base_net'].sum()/1e5:.2f} Lakhs")
    print(f"  • Win Rate of cut trades (F1):  {(cut_trades['f1_base_net']>0).mean()*100:.2f}%")
    print(f"  • Win Rate of cut trades (EQ):  {(cut_trades['eq_base_net']>0).mean()*100:.2f}%")
    
    # Analyze Pattern 1 and Pattern 2 triggers specifically
    p1_trades = valid[valid['passed_filter'] & valid['p1_trigger']]
    p2_trades = valid[valid['passed_filter'] & valid['p2_trigger']]
    print(f"\n🔍 WHAT HAPPENED TO PATTERN 1 & PATTERN 2 TRADES?")
    print(f"  • Pattern 1 (10:30 HOD break) Triggered: {len(p1_trades)} trades")
    print(f"    - Base Exit Gross (Hold till 14:45): Rs {((p1_trades['en'] - p1_trades['ex_aud']) * p1_trades['qty']).sum()/1e5:.2f} L")
    print(f"    - Cut Exit Gross (Cut at 10:30):      Rs {((p1_trades['en'] - p1_trades['ex_pat']) * p1_trades['qty']).sum()/1e5:.2f} L")
    print(f"    - Delta Saved by Pattern 1:          Rs {(((p1_trades['en'] - p1_trades['ex_pat']) * p1_trades['qty']).sum() - ((p1_trades['en'] - p1_trades['ex_aud']) * p1_trades['qty']).sum())/1e5:+.2f} L")
    
    print(f"\n  • Pattern 2 (Severe Midday Loss) Triggered: {len(p2_trades)} trades")
    print(f"    - Base Exit Gross (Hold till 14:45): Rs {((p2_trades['en'] - p2_trades['ex_aud']) * p2_trades['qty']).sum()/1e5:.2f} L")
    print(f"    - Cut Exit Gross (Cut Midday):        Rs {((p2_trades['en'] - p2_trades['ex_pat']) * p2_trades['qty']).sum()/1e5:.2f} L")
    print(f"    - Delta Saved by Pattern 2:          Rs {(((p2_trades['en'] - p2_trades['ex_pat']) * p2_trades['qty']).sum() - ((p2_trades['en'] - p2_trades['ex_aud']) * p2_trades['qty']).sum())/1e5:+.2f} L")

if __name__ == '__main__':
    main()
