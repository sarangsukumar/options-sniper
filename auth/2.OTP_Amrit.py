import os
import logging
import time
import imaplib
import email
import traceback
import datetime
import sys
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# -----------------------------------------------------------------------------
# Configuration & Suppressing Unwanted Logs/Warnings
# -----------------------------------------------------------------------------
os.environ['WDM_LOG_LEVEL'] = '0'  # Suppress Webdriver Manager logs
logging.getLogger('webdriver_manager').setLevel(logging.ERROR)
logging.getLogger('urllib3').setLevel(logging.ERROR)

# -----------------------------------------------------------------------------
# Utility Functions
# -----------------------------------------------------------------------------
def read_first_line(filename):
    try:
        with open(filename, 'r') as file:
            first_line = file.readline().strip()
            return first_line if first_line else 0
    except FileNotFoundError:
        print(f"[Error] File '{filename}' not found.")
        return 0

def update_file_content(filename, new_content, mode='w'):
    try:
        with open(filename, mode) as file:
            file.write(new_content)
    except FileNotFoundError:
        with open(filename, 'w') as file:
            file.write(new_content)

def is_session_valid(filename):
    if not os.path.exists(filename):
        return False
    token = read_first_line(filename)
    if token == 0 or token == '0' or not token:
        return False
    
    # Check if the file was modified on today's calendar date
    file_mtime = os.path.getmtime(filename)
    file_date = datetime.datetime.fromtimestamp(file_mtime).date()
    return file_date == datetime.date.today()

# -----------------------------------------------------------------------------
# Main Execution Flow
# -----------------------------------------------------------------------------
# Use absolute path relative to script directory
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
filename = os.path.join(SCRIPT_DIR, 'icicisession.txt')
existing_token = read_first_line(filename)

print(f"[Info] Existing session token: {existing_token}")

# Check if we should skip regeneration
force_regeneration = '--force' in sys.argv
if is_session_valid(filename) and not force_regeneration:
    print("[Success] Session token is already valid (generated today). Skipping regeneration.")
    print("[Info] To force a refresh, run the script with: python 2.OTP_Amrit.py --force")
    sys.exit(0)

print("[Info] Token is either expired, missing, or --force was specified. Regenerating...")

ORG_EMAIL = "@yahoo.co.in"
FROM_EMAIL = "amritpk" + ORG_EMAIL
FROM_PWD = "ynsabowwxlkquqzn"
SMTP_SERVER = "imap.mail.yahoo.com"
SMTP_PORT = 993
KEYWORD = "OTP for login to your ICICI Direct account"

def read_email_from_gmail():
    print("[Email] Waiting 20 seconds for the OTP email to arrive...")
    time.sleep(20)
    try:
        m = imaplib.IMAP4_SSL(SMTP_SERVER, SMTP_PORT)
        m.login(FROM_EMAIL, FROM_PWD)
        m.select('INBOX')

        typ, data = m.search(None, '(UNSEEN SUBJECT "' + KEYWORD + '")')
        latestOTP = 0
        for num in data[0].split():
            typ, data = m.fetch(num, '(RFC822.SIZE BODY[HEADER.FIELDS (SUBJECT)])')
            txt = data[0][1]
            temp = [int(s) for s in txt.split() if s.isdigit()]
            latestOTP = temp[0]
            m.store(num, '+FLAGS', '\\Seen')
        return latestOTP
    except Exception as e:
        traceback.print_exc()
        print("[Error] Critical issue retrieving OTP from email.")
        print(str(e))
        return 0

# Chrome Webdriver Setup (Headless & Silent)
options = Options()
options.add_argument('--headless')
options.add_argument('--no-sandbox')
options.add_argument('--disable-dev-shm-usage')
options.add_argument('--log-level=3')  # Silence Chrome logs
options.add_experimental_option('excludeSwitches', ['enable-logging'])  # Suppress DevTools console messages

print("[Browser] Launching headless Chrome browser...")
chromedriver_path = '/usr/bin/chromedriver'
driver = webdriver.Chrome(service=Service(chromedriver_path), options=options)

try:
    print("[Browser] Navigating to ICICI login...")
    driver.get("https://api.icicidirect.com/apiuser/login?api_key=77059JQ7633PoSc1mk465580B6wp1x04")

    # Enter credentials
    username_field = driver.find_element(By.ID, "txtuid")
    username_field.send_keys("AMRCC001")

    password_field = driver.find_element(By.ID, "txtPass")
    password_field.send_keys("Bharat@3451")

    # Accept Terms & Conditions Checkbox
    checkbox = driver.find_element(By.CSS_SELECTOR, "input[type='checkbox']")
    checkbox.click()

    # Click Submit
    login_button = driver.find_element(By.ID, "btnSubmit")
    login_button.click()
    print("[Login] Credentials submitted. Fetching OTP...")

    # Fetch OTP
    otp = read_email_from_gmail()
    if not otp:
        raise Exception("Failed to retrieve OTP from email.")
        
    print("[Login] OTP retrieved. entering security code...")

    # Wait for the OTP field
    otp_field = WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, "input[tg-nm='otp']"))
    )

    # Input OTP character-by-character
    for char in str(otp):
        otp_field.send_keys(char)
        active_element = driver.switch_to.active_element
        otp_field = active_element
        time.sleep(1)

    # Click Submit on the OTP page
    submit_button = driver.find_element(By.ID, "Button1")
    submit_button.click()
    print("[Login] Submitting OTP...")

    time.sleep(10)

    # Extract final session token URL
    final_url = driver.current_url
    from urllib.parse import urlparse, parse_qs
    parsed_url = urlparse(final_url)
    query_params = parse_qs(parsed_url.query)
    if 'apisession' in query_params:
        apisession = query_params['apisession'][0]
    else:
        import re
        match = re.search(r'apisession=([a-zA-Z0-9_]+)', final_url)
        apisession = match.group(1) if match else final_url.split("=")[-1]
        
    update_file_content(filename, apisession)
    print(f"[Success] New session token updated successfully: {apisession}")

except Exception as e:
    print(f"[Error] An error occurred during automation: {e}")
    traceback.print_exc()

finally:
    driver.quit()
    print("[Browser] Browser session closed.")
