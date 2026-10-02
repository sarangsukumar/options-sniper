import pymysql
import pandas as pd
import numpy as np
import lightgbm as lgb
import os
import requests
from datetime import datetime
import json

# ==========================================
# CONFIGURATION
# ==========================================
DRY_RUN = True  # Keep True to only send Telegram alerts, False to actually modify Kotak orders
MODEL_PATH = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/production_ready_two_shortsell_algos/02_hybrid_0942_1445/lgb_1300_exit_agent.txt'
LEDGER_PATH = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/production_ready_two_shortsell_algos/02_hybrid_0942_1445/daily_0940_live_ledger.csv'
THRESHOLD = 0.60
TELEGRAM_BOT_TOKEN = 'INSERT_TOKEN_HERE'  # Replace if needed or load from env
TELEGRAM_CHAT_ID = 'INSERT_CHAT_ID_HERE'

def send_telegram_message(message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"Telegram error: {e}")

def get_db_connection():
    return pymysql.connect(host='localhost', user='root', password='root', database='markets', cursorclass=pymysql.cursors.DictCursor)

def run_1300_manager():
    print(f"[{datetime.now()}] 🚀 Starting 13:00 PM ML Exit Agent (Dry Run: {DRY_RUN})")
    
    # 1. Load Model
    if not os.path.exists(MODEL_PATH):
        print("❌ Model not found! Exiting.")
        return
    mod = lgb.Booster(model_file=MODEL_PATH)
    
    # 2. Find today's trades
    today_str = datetime.now().strftime('%Y-%m-%d')
    if not os.path.exists(LEDGER_PATH):
        print("❌ Ledger not found.")
        return
    ledger = pd.read_csv(LEDGER_PATH)
    today_trades = ledger[ledger['date'] == today_str]
    
    if today_trades.empty:
        print("✅ No trades found for today in 09:40 ledger. Exiting.")
        return
        
    print(f"🔍 Found {len(today_trades)} active trades for today.")
    
    conn = get_db_connection()
    alerts = []
    
    # 3. Process each trade
    for _, row in today_trades.iterrows():
        stock = row['stockname']
        entry_price = float(row['entry_price'])
        
        try:
            with conn.cursor() as cur:
                cur.execute(f"SELECT time, price, high, low, volume FROM scrapdata WHERE date='{today_str}' AND stockname='{stock}' AND time>='{today_str} 09:42:00' AND time<='{today_str} 13:00:00' ORDER BY time ASC")
                ticks = cur.fetchall()
                
                cur.execute(f"SELECT time, price FROM scrapdata WHERE date='{today_str}' AND stockname='NIFTY' AND time>='{today_str} 09:00:00' AND time<='{today_str} 13:00:00' ORDER BY time ASC")
                nf = cur.fetchall()
                
                cur.execute(f"SELECT COUNT(*) as cnt FROM scrapdata s1 WHERE s1.date='{today_str}' AND TIME(s1.time)='13:00:00' AND s1.price < (SELECT s2.price FROM scrapdata s2 WHERE s2.date='{today_str}' AND s2.stockname=s1.stockname AND TIME(s2.time)='09:15:00' LIMIT 1)")
                breadth_row = cur.fetchone()
                
            if len(ticks) < 15:
                print(f"⚠️ Not enough ticks for {stock}. Skipping.")
                continue
                
            prices = [float(t['price']) for t in ticks]
            highs = [float(t['high'] or t['price']) for t in ticks]
            lows = [float(t['low'] or t['price']) for t in ticks]
            vols = [float(t['volume'] or 0) for t in ticks]
            
            p13 = prices[-1]
            vwap = np.average(prices, weights=vols) if sum(vols) > 0 else prices[-1]
            
            unrealized_pct = (entry_price - p13) / entry_price
            dist_vwap = (vwap - p13) / vwap
            mom_30m = (p13 - prices[-31]) / prices[-31] if len(prices) >= 31 else (p13 - prices[0]) / prices[0]
            mom_60m = (p13 - prices[-61]) / prices[-61] if len(prices) >= 61 else (p13 - prices[0]) / prices[0]
            
            avg_vol_morn = np.mean(vols[:60]) if len(vols) >= 60 else np.mean(vols)
            last15_vol = np.mean(vols[-15:]) if len(vols) >= 15 else np.mean(vols)
            vol_surge_15m = last15_vol / (avg_vol_morn + 1)
            
            wick_scores = []
            for i in range(-10, 0):
                if -i > len(prices): break
                h_ = highs[i]; l_ = lows[i]; p_ = prices[i]
                prev_p = prices[i-1] if i > -len(prices) else p_
                upper_wick = h_ - max(p_, prev_p)
                wick_scores.append(upper_wick / (h_ - l_ + 1e-6))
            avg_upper_wick = np.mean(wick_scores) if wick_scores else 0
            
            dist_from_day_high = (max(highs) - p13) / entry_price
            
            nifty_ret_full = 0; nifty_mom_30m = 0; nifty_is_recovering = 0
            if nf:
                np0 = float(nf[0]['price']); np13 = float(nf[-1]['price'])
                nifty_ret_full = (np13 - np0) / np0
                np1230 = float(nf[-31]['price']) if len(nf) >= 31 else np0
                nifty_mom_30m = (np13 - np1230) / np1230
                nifty_is_recovering = 1 if nifty_mom_30m > 0 else 0
                
            breadth_pct = int(breadth_row['cnt']) / 180.0 if breadth_row else 0.5
            
            consec_green = 0
            for i in range(-1, -6, -1):
                if i-1 >= -len(prices) and prices[i] > prices[i-1]: consec_green += 1
                else: break
                
            features = pd.DataFrame([{
                'unrealized_pct': unrealized_pct, 'dist_vwap': dist_vwap, 'mom_30m': mom_30m,
                'mom_60m': mom_60m, 'vol_surge_15m': vol_surge_15m, 'avg_upper_wick': avg_upper_wick,
                'dist_from_day_high': dist_from_day_high, 'nifty_ret_full': nifty_ret_full,
                'nifty_mom_30m': nifty_mom_30m, 'nifty_is_recovering': nifty_is_recovering,
                'breadth_pct': breadth_pct, 'consec_green': consec_green
            }])
            
            prob = mod.predict(features)[0]
            
            if prob > THRESHOLD:
                msg = f"⚠️ <b>[13:00 ML AGENT] DANGER ON {stock}</b>\nProb: {prob:.2f} > {THRESHOLD}\nUnrealized: {unrealized_pct*100:.2f}%\nAction: Moving SL to Breakeven (₹{entry_price})"
                print(msg)
                alerts.append(msg)
                
                if not DRY_RUN:
                    # TODO: Call Kotak neo.modify_order() to change trigger_price to entry_price
                    pass
            else:
                print(f"✅ {stock} looks safe (Prob: {prob:.2f}). Keeping 3% SL.")
                
        except Exception as e:
            print(f"❌ Error processing {stock}: {e}")
            
    conn.close()
    
    if alerts:
        send_telegram_message("\n\n".join(alerts))
        
if __name__ == "__main__":
    run_1300_manager()
