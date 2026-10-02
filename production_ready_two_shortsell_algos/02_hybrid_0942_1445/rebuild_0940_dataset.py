import pandas as pd
import pymysql
import os
import sys

from live_0940_hybrid_pipeline import fetch_live_data, compute_features, get_db_connection

def build_1_month_dataset():
    conn = get_db_connection()
    with conn.cursor() as cur:
        # Get dates for July 2026 (the last month in the historical dataset)
        cur.execute("SELECT DISTINCT date FROM scrapdata WHERE date >= '2026-07-01' AND date <= '2026-07-28' ORDER BY date ASC")
        dates = [str(r['date']) for r in cur.fetchall()]
    conn.close()

    print(f"Testing dataset builder on {len(dates)} dates in July 2026...")
    
    all_features = []
    
    for i in range(1, len(dates)):
        target_date = dates[i]
        prev_date = dates[i-1]
        print(f"Processing {target_date}...")
        
        # We don't have cl_stocks for the historical dates easily without recreating the logic,
        # but the is_in_cl feature isn't in PURE_DB_FEATURES anyway, it's just used to filter.
        cl_stocks = [] 
        
        df_prev_ticks, df_0907, df_morn_ticks, macro = fetch_live_data(target_date, prev_date)
        df_features = compute_features(df_prev_ticks, df_0907, df_morn_ticks, target_date, cl_stocks, macro)
        
        all_features.append(df_features)

    final_df = pd.concat(all_features, ignore_index=True)
    out_file = 'test_0940_rebuild_july.csv'
    final_df.to_csv(out_file, index=False)
    print(f"Saved {len(final_df)} rows to {out_file}")

if __name__ == "__main__":
    build_1_month_dataset()
