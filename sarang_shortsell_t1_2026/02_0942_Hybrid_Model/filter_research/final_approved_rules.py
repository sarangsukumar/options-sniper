import pandas as pd
import yfinance as yf

tickers = {'NIFTY': '^NSEI'}
data = yf.download(list(tickers.values()), start='2018-01-01', end='2026-12-31', progress=False)
df_close = data['Close'].reset_index()
df_open = data['Open'].reset_index()
dates = pd.date_range(start='2018-01-01', end='2026-12-31', freq='B')
features = pd.DataFrame({'date': dates})
features['date_str'] = features['date'].dt.strftime('%Y-%m-%d')
features = features.merge(df_close[['Date', '^NSEI']].rename(columns={'Date':'date','^NSEI':'nifty_close'}), on='date', how='left')
features = features.merge(df_open[['Date', '^NSEI']].rename(columns={'Date':'date','^NSEI':'nifty_open'}), on='date', how='left')
features['nifty_gap'] = ((features['nifty_open'] / features['nifty_close'].shift(1)) - 1) * 100
features['nifty_gap'] = features['nifty_gap'].fillna(0)

pnl = pd.read_csv('../0942_verified_pnl_sheet.csv')
pnl['Year'] = pd.to_datetime(pnl['Date']).dt.year
pnl['Stock_clean'] = pnl['Stock'].astype(str).str.strip().str.upper()

df = pd.read_csv('../data/short_sell_ml_dataset_v5_scratch.csv.gz', low_memory=False)
df['clean_stock'] = df['clean_stock'].astype(str).str.strip().str.upper()

merged = pnl.merge(df[['date_str','clean_stock','prev_close']], left_on=['Date','Stock_clean'], right_on=['date_str','clean_stock'], how='inner')
merged = merged.drop_duplicates(subset=['Date','Stock_clean'])
merged['pct'] = (merged['Sell_Price'] - merged['prev_close']) / merged['prev_close'] * 100
merged = merged.merge(features[['date_str','nifty_gap']], on='date_str', how='left')
merged['DayOfWeek'] = pd.to_datetime(merged['Date']).dt.dayofweek

# ============================================================
# APPROVED RULES (in order of application)
# ============================================================
# RULE 1: Stock < -1.0% (Always Skip)
# Hypothesis: Deeply oversold stocks on any day are prone to violent short-squeezes
#
# RULE 2: Crash Day Protector (Nifty < -0.5% AND Stock < -0.5%)
# Hypothesis: On crash days, algorithmic buy-the-dip bots target any oversold stock
#
# RULE 3: Monday Danger (Monday AND Stock < -0.5%)
# Hypothesis: Monday mornings have max retail buy-the-dip pressure after weekend news digestion
# ============================================================

def apply_all_rules(row):
    # Rule 1: Always skip if stock is heavily gapped down
    if row['pct'] < -1.0:
        return False, "Rule 1: Stock < -1%"
    # Rule 2: On crash days be stricter
    if row['nifty_gap'] < -0.5 and row['pct'] < -0.5:
        return False, "Rule 2: Crash Day"
    # Rule 3: On Mondays be stricter
    if row['DayOfWeek'] == 0 and row['pct'] < -0.5:
        return False, "Rule 3: Monday"
    return True, None

# Apply rule by rule to track each rule's contribution
r1_mask = merged['pct'] >= -1.0
r2_mask = ~((merged['nifty_gap'] < -0.5) & (merged['pct'] < -0.5))
r3_mask = ~((merged['DayOfWeek'] == 0) & (merged['pct'] < -0.5))

baseline          = merged
after_r1          = merged[r1_mask]
after_r1_r2       = merged[r1_mask & r2_mask]
after_r1_r2_r3    = merged[r1_mask & r2_mask & r3_mask]

print("=" * 110)
print("🏆 FINAL APPROVED RULES — YEAR-BY-YEAR COMPARISON vs RAW BASELINE")
print("=" * 110)
print(f"\nRules Applied:")
print(f"  RULE 1: Always skip if Stock < -1.0%")
print(f"  RULE 2: If Nifty < -0.5%, also skip if Stock < -0.5% (Crash Day Protector)")
print(f"  RULE 3: If Monday, also skip if Stock < -0.5% (Monday Danger Rule)")
print()
print(f"{'Year':<5} | {'Baseline':<12} | {'After R1':<12} | {'After R1+R2':<12} | {'After R1+R2+R3':<15} | {'Final Delta':<12} | {'Skipped'}")
print("-" * 110)

total_base = total_r1 = total_r2 = total_r3 = 0
total_trades = 0
total_skip_r1 = total_skip_r2 = total_skip_r3 = 0

for year in sorted(merged['Year'].unique()):
    b  = baseline[baseline['Year'] == year]['Net_PnL'].sum()
    r1 = after_r1[after_r1['Year'] == year]['Net_PnL'].sum()
    r2 = after_r1_r2[after_r1_r2['Year'] == year]['Net_PnL'].sum()
    r3 = after_r1_r2_r3[after_r1_r2_r3['Year'] == year]['Net_PnL'].sum()
    
    n_base = len(baseline[baseline['Year'] == year])
    n_r1   = len(after_r1[after_r1['Year'] == year])
    n_r2   = len(after_r1_r2[after_r1_r2['Year'] == year])
    n_r3   = len(after_r1_r2_r3[after_r1_r2_r3['Year'] == year])
    
    skip_r1 = n_base - n_r1
    skip_r2 = n_r1 - n_r2
    skip_r3 = n_r2 - n_r3
    
    total_base += b; total_r1 += r1; total_r2 += r2; total_r3 += r3
    total_trades += n_base
    total_skip_r1 += skip_r1; total_skip_r2 += skip_r2; total_skip_r3 += skip_r3
    
    delta = r3 - b
    delta_str = f"{'+' if delta>0 else ''}₹{delta:>8,.0f}"
    tag = "(OOS)" if year == 2026 else ""
    
    print(f"{year:<5} | ₹{b:>10,.0f} | ₹{r1:>10,.0f} | ₹{r2:>10,.0f} | ₹{r3:>12,.0f}   | {delta_str:<12} | {skip_r1}+{skip_r2}+{skip_r3}={skip_r1+skip_r2+skip_r3} {tag}")

print("=" * 110)
total_skip = total_skip_r1 + total_skip_r2 + total_skip_r3
final_delta = total_r3 - total_base
print(f"TOTAL | ₹{total_base:>10,.0f} | ₹{total_r1:>10,.0f} | ₹{total_r2:>10,.0f} | ₹{total_r3:>12,.0f}   | +₹{final_delta:>7,.0f}     | {total_skip_r1}+{total_skip_r2}+{total_skip_r3}={total_skip}")
print(f"\nTotal Trades Skipped: {total_skip} out of {total_trades} ({total_skip/total_trades*100:.1f}%)")
print(f"\n📌 Individual Rule Contribution:")
print(f"   Rule 1 alone : +₹{total_r1-total_base:>8,.0f}  (Skipped {total_skip_r1} trades)")
print(f"   Rule 2 adds  : +₹{total_r2-total_r1:>8,.0f}  (Skipped {total_skip_r2} more trades)")
print(f"   Rule 3 adds  : +₹{total_r3-total_r2:>8,.0f}  (Skipped {total_skip_r3} more trades)")
print(f"   TOTAL GAIN   : +₹{final_delta:>8,.0f}")
