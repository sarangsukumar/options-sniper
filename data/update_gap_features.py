"""
Fetch Open/Close Prices from Yahoo Finance - PARALLEL VERSION
Downloads historical OHLC data for all major Indian stocks in parallel
"""

import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

warnings.filterwarnings('ignore')

# ============================================================================
# COMPREHENSIVE STOCK LIST
# ============================================================================

STOCKS = [
    # Nifty 50 Core
    'RELIANCE', 'TCS', 'INFY', 'HDFC', 'ICICIBANK', 'SBIN', 'MARUTI', 'BAJAJFINSV',
    'LT', 'ASIANPAINT', 'HCLTECH', 'WIPRO', 'TECHM', 'AXISBANK', 'KOTAKBANK',
    'SUNPHARMA', 'DMART', 'NESTLEIND', 'POWERGRID', 'JSWSTEEL', 'TATASTEEL',
    'BAJAJHLDNG', 'BHARTIARTL', 'INDIGO', 'ULTRACEMCO', 'ADANIPORTS', 'ADANIGREEN',
    'ADANIPOWER', 'TVSMOTOR', 'EICHERMOT', 'HEROMOTOCO', 'PAGEIND', 'MARICO', 
    'BRITANNIA', 'COLPAL', 'GODREJCP', 'ITC', 'HINDUNILVR', 'DABUR', 'BPCL', 
    'NTPC', 'GAIL', 'COALINDIA', 'NMDC', 'SAIL', 'ONGC', 'CIPLA',
    
    # Additional Nifty 100 stocks
    'BAJAJ-AUTO', 'BHEL', 'CANBK', 'CHOLAFIN', 'DIVISLAB', 'DRREDDY',
    'GRASIM', 'HAVELLS', 'KPITTECH', 'LUPIN', 'M&M', 'MANAPPURAM', 
    'MINDTREE', 'MOTHERSON', 'MRF', 'MUTHOOTFIN', 'NYKAA', 'PIDILITIND',
    'PIIND', 'PNBHOUSING', 'SBICARD', 'SBILIFE', 'SHREECEM', 'SIEMENS',
    'SYNGENE', 'TATAPOWER', 'TITAN', 'TORNTPHARM', 'TRENT', 'UPL', 'VEDL', 
    'VOLTAS', 'WHIRLPOOL', 'ZEEL', 'ADANIGAS', 'ADANIENT', 'APOLLOHOSP', 
    'APOLLOTYRE', 'ASTRAL', 'ATUL', 'AUROPHARMA', 'AUBANK', 'BANKINDIA', 
    'BANKBARODA', 'BATAINDIA', 'BERGEPAINT', 'BIRLACORP', 'BLUESTARCO', 
    'BOMDYEING', 'BSOFT', 'CADSYS', 'CAIRN', 'CAMS', 'CANFINHOME', 'CARBORUNDUM',
    'CASTROL', 'CEATLTD', 'CENTRALBK', 'CENTURYPLY', 'CENTURYTEX', 'CERA', 
    'CGPOWER', 'CHEMPLAST', 'CHOLAHLDNG', 'CHOLAMANDIR', 'CIGNITITECH', 'CINELINE',
    'COFORGE', 'CONCOR', 'COROMANDEL', 'COSMOFILMS', 'CRAFTSMAN', 'CREDITACC',
    'CRISIL', 'CROMPTON', 'CROWN', 'CUMMINSIND', 'CUPID', 'CYBERTECH', 'CYIENT', 
    'DABUR', 'DALBHARAT', 'DALMIASUG', 'DATAMATICS', 'DBREALTY', 'DCBBANK', 
    'DCMSHRIRAM', 'DEEPAKNTR', 'DELHIVERY', 'DELTACORP', 'DENORA', 'DENTALKART', 
    'DEVYANI', 'DGCONTENT', 'DHANUKA', 'DHARSUGAR', 'DHUNINV', 'DIAMONDYD', 
    'DICIND', 'DISHTV', 'DLINDIA', 'DMART', 'DNAMEDIA', 'DODLA', 'DOLLEX', 
    'DOLPHIN', 'DONEAR', 'DRREDDY', 'EICHERMOT', 'GAIL', 'GODREJCP', 'GRASIM', 
    'HAVELLS', 'HEROMOTOCO', 'HINDUNILVR', 'ICICIBANK', 'INDIGO', 'INFY', 
    'ITC', 'JSWSTEEL', 'KOTAKBANK', 'KPITTECH', 'LT', 'LUPIN', 'M&M', 
    'MANAPPURAM', 'MARICO', 'MARUTI', 'MOTHERSON', 'MRF', 'MUTHOOTFIN', 
    'NESTLEIND', 'NMDC', 'NTPC', 'NYKAA', 'ONGC', 'PAGEIND', 'PIDILITIND', 
    'PIIND', 'PNBHOUSING', 'POWERGRID', 'RELIANCE', 'SAIL', 'SBICARD', 
    'SBILIFE', 'SBIN', 'SHREECEM', 'SIEMENS', 'SUNPHARMA', 'SYNGENE', 
    'TATAPOWER', 'TATASTEEL', 'TCS', 'TECHM', 'TITAN', 'TORNTPHARM', 'TRENT', 
    'TVSMOTOR', 'ULTRACEMCO', 'UPL', 'VEDL', 'VOLTAS', 'WHIRLPOOL', 'WIPRO', 'ZEEL'
]

# Clean up and get unique stocks
STOCKS = list(set([s.strip() for s in STOCKS if s.strip()]))
STOCKS = sorted(STOCKS)

print(f"Total unique stocks to fetch: {len(STOCKS)}")

# ============================================================================
# THREAD-SAFE COUNTER
# ============================================================================
lock = threading.Lock()
success_count = 0
total_rows = 0

# ============================================================================
# FETCH DATA FROM YAHOO FINANCE (SINGLE STOCK)
# ============================================================================
def flatten_yfinance_columns(df):
    """Flatten MultiIndex columns returned by yfinance to simple OHLCV names."""
    if isinstance(df.columns, pd.MultiIndex):
        # yfinance returns columns like ('Open', 'RELIANCE.NS')
        # Keep only the first level (Open, High, Low, Close, Volume)
        df.columns = [col[0] for col in df.columns]
    return df

def fetch_stock_data_yahoo(symbol, start_date, end_date):
    """Fetches historical OHLC data from Yahoo Finance for a single stock."""
    global success_count, total_rows
    
    try:
        ticker = f"{symbol}.NS"
        df = yf.download(ticker, start=start_date, end=end_date, progress=False)
        
        if df.empty:
            print(f"[{symbol}] SKIP - No data")
            return None
        
        # Fix MultiIndex columns
        df = flatten_yfinance_columns(df)
        
        df = df.reset_index()
        df = df[['Date', 'Open', 'High', 'Low', 'Close', 'Volume']]
        df['Stock'] = symbol
        df = df[['Date', 'Stock', 'Open', 'High', 'Low', 'Close', 'Volume']]
        df['Date'] = df['Date'].dt.strftime('%Y-%m-%d')
        
        # Convert to numeric
        for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # Remove rows with missing Close
        df = df.dropna(subset=['Close'])
        df = df[df['Close'] > 0]
        
        with lock:
            success_count += 1
            total_rows += len(df)
        
        print(f"[{symbol}] OK - {len(df)} rows")
        return df
        
    except Exception as e:
        print(f"[{symbol}] ERROR - {str(e)[:30]}")
        return None

# ============================================================================
# FETCH ALL STOCKS IN PARALLEL
# ============================================================================
def fetch_all_stocks_parallel(stocks, start_date, end_date, max_workers=10):
    """Fetches historical data for all stocks in parallel."""
    print("\n" + "="*70)
    print("FETCHING DATA FROM YAHOO FINANCE (PARALLEL)")
    print("="*70)
    print(f"\nDate range: {start_date} to {end_date}")
    print(f"Stocks to fetch: {len(stocks)}")
    print(f"Max parallel workers: {max_workers}\n")
    
    all_data = []
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(fetch_stock_data_yahoo, stock, start_date, end_date): stock 
            for stock in stocks
        }
        
        completed = 0
        for future in as_completed(futures):
            completed += 1
            stock = futures[future]
            
            try:
                df = future.result()
                if df is not None:
                    all_data.append(df)
            except Exception as e:
                print(f"[{stock}] EXCEPTION - {str(e)[:30]}")
            
            if completed % 10 == 0:
                print(f"Progress: {completed}/{len(stocks)} stocks processed")
    
    if all_data:
        combined_df = pd.concat(all_data, ignore_index=True)
        print(f"\n[OK] Successfully fetched {success_count}/{len(stocks)} stocks")
        print(f"    Total rows: {len(combined_df):,}")
        print(f"    Unique stocks: {combined_df['Stock'].nunique()}")
        print(f"    Date range: {combined_df['Date'].min()} to {combined_df['Date'].max()}")
        
        return combined_df
    else:
        print("[ERROR] No data fetched")
        return pd.DataFrame()

# ============================================================================
# COMPUTE GAP FEATURES
# ============================================================================
def compute_gap_features_from_yahoo(df):
    """Computes gap features from Yahoo Finance data."""
    print("\n" + "="*70)
    print("COMPUTING GAP FEATURES")
    print("="*70)
    
    gap_features_list = []
    
    for stock in df['Stock'].unique():
        stock_df = df[df['Stock'] == stock].copy()
        stock_df = stock_df.sort_values('Date').reset_index(drop=True)
        
        for idx in range(len(stock_df)):
            try:
                row = stock_df.iloc[idx]
                current_date = str(row['Date'])
                today_open = float(row['Open'])
                
                prev_day_close = None
                if idx > 0:
                    prev_day_close = float(stock_df.iloc[idx - 1]['Close'])
                
                gap_pct = None
                if prev_day_close is not None and prev_day_close != 0:
                    gap_pct = ((today_open - prev_day_close) / prev_day_close) * 100
                
                today_volume = float(row['Volume'])
                prev_day_volume = None
                if idx > 0:
                    prev_day_volume = float(stock_df.iloc[idx - 1]['Volume'])
                    
                day_before_volume = None
                if idx > 1:
                    day_before_volume = float(stock_df.iloc[idx - 2]['Volume'])
                
                volume_change_pct = None
                if day_before_volume is not None and day_before_volume != 0 and prev_day_volume is not None:
                    # Match JS pipeline: primary logic is Yesterday vs Day Before
                    volume_change_pct = ((prev_day_volume - day_before_volume) / day_before_volume) * 100
                elif prev_day_volume is not None and prev_day_volume != 0:
                    # Fallback
                    volume_change_pct = ((today_volume - prev_day_volume) / prev_day_volume) * 100
            except (ValueError, TypeError):
                continue
            
            gap_features_list.append({
                'Date': current_date,
                'Stock': stock,
                'Open': today_open,
                'Prev_Close': prev_day_close,
                'Gap_Pct': gap_pct,
                'Volume_Change_Pct': volume_change_pct
            })
    
    gap_df = pd.DataFrame(gap_features_list)
    
    print(f"\n[OK] Computed gap features for {len(gap_df):,} stock-day combinations")
    if not gap_df.empty:
        print(f"    Stocks: {gap_df['Stock'].nunique()}")
        print(f"    Date range: {gap_df['Date'].min()} to {gap_df['Date'].max()}")
    
    return gap_df

# ============================================================================
# MAIN EXECUTION
# ============================================================================
import os

def main():
    print("\n" + "="*70)
    print("YAHOO FINANCE DATA FETCHER - INCREMENTAL UPDATE")
    print("="*70)
    
    import os
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
    output_file1 = os.path.join(SCRIPT_DIR, 'yahoo_finance_all_stocks_2015_2026_ohlc.csv')
    output_file2 = os.path.join(SCRIPT_DIR, 'yahoo_finance_all_stocks_2015_2026_gap_features.csv')
    
    # Determine start_date based on existing gap features file
    if os.path.exists(output_file2):
        try:
            existing = pd.read_csv(output_file2, usecols=['Date'])
            last_date_str = existing['Date'].max()
            last_date_obj = datetime.strptime(last_date_str, '%Y-%m-%d').date()
            # Fetch from 10 days before to compute gap for the new dates correctly
            start_date = last_date_obj - timedelta(days=10)
            print(f"Found existing data up to {last_date_str}.")
        except Exception as e:
            print(f"Error reading {output_file2}: {e}")
            last_date_str = '2015-01-01'
            start_date = datetime(2015, 1, 1).date()
    else:
        last_date_str = '2015-01-01'
        start_date = datetime(2015, 1, 1).date()

    end_date = datetime.now().date() + timedelta(days=1)
    
    if datetime.now().date() <= datetime.strptime(last_date_str, '%Y-%m-%d').date():
        print(f"Data is already up to date ({last_date_str}).")
        return
    
    print(f"\nFetching data incrementally")
    print(f"Start: {start_date}")
    print(f"End: {end_date}")
    print(f"Duration: {(end_date - start_date).days} days (~11 years)")
    
    # Fetch data in parallel (10 workers)
    df = fetch_all_stocks_parallel(STOCKS, str(start_date), str(end_date), max_workers=10)
    
    if df.empty:
        print("[ERROR] No data fetched")
        return
    
    # Compute gap features for fetched data
    gap_df = compute_gap_features_from_yahoo(df)
    
    # Filter only new dates
    df_new = df[df['Date'] > last_date_str]
    gap_df_new = gap_df[gap_df['Date'] > last_date_str] if not gap_df.empty else pd.DataFrame()
    
    if df_new.empty or gap_df_new.empty:
        print("[WARNING] No new data found for the missing dates.")
        return
        
    print(f"\nFound {len(gap_df_new)} new gap feature rows to insert after {last_date_str}.")
    
    # Save/Append raw data
    header1 = not os.path.exists(output_file1)
    df_new.to_csv(output_file1, mode='a', index=False, header=header1)
    print(f"\n[OK] Appended {len(df_new):,} rows to: {output_file1}")
    
    # Save/Append gap features
    header2 = not os.path.exists(output_file2)
    gap_df_new.to_csv(output_file2, mode='a', index=False, header=header2)
    print(f"[OK] Appended {len(gap_df_new):,} rows to: {output_file2}")
    
    # For statistics, use the new data
    gap_df = gap_df_new
    
    # Display statistics
    print("\n" + "="*70)
    print("GAP FEATURES STATISTICS")
    print("="*70)
    
    if not gap_df.empty:
        print(f"\nGap % statistics:")
        print(gap_df['Gap_Pct'].describe())
        
        print(f"\nVolume Change % statistics:")
        print(gap_df['Volume_Change_Pct'].describe())
        
        print("\n" + "="*70)
        print("SAMPLE DATA")
        print("="*70)
        
        print("\nTop 10 largest gaps (up):")
        print(gap_df.nlargest(10, 'Gap_Pct')[['Date', 'Stock', 'Gap_Pct', 'Volume_Change_Pct']])
        
        print("\nTop 10 largest gaps (down):")
        print(gap_df.nsmallest(10, 'Gap_Pct')[['Date', 'Stock', 'Gap_Pct', 'Volume_Change_Pct']])
    
    print("\n" + "="*70)
    print("EXECUTION COMPLETE")
    print("="*70)
    
    return df, gap_df

if __name__ == '__main__':
    result = main()
