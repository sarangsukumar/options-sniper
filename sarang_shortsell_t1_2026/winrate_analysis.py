import pandas as pd
import numpy as np

def analyze_model(csv_path, model_name):
    df = pd.read_csv(csv_path)
    df['Date'] = pd.to_datetime(df['Date'])
    df['year'] = df['Date'].dt.year
    df['month'] = df['Date'].dt.to_period('M')
    df['week'] = df['Date'].dt.to_period('W')
    df['quarter'] = df['Date'].dt.to_period('Q')
    df['win'] = df['Net_PnL'] > 0

    print(f"\n{'='*60}")
    print(f"  {model_name}")
    print(f"{'='*60}")

    # --- PER TRADE ---
    total = len(df)
    wins = df['win'].sum()
    print(f"\n📌 PER TRADE:")
    print(f"   Total Trades : {total:,}")
    print(f"   Wins         : {int(wins):,}")
    print(f"   Losses       : {int(total - wins):,}")
    print(f"   Win Rate     : {wins/total*100:.2f}%")
    print(f"   Avg Win PnL  : Rs {df[df['win']]['Net_PnL'].mean():,.2f}")
    print(f"   Avg Loss PnL : Rs {df[~df['win']]['Net_PnL'].mean():,.2f}")

    # --- PER DAY ---
    daily = df.groupby('Date').agg(
        day_pnl=('Net_PnL', 'sum'),
        trades=('Net_PnL', 'count')
    ).reset_index()
    daily['day_win'] = daily['day_pnl'] > 0
    print(f"\n📌 PER DAY:")
    print(f"   Total Trading Days : {len(daily):,}")
    print(f"   Profitable Days    : {daily['day_win'].sum():,}")
    print(f"   Losing Days        : {(~daily['day_win']).sum():,}")
    print(f"   Day Win Rate       : {daily['day_win'].mean()*100:.2f}%")
    print(f"   Avg Trades/Day     : {daily['trades'].mean():.2f}")
    print(f"   Avg Day PnL        : Rs {daily['day_pnl'].mean():,.2f}")
    print(f"   Best Day           : Rs {daily['day_pnl'].max():,.2f}")
    print(f"   Worst Day          : Rs {daily['day_pnl'].min():,.2f}")

    # --- PER WEEK ---
    weekly = df.groupby('week').agg(
        week_pnl=('Net_PnL', 'sum'),
        trades=('Net_PnL', 'count')
    ).reset_index()
    weekly['week_win'] = weekly['week_pnl'] > 0
    print(f"\n📌 PER WEEK:")
    print(f"   Total Weeks        : {len(weekly):,}")
    print(f"   Profitable Weeks   : {weekly['week_win'].sum():,}")
    print(f"   Losing Weeks       : {(~weekly['week_win']).sum():,}")
    print(f"   Week Win Rate      : {weekly['week_win'].mean()*100:.2f}%")
    print(f"   Avg Week PnL       : Rs {weekly['week_pnl'].mean():,.2f}")
    print(f"   Best Week          : Rs {weekly['week_pnl'].max():,.2f}")
    print(f"   Worst Week         : Rs {weekly['week_pnl'].min():,.2f}")

    # --- PER MONTH ---
    monthly = df.groupby('month').agg(
        month_pnl=('Net_PnL', 'sum'),
        trades=('Net_PnL', 'count')
    ).reset_index()
    monthly['month_win'] = monthly['month_pnl'] > 0
    print(f"\n📌 PER MONTH:")
    print(f"   Total Months       : {len(monthly):,}")
    print(f"   Profitable Months  : {monthly['month_win'].sum():,}")
    print(f"   Losing Months      : {(~monthly['month_win']).sum():,}")
    print(f"   Month Win Rate     : {monthly['month_win'].mean()*100:.2f}%")
    print(f"   Avg Month PnL      : Rs {monthly['month_pnl'].mean():,.2f}")
    print(f"   Best Month         : Rs {monthly['month_pnl'].max():,.2f}")
    print(f"   Worst Month        : Rs {monthly['month_pnl'].min():,.2f}")

    # --- PER QUARTER ---
    quarterly = df.groupby('quarter').agg(
        qtr_pnl=('Net_PnL', 'sum'),
        trades=('Net_PnL', 'count')
    ).reset_index()
    quarterly['qtr_win'] = quarterly['qtr_pnl'] > 0
    print(f"\n📌 PER QUARTER:")
    print(f"   Total Quarters     : {len(quarterly):,}")
    print(f"   Profitable Qtrs    : {quarterly['qtr_win'].sum():,}")
    print(f"   Losing Qtrs        : {(~quarterly['qtr_win']).sum():,}")
    print(f"   Quarter Win Rate   : {quarterly['qtr_win'].mean()*100:.2f}%")
    print(f"   Avg Quarter PnL    : Rs {quarterly['qtr_pnl'].mean():,.2f}")
    for _, row in quarterly.iterrows():
        print(f"   {row['quarter']}: Rs {row['qtr_pnl']:,.2f} ({'✅' if row['qtr_win'] else '❌'})")

analyze_model(
    '/home/ubuntu/sarang_shortsell_t1_2026/01_0920_Scalp_Model/0920_verified_pnl_sheet.csv',
    '09:20 SCALP MODEL'
)
analyze_model(
    '/home/ubuntu/sarang_shortsell_t1_2026/02_0942_Hybrid_Model/0942_verified_pnl_sheet.csv',
    '09:42 HYBRID MODEL'
)
