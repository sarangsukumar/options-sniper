import pandas as pd
import os

BASE_DIR = "/home/ubuntu/daily_prediction_sytem_Dynamic_threshold"
TRADES_CSV = os.path.join(BASE_DIR, "historical_models", "output", "trades_dynamic_threshold_ensemble.csv")
SANDBOX_REPORT = os.path.join(BASE_DIR, "first_mondays_sandbox_report.txt")

# Read sandbox report to extract top picks for each date
sandbox_picks = {}
current_date = None

with open(SANDBOX_REPORT, 'r') as f:
    for line in f:
        if "RESULTS FOR" in line:
            current_date = line.strip().split()[-1]
            sandbox_picks[current_date] = []
        elif current_date and "|" in line and "Stock Name" not in line and "---" not in line:
            parts = line.split("|")
            if len(parts) > 1:
                stock = parts[0].strip()
                score = parts[1].strip()
                sandbox_picks[current_date].append((stock, score))

# Read historical backtest trades
trades_df = pd.read_csv(TRADES_CSV)
trades_df['Date'] = pd.to_datetime(trades_df['date']).dt.strftime('%Y-%m-%d')

print("="*80)
print("COMPARISON: SANDBOX (Lookahead-Free) vs HISTORICAL BACKTEST TRADES")
print("="*80)

for dt in sorted(sandbox_picks.keys()):
    print(f"\n[Date: {dt}]")
    s_picks = sandbox_picks[dt][:5]  # Top 5
    print("  Sandbox Top 5 Candidates : " + ", ".join([f"{s} ({sc})" for s, sc in s_picks]))
    
    day_trades = trades_df[trades_df['Date'] == dt]
    if day_trades.empty:
        print("  Historical Backtest Trades: NONE (Probably filtered out by threshold/rules)")
    else:
        traded_stocks = day_trades['stock'].tolist()
        print("  Historical Backtest Trades: " + ", ".join(traded_stocks))
        
        # Check for overlap
        overlap = [s for s, sc in s_picks if s in traded_stocks]
        if overlap:
            print("  -> MATCH! The sandbox predicted exactly what the backtest traded: " + ", ".join(overlap))
        else:
            print("  -> MISMATCH or different threshold filtering applied.")
