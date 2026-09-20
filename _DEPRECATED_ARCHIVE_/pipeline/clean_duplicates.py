import pandas as pd
import os
import shutil

def clean_file(filepath, date_col, stock_col, date_format_fn=None):
    if not os.path.exists(filepath):
        print(f"File not found: {filepath}")
        return
    
    print(f"\n--- Cleaning File: {os.path.basename(filepath)} ---")
    
    # Create a safe backup before cleaning
    backup_path = filepath + ".bak_before_dedup"
    shutil.copy2(filepath, backup_path)
    print(f"Created secure backup at: {backup_path}")
    
    # Load data
    df = pd.read_csv(filepath, dtype=str)
    initial_rows = len(df)
    
    # Standardize columns for duplicate check
    df_check = df.copy()
    df_check[stock_col] = df_check[stock_col].str.strip().str.upper()
    df_check[date_col] = df_check[date_col].str.strip()
    
    # Drop duplicates keeping the first occurrence
    df_cleaned = df.loc[df_check.drop_duplicates(subset=[date_col, stock_col], keep='first').index].copy()
    final_rows = len(df_cleaned)
    removed_count = initial_rows - final_rows
    
    if removed_count > 0:
        # Save back to CSV
        df_cleaned.to_csv(filepath, index=False)
        print(f"✔ Successfully removed {removed_count} duplicate rows! Rows reduced from {initial_rows} to {final_rows}.")
    else:
        print(f"✔ No duplicate rows found in file. Row count remains steady at {initial_rows}.")

if __name__ == "__main__":
    base_dir = "/home/ubuntu/daily_prediction_sytem_Dynamic_threshold"
    
    # 1. Clean markets_pnl0325.csv
    pnl_path = os.path.join(base_dir, "data", "markets_pnl0325.csv")
    clean_file(pnl_path, "simulationdate", "stockname")
    
    # 2. Clean f11_intraday_features_all.csv
    intraday_path = os.path.join(base_dir, "data", "f11_intraday_features_all.csv")
    clean_file(intraday_path, "Date", "Stock")
    
    # 3. Clean yahoo_finance_all_stocks_2015_2026_gap_features.csv
    gap_path = os.path.join(base_dir, "data", "yahoo_finance_all_stocks_2015_2026_gap_features.csv")
    clean_file(gap_path, "Date", "Stock")
