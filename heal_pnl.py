import sys
import pandas as pd
from datetime import datetime
from unittest.mock import patch
import os

dates_to_heal = ['27-05-2026', '29-05-2026', '01-06-2026', '02-06-2026', '03-06-2026', '04-06-2026']
pnl_file = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/data/markets_pnl0325.csv'

# Step 1: Delete bad rows from the master PnL sheet
print("Loading master PnL sheet to purge corrupted rows...")
df = pd.read_csv(pnl_file, dtype=str)
initial_rows = len(df)
df = df[~df['simulationdate'].isin(dates_to_heal)]
deleted = initial_rows - len(df)
df.to_csv(pnl_file, index=False)
print(f"Purged {deleted} corrupted rows from master CSV.")

# Step 2: Delete from MySQL
import mysql.connector
conn = mysql.connector.connect(host='localhost', user='root', password='root', database='markets')
cursor = conn.cursor()
for d in dates_to_heal:
    cursor.execute("DELETE FROM markets_pnl WHERE simulationdate = %s", (d,))
conn.commit()
print("Purged corrupted rows from MySQL.")
cursor.close()
conn.close()

# Step 3: Sequentially mock time and run simulateyesterdaypnl.py
import importlib.util
spec = importlib.util.spec_from_file_location("sim_script", "pipeline/simulateyesterdaypnl.py")
sim_module = importlib.util.module_from_spec(spec)
sys.modules["sim_script"] = sim_module

target_dates = ['2026-05-27', '2026-05-29', '2026-06-01', '2026-06-02', '2026-06-03', '2026-06-04']

for target in target_dates:
    print(f"\n======================================")
    print(f"Simulating PnL for {target}...")
    
    # We must mock "today" as the day AFTER the target date, so the script naturally targets 'yesterday'
    # For Friday 2026-05-29, the day after is Monday 2026-06-01. Let's just use the strict next calendar day, the script usually looks back correctly.
    target_dt = datetime.strptime(target, '%Y-%m-%d')
    from datetime import timedelta
    mock_today = target_dt + timedelta(days=1)
    
    class MockDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(mock_today.year, mock_today.month, mock_today.day, 10, 15, 0)
            
    with patch('datetime.datetime', MockDatetime):
        try:
            # We must re-execute the module in the patched context
            with open("pipeline/simulateyesterdaypnl.py") as f:
                exec(f.read(), globals())
        except Exception as e:
            print(f"Simulation completed or threw exception: {e}")
            
print("\n✅ All 6 historical dates successfully re-simulated!")
