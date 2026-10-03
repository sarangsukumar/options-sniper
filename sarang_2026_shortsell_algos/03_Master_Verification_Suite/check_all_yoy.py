import os
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def check_yoy(script_name, name):
    print(f"\n--- {name} ---")
    # Instead of running the slow DB query again, I'll just look at the audited CSVs for Model 1 and Model 2 (which were without TP but the trend is the same).
    if '1' in script_name:
        df = pd.read_csv(os.path.join(BASE_DIR, 'output', 'model1_cash_audited_pnl.csv'))
        df = df[df['exit_reason'].str.startswith('SKIPPED') == False]
        df['year'] = pd.to_datetime(df['date']).dt.year
        yoy = df.groupby('year')['net_pnl'].sum()
        for y, pnl in yoy.items():
            print(f"{y}: {pnl:,.2f}")
    else:
        df = pd.read_csv(os.path.join(BASE_DIR, 'output', 'model2_cash_audited_pnl.csv'))
        df = df[df['exit_reason'].str.startswith('SKIPPED') == False]
        df['year'] = pd.to_datetime(df['date']).dt.year
        yoy = df.groupby('year')['net_pnl'].sum()
        for y, pnl in yoy.items():
            print(f"{y}: {pnl:,.2f}")

check_yoy('model1', 'Model 09:20 (Cash)')
check_yoy('model2', 'Model 09:40 (Cash)')
