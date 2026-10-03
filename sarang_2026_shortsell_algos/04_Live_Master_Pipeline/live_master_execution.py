import os
import sys
import time
import datetime
import subprocess
import pymysql

# Set paths to the existing models
MODEL1_DIR = "/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_2026_shortsell_algos/01_Best_Shorter_Window_0920_0940"
MODEL2_DIR = "/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_2026_shortsell_algos/02_Best_Longer_Window_0942_1445"
BOT_SCRIPT = "/home/ubuntu/KotakCodes1/status_Info_bot.js"

# Connect to DB
def get_db_connection():
    return pymysql.connect(host='localhost', user='root', password='root', database='markets', cursorclass=pymysql.cursors.DictCursor)

def send_telegram(message):
    try:
        # Write to temp file
        tmp = "/tmp/master_msg.txt"
        with open(tmp, 'w') as f:
            f.write(message)
        subprocess.run(["node", BOT_SCRIPT, f"$(cat {tmp})"], shell=True)
    except Exception as e:
        print(f"Telegram error: {e}")

def run_model(model_dir, script_name):
    print(f"Running {script_name}...")
    try:
        subprocess.run(["python3", script_name], cwd=model_dir, check=True)
        return True
    except subprocess.CalledProcessError:
        return False

def get_latest_price(stock_name, today_str):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            q = f"SELECT time, price, close FROM scrapdata WHERE date = '{today_str}' AND stockname LIKE '%{stock_name}%' ORDER BY time DESC LIMIT 1"
            cur.execute(q)
            res = cur.fetchone()
            if res:
                return float(res['close'] or res['price'] or 0)
    finally:
        conn.close()
    return 0.0

def monitor_positions(positions, today_str, square_off_time, model_name):
    print(f"Monitoring {len(positions)} positions until {square_off_time}...")
    active_positions = list(positions)
    
    while active_positions:
        now_time = datetime.datetime.now().strftime('%H:%M:%S')
        if now_time >= square_off_time:
            msg = f"⏳ **SQUARE OFF TIME ({square_off_time})**\n\nClose all remaining {model_name} positions immediately to free up margin!"
            send_telegram(msg)
            break
            
        new_active = []
        for pos in active_positions:
            stock = pos['stock']
            entry = pos['entry']
            sl = pos['sl']
            tp = pos['tp']
            
            cmp = get_latest_price(stock, today_str)
            if cmp == 0:
                new_active.append(pos)
                continue
                
            if cmp >= sl:
                msg = f"🚨 **STOP LOSS HIT!**\n\nModel: {model_name}\nStock: {stock}\nEntry: {entry}\nSL Hit At: {cmp}\n\nSquare off immediately!"
                send_telegram(msg)
            elif cmp <= tp:
                msg = f"✅ **TAKE PROFIT HIT!**\n\nModel: {model_name}\nStock: {stock}\nEntry: {entry}\nTP Hit At: {cmp}\n\nLock in 5% profit now!"
                send_telegram(msg)
            else:
                new_active.append(pos)
                
        active_positions = new_active
        time.sleep(30) # Poll every 30 seconds

def load_predictions(csv_path):
    import pandas as pd
    if not os.path.exists(csv_path): return []
    df = pd.read_csv(csv_path)
    positions = []
    for _, row in df.iterrows():
        stock = row['stockname']
        entry = float(row.get('cmp_0919', row.get('cmp_0940', 0))) # Depends on which model
        positions.append({
            'stock': stock,
            'entry': entry,
            'sl': round(entry * 1.03, 2),
            'tp': round(entry * 0.95, 2)
        })
    return positions

def main():
    print("Master Pipeline Started.")
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    
    # Wait until 09:19 to run Model 1
    while True:
        now = datetime.datetime.now().strftime("%H:%M:%S")
        if now >= "09:19:30":
            break
        time.sleep(10)
        
    # --- STAGE 1: 09:20 SCALP ---
    send_telegram("🚀 **Starting Master Sequence: Model 09:20**")
    run_model(MODEL1_DIR, "live_0920_scalp_pipeline.py")
    
    # Read output and monitor
    m1_csv = os.path.join(MODEL1_DIR, "live_0920_predictions_today.csv")
    m1_positions = load_predictions(m1_csv)
    
    monitor_positions(m1_positions, today, "09:40:00", "09:20 Scalp")
    
    # Wait until 09:41 to run Model 2
    while True:
        now = datetime.datetime.now().strftime("%H:%M:%S")
        if now >= "09:41:30":
            break
        time.sleep(10)
        
    # --- STAGE 2: 09:42 TREND ---
    send_telegram("🚀 **Starting Master Sequence: Model 09:42**")
    run_model(MODEL2_DIR, "live_0940_hybrid_pipeline.py")
    
    m2_csv = os.path.join(MODEL2_DIR, "live_predictions_today.csv")
    m2_positions = load_predictions(m2_csv)
    
    monitor_positions(m2_positions, today, "14:45:00", "09:42 Trend")
    
    send_telegram("🏁 **Trading Day Concluded.**")

if __name__ == "__main__":
    main()
