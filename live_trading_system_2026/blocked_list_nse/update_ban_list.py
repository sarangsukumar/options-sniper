import pandas as pd
import os
import sys
from datetime import datetime, timedelta
import json
import time
import requests

def get_latest_banned_date(ban_list_path, checkpoint_path):
    """
    Finds the latest date processed. First checks the checkpoint file to avoid redundant fetches.
    Falls back to the maximum date in the CSV if the checkpoint is missing.
    """
    if os.path.exists(checkpoint_path):
        try:
            with open(checkpoint_path, 'r') as f:
                date_str = f.read().strip()
                return datetime.strptime(date_str, "%Y-%m-%d").date()
        except Exception as e:
            print(f"⚠️ Warning: Could not read checkpoint file: {e}")
            
    if not os.path.exists(ban_list_path) or os.stat(ban_list_path).st_size == 0:
        return datetime.strptime("2015-01-01", "%Y-%m-%d").date()
    
    try:
        df = pd.read_csv(ban_list_path)
        df['parsed_date'] = pd.to_datetime(df['date'], dayfirst=True, format='mixed')
        max_date = df['parsed_date'].max().date()
        return max_date
    except Exception as e:
        print(f"⚠️ Warning: Could not read max date from CSV: {e}")
        return datetime.strptime("2015-01-01", "%Y-%m-%d").date()

def generate_date_range_to_today(start_date):
    """
    Generates list of dates (in DD-MMM-YYYY format) from start_date + 1 day to today.
    """
    today = datetime.now().date()
    if start_date >= today:
        print(f"ℹ Ban list is already up to date (Latest processed: {start_date}, Today: {today}).")
        return []
    
    date_list = []
    current_date = start_date + timedelta(days=1)
    while current_date <= today:
        # Format as '24-Jul-2026'
        date_list.append(current_date.strftime('%d-%b-%Y'))
        current_date += timedelta(days=1)
    return date_list

def run_update():
    ban_list_path = '/home/ubuntu/banlist/fo_ban_list_historical.csv'
    checkpoint_path = '/home/ubuntu/banlist/last_checked_date.txt'
    os.makedirs(os.path.dirname(ban_list_path), exist_ok=True)
    
    # 1. Detect gap in dates
    print("=========================================================================")
    print("             NSE F&O BAN LIST - AUTOMATED SYNC & FILL SYSTEM")
    print("=========================================================================")
    print(f"Checking current ban list status at {ban_list_path}...")
    
    latest_date = get_latest_banned_date(ban_list_path, checkpoint_path)
    print(f"✔ Latest processed date: {latest_date.strftime('%Y-%m-%d')}")
    
    target_dates = generate_date_range_to_today(latest_date)
    if not target_dates:
        print("🎉 No update required. Your F&O ban list is fully up to date.")
        print("=========================================================================")
        
        # Send Telegram Notification for today's status anyway
        try:
            import subprocess
            df = pd.read_csv(ban_list_path)
            df['parsed_date'] = pd.to_datetime(df['date'], dayfirst=True, format='mixed')
            today_date = datetime.now().date()
            today_banned = df[df['parsed_date'].dt.date == today_date]['stock_name'].tolist()
            
            if today_banned:
                msg = f"⛔ <b>F&O Ban List Status</b>\nToday ({today_date}): {', '.join(today_banned)}"
            else:
                msg = f"✅ <b>F&O Ban List Status</b>\nToday ({today_date}): No stocks in ban period."
                
            subprocess.run(['node', '/home/ubuntu/KotakCodes1/status_Info_bot.js', msg], check=True, timeout=10)
            print("✔ Sent Telegram notification via status bot.")
        except Exception as e_tg:
            print(f"⚠️ Failed to send Telegram notification: {e_tg}")
            
        return
    
    print(f"🚀 Found {len(target_dates)} missing day(s) to fetch: {target_dates}")
    print("=========================================================================")
    
    # Initialize Requests Session with clean browser headers
    session = requests.Session()
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9',
        'Referer': 'https://www.nseindia.com/'
    }
    
    success_all = True
    try:
        # Establish session cookies by hitting homepage
        print("📡 Establishing session with NSE India homepage...")
        homepage_res = session.get('https://www.nseindia.com', headers=headers, timeout=10)
        if homepage_res.status_code == 200:
            print("✔ Session cookies successfully established. Beginning API downloads...")
        else:
            print(f"⚠️ Warning: Landing page status code {homepage_res.status_code}. Proceeding anyway...")
            
        all_new_records = []
        
        for idx, date_str in enumerate(target_dates, 1):
            print(f"🔄 [{idx}/{len(target_dates)}] Fetching F&O ban list for: {date_str} ...")
            
            # Construct API URL
            url = f"https://www.nseindia.com/api/reports?archives=%5B%7B%22name%22%3A%22F%26O%20-%20Security%20in%20ban%20period%22%2C%22type%22%3A%22archives%22%2C%22category%22%3A%22derivatives%22%2C%22section%22%3A%22equity%22%7D%5D&date={date_str}&type=equity&mode=single"
            
            # Format date for CSV (DD-MM-YYYY)
            date_obj = datetime.strptime(date_str, '%d-%b-%Y')
            csv_date_str = date_obj.strftime('%d-%m-%Y')
            
            try:
                res = session.get(url, headers=headers, timeout=15)
                banned_symbols = []
                
                if res.status_code == 200:
                    raw_text = res.text
                    
                    # Try to parse as JSON first
                    try:
                        data = res.json()
                        if 'data' in data and isinstance(data['data'], list):
                            for item in data['data']:
                                if 'symbol' in item:
                                    banned_symbols.append(item['symbol'].strip().upper())
                    except Exception:
                        # Fallback to parsing text format
                        if "Securities in Ban For Trade Date" in raw_text:
                            if "NIL" in raw_text:
                                pass # No symbols
                            else:
                                lines = raw_text.split('\n')
                                for line in lines:
                                    line = line.strip()
                                    if line and line.startswith(('1,', '2,', '3,', '4,', '5,', '6,', '7,', '8,', '9,')) and ',' in line:
                                        parts = line.split(',', 1)
                                        if len(parts) > 1:
                                            banned_symbols.append(parts[1].strip().upper())
                                            
                elif res.status_code == 404:
                    print(f"  ℹ No reports found for {date_str} (likely a weekend or holiday - HTTP 404).")
                else:
                    print(f"  ⚠️ HTTP Error {res.status_code} for {date_str}.")
                    success_all = False
                    
                if banned_symbols:
                    banned_symbols = [s for s in banned_symbols if s and s != "NIL"]
                    if banned_symbols:
                        print(f"  🟢 Found {len(banned_symbols)} banned stock(s): {banned_symbols}")
                        for symbol in banned_symbols:
                            all_new_records.append({'date': csv_date_str, 'stock_name': symbol})
                    else:
                        print(f"  ℹ No active banned stocks found.")
                elif res.status_code == 200:
                    print(f"  ℹ No active banned stocks found.")
                    
            except Exception as e_fetch:
                print(f"  ❌ Error fetching data for {date_str}: {e_fetch}")
                success_all = False
                
            time.sleep(1.0)  # Safe delay between calls to respect NSE rate limits
            
        # 3. Save new entries to master file
        if all_new_records:
            df_new = pd.DataFrame(all_new_records)
            
            if os.path.exists(ban_list_path) and os.stat(ban_list_path).st_size > 0:
                df_existing = pd.read_csv(ban_list_path)
                df_combined = pd.concat([df_existing, df_new], ignore_index=True)
                df_combined.drop_duplicates(subset=['date', 'stock_name'], keep='first', inplace=True)
            else:
                df_combined = df_new
                
            df_combined.to_csv(ban_list_path, index=False)
            print(f"\n✔ Success! Appended {len(all_new_records)} new records. Master ban list now has {len(df_combined)} rows total.")
        else:
            print("\n✔ Update complete. No new banned stocks were found across the missing range.")
            
        # 4. Save checkpoint to avoid redundant downloads in the future
        if success_all:
            today_str = datetime.now().strftime('%Y-%m-%d')
            try:
                with open(checkpoint_path, 'w') as f:
                    f.write(today_str)
                print(f"✔ Checkpoint saved. Latest checked date updated to: {today_str}")
            except Exception as e_cp:
                print(f"⚠️ Error saving checkpoint file: {e_cp}")
                
        # 5. Send Telegram Notification
        try:
            import subprocess
            df = pd.read_csv(ban_list_path)
            df['parsed_date'] = pd.to_datetime(df['date'], dayfirst=True, format='mixed')
            today_date = datetime.now().date()
            today_banned = df[df['parsed_date'].dt.date == today_date]['stock_name'].tolist()
            
            if today_banned:
                msg = f"⛔ <b>F&O Ban List Updated</b>\nToday ({today_date}): {', '.join(today_banned)}"
            else:
                msg = f"✅ <b>F&O Ban List Updated</b>\nToday ({today_date}): No stocks in ban period."
                
            subprocess.run(['node', '/home/ubuntu/KotakCodes1/status_Info_bot.js', msg], check=True, timeout=10)
            print("✔ Sent Telegram notification via status bot.")
        except Exception as e_tg:
            print(f"⚠️ Failed to send Telegram notification: {e_tg}")
            
    finally:
        session.close()
        print("✔ Session closed safely.")
        print("=========================================================================")

if __name__ == "__main__":
    run_update()
