import csv
import os
from datetime import datetime, timedelta

valid_stocks_str = "AARTIIND,ABB,ABBOTINDIA,ABCAPITAL,ABFRL,ACC,ADANIENT,ADANIPORTS,ALKEM,AMBUJACEM,APOLLOHOSP,APOLLOTYRE,ASHOKLEY,ASIANPAINT,ASTRAL,ATUL,AUBANK,AUROPHARMA,AXISBANK,BAJAJ-AUTO,BAJAJFINSV,BAJFINANCE,BALKRISIND,BALRAMCHIN,BANDHANBNK,BANKBARODA,BANKNIFTY,BATAINDIA,BEL,BERGEPAINT,BHARATFORG,BHARTIARTL,BHEL,BIOCON,BOSCHLTD,BPCL,BRITANNIA,BSOFT,CANBK,CANFINHOME,CHAMBLFERT,CHOLAFIN,CIPLA,COALINDIA,COFORGE,COLPAL,CONCOR,COROMANDEL,CROMPTON,CUB,CUMMINSIND,DABUR,DALBHARAT,DEEPAKNTR,DELTACORP,DIVISLAB,DIXON,DLF,DRREDDY,EICHERMOT,ESCORTS,EXIDEIND,FEDERALBNK,FINNIFTY,GAIL,GLENMARK,GMRINFRA,GNFC,GODREJCP,GODREJPROP,GRANULES,GRASIM,GUJGASLTD,HAL,HAVELLS,HCLTECH,HDFCAMC,HDFCBANK,HDFCLIFE,HEROMOTOCO,HINDALCO,HINDCOPPER,HINDPETRO,HINDUNILVR,IBULHSGFIN,ICICIBANK,ICICIGI,ICICIPRULI,IDEA,IDFC,IDFCFIRSTB,IEX,IGL,INDHOTEL,INDIACEM,INDIAMART,INDIGO,INDUSINDBK,INDUSTOWER,INFY,IOC,IPCALAB,IRCTC,ITC,JINDALSTEL,JKCEMENT,JSWSTEEL,JUBLFOOD,KOTAKBANK,L&TFH,LALPATHLAB,LAURUSLABS,LICHSGFIN,LT,LTF,LTIM,LTTS,LUPIN,M&M,M&MFIN,MANAPPURAM,MARICO,MARUTI,MCDOWELL-N,MCX,METROPOLIS,MFSL,MGL,MIDCPNIFTY,MOTHERSON,MPHASIS,MRF,MUTHOOTFIN,NATIONALUM,NAUKRI,NAVINFLUOR,NESTLEIND,NIFTY,NIFTY NEXT 50,NMDC,NTPC,OBEROIRLTY,OFSS,ONGC,PAGEIND,PEL,PERSISTENT,PETRONET,PFC,PIDILITIND,PIIND,PNB,POLYCAB,POWERGRID,PVRINOX,RAMCOCEM,RBLBANK,RECLTD,RELIANCE,SAIL,SBICARD,SBILIFE,SBIN,SHREECEM,SHRIRAMFIN,SIEMENS,SRF,SUNPHARMA,SUNTV,SYNGENE,TATACHEM,TATACOMM,TATACONSUM,TATAMOTORS,TATAPOWER,TATASTEEL,TCS,TECHM,TITAN,TORNTPHARM,TRENT,TVSMOTOR,UBL,ULTRACEMCO,UNITDSPR,UPL,VEDL,VOLTAS,WIPRO,ZEEL,ZYDUSLIFE"
valid_stocks = [s.strip() for s in valid_stocks_str.split(",")]

# 2. Dynamic Expiry Dates Parser
def get_all_expiry_dates():
    """Parses all unique contract expiry dates from config/historical_lotsize_new.csv."""
    try:
        import pandas as pd
        SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
        parent_dir = os.path.dirname(SCRIPT_DIR)
        lotsize_file = os.path.join(parent_dir, "config", "historical_lotsize_new.csv")
        if os.path.exists(lotsize_file):
            df_lotsize = pd.read_csv(lotsize_file)
            expdates = pd.to_datetime(df_lotsize['expdate'], format='%d/%m/%Y').dt.date.unique()
            print(f"✔ Successfully loaded {len(expdates)} dynamic contract expiry dates.")
            return set(expdates)
    except Exception as e:
        print(f"⚠️ Warning: Failed to dynamically load expiry dates from config: {e}")
    
    return set()

expiry_set = get_all_expiry_dates()


def get_latest_trading_date():
    """Queries scrapdata_F1 MySQL to find the latest date strictly less than today."""
    try:
        import mysql.connector
        conn = mysql.connector.connect(
            host="localhost",
            user="root",
            password="root",
            database="markets"
        )
        cursor = conn.cursor()
        today_str = datetime.now().date().strftime('%Y-%m-%d')
        cursor.execute("SELECT MAX(date) FROM scrapdata_F1 WHERE date < %s", (today_str,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        if row and row[0]:
            # row[0] is returned as a datetime.date object from mysql.connector
            print(f"✔ Successfully queried MySQL. Latest trading date on scrapdata_F1 is: {row[0]}")
            return row[0]
    except Exception as e:
        print(f"⚠️ Warning: Failed to query MySQL for latest date: {e}")
    
    # Fallback to standard yesterday date
    yesterday = datetime.now().date() - timedelta(days=1)
    print(f"ℹ Using fallback yesterday calculation: {yesterday}")
    return yesterday

# 3. Target Date: Dynamically fetch latest trading day
target_date = get_latest_trading_date()

records = []

# Verify target_date is not in expiry_set
if target_date not in expiry_set:
    date_str = target_date.strftime("%Y%m%d")
    for stock in valid_stocks:
        records.append((date_str, stock))
    # Sort alphabetically by stock name
    records.sort(key=lambda x: x[1])
    is_expiry_skipped = False
else:
    print(f"⚠️ SKIPPING ORDER GENERATION: Target date {target_date.strftime('%Y-%m-%d')} is an official contract expiry date!")
    is_expiry_skipped = True

# 4. Resolve paths relative to script location
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(SCRIPT_DIR)  # Resolve back to project root
filename = os.path.join(parent_dir, 'output', 'simulation_results', 'ordersheetforsimulation.csv')
os.makedirs(os.path.dirname(filename), exist_ok=True)

# 5. Write to CSV
with open(filename, 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerows(records)

if is_expiry_skipped:
    print(f"✔ Cleaned and wrote 0-row empty ordersheet at {filename} to skip simulation.")
else:
    print(f"Success! Generated {len(records)} orders for target date ({target_date.strftime('%Y-%m-%d')}) in {filename}")
