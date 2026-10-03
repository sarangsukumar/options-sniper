#!/usr/bin/env python3
"""
simulate_realistic_7p5L_kotak.py
================================
Simulates Model 1 and Model 2 under realistic production conditions:
1. Daily Starting Capital: Exactly Rs 7,50,000 (7.5 Lakhs) cash in hand every morning.
2. Sizing: Historical dynamic lot sizes.
3. Margin Calculator: Exact Kotak Securities / Kotak Neo MIS rules (5.0x leverage / 20% margin).
4. Capital Constraint: If capital is insufficient to take all 4 orders, skips the later trade(s).
5. Exact Kotak Charges: Real brokerage (Rs 20/order) + STT (0.025% sell) + NSE Txn charges + SEBI + Stamp Duty + 18% GST.
6. Exports full audited CSVs for Model 1, Model 2, and the Master Combined Portfolio.
"""

import os, sys, time, warnings
import pandas as pd
import numpy as np

# Import our exact Kotak calculator
from kotak_mis_calculator import calculate_kotak_margin, calculate_kotak_charges

BASE_DIR = '/home/ubuntu/sarang_2026_shortsell_algos'
M1_FILE  = os.path.join(BASE_DIR, '01_Best_Shorter_Window_0920_0940', 'audited_0920_0940_trades.csv')
M2_FILE  = os.path.join(BASE_DIR, '02_Best_Longer_Window_0942_1445', 'audited_0940_hybrid_trades.csv')

M1_OUT   = os.path.join(BASE_DIR, '01_Best_Shorter_Window_0920_0940', 'audited_0920_0940_realistic_7p5L_kotak.csv')
M2_OUT   = os.path.join(BASE_DIR, '02_Best_Longer_Window_0942_1445', 'audited_0940_hybrid_realistic_7p5L_kotak.csv')
MAST_OUT = os.path.join(BASE_DIR, 'master_realistic_7p5L_kotak_simulation.csv')

CAPITAL_LIMIT = 750000.0  # Rs 7.5 Lakhs cash
LEVERAGE      = 5.0       # 5x leverage (20% margin for MIS on F&O stocks)

def simulate_model_1():
    print("=" * 85)
    print("🚀 1. SIMULATING MODEL 1 (09:20 - 09:40 SCALP) WITH Rs 7.5L MARGIN & KOTAK CHARGES")
    print("=" * 85)
    
    df1 = pd.read_csv(M1_FILE)
    df1['rank'] = df1.groupby('short_date')['prob'].rank(ascending=False, method='first')
    df1 = df1.sort_values(['short_date', 'rank']).reset_index(drop=True)
    
    records = []
    
    for dt, grp in df1.groupby('short_date'):
        avail_cash = CAPITAL_LIMIT
        
        for _, row in grp.iterrows():
            stk = row['clean_stock']
            qty = int(row['dynamic_lotsize'])
            ep  = float(row['p_0921'])
            xp  = float(row['p_0941'])
            rk  = int(row['rank'])
            yr  = int(row['year'])
            
            # Margin check
            margin_info = calculate_kotak_margin(ep, qty, leverage=LEVERAGE)
            req_margin  = margin_info['margin_required']
            trade_val   = margin_info['trade_value']
            
            if req_margin <= avail_cash:
                status = 'EXECUTED'
                margin_used = req_margin
                avail_cash -= req_margin
                gross_pnl = round((ep - xp) * qty, 2)
                charges_info = calculate_kotak_charges(ep, xp, qty, is_short=True)
                charges = charges_info['total_charges']
                net_pnl = round(gross_pnl - charges, 2)
                allocated_qty = qty
            else:
                status = 'SKIPPED_INSUFFICIENT_MARGIN'
                margin_used = 0.0
                gross_pnl = 0.0
                charges = 0.0
                net_pnl = 0.0
                allocated_qty = 0
                charges_info = {
                    'brokerage': 0.0, 'stt': 0.0, 'exchange_charges': 0.0,
                    'sebi_fees': 0.0, 'stamp_duty': 0.0, 'gst': 0.0, 'total_charges': 0.0
                }
                
            records.append({
                'strategy': 'Model_1_Scalp_0920_0940',
                'date': dt,
                'year': yr,
                'rank': rk,
                'stockname': stk,
                'entry_time': '09:21:00',
                'exit_time': '09:41:00',
                'entry_price': ep,
                'exit_price': xp,
                'requested_qty': qty,
                'allocated_qty': allocated_qty,
                'trade_value': trade_val,
                'margin_required': req_margin,
                'margin_used': margin_used,
                'cash_remaining': round(avail_cash, 2),
                'execution_status': status,
                'gross_pnl': gross_pnl,
                'kotak_brokerage': charges_info['brokerage'],
                'kotak_stt': charges_info['stt'],
                'kotak_exchange_txn': charges_info['exchange_charges'],
                'kotak_sebi_fee': charges_info['sebi_fees'],
                'kotak_stamp_duty': charges_info['stamp_duty'],
                'kotak_gst': charges_info['gst'],
                'total_kotak_charges': charges,
                'net_pnl': net_pnl,
                'win': 1 if net_pnl > 0 else 0
            })
            
    res_df = pd.DataFrame(records)
    res_df.to_csv(M1_OUT, index=False)
    print(f"✔ Model 1 Realistic trade ledger saved to:\n  {M1_OUT}")
    return res_df

def simulate_model_2():
    print("\n" + "=" * 85)
    print("🚀 2. SIMULATING MODEL 2 (09:42 - 14:45 HYBRID) WITH Rs 7.5L MARGIN & KOTAK CHARGES")
    print("=" * 85)
    
    df2 = pd.read_csv(M2_FILE)
    df2 = df2.sort_values(['date', 'rank']).reset_index(drop=True)
    
    records = []
    
    for dt, grp in df2.groupby('date'):
        avail_cash = CAPITAL_LIMIT
        
        for _, row in grp.iterrows():
            stk = row['stockname']
            lot_size = int(row['lotsize'])
            requested_lots = int(row['lots_to_trade'])
            ep = float(row['entry_price'])
            xp = float(row['exit_price'])
            pts = float(row['points'])
            rk = int(row['rank'])
            yr = int(row['year']) if pd.notna(row['year']) else int(str(dt)[:4])
            sig_type = row['signal_type']
            exit_reason = row['exit_reason']
            
            # Check margin for requested lots down to 1
            allocated_lots = 0
            for l in range(requested_lots, 0, -1):
                req = (ep * lot_size * l) / LEVERAGE
                if req <= avail_cash:
                    allocated_lots = l
                    break
                    
            full_req_margin = round((ep * lot_size * requested_lots) / LEVERAGE, 2)
            
            if allocated_lots > 0:
                allocated_qty = lot_size * allocated_lots
                margin_used = round((ep * allocated_qty) / LEVERAGE, 2)
                avail_cash -= margin_used
                gross_pnl = round(pts * allocated_qty, 2)
                charges_info = calculate_kotak_charges(ep, xp, allocated_qty, is_short=True)
                charges = charges_info['total_charges']
                net_pnl = round(gross_pnl - charges, 2)
                status = 'EXECUTED' if allocated_lots == requested_lots else f'EXECUTED_PARTIAL_{allocated_lots}_OF_{requested_lots}_LOTS'
            else:
                allocated_qty = 0
                margin_used = 0.0
                gross_pnl = 0.0
                charges = 0.0
                net_pnl = 0.0
                status = 'SKIPPED_INSUFFICIENT_MARGIN'
                charges_info = {
                    'brokerage': 0.0, 'stt': 0.0, 'exchange_charges': 0.0,
                    'sebi_fees': 0.0, 'stamp_duty': 0.0, 'gst': 0.0, 'total_charges': 0.0
                }
                
            records.append({
                'strategy': 'Model_2_Hybrid_0942_1445',
                'date': dt,
                'year': yr,
                'rank': rk,
                'stockname': stk,
                'signal_type': sig_type,
                'exit_reason': exit_reason,
                'entry_time': '09:42:00',
                'exit_time': row['exit_time'],
                'entry_price': ep,
                'exit_price': xp,
                'single_lotsize': lot_size,
                'requested_lots': requested_lots,
                'allocated_lots': allocated_lots,
                'requested_qty': lot_size * requested_lots,
                'allocated_qty': allocated_qty,
                'trade_value': round(ep * allocated_qty, 2),
                'margin_required_full': full_req_margin,
                'margin_used': margin_used,
                'cash_remaining': round(avail_cash, 2),
                'execution_status': status,
                'points': pts,
                'gross_pnl': gross_pnl,
                'kotak_brokerage': charges_info['brokerage'],
                'kotak_stt': charges_info['stt'],
                'kotak_exchange_txn': charges_info['exchange_charges'],
                'kotak_sebi_fee': charges_info['sebi_fees'],
                'kotak_stamp_duty': charges_info['stamp_duty'],
                'kotak_gst': charges_info['gst'],
                'total_kotak_charges': charges,
                'net_pnl': net_pnl,
                'win': 1 if net_pnl > 0 else 0
            })
            
    res_df = pd.DataFrame(records)
    res_df.to_csv(M2_OUT, index=False)
    print(f"✔ Model 2 Realistic trade ledger saved to:\n  {M2_OUT}")
    return res_df

def print_detailed_metrics(df, name):
    if 'allocated_qty' in df.columns:
        ex = df[df['allocated_qty'] > 0].copy()
        sk = df[df['allocated_qty'] == 0].copy()
    else:
        ex = df.copy()
        sk = pd.DataFrame()
    
    tot_candidates = len(df)
    tot_executed   = len(ex)
    tot_skipped    = len(sk)
    
    tot_gross   = ex['gross_pnl'].sum()
    tot_charges = ex['total_kotak_charges'].sum()
    tot_net     = ex['net_pnl'].sum()
    
    wr = (ex['net_pnl'] > 0).mean() * 100 if tot_executed > 0 else 0.0
    
    daily = ex.groupby('date')['net_pnl'].sum().reset_index()
    daily['cum_pnl'] = daily['net_pnl'].cumsum()
    daily['peak']    = daily['cum_pnl'].cummax()
    daily['dd']      = daily['cum_pnl'] - daily['peak']
    max_dd = daily['dd'].min() if len(daily) > 0 else 0.0
    day_wr = (daily['net_pnl'] > 0).mean() * 100 if len(daily) > 0 else 0.0
    
    std = daily['net_pnl'].std()
    sharpe = (daily['net_pnl'].mean() / std) * np.sqrt(252) if std > 0 else 0.0
    
    pos = ex[ex['net_pnl'] > 0]['net_pnl']
    neg = ex[ex['net_pnl'] < 0]['net_pnl']
    pf = abs(pos.sum() / neg.sum()) if len(neg) > 0 and neg.sum() != 0 else np.nan
    
    roi_on_capital = (tot_net / CAPITAL_LIMIT) * 100
    
    print("\n" + "=" * 85)
    print(f"📊 PERFORMANCE AUDIT: {name}")
    print("=" * 85)
    print(f"Daily Capital Base         : Rs {CAPITAL_LIMIT/1e5:,.2f} Lakhs (Recycled Daily)")
    print(f"Total Trade Candidates     : {tot_candidates:,}")
    print(f"Trades Executed            : {tot_executed:,} ({tot_executed/tot_candidates*100:.1f}%)")
    print(f"Trades Skipped (Low Margin): {tot_skipped:,} ({tot_skipped/tot_candidates*100:.1f}%)")
    print("-" * 85)
    print(f"Gross PnL                  : +Rs {tot_gross/1e5:,.2f} Lakhs (+Rs {tot_gross/1e7:,.3f} Cr)")
    print(f"Kotak Charges & Taxes      : -Rs {tot_charges/1e5:,.2f} Lakhs (Avg: Rs {tot_charges/tot_executed:.2f}/trade)")
    print(f"Audited Net PnL            : +Rs {tot_net/1e5:,.2f} Lakhs (👑 +Rs {tot_net/1e7:,.3f} CRORE)")
    print(f"Return on Rs 7.5L Capital  : +{roi_on_capital:,.1f}% ({tot_net/CAPITAL_LIMIT:.1f}x Capital Multiplier)")
    print("-" * 85)
    print(f"Trade Win Rate             : {wr:.2f}%")
    print(f"Daily Win Rate             : {day_wr:.2f}%")
    print(f"Profit Factor              : {pf:.2f}")
    print(f"Sharpe Ratio               : {sharpe:.2f}")
    print(f"Max Portfolio Drawdown     : -Rs {abs(max_dd)/1e5:,.2f} Lakhs")
    print("=" * 85)
    
    # Year-by-Year
    print(f"{'Year':<6} | {'Trades':<8} | {'WR %':<8} | {'Gross PnL':<14} | {'Kotak Charges':<15} | {'Net PnL':<14} | {'PF':<6}")
    print("-" * 85)
    for yr, y_grp in ex.groupby('year'):
        y_w = (y_grp['net_pnl'] > 0).mean() * 100
        y_g = y_grp['gross_pnl'].sum() / 1e5
        y_c = y_grp['total_kotak_charges'].sum() / 1e5
        y_n = y_grp['net_pnl'].sum() / 1e5
        y_pos = y_grp[y_grp['net_pnl'] > 0]['net_pnl']
        y_neg = y_grp[y_grp['net_pnl'] < 0]['net_pnl']
        y_pf = abs(y_pos.sum() / y_neg.sum()) if len(y_neg) > 0 and y_neg.sum() != 0 else np.nan
        print(f"{yr:<6} | {len(y_grp):<8} | {y_w:<7.1f}% | +Rs {y_g:>7.2f} L | -Rs {y_c:>7.2f} L | +Rs {y_n:>7.2f} L | {y_pf:>5.2f}")
    print("=" * 85)

def main():
    t0 = time.time()
    
    df1_res = simulate_model_1()
    print_detailed_metrics(df1_res, "MODEL 1 (09:20 - 09:40 SCALP) @ Rs 7.5L CAPITAL")
    
    df2_res = simulate_model_2()
    print_detailed_metrics(df2_res, "MODEL 2 (09:42 - 14:45 HYBRID) @ Rs 7.5L CAPITAL")
    
    # Combined Master Simulation
    print("\n" + "=" * 85)
    print("👑 3. MASTER COMBINED DUAL-ENGINE PORTFOLIO (MODEL 1 + MODEL 2)")
    print("   Total Capital Invested: Exactly Rs 7,50,000 (100% Recycled from M1 to M2)")
    print("=" * 85)
    
    # Filter executed
    ex1 = df1_res[df1_res['allocated_qty'] > 0][['date', 'year', 'stockname', 'strategy', 'allocated_qty', 'gross_pnl', 'total_kotak_charges', 'net_pnl']].copy()
    ex2 = df2_res[df2_res['allocated_qty'] > 0][['date', 'year', 'stockname', 'strategy', 'allocated_qty', 'gross_pnl', 'total_kotak_charges', 'net_pnl']].copy()
    
    mast_ex = pd.concat([ex1, ex2]).sort_values(['date', 'strategy']).reset_index(drop=True)
    mast_ex.to_csv(MAST_OUT, index=False)
    print(f"✔ Master combined trade ledger saved to:\n  {MAST_OUT}")
    
    print_detailed_metrics(mast_ex, "MASTER COMBINED DUAL SHORT-SELL PORTFOLIO (Rs 7.5L CAPITAL)")
    
    print(f"\nElapsed time: {time.time()-t0:.2f} seconds")

if __name__ == '__main__':
    main()
