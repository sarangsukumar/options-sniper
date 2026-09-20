#!/usr/bin/env python3
import os
import sys
# Fallback to local site-packages for dependencies
sys.path.insert(0, '/home/ubuntu/.local/lib/python3.10/site-packages')
import pandas as pd
import subprocess
import requests
import datetime
from breeze_connect import BreezeConnect

# Disable TLS warning
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def get_formatted_timestamp():
    # IST is UTC + 5:30
    ist_time = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)
    return ist_time.strftime('%Y-%m-%d %H:%M:%S IST')

def send_telegram_notification(message):
    token = "7920868588:AAE4mPlDQJWnkv9CbmHO8idiSBVnP7K0Gko"
    chat_id = "-1002365534285"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        'chat_id': chat_id,
        'text': message,
        'parse_mode': 'HTML'
    }
    try:
        r = requests.post(url, data=payload, timeout=10, verify=False)
        print(f"[Telegram Sent]: {message}")
        return r.json()
    except Exception as e:
        print(f"[Telegram Error]: {e}")
        return None

def read_session_token(file_path):
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r') as f:
                token = f.read().strip()
                return token if len(token) > 0 else None
        except Exception as e:
            print(f"Error reading session file {file_path}: {e}")
    return None

def run_otp_script_for_user(username):
    script_name = '2.OTP_Manisha.py' if username.lower() == 'manisha' else '2.OTP_Amrit.py'
    script_path = os.path.join('/home/ubuntu/KotakCodes1/ICICI', script_name)
    
    # Ensure PYTHONPATH is passed so selenium is found!
    env = os.environ.copy()
    env['PYTHONPATH'] = '/home/ubuntu/.local/lib/python3.10/site-packages'
    cmd = ['/usr/bin/python3', script_path, '--force']
    print(f"[User: {username}] Launching OTP script: {' '.join(cmd)}")
    result = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if result.stdout:
        print(f"[User: {username}] OTP stdout:\n{result.stdout}")
    if result.stderr:
        print(f"[User: {username}] OTP stderr:\n{result.stderr}")
    if result.returncode != 0:
        raise Exception(f"OTP script failed with exit code {result.returncode}")

def verify_user_session(row):
    username = str(row['username']).strip()
    api_username = str(row['api_username']).strip()
    appKey = str(row['appKey']).strip()
    appSecret = str(row['appSecret']).strip()
    sessionFilePath = str(row['sessionFilePath']).strip()

    print(f"\n=======================================================")
    print(f"[ICICI Check] Processing user: {username} ({api_username})")
    print(f"[Session Path] {sessionFilePath}")
    print(f"=======================================================")

    sessionToken = read_session_token(sessionFilePath)

    if not sessionToken:
        print(f"[User: {username}] No existing token found. Running OTP generator...")
        try:
            run_otp_script_for_user(username)
            sessionToken = read_session_token(sessionFilePath)
        except Exception as e:
            time_str = get_formatted_timestamp()
            msg = f"ICICI Breeze API login failed for {username} ({api_username}) at {time_str}. Error generating OTP: {e}"
            print(f"[User: {username}] {msg}")
            send_telegram_notification(msg)
            return

    if not sessionToken:
        time_str = get_formatted_timestamp()
        msg = f"ICICI Breeze API login failed for {username} ({api_username}) at {time_str}. Error: Session token file empty after OTP run."
        print(f"[User: {username}] {msg}")
        send_telegram_notification(msg)
        return

    breeze = BreezeConnect(api_key=appKey)
    authenticated = False
    auth_error = None

    try:
        print(f"[User: {username}] Authenticating with token: {sessionToken}")
        # Validate session by calling generate_session in breeze_connect
        breeze.generate_session(api_secret=appSecret, session_token=sessionToken)
        authenticated = True
    except Exception as err:
        auth_error = str(err)
        print(f"[User: {username}] Initial session auth failed ({auth_error}). Triggering OTP refresh...")

    if not authenticated:
        try:
            run_otp_script_for_user(username)
            sessionToken = read_session_token(sessionFilePath)
            if sessionToken:
                print(f"[User: {username}] Retrying authentication with fresh token: {sessionToken}")
                breeze = BreezeConnect(api_key=appKey)
                breeze.generate_session(api_secret=appSecret, session_token=sessionToken)
                authenticated = True
        except Exception as err:
            auth_error = str(err)

    time_str = get_formatted_timestamp()
    if authenticated:
        msg = f"ICICI Breeze API login successful for {username} ({api_username}) at {time_str}. Session Token: {sessionToken}"
        print(f"[User: {username}] SUCCESS: {msg}")
        send_telegram_notification(msg)
    else:
        msg = f"ICICI Breeze API login failed for {username} ({api_username}) at {time_str}. Error: {auth_error}"
        print(f"[User: {username}] FAILED: {msg}")
        send_telegram_notification(msg)

def main():
    try:
        csv_path = '/home/ubuntu/KotakCodes1/ICICI/icici_auth.csv'
        if not os.path.exists(csv_path):
            print(f"CSV file not found: {csv_path}")
            sys.exit(1)
        users_df = pd.read_csv(csv_path)
        print(f"Loaded {len(users_df)} ICICI user(s) from CSV.")
        for _, row in users_df.iterrows():
            verify_user_session(row)
        print("\n✅ All ICICI user session checks completed.")
    except Exception as e:
        print(f"Critical error in ICICI checker: {e}")

if __name__ == '__main__':
    main()
