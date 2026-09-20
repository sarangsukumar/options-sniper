#!/usr/bin/env python3
"""
self_heal_production_data.py
================================================================================
Production Self-Healing and File Synchronization Engine.
Checks the integrity and completeness of the CSV data files against the persistent 
MySQL database, automatically repairing and backfilling any missing dates.
================================================================================
"""

import os
import sys
import subprocess
import pandas as pd
import mysql.connector
from datetime import datetime

print("="*80)
print("🛡️  DAILY PRODUCTION SIMULATION - AUTOMATIC SELF-HEALING ENGINE")
print("="*80)

# Paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PNL_FILE = os.path.join(BASE_DIR, "data", "markets_pnl0325.csv")
GAP_FILE = os.path.join(BASE_DIR, "data", "yahoo_finance_all_stocks_2015_2026_gap_features.csv")
INTRADAY_FILE = os.path.join(BASE_DIR, "data", "f11_intraday_features_all.csv")

# MySQL Configuration
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': 'root',
    'database': 'markets'
}

def get_mysql_connection():
    return mysql.connector.connect(**DB_CONFIG)

def log(msg, symbol="✔"):
    print(f"[{symbol}] {msg}")

# ──────────────────────────────────────────────────────────────────────────────
# 1. SELF-HEAL PNL LEDGER
# ──────────────────────────────────────────────────────────────────────────────
def self_heal_pnl():
    log("Checking P&L Ledger completeness against MySQL...", "⏳")
    if not os.path.exists(PNL_FILE):
        log(f"Warning: Master P&L file {PNL_FILE} not found! Skipping healing.", "⚠️")
        return

    try:
        # Load local CSV dates
        df_pnl = pd.read_csv(PNL_FILE, dtype=str)
        local_dates = set(pd.to_datetime(df_pnl['simulationdate'], format='mixed', dayfirst=True).dt.strftime('%Y-%m-%d').unique())
        
        # Query MySQL dates
        conn = get_mysql_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT simulationdate FROM markets_pnl")
        mysql_dates = set([row[0] for row in cursor.fetchall() if row[0]])
        cursor.close()
        conn.close()

        missing_dates = mysql_dates - local_dates
        if missing_dates:
            log(f"Found {len(missing_dates)} missing dates in P&L ledger CSV: {sorted(list(missing_dates))}", "⚠️")
            conn = get_mysql_connection()
            for m_date in sorted(list(missing_dates)):
                log(f"Recovering trades for {m_date} from MySQL...", "📥")
                # Query MySQL for rows on this date
                query = "SELECT simulationdate, stockname, buy_price, sell_price, quantity, commission_paid, pnl, sell_exec_type, completion_day, expiry_capping_details FROM markets_pnl WHERE simulationdate = %s"
                df_mysql_rows = pd.read_sql(query, conn, params=[m_date])
                
                if not df_mysql_rows.empty:
                    # Convert date to DD-MM-YYYY format for CSV matching
                    df_mysql_rows['simulationdate'] = pd.to_datetime(df_mysql_rows['simulationdate']).dt.strftime('%d-%m-%Y')
                    
                    # Prevent duplicates and concat
                    dates_to_remove = df_mysql_rows['simulationdate'].unique()
                    df_pnl_clean = df_pnl[~df_pnl['simulationdate'].isin(dates_to_remove)]
                    df_pnl = pd.concat([df_pnl_clean, df_mysql_rows], ignore_index=True)
            
            # Save final healed file
            df_pnl.to_csv(PNL_FILE, index=False)
            log(f"Successfully self-healed local P&L ledger! Total rows: {len(df_pnl)}", "✅")
            conn.close()
        else:
            log("P&L Ledger CSV is completely in sync with MySQL.", "✅")
    except Exception as e:
        log(f"Error self-healing P&L ledger: {e}", "❌")

# ──────────────────────────────────────────────────────────────────────────────
# 2. SELF-HEAL FEATURE FILES (GAP & INTRADAY)
# ──────────────────────────────────────────────────────────────────────────────
def self_heal_features():
    log("Checking Intraday & Gap Feature files for completeness...", "⏳")
    
    try:
        # Get last 10 trading dates from scrapdata in MySQL (actual trading days)
        conn = get_mysql_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT date FROM scrapdata ORDER BY date DESC LIMIT 10")
        trading_dates = sorted([row[0].strftime('%Y-%m-%d') for row in cursor.fetchall() if row[0]])
        cursor.close()
        conn.close()

        if not trading_dates:
            log("No trading dates detected in MySQL scrapdata! Features healing skipped.", "⚠️")
            return

        # A. Heal Yahoo Gap Features
        if os.path.exists(GAP_FILE):
            df_gap = pd.read_csv(GAP_FILE, dtype=str)
            local_gap_dates = set(pd.to_datetime(df_gap['Date'], format='mixed', dayfirst=True).dt.strftime('%Y-%m-%d').unique())
            missing_gap_dates = [d for d in trading_dates if d not in local_gap_dates]
            
            if missing_gap_dates:
                log(f"Found {len(missing_gap_dates)} missing dates in Gap Features CSV: {missing_gap_dates}", "⚠️")
                for m_date in missing_gap_dates:
                    log(f"Triggering morning gap downloader for {m_date}...", "🔄")
                    subprocess.run(["node", "pipeline/update_today_gaps_morning.js", m_date], cwd=BASE_DIR, check=True)
                log("Gap Features file self-healed successfully!", "✅")
            else:
                log("Gap features file has zero missing recent dates.", "✅")
        else:
            log(f"Warning: Gap Features file {GAP_FILE} not found!", "⚠️")

        # B. Heal Intraday Features
        if os.path.exists(INTRADAY_FILE):
            df_intra = pd.read_csv(INTRADAY_FILE, dtype=str)
            local_intra_dates = set(pd.to_datetime(df_intra['Date'], format='mixed', dayfirst=True).dt.strftime('%Y-%m-%d').unique())
            missing_intra_dates = [d for d in trading_dates if d not in local_intra_dates]
            
            if missing_intra_dates:
                log(f"Found {len(missing_intra_dates)} missing dates in Intraday Features CSV: {missing_intra_dates}", "⚠️")
                for m_date in missing_intra_dates:
                    log(f"Triggering intraday features update generator for {m_date}...", "🔄")
                    subprocess.run(["python3", "pipeline/compute_f11_intraday_features_update.py", m_date], cwd=BASE_DIR, check=True)
                log("Intraday Features file self-healed successfully!", "✅")
            else:
                log("Intraday features file has zero missing recent dates.", "✅")
        else:
            log(f"Warning: Intraday Features file {INTRADAY_FILE} not found!", "⚠️")

    except Exception as e:
        log(f"Error self-healing feature files: {e}", "❌")

# ──────────────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    self_heal_pnl()
    self_heal_features()
    print("="*80)
    print("🛡️  SELF-HEALING AND SYNCHRONIZATION RUN COMPLETE!")
    print("="*80)
