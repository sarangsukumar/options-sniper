#!/usr/bin/env python3
"""
generate_kotak_mis_reference_sheet.py
=====================================
Generates a comprehensive reference sheet CSV for all traded F&O stocks containing:
1. Stock Name
2. Current Market Price (CMP / Latest Price)
3. Historical/Active Lot Size (1 Lot)
4. Net Value of One Lot (Total Contract / Trade Value = CMP * Lot Size)
5. Upfront Margin Required for MIS (5.0x leverage / 20% margin as per Kotak / SEBI)
6. Leverage & Margin Percentage (5x / 20%)
7. Exact Itemized Kotak Neo Charges & Commission for 1 Lot:
   - Brokerage (Rs 40 round trip)
   - STT (0.025% on sell)
   - Exchange Txn Fee (0.00297% on round-trip turnover)
   - SEBI Turnover Fee (Rs 10 / Crore)
   - Stamp Duty (0.003% on buy)
   - GST (18% on Brokerage + Exchange + SEBI)
   - Total Commission & Taxes
8. Net Break-Even Points Needed to Cover Commission
"""

import os
import pymysql
import pandas as pd
import numpy as np
from datetime import datetime

# Import Kotak MIS calculator
from kotak_mis_calculator import calculate_kotak_margin, calculate_kotak_charges

LOTS_FILE = '/home/ubuntu/sarang_2026_shortsell_algos/02_Best_Longer_Window_0942_1445/data/historical_lotsize_new.csv'
OUT_CSV   = '/home/ubuntu/sarang_2026_shortsell_algos/kotak_mis_stock_margin_and_commission_reference.csv'

def main():
    print("=" * 80)
    print("📊 GENERATING KOTAK NEO MIS STOCK MARGIN & COMMISSION REFERENCE SHEET")
    print("=" * 80)

    # 1. Load lot size file
    df_lots = pd.read_csv(LOTS_FILE)
    df_lots['clean_stock'] = df_lots['stockname'].astype(str).str.strip().str.upper()
    df_lots['exp_dt'] = pd.to_datetime(df_lots['expdate'], format='%d/%m/%Y', errors='coerce')
    
    # Get active lot size (latest expiry date available per stock)
    lot_map = {}
    for s, grp in df_lots.groupby('clean_stock'):
        grp_sorted = grp.sort_values('exp_dt', ascending=False)
        lot_map[s] = int(grp_sorted.iloc[0]['lotsize'])
        
    print(f"Loaded active lot sizes for {len(lot_map)} stocks.")

    # 2. Fetch latest prices from MySQL markets database
    conn = pymysql.connect(host='localhost', user='root', password='root', database='markets', cursorclass=pymysql.cursors.DictCursor)
    
    with conn.cursor() as cur:
        # Prefer Futures (scrapdata_F1) latest price, fallback to Cash (scrapdata)
        cur.execute("""
            SELECT TRIM(BOTH '"' FROM TRIM(stockname)) as stockname, 
                   SUBSTRING_INDEX(GROUP_CONCAT(price ORDER BY time DESC), ',', 1) as latest_price
            FROM scrapdata_F1 
            WHERE date >= '2026-09-11'
            GROUP BY stockname
        """)
        f1_rows = cur.fetchall()
        
        cur.execute("""
            SELECT TRIM(BOTH '"' FROM TRIM(stockname)) as stockname, 
                   SUBSTRING_INDEX(GROUP_CONCAT(price ORDER BY time DESC), ',', 1) as latest_price
            FROM scrapdata 
            WHERE date >= '2026-09-11'
            GROUP BY stockname
        """)
        eq_rows = cur.fetchall()
    conn.close()

    price_map = {}
    for r in eq_rows:
        s = str(r['stockname']).strip().upper()
        if r['latest_price']:
            price_map[s] = float(r['latest_price'])
            
    for r in f1_rows:
        s = str(r['stockname']).strip().upper()
        if r['latest_price']:
            price_map[s] = float(r['latest_price'])

    print(f"Loaded latest prices for {len(price_map)} stocks from database.")

    # 3. Build reference sheet
    # Filter out index contracts
    exclude = {'NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'NIFTYNXT50'}
    
    all_stocks = sorted(set(list(lot_map.keys()) + list(price_map.keys())))
    
    rows = []
    for s in all_stocks:
        if s in exclude:
            continue
        
        cmp = price_map.get(s)
        lot = lot_map.get(s)
        
        if cmp is None or lot is None or cmp <= 0 or lot <= 0:
            continue
            
        cmp = round(cmp, 2)
        
        # Net value of 1 lot
        net_lot_val = round(cmp * lot, 2)
        
        # Margin required (Kotak MIS: 5x leverage / 20%)
        margin_info = calculate_kotak_margin(cmp, lot, leverage=5.0)
        upfront_margin = margin_info['margin_required']
        
        # Calculate exact Kotak charges for 1 round-trip lot (assuming entry @ CMP, exit @ CMP)
        charges = calculate_kotak_charges(cmp, cmp, lot, is_short=True)
        
        tot_comm = charges['total_charges']
        be_points = round(tot_comm / lot, 2) # Points needed to break even on charges
        
        rows.append({
            'stockname': s,
            'cmp_price': cmp,
            'lot_size': lot,
            'net_value_1_lot': net_lot_val,
            'upfront_margin_mis': upfront_margin,
            'leverage': '5x (20%)',
            'kotak_brokerage': charges['brokerage'],
            'stt_tax': charges['stt'],
            'exchange_txn_charge': charges['exchange_charges'],
            'sebi_fee': charges['sebi_fees'],
            'stamp_duty': charges['stamp_duty'],
            'gst_tax': charges['gst'],
            'total_commission_and_charges': tot_comm,
            'breakeven_points_per_share': be_points,
            'breakeven_pct': round((be_points / cmp) * 100, 3)
        })

    ref_df = pd.DataFrame(rows).sort_values('stockname').reset_index(drop=True)
    ref_df.to_csv(OUT_CSV, index=False)
    
    # Also copy to repo folder for git tracking
    repo_copy = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/production_ready_two_shortsell_algos/kotak_mis_stock_margin_and_commission_reference.csv'
    ref_df.to_csv(repo_copy, index=False)
    
    print("\n" + "=" * 80)
    print(f"🎉 REFERENCE SHEET CREATED SUCCESSFULLY! ({len(ref_df)} active stocks)")
    print(f"Saved to:\n  1. {OUT_CSV}\n  2. {repo_copy}")
    print("=" * 80)
    
    # Display sample top 10 rows
    print("\nSample Preview (First 15 Stocks):")
    sample_cols = ['stockname', 'cmp_price', 'lot_size', 'net_value_1_lot', 'upfront_margin_mis', 'total_commission_and_charges', 'breakeven_points_per_share']
    print(ref_df[sample_cols].head(15).to_string(index=False))
    
    # Margin distribution summary
    print("\n" + "-" * 80)
    print("📊 MARGIN REQUIREMENT DISTRIBUTION (1 LOT):")
    print(f"• Cheapest Margin Stock : {ref_df.loc[ref_df['upfront_margin_mis'].idxmin()]['stockname']} @ Rs {ref_df['upfront_margin_mis'].min():,.2f}")
    print(f"• Highest Margin Stock  : {ref_df.loc[ref_df['upfront_margin_mis'].idxmax()]['stockname']} @ Rs {ref_df['upfront_margin_mis'].max():,.2f}")
    print(f"• Median Margin / Lot   : Rs {ref_df['upfront_margin_mis'].median():,.2f}")
    print(f"• Mean Margin / Lot     : Rs {ref_df['upfront_margin_mis'].mean():,.2f}")
    print(f"• Stocks < Rs 1.875L Margin (Fits 4 stocks in Rs 7.5L) : {(ref_df['upfront_margin_mis'] <= 187500).sum()} / {len(ref_df)} ({(ref_df['upfront_margin_mis'] <= 187500).mean()*100:.1f}%)")
    print("-" * 80)

if __name__ == '__main__':
    main()
