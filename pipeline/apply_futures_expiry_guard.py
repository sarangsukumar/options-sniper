import re

filepath = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/pipeline/insert_live_orders.py'

with open(filepath, 'r') as f:
    content = f.read()

# Add get_active_expiry logic
expiry_logic = """
def last_tuesday_of_month(year, month):
    import calendar
    import datetime
    last_day = calendar.monthrange(year, month)[1]
    dt = datetime.date(year, month, last_day)
    offset = (dt.weekday() - 1) % 7
    return dt - datetime.timedelta(days=offset)

def get_active_expiry():
    import datetime
    import re
    today = datetime.datetime.utcnow().date() + datetime.timedelta(hours=5, minutes=30)
    
    try:
        with open('/home/ubuntu/KotakCodes1/expiry_dates.txt', 'r') as f:
            txt_content = f.read()
        match = re.search(r'const expiryDatesList = "(.*)";', txt_content)
        if not match:
            raise ValueError("Regex failed to find expiryDatesList string")
            
        dates_str = match.group(1)
        valid_dates = []
        for d in dates_str.split(','):
            try:
                valid_dates.append(datetime.datetime.strptime(d.strip(), '%Y-%m-%d').date())
            except:
                pass
                
        valid_dates.sort()
        future_expiries = [d for d in valid_dates if d >= today]
        
        if future_expiries:
            expiry = future_expiries[0]
        else:
            raise ValueError("No future expiry dates found in txt file")
            
    except Exception as e:
        print(f"⚠️ Falling back to manual expiry calculation: {e}")
        expiry = last_tuesday_of_month(today.year, today.month)
        if today > expiry:
            if today.month == 12:
                expiry = last_tuesday_of_month(today.year + 1, 1)
            else:
                expiry = last_tuesday_of_month(today.year, today.month + 1)
    return expiry

def is_expiry_day():
    import datetime
    today = datetime.datetime.utcnow().date() + datetime.timedelta(hours=5, minutes=30)
    expiry_date = get_active_expiry()
    return today >= expiry_date

"""

# Insert the function definitions before main()
content = content.replace("def main():", expiry_logic + "\ndef main():")

# Add the check inside main()
search_pattern = r"def main\(\):\n(.*?print\(\"=\*60\"\))"
replacement = r"""def main():\n\1\n
    if is_expiry_day():
        print("⚠️ TODAY IS EXPIRY DAY! Simulation rules mandate: NEVER ENTER ON EXPIRY DAY.")
        print("🛑 Aborting insertion of Futures orders into markets.orders table.")
        print("   (Data features were collected correctly for walk-forward continuity).")
        return\n"""

content = re.sub(search_pattern, replacement, content, flags=re.DOTALL)

with open(filepath, 'w') as f:
    f.write(content)

