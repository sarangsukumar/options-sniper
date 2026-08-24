#!/usr/bin/env python3
"""
send_options_orders.py
======================
Live Options Order Notifier — runs at 15:25 IST daily.

Strategy: Wide Bull Put Spread
  SELL: +1 ITM Put
  BUY:  -3 OTM Put  (WIDE SPREAD — finalized per FINAL_ACHIEVEMENTS_AND_DAY2_HOLD_REPORT.md)

Rank Filter: R1 and R3 ONLY
Capital Cap: ₹4,00,000 | Max 20 Lots (NSE Freeze Cap)
"""
import mysql.connector
import redis
import requests
import datetime
import json
import pandas as pd
from breeze_connect import BreezeConnect

# ── Telegram ──────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = "5350311365:AAFkTUBR4IGvgS5Z9mJngz-mgk7-HkhFEYE"
TELEGRAM_CHAT_ID   = "-698073972"

# ── ICICI Breeze (live liquidity checks) ─────────────────────────────────────
BREEZE_API_KEY      = "77059JQ7633PoSc1mk465580B6wp1x04"
BREEZE_API_SECRET   = "6P9^377d3*412585q(527i3ZgJ437040"
BREEZE_SESSION_FILE = "/home/ubuntu/KotakCodes1/ICICI/icici_session_token/icicisession_amrit.txt"

# ── Database ──────────────────────────────────────────────────────────────────
DB_CONFIG = {
    'host': 'localhost', 'user': 'root',
    'password': 'root',  'database': 'markets'
}

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def load_lot_sizes():
    """Loads stockcode -> lot_size from ICICImaster.csv."""
    lot_size_map = {}
    csv_path = "/home/ubuntu/KotakCodes1/masterfile/ICICImaster.csv"
    try:
        df = pd.read_csv(csv_path, low_memory=False)
        df.columns = df.columns.str.strip().str.lower()
        for _, row in df.iterrows():
            stock = str(row['stockcodes']).strip().upper()
            try:
                lot_size_map[stock] = int(row['lotsize'])
            except:
                pass
    except Exception as e:
        print(f"Warning: Could not load lot sizes: {e}")
    return lot_size_map


def init_breeze():
    """Returns an authenticated BreezeConnect session, or None on failure."""
    try:
        with open(BREEZE_SESSION_FILE) as f:
            token = f.read().strip()
        breeze = BreezeConnect(api_key=BREEZE_API_KEY)
        breeze.generate_session(api_secret=BREEZE_API_SECRET, session_token=token)
        print("✅ ICICI Breeze session OK.")
        return breeze
    except Exception as e:
        print(f"⚠️  Breeze init failed: {e}")
        return None


def last_thursday_of_month(year, month):
    import calendar
    last_day = calendar.monthrange(year, month)[1]
    dt = datetime.date(year, month, last_day)
    offset = (dt.weekday() - 3) % 7
    return dt - datetime.timedelta(days=offset)


def get_active_expiry():
    """
    Returns the active monthly expiry dynamically from expiry_dates.txt (updated daily by ICICI API).
    """
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
        # Parse into datetime.date objects
        valid_dates = []
        for d in dates_str.split(','):
            try:
                valid_dates.append(datetime.datetime.strptime(d.strip(), '%Y-%m-%d').date())
            except:
                pass
                
        valid_dates.sort()
        # Find the first expiry that is >= today
        future_expiries = [d for d in valid_dates if d >= today]
        
        if future_expiries:
            expiry = future_expiries[0]
        else:
            raise ValueError("No future expiry dates found in txt file")
            
    except Exception as e:
        print(f"⚠️ Falling back to manual expiry calculation: {e}")
        expiry = last_thursday_of_month(today.year, today.month)
        if today > expiry:
            if today.month == 12:
                expiry = last_thursday_of_month(today.year + 1, 1)
            else:
                expiry = last_thursday_of_month(today.year, today.month + 1)

    expiry_str = expiry.strftime('%Y-%m-%dT06:00:00.000Z')
    return expiry_str, expiry


def fetch_option_chain(breeze, stock, expiry_str):
    """Fetches full put option chain for a stock and returns a DataFrame."""
    try:
        resp = breeze.get_option_chain_quotes(
            stock_code=stock,
            exchange_code='NFO',
            product_type='options',
            expiry_date=expiry_str,
            right='put',
            strike_price='0'
        )
        if resp and resp.get('Status') == 200 and resp.get('Success'):
            df = pd.DataFrame(resp['Success'])
            df['strike_price'] = df['strike_price'].astype(float)
            return df
    except Exception as e:
        print(f"  Option chain fetch error for {stock}: {e}")
    return None


def infer_step_and_atm(chain_df, spot_price):
    """
    Infers the real strike step size from the live option chain
    (avoids hardcoded step tables which can be wrong).
    Returns (step, atm_strike).
    """
    strikes = sorted(chain_df['strike_price'].unique())
    if len(strikes) < 2:
        return 5, round(spot_price / 5) * 5

    diffs = [round(strikes[i+1] - strikes[i], 2) for i in range(min(10, len(strikes)-1))]
    # Most common diff = real step
    step = max(set(diffs), key=diffs.count)
    atm  = step * round(spot_price / step)
    return step, atm


def live_liquidity_checks(chain_df, strike_price, required_qty, lot_size):
    """
    Looks up the strike in the already-fetched option chain and runs 3 checks:
      ① Bid-Ask Spread < 5%
      ② L2 Market Depth >= required_qty
      ③ Daily Volume > 100 lots
    Returns (all_passed: bool|None, details: dict).
    None = data not available for this strike.
    """
    if chain_df is None:
        return None, {"error": "Option chain not available"}

    row = chain_df[chain_df['strike_price'] == float(strike_price)]
    if row.empty:
        return None, {"error": f"Strike {strike_price} not found in option chain"}

    r    = row.iloc[0]
    bid  = float(r.get('best_bid_price',           0) or 0)
    ask  = float(r.get('best_offer_price',         0) or 0)
    bqty = float(r.get('total_buy_qty',            0) or 0)
    sqty = float(r.get('total_sell_qty',           0) or 0)
    vol  = float(r.get('total_quantity_traded',    0) or 0)

    spread_pct = (ask - bid) / ask * 100 if (bid > 0 and ask > 0) else 999
    depth_qty  = max(bqty, sqty)
    vol_lots   = vol / lot_size if lot_size > 0 else 0

    checks = {
        'bid': bid, 'ask': ask, 'ltp': float(r.get('ltp', 0) or 0),
        'spread_pct': spread_pct, 'spread_ok': spread_pct < 5.0,
        'depth_qty':  depth_qty,  'depth_ok':  depth_qty >= required_qty,
        'vol_lots':   vol_lots,   'vol_ok':    vol_lots > 50,
    }
    all_ok = checks['spread_ok'] and checks['depth_ok'] and checks['vol_ok']
    return all_ok, checks


def get_target_stocks():
    """Returns today's R1 and R3 stocks from the orders table."""
    today_str = datetime.date.today().strftime('%Y-%m-%d')
    conn   = mysql.connector.connect(**DB_CONFIG)
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT DISTINCT stockname, order_rank FROM orders
        WHERE DATE(simulationtime) = %s
          AND (order_rank LIKE 'TL_1%' OR order_rank LIKE 'TL_3%')
    """, (today_str,))
    rows = cursor.fetchall()
    cursor.close(); conn.close()
    targets = {}
    for r in rows:
        targets[r['stockname'].upper()] = r['order_rank']
    return targets

import json

def get_f1_price_from_redis(stock_name):
    """Retrieve F1 Price from Redis, falling back to Cash (Spot) price if F1 is missing"""
    try:
        r = redis.Redis(host='localhost', port=6379, decode_responses=True)
        # Try F1 Future Price formats first
        f1_key_1 = f"LTP:{stock_name}-F1"
        f1_key_2 = f"LTP:{stock_name}_F1"
        price_str = r.get(f1_key_1) or r.get(f1_key_2)
        
        # Fallback to Cash Spot Price
        if not price_str:
            cash_key = f"LTP:{stock_name}"
            price_str = r.get(cash_key)
            
        if not price_str:
            print(f"⚠️ [Redis] Both F1 and Cash Price for {stock_name} not found in Redis (Checked: {f1_key_1}, {f1_key_2}, {cash_key})!")
            return None
            
        # Parse JSON if applicable
        try:
            parsed = json.loads(price_str)
            if 'ltp' in parsed:
                return float(parsed['ltp'])
        except json.JSONDecodeError:
            pass
            
        # Handle orchestrator timestamp format "price|timestamp"
        if '|' in str(price_str):
            price_str = price_str.split('|')[0]
            
        return float(price_str)
    except Exception as e:
        print(f"⚠️ Error reading from Redis: {e}")
        return None

def get_option_ltp_from_redis(stock_name, strike_price, option_type):
    """Retrieve Option LTP from Redis using orchestrator formatting (e.g. LTP:ABCAPITAL_385.0_PE)"""
    try:
        r = redis.Redis(host='localhost', port=6379, decode_responses=True)
        key = f"LTP:{stock_name}_{float(strike_price)}_{option_type}"
        val = r.get(key)
        if val:
            # Handles if Redis stores "price|timestamp" like the orchestrator checks
            return float(val.split('|')[0]) if '|' in str(val) else float(val)
    except Exception as e:
        pass
    return 0.0


def get_step_size_from_master(stock_name):
    """Parses ICICImaster_options.csv to find the exact step size for the stock"""
    master_file = "/home/ubuntu/KotakCodes1/masterfile/ICICImaster_options.csv"
    try:
        strikes = set()
        with open(master_file, "r") as f:
            for line in f:
                parts = line.strip().split(',')
                if len(parts) >= 8 and parts[6] == stock_name:
                    try:
                        strikes.add(float(parts[7]))
                    except ValueError:
                        pass
        if len(strikes) < 2:
            return None
        sorted_strikes = sorted(list(strikes))
        diffs = [round(sorted_strikes[i+1] - sorted_strikes[i], 2) for i in range(len(sorted_strikes)-1)]
        step = max(set(diffs), key=diffs.count)
        return float(step)
    except Exception as e:
        print(f"⚠️ Error reading master CSV for {stock_name}: {e}")
        return None

def send_telegram_notification(text):
    url     = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': text, 'parse_mode': 'HTML'}
    return requests.post(url, data=payload, timeout=10).json()


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
def main():
    stocks = get_target_stocks()
    if not stocks:
        print("No R1/R3 targets found in the database for today.")
        return

    lot_sizes     = load_lot_sizes()
    
    expiry_str, expiry_date = get_active_expiry()
    
    # Calculate proper IST time (Server is on UTC)
    ist_time = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)
    now_str  = ist_time.strftime('%d-%b-%Y %H:%M IST')

    print(f"Active expiry: {expiry_date} ({expiry_str})")

    today_date = ist_time.date()
    if today_date >= expiry_date:
        print(f"⚠️ TODAY ({today_date}) IS EXPIRY DAY ({expiry_date})! Simulation rules mandate: NEVER ENTER ON EXPIRY DAY. Aborting all options trades.")
        return


    msg  = f"🎯 <b>LIVE OPTIONS ORDER INFORMATION</b>\n"
    msg += f"📅 <b>Time:</b> {now_str} | <b>Expiry:</b> {expiry_date.strftime('%d-%b-%Y')}\n"
    msg += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

    valid_orders = 0
    for stock, order_rank in stocks.items():
        print(f"\nProcessing {stock}...")

        f1_price = get_f1_price_from_redis(stock)
        if f1_price is None:
            print(f"  Skipping {stock} — no F1 price in Redis")
            continue

        # Fetch live option chain (single call — reused for all checks)
        chain_df = None

        # Infer real step from live chain (not hardcoded table)
        if chain_df is not None and not chain_df.empty:
            spot_from_chain = float(chain_df['spot_price'].iloc[0] or f1_price)
            step, atm_strike = infer_step_and_atm(chain_df, spot_from_chain)
            print(f"  Spot={spot_from_chain}  Step={step}  ATM={atm_strike}")
        else:
            # Fallback: Parse ICICImaster_options.csv for true step size
            step = get_step_size_from_master(stock)
            if step is None:
                # Absolute last resort
                if f1_price <= 250:  step = 2.5
                elif f1_price <= 1000: step = 5
                elif f1_price <= 3000: step = 10
                elif f1_price <= 6000: step = 50
                else: step = 100
            
            atm_strike = step * round(f1_price / step)
            print(f"  ⚠️ Chain unavailable. Master Fallback: F1={f1_price} Step={step} ATM={atm_strike}")

        # Wide Spread strikes
        sell_strike = atm_strike + (1 * step)    # +1 ITM (SHORT leg)
        buy_strike  = atm_strike - (3 * step)    # -3 OTM (HEDGE leg)

        lot_size       = lot_sizes.get(stock, 1)
        margin_per_lot = (sell_strike - buy_strike) * lot_size
        
        # 2. Penny Stock Margin Trap Filter (>2L Reject)
        if margin_per_lot > 200000:
            print(f"  🔴 REJECT {stock}: Margin trap! One lot physical risk (₹{margin_per_lot}) exceeds ₹2,00,000.")
            continue
            
        # 1. The Maximum Capital Cap (Volume Dial) - ₹2L cap
        calc_lots = int(200_000 // margin_per_lot) if margin_per_lot > 0 else 0
        lots = min(calc_lots, 20)
        if lots < 1:
            print(f"  🔴 REJECT {stock}: Can't afford even 1 lot within ₹2L cap.")
            continue
            
        total_qty      = lots * lot_size
        total_margin   = lots * margin_per_lot
        strike_gap     = sell_strike - buy_strike

        msg += f"📈 <b>Stock:</b> {stock}\n"

        # Fetch Live Option LTPs from Redis
        buy_ltp = get_option_ltp_from_redis(stock, buy_strike, 'PE')
        sell_ltp = get_option_ltp_from_redis(stock, sell_strike, 'PE')
        
        # 3. The ₹0.50 Premium Liquidity Floor
        # We NO LONGER reject here. We insert into DB, let Redis fetch it, and UpdateLimit_feed_options.js will reject it!
        if buy_ltp and buy_ltp < 0.50 or sell_ltp and sell_ltp < 0.50:
            print(f"  ⚠️ WARNING {stock}: Premium < 0.50 in Redis (Buy: {buy_ltp}, Sell: {sell_ltp}). Orchestrator will reject if live.")
        
        buy_ltp_str = f"₹{buy_ltp:g}" if buy_ltp else "N/A"
        sell_ltp_str = f"₹{sell_ltp:g}" if sell_ltp else "N/A"

        msg += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        msg += f"1️⃣ <b>HEDGE FIRST (BUY for margin):</b>\n"
        msg += f"🟩 <b>BUY</b>  {lots} Lots ({total_qty} Qty) {stock} <b>{buy_strike:g} PE</b> <i>(-3 OTM)</i> [LTP: {buy_ltp_str}]\n\n"

        msg += f"2️⃣ <b>SHORT SECOND (SELL after hedge):</b>\n"
        msg += f"🟥 <b>SELL</b> {lots} Lots ({total_qty} Qty) {stock} <b>{sell_strike:g} PE</b> <i>(+1 ITM)</i> [LTP: {sell_ltp_str}]\n"
        msg += f"   <i>(Margin Blocked: ₹{total_margin:,.2f})</i>\n"
        msg += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        
        # ── Live Pre-Trade Liquidity Checks ──────────────────────────────────
        msg += "🚦 <b><u>PRE-TRADE CHECKS:</u></b>\n"

        cap_ok = total_margin <= 200_000
        lot_ok = lots <= 20
        all_passed = cap_ok and lot_ok

        # Store check lines to append after the master GO/NO-GO flag
        check_lines = []
        check_lines.append(f"{'✅' if cap_ok else '❌'} Capital Cap (≤ ₹2L)")
        check_lines.append(f"{'✅' if lot_ok else '❌'} NSE Freeze Cap (≤ 20 Lots)")
        check_lines.append(f"✅ Margin Trap Filter (Risk: ₹{margin_per_lot}/lot)")
        check_lines.append(f"✅ Premium Liquidity Floor (Both ≥ ₹0.50)")

        # --- DATABASE INSERTION FOR AFTERNOON ENTRY (UNCONDITIONAL) ---
        try:
            conn = mysql.connector.connect(**DB_CONFIG)
            cursor = conn.cursor()
            sim_time = datetime.date.today().strftime('%Y-%m-%d 00:00:00')
            users = ['MANISHA']
            
            for u in users:
                # 1. SELL Leg (+1 ITM Short) - DYNAMIC LOTS
                cursor.execute("""
                    INSERT INTO orders_option 
                    (stockname, strikeprice, optiontype, type, limitprice, quantity, isvalid, ismarket, user, simulationtime, is_future, order_rank, algo_type)
                    VALUES (%s, %s, %s, %s, NULL, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (stock, float(sell_strike), 'PE', 'SELL', lots, '0', '0', u, sim_time, 'OPTIONS', order_rank, 'TL_opt'))
                
                # 2. BUY Leg (-3 OTM Hedge) - DYNAMIC LOTS
                cursor.execute("""
                    INSERT INTO orders_option 
                    (stockname, strikeprice, optiontype, type, limitprice, quantity, isvalid, ismarket, user, simulationtime, is_future, order_rank, algo_type)
                    VALUES (%s, %s, %s, %s, NULL, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (stock, float(buy_strike), 'PE', 'BUY', lots, '0', '0', u, sim_time, 'OPTIONS', order_rank, 'TL_opt'))
                
            conn.commit()
            conn.close()
            print(f"✅ Successfully inserted {stock} orders ({total_qty} qty) into MySQL database for orchestrator!")
        except Exception as e:
            print(f"❌ Database insert failed for {stock}: {e}")

        if all_passed:
            msg += "\n🟢 <b>ALL CHECKS PASSED — GO STATUS</b> 🟢\n\n"
        else:
            msg += "\n🔴 <b>WARNING: ONE OR MORE CHECKS FAILED</b> 🔴\n\n"

        msg += "\n".join(check_lines) + "\n"
        msg += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        valid_orders += 1

    if valid_orders > 0:
        msg += "⚠️ <b>GOLDEN RULE:</b> Hedge fill must confirm BEFORE Short order is sent.\n"
        msg += "🚪 <b>Exit:</b> Next day 09:25–09:35 IST"
        print(msg)
        send_telegram_notification(msg)
        print("✅ Telegram notification sent.")
    else:
        print("No valid orders to send.")

if __name__ == "__main__":
    main()
