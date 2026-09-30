import imaplib
import email
import re
from datetime import datetime
import pymysql
import sys
import requests

# ==========================================
# 1. CREDENTIALS & CONFIGURATION
# ==========================================
EMAIL_USER = 'amritpk@yahoo.co.in'
EMAIL_PWD = 'ynsabowwxlkquqzn'
IMAP_SERVER = 'imap.mail.yahoo.com'
IMAP_PORT = 993

DB_HOST = 'localhost'
DB_USER = 'root'
DB_PASSWORD = 'root'
DB_NAME = 'markets'

# ==========================================
# 2. EMAIL EXTRACTION FUNCTION
# ==========================================
def get_unread_recommendations():
    print(f"[{datetime.now()}] [Info] Connecting to Yahoo Mail...")
    m = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
    m.login(EMAIL_USER, EMAIL_PWD)
    
    # Check only INBOX for unread emails for recommendations
    folders_to_check = ['INBOX']
    latest_email_body = ""
    latest_date = None
    email_to_mark_seen = None
    
    for folder in folders_to_check:
        try:
            m.select(folder, readonly=False)  # Read-Write to allow marking as seen
            typ, data = m.search(None, 'UNSEEN')  # Fetch only UNREAD emails
            if data[0]:
                nums = data[0].split()
                # Check the last 10 unread emails
                for num in reversed(nums[-10:]):
                    typ, msg_data = m.fetch(num, '(RFC822)')
                    for response_part in msg_data:
                        if isinstance(response_part, tuple):
                            msg = email.message_from_bytes(response_part[1])
                            subj = str(msg['subject']).strip()
                            
                            if 'Daily Trade' in subj or 'Daily Pipeline' in subj or 'Trade Recommendation' in subj:
                                body = ""
                                if msg.is_multipart():
                                    for part in msg.walk():
                                        if part.get_content_type() == 'text/plain':
                                            body += part.get_payload(decode=True).decode(errors='ignore')
                                else:
                                    body = msg.get_payload(decode=True).decode(errors='ignore')
                                
                                if 'TOP ' in body or 'RECOMMENDED STOCKS' in body:
                                    date_tuple = email.utils.parsedate_tz(msg['Date'])
                                    if date_tuple:
                                        email_date = datetime.fromtimestamp(email.utils.mktime_tz(date_tuple))
                                        if latest_date is None or email_date > latest_date:
                                            latest_date = email_date
                                            latest_email_body = body
                                            email_to_mark_seen = num
        except Exception as e:
            print(f"[Error] Failed to process folder {folder}: {e}")

    if not latest_email_body:
        print("[Info] No UNREAD stock recommendation emails found.")
        return []

    print("[Info] Found an UNREAD stock recommendations email. Extracting stocks...")
    stock_pattern = re.compile(r'•\s+([A-Z0-9]+)\s+\(Probability:')
    stocks = stock_pattern.findall(latest_email_body)
    
    if not stocks:
        print("[Warning] Email found but no stocks could be extracted.")
        return []
        
    # Mark as Seen so we don't process it again
    if email_to_mark_seen:
        m.store(email_to_mark_seen, '+FLAGS', '\\Seen')
        print("[Info] Marked email as READ.")

    return stocks

# ==========================================
# 3. DATABASE INSERTION LOGIC
# ==========================================
def process_and_insert_orders(recommended_stocks):
    if not recommended_stocks:
        return

    # Use today's date formatted as YYYY-MM-DD
    today_str = datetime.now().strftime('%Y-%m-%d')
    
    print("[Info] Connecting to Database...")
    try:
        import pymysql
        conn = pymysql.connect(host=DB_HOST, user=DB_USER, password=DB_PASSWORD, database=DB_NAME)
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        
        # 3. Insert new stocks (Always prioritize as TL_1_amrit, TL_2_amrit)
        current_rank_num = 1
        inserted_count = 0
        
        top_stocks = recommended_stocks[:2]
        
        for stock in top_stocks:
            rank_str = f"TL_{current_rank_num}_amrit"
            insert_sql = """
                INSERT INTO orders 
                (stockname, price, quantity, type, ismarket, stoplossprice, 
                limitprice, limitprice_original, simulationtime, credate, 
                isvalid, is_future, USER, order_rank) 
                VALUES (%s, 0.0, 1, 'BUY', 'FALSE', 0.0, 0.0, 0.0, %s, %s, 'FALSE', 'TL', 'MANISHA', %s)
            """
            cursor.execute(insert_sql, (stock, today_str, today_str, rank_str))
            
            print(f"[Success] Inserted: {stock} with rank {rank_str}")
            
            current_rank_num += 1
            inserted_count += 1
            
        conn.commit()
        print(f"[Done] Inserted {inserted_count} new orders successfully.")
        
    except Exception as e:
        print(f"[Error] Database operation failed: {e}")
    finally:
        if 'conn' in locals() and conn.open:
            cursor.close()
            conn.close()

# ==========================================
# 4. TELEGRAM ALERT FUNCTION
# ==========================================
def send_telegram_alert(stocks):
    bot_token = "5350311365:AAFkTUBR4IGvgS5Z9mJngz-mgk7-HkhFEYE"
    chat_id = "-698073972"
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    msg = f"📧 <b>EMAIL ORDERS PROCESSED ({today_str})</b>\n"
    msg += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    msg += "The Yahoo Mail parser has successfully extracted the following stocks:\n\n"
    
    for idx, stock in enumerate(stocks, 1):
        msg += f"<b>{idx}. {stock}</b>\n"
        
    msg += "\n<i>These have been inserted into the live database for execution.</i>\n"
    msg += "------------------------------------\n"
    
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": msg,
            "parse_mode": "HTML"
        }
        resp = requests.post(url, json=payload, timeout=10)
        print(f"[Info] Telegram Alert Sent: {resp.status_code}")
    except Exception as e:
        print(f"[Error] Failed to send Telegram alert: {e}")

# ==========================================
# 5. EXECUTE PIPELINE
# ==========================================
if __name__ == '__main__':
    stocks = get_unread_recommendations()
    if stocks:
        print(f"[Info] Target Stocks: {stocks}")
        process_and_insert_orders(stocks)
        send_telegram_alert(stocks)
    else:
        print("[Info] Script finished. No actions taken.")
