#!/usr/bin/env python3
"""
1_build_dataset_v6.py
---------------------
Rebuilds the ML dataset from scratch for the 100% Pure 09:42 AM Entry -> 14:45 PM Exit Model (Model v6).

Instant B-tree index lookup using exact DATETIME string matches in MySQL `scrapdata_F1`.

Outputs:
  /home/ubuntu/daily_prediction_sytem_Dynamic_threshold/v6_pure_0942_1445_scratch/data/short_sell_ml_dataset_v6.csv
"""

import os
import pandas as pd
import numpy as np
import pymysql

BASE_DIR = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/v6_pure_0942_1445_scratch'
DATA_DIR = os.path.join(BASE_DIR, 'data')
os.makedirs(DATA_DIR, exist_ok=True)

V5_BASE_FILE = '/home/ubuntu/v5_from_scratch/data/short_sell_ml_dataset_v5_scratch.csv'
OUT_FILE = os.path.join(DATA_DIR, 'short_sell_ml_dataset_v6.csv')

def main():
    print("===================================================================================")
    print("🚀 STEP 1: BUILDING MODEL v6 ML DATASET FROM SCRATCH (100% PURE scrapdata_F1 TICKS)")
    print("===================================================================================\n")

    print("1. Loading candidate base dataset...")
    if not os.path.exists(V5_BASE_FILE):
        raise FileNotFoundError(f"Base file {V5_BASE_FILE} missing!")

    df = pd.read_csv(V5_BASE_FILE, low_memory=False)
    df['date_str'] = pd.to_datetime(df['date_str'], format='mixed').dt.strftime('%Y-%m-%d')
    df['clean_stock'] = df['clean_stock'].astype(str).str.strip().str.upper()

    print("2. Instant B-tree index querying scrapdata_F1 via exact DATETIME strings...")
    conn = pymysql.connect(host='localhost', user='root', password='root', database='markets')
    cursor = conn.cursor()

    unique_dates = sorted(df['date_str'].unique())
    db_rows = []

    # Batch 100 dates = 200 exact time values per query
    batch_size = 100
    for i in range(0, len(unique_dates), batch_size):
        date_batch = unique_dates[i:i+batch_size]
        time_vals = []
        for d in date_batch:
            time_vals.append(f"{d} 09:42:00")
            time_vals.append(f"{d} 14:45:00")
        
        times_in = "', '".join(time_vals)

        q = f"""
        SELECT 
            DATE(time) AS date_str,
            stockname AS clean_stock,
            MAX(CASE WHEN TIME(time) = '09:42:00' THEN CAST(price AS DECIMAL(10,2)) END) AS e_p,
            MAX(CASE WHEN TIME(time) = '14:45:00' THEN CAST(price AS DECIMAL(10,2)) END) AS x_p
        FROM scrapdata_F1
        WHERE time IN ('{times_in}')
          AND is_future = 'F1'
          AND isvalid = 'TRUE'
        GROUP BY DATE(time), stockname;
        """
        cursor.execute(q)
        res = cursor.fetchall()
        for row in res:
            if row[2] is not None and row[3] is not None:
                db_rows.append({
                    'date_str': str(row[0]),
                    'clean_stock': str(row[1]).strip().upper(),
                    'db_entry_0942_f1': float(row[2]),
                    'db_exit_1445_f1': float(row[3])
                })

    conn.close()

    df_db_ticks = pd.DataFrame(db_rows)
    print(f"   • Successfully fetched exact 09:42 and 14:45 ticks for {len(df_db_ticks):,} rows!")

    # Drop old db_entry or db_exit columns if present
    for col in ['db_entry_0942_f1', 'db_exit_1445_f1']:
        if col in df.columns:
            df.drop(columns=[col], inplace=True)

    df = df.merge(df_db_ticks, on=['date_str', 'clean_stock'], how='left')

    print("3. Computing 100% pure target labels and morning features...")
    # Drop rows if DB ticks missing for exact 09:42 or 14:45 (ZERO FALLBACK!)
    df = df.dropna(subset=['db_entry_0942_f1', 'db_exit_1445_f1']).copy()
    df['db_entry_0942_f1'] = df['db_entry_0942_f1'].astype(float)
    df['db_exit_1445_f1'] = df['db_exit_1445_f1'].astype(float)

    # Calculate 100% PURE Short Return from scrapdata_F1
    df['short_pct_return'] = ((df['db_entry_0942_f1'] - df['db_exit_1445_f1']) / df['db_entry_0942_f1']) * 100.0
    df['target'] = (df['short_pct_return'] > 0).astype(int)

    # Ensure NO Volume_Change_Pct lookahead
    if 'Volume_Change_Pct' in df.columns:
        df.drop(columns=['Volume_Change_Pct'], inplace=True)

    print("4. Computing Positive Arc features (09:07 -> 09:40 Arc Shape)...")
    for col in ['rejection_wick', 'gap_fade_0907_to_940_pct', 'morn_range_pct']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)

    df['positive_arc_score'] = df['rejection_wick'] / (1.0 + df['gap_fade_0907_to_940_pct'].abs())
    df['positive_arc_ratio'] = (df['morn_range_pct'] - df['gap_fade_0907_to_940_pct'].abs()) / (1.0 + df['gap_fade_0907_to_940_pct'].abs())

    print("5. Computing Days To Expiry (DTE) from master_expiry_dates.csv...")
    exp_csv = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/config/master_expiry_dates.csv'
    if os.path.exists(exp_csv):
        df_exp = pd.read_csv(exp_csv)
        exp_dates = sorted(pd.to_datetime(df_exp['master_expiry_date']).tolist())
        df['dt_tmp'] = pd.to_datetime(df['date_str'])
        
        def get_dte_val(td):
            for e in exp_dates:
                if e >= td:
                    return (e - td).days
            return 0
            
        df['dte'] = df['dt_tmp'].apply(get_dte_val)
        df.drop(columns=['dt_tmp'], inplace=True)
    else:
        df['dte'] = 15.0

    print(f"6. Saving Model v6 dataset to: {OUT_FILE}...")
    df.to_csv(OUT_FILE, index=False)
    print(f"✅ Step 1 complete! Saved dataset v6 with {len(df):,} valid 100% pure scrapdata_F1 rows.")

if __name__ == '__main__':
    main()
