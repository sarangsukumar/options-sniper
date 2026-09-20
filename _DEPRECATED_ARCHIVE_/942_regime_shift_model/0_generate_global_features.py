import yfinance as yf
import pandas as pd
import numpy as np

# Download tickers
tickers = {
    'NIFTY': '^NSEI',
    'SP500': '^GSPC',
    'NASDAQ': '^IXIC',
    'NIKKEI': '^N225',
    'HANGSENG': '^HSI'
}

print("Downloading Global Indices...")
data = yf.download(list(tickers.values()), start='2018-01-01', end='2026-12-31')

# Flatten columns if multi-index
if isinstance(data.columns, pd.MultiIndex):
    df_close = data['Close']
    df_open = data['Open']
else:
    # Single ticker (fallback)
    df_close = pd.DataFrame(data['Close'], columns=['^NSEI'])
    df_open = pd.DataFrame(data['Open'], columns=['^NSEI'])

df_close = df_close.reset_index()
df_open = df_open.reset_index()

# Convert to a daily feature set based on the INDIAN trading date
dates = pd.date_range(start='2018-01-01', end='2026-12-31', freq='B')
features = pd.DataFrame({'date': dates})
features['date_str'] = features['date'].dt.strftime('%Y-%m-%d')

# Merge NIFTY
nifty_c = df_close[['Date', '^NSEI']].rename(columns={'Date': 'date', '^NSEI': 'nifty_close'})
nifty_o = df_open[['Date', '^NSEI']].rename(columns={'Date': 'date', '^NSEI': 'nifty_open'})
features = features.merge(nifty_c, on='date', how='left').merge(nifty_o, on='date', how='left')

# Calculate Nifty Gap (Open today / Close yesterday - 1)
features['nifty_prev_close'] = features['nifty_close'].shift(1)
features['nifty_gap'] = (features['nifty_open'] / features['nifty_prev_close']) - 1

# Merge S&P 500 (US closes the NIGHT BEFORE the Indian market opens)
sp_c = df_close[['Date', '^GSPC']].rename(columns={'Date': 'date', '^GSPC': 'sp500_close'})
features = features.merge(sp_c, on='date', how='left')
features['sp500_prev_close'] = features['sp500_close'].shift(1)
features['sp500_prev_prev_close'] = features['sp500_close'].shift(2)
# S&P overnight return (from India's perspective, this is S&P close on T-1 vs T-2)
features['sp500_overnight_ret'] = (features['sp500_prev_close'] / features['sp500_prev_prev_close']) - 1

# Merge NIKKEI (Opens BEFORE India on the SAME day)
nikkei_c = df_close[['Date', '^N225']].rename(columns={'Date': 'date', '^N225': 'nikkei_close'})
nikkei_o = df_open[['Date', '^N225']].rename(columns={'Date': 'date', '^N225': 'nikkei_open'})
features = features.merge(nikkei_c, on='date', how='left').merge(nikkei_o, on='date', how='left')
features['nikkei_prev_close'] = features['nikkei_close'].shift(1)
# Nikkei Gap is Nikkei open today vs close yesterday
features['nikkei_gap'] = (features['nikkei_open'] / features['nikkei_prev_close']) - 1
# Nikkei morning trend (Nikkei close today is usually around India's noon, so Nikkei Open -> Nikkei Close represents Asian morning trend)
features['nikkei_intraday'] = (features['nikkei_close'] / features['nikkei_open']) - 1

# Forward fill missing values for global markets (holidays)
features['sp500_overnight_ret'] = features['sp500_overnight_ret'].fillna(0)
features['nikkei_gap'] = features['nikkei_gap'].fillna(0)
features['nikkei_intraday'] = features['nikkei_intraday'].fillna(0)
features['nifty_gap'] = features['nifty_gap'].fillna(0)

# The "Global vs Nifty" Gap Spread
features['nifty_vs_sp500_gap'] = features['nifty_gap'] - features['sp500_overnight_ret']
features['nifty_vs_nikkei_gap'] = features['nifty_gap'] - features['nikkei_gap']

output_cols = ['date_str', 'nifty_gap', 'sp500_overnight_ret', 'nikkei_gap', 'nikkei_intraday', 'nifty_vs_sp500_gap', 'nifty_vs_nikkei_gap']
final_df = features[output_cols].dropna()

out_file = '/home/ubuntu/942_regime_shift_model/global_macro_features.csv'
final_df.to_csv(out_file, index=False)
print(f"Saved {len(final_df)} days of global macro features to {out_file}")

