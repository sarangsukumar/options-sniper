#!/usr/bin/env python3
"""
merge_actuals.py
================================================================================
Daily Post-Trade Merger — Sniper v3.0 Pipeline Step 0
================================================================================
Runs BEFORE predict_today.py every morning. Automatically:

  1. Finds yesterday's simulation results (output/simulation_results/
     simulation_results_YYYYMMDD_*/markets_pnl_predicted.csv)
  2. Patches the ACTUAL non-zero PnL into data/markets_pnl0325.csv
     (replacing the placeholder 0.0 rows that the simulation wrote)
  3. Appends / updates output/trades_dynamic_threshold.csv with the real
     actual_pnl values so run_master_backtest.py stays accurate

Run via:
    python3 pipeline/merge_actuals.py

Or called automatically from run_todays_prediction_pipeline.sh.
================================================================================
"""

import os
import sys
import glob
import pandas as pd
from datetime import datetime, timedelta

# ── Paths ──────────────────────────────────────────────────────────────────────
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
BASE_DIR    = os.path.dirname(SCRIPT_DIR)
PNL_FILE    = os.path.join(BASE_DIR, "data",   "markets_pnl0325.csv")
TRACKER     = os.path.join(BASE_DIR, "output", "trades_dynamic_threshold.csv")
SIM_RESULTS = os.path.join(BASE_DIR, "output", "simulation_results")

def log(msg, sym="✔"):
    print(f"[merge_actuals] {sym} {msg}")

# ── Helper: find the most-recent markets_pnl_predicted.csv for a given date ───
def find_sim_file_for_date(target_date: datetime) -> str | None:
    """
    Searches output/simulation_results/ for the markets_pnl_predicted.csv
    that contains actual trades for target_date.

    The simulation folder is named by the RUN date (which may be target_date
    itself OR target_date+1 if the simulation ran next morning).
    We search all folders within ±2 days and pick the one whose CSV contains
    rows for target_date.
    """
    candidates = []
    for delta in range(-1, 4):        # look from day-1 to day+3 to be safe
        run_date   = target_date + timedelta(days=delta)
        pattern    = os.path.join(
            SIM_RESULTS,
            f"simulation_results_{run_date.strftime('%Y%m%d')}_*",
            "markets_pnl_predicted.csv"
        )
        candidates.extend(glob.glob(pattern))

    target_str = target_date.strftime('%Y-%m-%d')
    for path in sorted(candidates, reverse=True):   # newest first
        try:
            df = pd.read_csv(path)
            if df.empty:
                continue
            df['_dt'] = pd.to_datetime(df['simulationdate'], format='mixed',
                                       dayfirst=True, errors='coerce')
            if (df['_dt'].dt.strftime('%Y-%m-%d') == target_str).any():
                return path
        except Exception:
            continue
    return None

# ── Step 1: Find yesterday's simulation results ────────────────────────────────
def get_yesterday() -> datetime:
    """Return most-recent trading day (skip weekends)."""
    today = datetime.now().date()
    delta = 1
    while True:
        candidate = datetime.combine(today - timedelta(days=delta),
                                     datetime.min.time())
        if candidate.weekday() < 5:   # Mon–Fri only
            return candidate
        delta += 1

def load_sim_results(target_date: datetime) -> pd.DataFrame:
    sim_path = find_sim_file_for_date(target_date)
    if sim_path is None:
        log(f"No simulation results found for {target_date.date()}", "⚠️")
        return pd.DataFrame()
    log(f"Found simulation file: {os.path.relpath(sim_path, BASE_DIR)}")
    df = pd.read_csv(sim_path)
    if df.empty:
        log(f"Simulation file is empty — no trades to merge", "⚠️")
        return pd.DataFrame()
    # Keep only rows with a real PnL (sell was executed)
    df['pnl'] = pd.to_numeric(df['pnl'], errors='coerce')
    df = df.dropna(subset=['pnl'])
    df = df[df['pnl'] != 0.0]
    log(f"Loaded {len(df)} executed trade(s) for {target_date.date()}")
    for _, r in df.iterrows():
        log(f"  {r['stockname']:<14} Buy: ₹{r['buy_price']:>9,.2f}  "
            f"Sell: ₹{r['sell_price']:>9,.2f}  "
            f"Qty: {int(r['quantity'])}  "
            f"PnL: ₹{r['pnl']:>10,.2f}")
    return df

# ── Step 2: Patch data/markets_pnl0325.csv ────────────────────────────────────
def patch_master_pnl(sim_df: pd.DataFrame, target_date: datetime) -> int:
    if not os.path.exists(PNL_FILE):
        log(f"Master PnL file not found: {PNL_FILE}", "❌")
        return 0

    pnl = pd.read_csv(PNL_FILE)
    pnl.columns = pnl.columns.str.strip().str.lower()
    date_col = next((c for c in pnl.columns if 'date' in c or 'time' in c),
                    pnl.columns[0])
    pnl['_dt'] = pd.to_datetime(pnl[date_col], dayfirst=True,
                                 format='mixed', errors='coerce')

    sim_map = {row['stockname']: row for _, row in sim_df.iterrows()}
    target_str = target_date.date()
    patched = 0

    for idx, row in pnl.iterrows():
        if (pd.notna(row['_dt']) and
                row['_dt'].date() == target_str and
                row['stockname'] in sim_map):
            s = sim_map[row['stockname']]
            pnl.at[idx, 'pnl'] = round(float(s['pnl']), 2)
            # Optional extra columns (fill if they exist in master)
            col_map = {
                'buy_price':        'buyprice',
                'sell_price':       'sellprice',
                'quantity':         'qty',
                'commission_paid':  'commission_paid',
                'sell_exec_type':   'sell_exec_type',
                'completion_day':   'completion_day',
            }
            for src, dst in col_map.items():
                if dst in pnl.columns and src in s.index:
                    pnl.at[idx, dst] = s[src]
            patched += 1

    pnl.drop(columns=['_dt'], inplace=True)
    pnl.to_csv(PNL_FILE, index=False)
    log(f"Patched {patched} row(s) in markets_pnl0325.csv")
    return patched

# ── Step 3: Update output/trades_dynamic_threshold.csv ────────────────────────
def update_tracker(sim_df: pd.DataFrame, target_date: datetime) -> int:
    if not os.path.exists(TRACKER):
        log(f"Tracker file not found: {TRACKER}", "⚠️")
        return 0

    tracker = pd.read_csv(TRACKER)
    tracker['_dt'] = pd.to_datetime(tracker['date'], format='mixed',
                                     errors='coerce')
    target_str = target_date.date()
    sim_map = {row['stockname']: row for _, row in sim_df.iterrows()}

    updated = 0
    appended_stocks = []

    # Update existing rows
    for idx, row in tracker.iterrows():
        if (pd.notna(row['_dt']) and
                row['_dt'].date() == target_str and
                row['stock'] in sim_map):
            tracker.at[idx, 'actual_pnl'] = round(
                float(sim_map[row['stock']]['pnl']), 2)
            updated += 1

    tracker.drop(columns=['_dt'], inplace=True)

    # Find stocks in sim that have NO row in tracker for that date (e.g. R3 pick)
    existing_stocks = set(
        tracker[tracker['date'] == target_date.strftime('%Y-%m-%d')]['stock']
        if 'date' in tracker.columns else []
    )

    new_rows = []
    for stock, s in sim_map.items():
        if stock not in existing_stocks:
            new_row = {col: '' for col in tracker.columns}
            new_row['date']       = target_date.strftime('%Y-%m-%d')
            new_row['day']        = target_date.strftime('%A')
            new_row['stock']      = stock
            new_row['pred_pnl']   = ''
            new_row['actual_pnl'] = round(float(s['pnl']), 2)
            # Carry threshold from latest row if available
            if not tracker.empty and 'threshold_used' in tracker.columns:
                new_row['threshold_used'] = tracker['threshold_used'].dropna().iloc[-1] \
                    if not tracker['threshold_used'].dropna().empty else ''
            new_row['multiplier_used'] = 1
            new_row['qty'] = 1
            new_rows.append(new_row)
            appended_stocks.append(stock)

    if new_rows:
        tracker = pd.concat([tracker, pd.DataFrame(new_rows)], ignore_index=True)

    tracker.to_csv(TRACKER, index=False)
    total = updated + len(new_rows)
    log(f"Updated {updated} existing row(s) in trades_dynamic_threshold.csv")
    if new_rows:
        log(f"Appended {len(new_rows)} new row(s) for: {appended_stocks}")
    return total

# ── Step 4: Verify final state ─────────────────────────────────────────────────
def verify(target_date: datetime):
    target_str = target_date.date()

    pnl = pd.read_csv(PNL_FILE)
    pnl.columns = pnl.columns.str.strip().str.lower()
    pnl['_dt'] = pd.to_datetime(pnl['simulationdate'], dayfirst=True,
                                 format='mixed', errors='coerce')
    nz = pnl[(pnl['_dt'].dt.date == target_str) &
              (pd.to_numeric(pnl['pnl'], errors='coerce').fillna(0) != 0)]

    tracker = pd.read_csv(TRACKER)
    tracker['_dt'] = pd.to_datetime(tracker['date'], format='mixed', errors='coerce')
    t_day = tracker[tracker['_dt'].dt.date == target_str]

    print()
    print("─" * 55)
    print(f"  VERIFICATION — {target_date.strftime('%A %d-%m-%Y')}")
    print("─" * 55)
    print(f"  markets_pnl0325.csv non-zero rows : {len(nz)}")
    for _, r in nz.iterrows():
        print(f"    {r['stockname']:<14} ₹{float(r['pnl']):>10,.2f}")
    print(f"  trades_dynamic_threshold.csv rows : {len(t_day)}")
    for _, r in t_day.iterrows():
        try:
            apnl = f"₹{float(r['actual_pnl']):>10,.2f}"
        except Exception:
            apnl = str(r.get('actual_pnl', ''))
        print(f"    {r['stock']:<14} actual_pnl: {apnl}")
    print("─" * 55)

# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    print("=" * 55)
    print("  MERGE ACTUALS — Sniper v3.0 Pipeline Step 0")
    print(f"  Run time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 55)

    yesterday = get_yesterday()
    log(f"Target date (yesterday's trades): {yesterday.date()}")

    sim_df = load_sim_results(yesterday)
    if sim_df.empty:
        log("Nothing to merge. Exiting cleanly.", "ℹ️")
        return

    print()
    log("Patching markets_pnl0325.csv...", "⏳")
    patch_master_pnl(sim_df, yesterday)

    print()
    log("Updating trades_dynamic_threshold.csv...", "⏳")
    update_tracker(sim_df, yesterday)

    verify(yesterday)
    print("\n✅ merge_actuals.py completed successfully.\n")

if __name__ == '__main__':
    main()
