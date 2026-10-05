import pandas as pd
import yfinance as yf

# Macro Nifty
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

df = pd.read_csv('../data/short_sell_ml_dataset_v5_scratch.csv.gz', low_memory=False)
df['clean_stock'] = df['clean_stock'].astype(str).str.strip().str.upper()

def evaluate(pnl_file, name):
    pnl = pd.read_csv(pnl_file)
    pnl['Year'] = pd.to_datetime(pnl['Date']).dt.year
    pnl['Stock_clean'] = pnl['Stock'].astype(str).str.strip().str.upper()

    merged = pnl.merge(df[['date_str','clean_stock','prev_close', 'prev_intraday_vwap_gap']], left_on=['Date','Stock_clean'], right_on=['date_str','clean_stock'], how='inner')
    merged = merged.drop_duplicates(subset=['Date','Stock_clean'])
    merged['pct'] = (merged['Sell_Price'] - merged['prev_close']) / merged['prev_close'] * 100
    merged = merged.merge(features[['date_str','nifty_gap']], on='date_str', how='left')
    merged['DayOfWeek'] = pd.to_datetime(merged['Date']).dt.dayofweek

    r1_mask = merged['pct'] >= -1.0
    r2_mask = ~((merged['nifty_gap'] < -0.5) & (merged['pct'] < -0.5))
    r3_mask = ~((merged['DayOfWeek'] == 0) & (merged['pct'] < -0.5))
    r5_mask = merged['prev_intraday_vwap_gap'] >= -0.52

    after_5f = merged[r1_mask & r2_mask & r3_mask & r5_mask]

    print(f"\n--- {name} ---")
    tot = 0
    for year in sorted(merged['Year'].unique()):
        f5 = after_5f[after_5f['Year'] == year]['Net_PnL'].sum()
        tot += f5
        print(f"{year}: ₹ {f5:>10,.0f}")
    print(f"TOTAL: ₹ {tot:>10,.0f}")

evaluate('../pnl_A.csv', "Exp A: Huber + Time Decay")
evaluate('../pnl_B.csv', "Exp B: Binary Probability")
evaluate('../pnl_C.csv', "Exp C: Heavy L1 Reg (Lasso)")
