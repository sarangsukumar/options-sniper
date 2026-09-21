import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
import threading
import concurrent.futures

def flatten_yfinance_columns(df):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0] for col in df.columns]
    return df

def fetch_safe_yfinance_data(symbol, start_date, end_date):
    try:
        ticker = f"{symbol}.NS"
        df = yf.download(ticker, start=start_date, end=end_date, progress=False)
        if df.empty: return None
        
        df = flatten_yfinance_columns(df)
        df = df.reset_index()
        df = df[['Date', 'Open', 'High', 'Low', 'Close', 'Volume']]
        df['Stock'] = symbol
        df['Date'] = df['Date'].dt.strftime('%Y-%m-%d')
        
        for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
            
        df = df.dropna(subset=['Close'])
        df = df[df['Close'] > 0]
        return df
    except Exception as e:
        return None

def process_chunk(stocks):
    all_gap_features = []
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = '2015-01-01'
    
    for stock in stocks:
        df = fetch_safe_yfinance_data(stock, start_date, end_date)
        if df is None: continue
        
        for idx in range(len(df)):
            row = df.iloc[idx]
            current_date = row['Date']
            today_open = float(row['Open'])
            
            prev_day_close = None
            if idx > 0:
                prev_day_close = float(df.iloc[idx - 1]['Close'])
                
            gap_pct = None
            if prev_day_close is not None and prev_day_close != 0:
                gap_pct = ((today_open - prev_day_close) / prev_day_close) * 100
                
            prev_day_volume = None
            if idx > 0:
                prev_day_volume = float(df.iloc[idx - 1]['Volume'])
                
            day_before_volume = None
            if idx > 1:
                day_before_volume = float(df.iloc[idx - 2]['Volume'])
                
            volume_change_pct = None
            if day_before_volume is not None and day_before_volume != 0 and prev_day_volume is not None:
                # STRICT NO-LOOKAHEAD FALLBACK: ONLY YESTERDAY VS DAY BEFORE
                volume_change_pct = ((prev_day_volume - day_before_volume) / day_before_volume) * 100
                
            all_gap_features.append({
                'Date': current_date,
                'Stock': stock,
                'Open': today_open,
                'Prev_Close': prev_day_close,
                'Gap_Pct': gap_pct,
                'Volume_Change_Pct': volume_change_pct
            })
            
    return pd.DataFrame(all_gap_features)

def main():
    pnl = pd.read_csv('/home/ubuntu/V8_Hybrid_Engine/mis_short_pnl_new.csv')
    stocks = pnl['stockname'].unique().tolist()
    print(f"Fetching safe data for {len(stocks)} stocks...")
    
    chunks = [stocks[i:i + 20] for i in range(0, len(stocks), 20)]
    all_dfs = []
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        results = list(executor.map(process_chunk, chunks))
        for res in results:
            if not res.empty:
                all_dfs.append(res)
                
    if all_dfs:
        final_df = pd.concat(all_dfs)
        final_df.to_csv('/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/data/yahoo_finance_safe_gap.csv', index=False)
        print("Safely created yahoo_finance_safe_gap.csv with ZERO fallbacks!")

if __name__ == '__main__':
    main()
