
import calendar
import traceback
import logging
from datetime import datetime
import pandas as pd
import os
import sys
import requests
import json
import subprocess
from neo_api_client import NeoAPI

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

BOT_SCRIPT_PATH = '/home/ubuntu/KotakCodes1/status_Info_bot.js'

def send_telegram_message(message):
    try:
        logging.info(f"Sending message to Telegram bot: '{message}'")
        result = subprocess.run(['/usr/bin/node', BOT_SCRIPT_PATH, message], capture_output=True, text=True, check=True)
        logging.info(f"Telegram bot response: {result.stdout}")
        if result.stderr:
            logging.warning(f"Telegram bot stderr: {result.stderr}")
        return result.stdout
    except subprocess.CalledProcessError as e:
        logging.error(f"Error sending message to Telegram bot: {e}")
        logging.error(f"Bot stderr: {e.stderr}")
        return None
    except FileNotFoundError:
        logging.error(f"Telegram bot script not found at: {BOT_SCRIPT_PATH}")
        return None

def process_user(userid):
    logging.info(f"--- Processing userid: {userid} ---")
    try:
        import pyotp
        auth_df = pd.read_csv("/home/ubuntu/KotakCodes1/kotak_auth_userid.csv")
        auth_data = auth_df[auth_df['userid'] == userid]

        if auth_data.empty:
            logging.error(f"User ID '{userid}' not found in kotak_auth_userid.csv.")
            send_telegram_message(f"Kotak API auth failed for user {userid}: not found in CSV.")
            return

        auth_row = auth_data.iloc[0]
        Kotak_user = auth_row['Kotak_user']
        consumer_key = auth_row['consumer_key']
        MPIN = str(int(auth_row['MPIN']))
        mobile_number = str(auth_row.get('mobile_number', '')).strip()
        totp_secret = str(auth_row.get('totp_secret', '')).strip()

        formatted_mobile = mobile_number if mobile_number.startswith('+') else f"+91{mobile_number}"

        client = NeoAPI(consumer_key=consumer_key, environment='prod', neo_fin_key="neotradeapi")

        totp_code = pyotp.TOTP(totp_secret).now()
        login_resp = client.totp_login(mobile_number=formatted_mobile, ucc=userid, totp=totp_code)
        if login_resp and 'error' in login_resp:
            raise Exception(f"TOTP Login Error: {login_resp['error']}")

        val_resp = client.totp_validate(mpin=MPIN)
        if val_resp and 'error' in val_resp:
            raise Exception(f"MPIN Validation Error: {val_resp['error']}")

        logged_in_data = val_resp.get("data", {}) if isinstance(val_resp, dict) else {}
        user_from_API = logged_in_data.get("greetingName", Kotak_user)

        from datetime import timezone, timedelta
        now_ist = (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).strftime('%Y-%m-%d %H:%M:%S IST')
        msg = f"Kotak API V2 login successful for {Kotak_user} ({userid}) at {now_ist}."
        logging.info(msg)
        send_telegram_message(msg)

    except Exception as e:
        from datetime import timezone, timedelta
        now_ist = (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).strftime('%Y-%m-%d %H:%M:%S IST')
        logging.error(f"Exception for user {userid}: {e}")
        traceback.print_exc()
        send_telegram_message(f"Kotak API login failed for user {userid} at {now_ist}. Error: {e}")

# === Main ===
try:
    user_df = pd.read_csv("/home/ubuntu/KotakCodes1/User_table.csv")
    userids = user_df['userid'].dropna().astype(str).str.strip().tolist()

    logging.info(f"Found {len(userids)} userids to process.")
    for userid in userids:
        process_user(userid)

    logging.info("All user logins processed.")
except Exception as e:
    logging.error(f"Critical failure: {e}")
    traceback.print_exc()
