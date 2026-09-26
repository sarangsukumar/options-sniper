import pandas as pd
import yfinance as yf
import numpy as np

# ============================================================
# INFORMATION AVAILABLE AT 09:40 AM (ZERO LOOK-AHEAD):
# - Nifty % gap today
# - Individual stock % gap today
# - Previous day's stock return / behaviour
# - Day of week
# - How gap faded from 09:07 to 09:40 (gap_fade_0907_to_940_pct)
# - Previous day's last 30 min behaviour (prev_1450_to_1519_pct)
# - ML Model prediction rank
# ============================================================

# Load Nifty
tickers = {'NIFTY': '^NSEI'}
data = yf.download(list(tickers.values()), start='2018-01-01', end='2026-12-31', progress=False)
df_close = data['Close'].reset_index()
df_open = data['Open'].reset_index()
dates = pd.date_range(start='2018-01-01', end='2026-12-31', freq='B')
features = pd.DataFrame({'date': dates})
features['date_str'] = features['date'].dt.strftime('%Y-%m-%d')
features = features.merge(df_close[['Date', '^NSEI']].rename(columns={'Date':'date', '^NSEI':'nifty_close'}), on='date', how='left')
features = features.merge(df_open[['Date', '^NSEI']].rename(columns={'Date':'date', '^NSEI':'nifty_open'}), on='date', how='left')
features['nifty_gap'] = ((features['nifty_open'] / features['nifty_close'].shift(1)) - 1) * 100
features['nifty_prev_close_ret'] = ((features['nifty_close'] / features['nifty_close'].shift(1)) - 1) * 100
features['nifty_2day_ret'] = ((features['nifty_close'] / features['nifty_close'].shift(2)) - 1) * 100
features['nifty_gap'] = features['nifty_gap'].fillna(0)
features['nifty_prev_close_ret'] = features['nifty_prev_close_ret'].fillna(0)
features['nifty_2day_ret'] = features['nifty_2day_ret'].fillna(0)

pnl = pd.read_csv('0942_verified_pnl_sheet.csv')
pnl['Year'] = pd.to_datetime(pnl['Date']).dt.year
pnl['Stock_clean'] = pnl['Stock'].astype(str).str.strip().str.upper()

df = pd.read_csv('data/short_sell_ml_dataset_v5_scratch.csv', low_memory=False)
df['clean_stock'] = df['clean_stock'].astype(str).str.strip().str.upper()

merged = pnl.merge(df[['date_str','clean_stock','prev_close','gap_fade_0907_to_940_pct',
                        'prev_intraday_return','prev_1450_to_1519_pct','rejection_wick',
                        'morn_range_pct','morning_volume']], 
                   left_on=['Date','Stock_clean'], right_on=['date_str','clean_stock'], how='inner')
merged = merged.drop_duplicates(subset=['Date','Stock_clean'])
merged['pct'] = (merged['Sell_Price'] - merged['prev_close']) / merged['prev_close'] * 100
merged = merged.merge(features[['date_str','nifty_gap','nifty_prev_close_ret','nifty_2day_ret']], on='date_str', how='left')
merged['DayOfWeek'] = pd.to_datetime(merged['Date']).dt.dayofweek  # 0=Mon, 4=Fri

base_is = merged[merged['Year'] <= 2025]['Net_PnL'].sum()
base_oos = merged[merged['Year'] == 2026]['Net_PnL'].sum()
total_trades = len(merged)

print("==========================================================================")
print("🧪 PRINCIPLED RULE TESTING (ZERO LOOK-AHEAD BIAS)")
print("==========================================================================")
print(f"Raw Baseline IS (2020-25): ₹ {base_is:,.0f}")
print(f"Raw Baseline OOS (2026)  : ₹ {base_oos:,.0f}")
print("==========================================================================")

def test_rule(name, hypothesis, skip_fn):
    filtered = merged[~merged.apply(skip_fn, axis=1)]
    is_pnl = filtered[filtered['Year'] <= 2025]['Net_PnL'].sum()
    oos_pnl = filtered[filtered['Year'] == 2026]['Net_PnL'].sum()
    is_delta = is_pnl - base_is
    oos_delta = oos_pnl - base_oos
    skipped = len(merged) - len(filtered)
    
    consistent = "✅ BOTH AGREE" if (is_delta > 0 and oos_delta > 0) else ("⚠️ MIXED" if (is_delta > 0 or oos_delta > 0) else "❌ BOTH LOSE")
    
    print(f"\n📌 {name}")
    print(f"   Hypothesis: {hypothesis}")
    print(f"   Trades Skipped: {skipped} ({skipped/total_trades*100:.1f}%)")
    print(f"   IS  Delta: {'+' if is_delta>0 else ''}₹ {is_delta:>9,.0f}")
    print(f"   OOS Delta: {'+' if oos_delta>0 else ''}₹ {oos_delta:>9,.0f}")
    print(f"   Verdict   : {consistent}")

# ----------------------------------------------------------
# HYPOTHESIS A: Monday Short Squeeze
# Reasoning: If market gapped down over the weekend, Monday 
# has maximum "buy the dip" retail pressure. Shorting stocks 
# on a Monday when Nifty is red is extra dangerous.
# ----------------------------------------------------------
test_rule(
    "A. Monday Danger Rule",
    "Monday gap-down days have max retail 'buy the dip' pressure. Skip Stock < -0.5% on Mondays.",
    lambda r: r['DayOfWeek'] == 0 and r['pct'] < -0.5
)

# ----------------------------------------------------------
# HYPOTHESIS B: Gap Fade Reversal Danger
# Reasoning: If a stock gapped down at 09:07 but by 09:40 the
# gap has EXPANDED further (negative fade), the selling 
# momentum is accelerating. Bad candidate to short more.
# If gap faded BACK (positive fade), that means early sellers 
# are covering already - dangerous to add fresh short.
# ----------------------------------------------------------
test_rule(
    "B. Gap Reversal (Fade) Danger",
    "If stock's gap FADED BACK by > 0.3% (buyers stepped in early), skip. Early buying = imminent short squeeze.",
    lambda r: r['gap_fade_0907_to_940_pct'] > 0.3
)

# ----------------------------------------------------------
# HYPOTHESIS C: Previous Day Strong Close
# Reasoning: If the stock had a strong positive close yesterday
# (last 30 mins were up), it still has underlying buying
# interest. Shorting today's gap down goes against the trend.
# ----------------------------------------------------------
test_rule(
    "C. Previous Day Strong Close",
    "If stock's last 30-mins of previous day were up > +0.5%, it has underlying buying. Skip shorting it today.",
    lambda r: r['prev_1450_to_1519_pct'] > 0.5
)

# ----------------------------------------------------------
# HYPOTHESIS D: Previous Day Bloodbath
# Reasoning: If Nifty itself fell heavily yesterday (> -1%),
# the market is 'oversold' on a 2-day basis. Shorts placed 
# today are likely to get short-squeezed as the market 
# stabilizes and algorithmic mean-reversion kicks in.
# ----------------------------------------------------------
test_rule(
    "D. Post-Bloodbath Bounce Risk",
    "If Nifty fell > -1% yesterday, market is 2-day oversold. Mean-reversion algo bots are primed. Skip all trades.",
    lambda r: r['nifty_prev_close_ret'] < -1.0
)

# ----------------------------------------------------------
# HYPOTHESIS E: 2-Day Consecutive Nifty Drop
# Reasoning: After 2 consecutive red days in Nifty, the 
# 'Buy-the-Dip' algorithmic pressure becomes extreme on day 3.
# Shorting on day 3 of a consecutive drop is high risk.
# ----------------------------------------------------------
test_rule(
    "E. 2-Day Consecutive Nifty Drop",
    "If Nifty is down > -1.5% over the last 2 days AND gapping down today, skip (extreme oversold = bounce risk).",
    lambda r: r['nifty_2day_ret'] < -1.5 and r['nifty_gap'] < 0
)

print("\n==========================================================================")
print("KEY: ✅ = Both IS and OOS improved (Robust rule)")
print("     ⚠️ = Only one period improved (Possibly overfitted)")
print("     ❌ = Both periods got worse (This rule is harmful)")
print("==========================================================================")
