import calendar
import csv
from datetime import datetime

import pandas as pd
from neo_api_client import NeoAPI
import requests

filename = '/home/ubuntu/KotakCodes1/masterfile/kotakneoscripcodemap_historical.csv'

# --- API Authentication & Login (V2 TOTP Flow) ---
import pyotp

auth_df = pd.read_csv("/home/ubuntu/KotakCodes1/kotak_auth_userid.csv")
auth_row = auth_df[auth_df['userid'] == 'ZCK30'].iloc[0]

consumer_key = auth_row['consumer_key']
mobile_number = str(auth_row['mobile_number']).strip()
totp_secret = str(auth_row['totp_secret']).strip()
mpin = str(int(auth_row['MPIN']))

formatted_mobile = mobile_number if mobile_number.startswith('+') else f"+91{mobile_number}"

client = NeoAPI(consumer_key=consumer_key, environment='prod', neo_fin_key="neotradeapi")

# --- Date and Time Calculations ---
today = datetime.now()
datetoday = today.strftime("%d")
monthtoday = today.strftime("%m")
yeartoday = today.strftime("%y")
yearupdated = 0
todaysdate = today.strftime("%Y-%m-%d")

month_shortname = calendar.month_abbr[int(monthtoday)].upper()
nextmonth_shortname = calendar.month_abbr[(today.month % 12) + 1].upper()

try:
    totp_code = pyotp.TOTP(totp_secret).now()
    login_resp = client.totp_login(mobile_number=formatted_mobile, ucc='ZCK30', totp=totp_code)
    val_resp = client.totp_validate(mpin=mpin)

    if val_resp and (val_resp.get('stCode') == 200 or (isinstance(val_resp.get('data'), dict) and val_resp.get('data', {}).get('status') == 'success')):
        print("NEO client logged in successfully via V2 TOTP")
    else:
        print("Error during API initialization or login:", val_resp)
except Exception as e:
    print("Error during API initialization or login:", e)

# --- Scrip Data Retrieval and Processing ---
todaysdf = pd.DataFrame()
validstocks = ["AARTIIND", "ABB", "ABBOTINDIA", "ABCAPITAL", "ABFRL", "ACC", "ADANIENT", "ADANIPORTS", 
               "ALKEM", "AMBUJACEM", "APOLLOHOSP", "APOLLOTYRE", "ASHOKLEY", "ASIANPAINT", "ASTRAL", "ATUL", 
               "AUBANK", "AUROPHARMA", "AXISBANK", "BAJAJ-AUTO", "BAJAJFINSV", "BAJFINANCE", "BALKRISIND", 
               "BALRAMCHIN", "BANDHANBNK", "BANKBARODA", "BANKNIFTY", "BATAINDIA", "BEL", "BERGEPAINT", 
               "BHARATFORG", "BHARTIARTL", "BHEL", "BIOCON", "BOSCHLTD", "BPCL", "BRITANNIA", "BSOFT", "CANBK", 
               "CANFINHOME", "CHAMBLFERT", "CHOLAFIN", "CIPLA", "COALINDIA", "COFORGE", "COLPAL", "CONCOR", 
               "COROMANDEL", "CROMPTON", "CUB", "CUMMINSIND", "DABUR", "DALBHARAT", "DEEPAKNTR", "DIVISLAB", 
               "DIXON", "DLF", "DRREDDY", "EICHERMOT", "ESCORTS", "EXIDEIND", "FEDERALBNK", "FINNIFTY", "GAIL", 
               "GLENMARK", "GMRINFRA", "GNFC", "GODREJCP", "GODREJPROP", "GRANULES", "GRASIM", "GUJGASLTD", "HAL", 
               "HAVELLS", "HCLTECH", "HDFCAMC", "HDFCBANK", "HDFCLIFE", "HEROMOTOCO", "HINDALCO", "HINDCOPPER", 
               "HINDPETRO", "HINDUNILVR", "ICICIBANK", "ICICIGI", "ICICIPRULI", "IDEA", "IDFC", "IDFCFIRSTB", "IEX", 
               "IGL", "INDHOTEL", "INDIAMART", "INDIGO", "INDUSINDBK", "INDUSTOWER", "INFY", "IOC", "IPCALAB", 
               "IRCTC", "ITC", "JINDALSTEL", "JKCEMENT", "JSWSTEEL", "JUBLFOOD", "KOTAKBANK", "LTF", "LALPATHLAB", 
               "LAURUSLABS", "LICHSGFIN", "LT", "LTIM", "LTTS", "LUPIN", "M&M", "MANAPPURAM", "MARICO", "MARUTI", 
               "MCDOWELL-N", "MCX", "METROPOLIS", "MFSL", "MGL", "MOTHERSON", "MPHASIS", "MRF", "MUTHOOTFIN", 
               "NATIONALUM", "NAUKRI", "NAVINFLUOR", "NESTLEIND", "NIFTY", "NMDC", "NTPC", "OBEROIRLTY", "OFSS", 
               "ONGC", "PAGEIND", "PEL", "PERSISTENT", "PETRONET", "PFC", "PIDILITIND", "PIIND", "PNB", "POLYCAB", 
               "POWERGRID", "PVRINOX", "RAMCOCEM", "RBLBANK", "RECLTD", "RELIANCE", "SAIL", "SBICARD", "SBILIFE", 
               "SBIN", "SHREECEM", "SHRIRAMFIN", "SIEMENS", "SRF", "SUNPHARMA", "SUNTV", "SYNGENE", "TATACHEM", 
               "TATACOMM", "TATACONSUM", "TATAMOTORS", "TATAPOWER", "TATASTEEL", "TCS", "TECHM", "TITAN", 
               "TORNTPHARM", "TRENT", "TVSMOTOR", "UBL", "ULTRACEMCO", "UPL", "VEDL", "VOLTAS", "WIPRO", "ZEEL", 
               "ZYDUSLIFE"]


for stockname in validstocks:
    try:
        data = client.search_scrip(exchange_segment="nse_fo", symbol=stockname, expiry="", option_type="", strike_price="")
        if not data or not isinstance(data, list) or len(data) == 0:
            print(f"{stockname} not found, skipping...")
            continue
        print(f"API success for {stockname}")
    except Exception as e:
        print(f"Exception when calling scrip search API for {stockname}: {e}")
        continue

    scripcode = None
    lot_size = None
    expiry_day = None

    for item in data:
        if not isinstance(item, dict):
            continue
        trd_sym = item.get('pTrdSymbol', '')
        if trd_sym.endswith("FUT") and item.get('pInstType') == 'FUTSTK':
            if month_shortname in trd_sym:
                scripcode = trd_sym
                lot_size = item.get("lLotSize", 0)
                try:
                    expiry_day = int(item.get("pExpiryDate", "")[:2])
                except Exception:
                    expiry_day = 28
                break
            elif nextmonth_shortname in trd_sym and not scripcode:
                scripcode = trd_sym
                lot_size = item.get("lLotSize", 0)
                try:
                    expiry_day = int(item.get("pExpiryDate", "")[:2])
                except Exception:
                    expiry_day = 28

    if not scripcode:
        print(f"No future contract found for {stockname}, skipping...")
        continue

    # Create DataFrame and append to todaysdf
    df = pd.DataFrame({'stockname': stockname, 'scripcode': scripcode, 'lot_size': lot_size, 
                       'credate': todaysdate, 'expiry_day': expiry_day}, index=[0])
    todaysdf = pd.concat([todaysdf, df], ignore_index=True)
    print(df)

# --- Save Data to CSV ---
try:
    existing_csv_path = "/home/ubuntu/KotakCodes1/kotakneoscripcodemap.csv"
    existing_df = pd.read_csv(existing_csv_path) if os.path.exists(existing_csv_path) else pd.DataFrame()
    combined_df = pd.concat([todaysdf, existing_df], ignore_index=True)
    combined_df.to_csv(filename, index=False)
    print(f"Successfully saved updated scrip map to {filename}")

    # Send Telegram Status Alert
    import subprocess
    import os
    from datetime import datetime, timezone, timedelta
    total_count = len(todaysdf)
    now_str = (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).strftime('%Y-%m-%d %H:%M:%S IST')
    
    msg = f"Kotak Scrip Code Map updated successfully at {now_str}!\nTotal Stocks Mapped: {total_count} stocks\n"
    if total_count > 0:
        sample1 = todaysdf.iloc[0]
        msg += f"\nSample Verification:\n• Stock: {sample1['stockname']} ➔ {sample1['scripcode']} (Lot Size: {sample1['lot_size']})"
        if total_count > 1:
            sample2 = todaysdf.iloc[1]
            msg += f"\n• Stock: {sample2['stockname']} ➔ {sample2['scripcode']} (Lot Size: {sample2['lot_size']})"
            
    bot_script = '/home/ubuntu/KotakCodes1/status_Info_bot.js'
    print(f"Sending Telegram alert:\n{msg}")
    subprocess.run(['node', bot_script, msg], check=True)

except Exception as e:
    print("Error in reading or writing scrip code file")
    print(e)