import pandas as pd
import os

def analyze_sniper_from_scratch():
    # Use the freshly rebuilt-from-scratch daily trades file
    csv_path = 'historical_models/output/trades_dynamic_threshold_daily.csv'
    
    if not os.path.exists(csv_path):
        print(f"❌ Error: Could not find rebuilt trade log at {csv_path}")
        print("Please ensure the rebuild script has been executed first.")
        return

    df = pd.read_csv(csv_path)
    df['date'] = pd.to_datetime(df['date'])
    df['year'] = df['date'].dt.year
    df['month'] = df['date'].dt.month

    # Year-Over-Year Breakdown
    yearly = df.groupby('year').agg(
        Trades=('actual_pnl', 'count'),
        WinPct=('actual_pnl', lambda x: (x > 0).mean() * 100),
        AvgPnL=('actual_pnl', 'mean'),
        TotalPnL=('actual_pnl', 'sum')
    ).reset_index()

    print("\n" + "="*70)
    print(" 🔥 R1+R3 SNIPER ALGORITHM — COMPILED 100% FROM SCRATCH 🔥")
    print("   (Non-Double-Filtered, Zero Reliance on Frozen Sheets)")
    print("="*70)
    
    # Formatted YoY Table
    print(f"{'Year':<6} | {'Trades':<8} | {'Win Rate':<10} | {'Avg PnL (Rs)':<15} | {'Total PnL (Rs)'}")
    print("-"*70)
    for _, row in yearly.iterrows():
        print(f"{int(row['year']):<6} | {int(row['Trades']):<8} | {row['WinPct']:>8.1f}% | Rs {row['AvgPnL']:>11,.0f} | Rs {row['TotalPnL']:>13,.0f}")
    
    print("-"*70)
    overall_trades = len(df)
    overall_win = (df['actual_pnl'] > 0).mean() * 100
    overall_avg = df['actual_pnl'].mean()
    overall_total = df['actual_pnl'].sum()
    print(f"{'TOTAL':<6} | {overall_trades:<8} | {overall_win:>8.1f}% | Rs {overall_avg:>11,.0f} | Rs {overall_total:>13,.0f}")
    print("="*70)

    # August 2026 Daily Breakdown
    print("\n📅 AUGUST 2026 DAILY TRADE LOG (Strictly R1 + R3)")
    print("-"*90)
    df_aug = df[(df['date'].dt.year == 2026) & (df['date'].dt.month == 8)].sort_values('date')
    print(f"{'Date':<12} | {'Day':<10} | {'Stock':<12} | {'Predicted PnL':<15} | {'Actual PnL':<15} | {'Threshold'}")
    print("-"*90)
    for _, row in df_aug.iterrows():
        date_str = row['date'].strftime('%Y-%m-%d')
        print(f"{date_str:<12} | {row['day']:<10} | {row['stock']:<12} | Rs {row['pred_pnl']:>11,.0f} | Rs {row['actual_pnl']:>11,.0f} | Rs {row['threshold_used']:>9,.0f}")
    print("="*90 + "\n")

if __name__ == '__main__':
    analyze_sniper_from_scratch()
