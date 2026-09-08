import pandas as pd
import lightgbm as lgb
import joblib
from datetime import datetime
import re
import calendar
from dateutil.relativedelta import relativedelta
import pymysql
import subprocess
import os

def get_active_expiry(today):
    try:
        with open('/home/ubuntu/KotakCodes1/expiry_dates.txt', 'r') as f:
            txt_content = f.read()
        match = re.search(r'const expiryDatesList = "(.*)";', txt_content)
        if not match:
            raise ValueError("Regex failed to find expiryDatesList string")
            
        date_strs = match.group(1).split(',')
        expiries = pd.to_datetime(date_strs, format='mixed').date
        
        future_expiries = sorted([e for e in expiries if e >= today.date()])
        if not future_expiries:
            raise ValueError("No future expiry dates found in txt file")
            
        return future_expiries[0]
    except Exception as e:
        print(f"Warning: Could not read Kotak expiry file ({e}).")
        last_day = calendar.monthrange(today.year, today.month)[1]
        dt_last = pd.Timestamp(year=today.year, month=today.month, day=last_day).date()
        offset = (dt_last.weekday() - 3) % 7
        expiry = dt_last - pd.Timedelta(days=offset)
        if today.date() <= expiry:
            return expiry
        else:
            next_month = today + relativedelta(months=1)
            last_day = calendar.monthrange(next_month.year, next_month.month)[1]
            dt_last = pd.Timestamp(year=next_month.year, month=next_month.month, day=last_day).date()
            offset = (dt_last.weekday() - 3) % 7
            return dt_last - pd.Timedelta(days=offset)

def send_telegram_alert(msg):
    try:
        bot_path = "/home/ubuntu/telegram_bot/New_OrderInfoBot.js"
        if os.path.exists(bot_path):
            subprocess.run(["node", bot_path, msg], check=True, timeout=15)
            print("Telegram alert sent successfully.")
        else:
            print(f"Warning: OrderInfoBot not found at {bot_path}")
    except Exception as e:
        print(f"Warning: Failed to send Telegram alert: {e}")

if __name__ == "__main__":
    today = datetime.now()
    today_str = today.strftime('%Y-%m-%d')
    print(f"Running ML Prediction Pipeline for {today_str}...")

    # 0. The Master Candidate Filter
    print("Filtering candidates using overnight Custom Limit Fills...")
    pnl_path = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/data/markets_pnl0325.csv'
    pnl_df = pd.read_csv(pnl_path)
    
    pnl_df['entry_date'] = pd.to_datetime(pnl_df['simulationdate'], format='mixed', dayfirst=True, errors='coerce')
    last_trading_date = pnl_df['entry_date'].max()
    
    recent_fills = pnl_df[(pnl_df['entry_date'] == last_trading_date) & (pnl_df['sell_exec_type'] == 'Custom Limit Fill')].copy()
    valid_candidates = recent_fills['stockname'].str.strip().str.upper().tolist()
    
    if not valid_candidates:
        msg = f"📉 *09:40 SHORT SELL ALGO*\n📅 {today_str}\n\n⚠️ No Custom Limit Fills occurred yesterday. ZERO candidates to trade today."
        print(msg)
        send_telegram_alert(msg)
        exit(0)
    
    # 1. Load Yesterday's Features
    prev_feats_path = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/data/f11_intraday_features_all.csv'
    df_prev = pd.read_csv(prev_feats_path)
    df_prev['Date'] = pd.to_datetime(df_prev['Date'])
    df_prev = df_prev.sort_values('Date').groupby('Stock').tail(1).reset_index(drop=True)
    df_prev = df_prev.rename(columns={'Stock': 'clean_stock'})
    if 'prev_close' in df_prev.columns:
        df_prev = df_prev.drop(columns=['prev_close'])

    # 2. Load Today's Morning Features
    morn_feats_path = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_shortsell940_2026/data/live_morning_features.csv'
    try:
        df_morn = pd.read_csv(morn_feats_path)
        df_morn = df_morn.rename(columns={'Stock': 'clean_stock'})
    except:
        msg = f"📉 *09:40 SHORT SELL ALGO*\n📅 {today_str}\n\n🚨 ERROR: live_morning_features.csv missing."
        send_telegram_alert(msg)
        exit(1)

    live_df = pd.merge(df_morn, df_prev, on='clean_stock', how='inner')
    live_df = live_df[live_df['clean_stock'].isin(valid_candidates)].copy()

    if live_df.empty:
        msg = f"📉 *09:40 SHORT SELL ALGO*\n📅 {today_str}\n\n⚠️ None of the Custom Limit Fill candidates have morning feature data. Exiting."
        send_telegram_alert(msg)
        exit(0)

    # 3. Load Ban List
    banlist_path = '/home/ubuntu/banlist/fo_ban_list_historical.csv'
    if os.path.exists(banlist_path):
        ban = pd.read_csv(banlist_path)
        ban['date'] = pd.to_datetime(ban['date'], format='%d-%m-%Y', errors='coerce').dt.strftime('%Y-%m-%d')
        ban = ban[ban['date'] == today_str]
        banned_stocks = ban['stock_name'].tolist()
        live_df = live_df[~live_df['clean_stock'].isin(banned_stocks)].copy()

    # 4. Fetch Prev Close, Premarket (09:07), AND Today's Open (09:15) STRICTLY from MySQL
    print("Fetching prev_close and premarket (09:07) from scrapdata...")
    conn = pymysql.connect(host='localhost', user='root', password='root', database='markets')
    cursor = conn.cursor()

    # Dynamic lookup of previous trading date from scrapdata
    cursor.execute(f"SELECT MAX(date) FROM scrapdata WHERE date < '{today_str}'")
    row = cursor.fetchone()
    prev_date_str = str(row[0]) if row and row[0] else '2026-09-03'
    print(f"Detected previous trading date in scrapdata: {prev_date_str}")

    cand_strs = ",".join([f"'{s}'" for s in live_df['clean_stock']])

    # 1. PREV CLOSE
    cursor.execute(f"SELECT stockname, CAST(close AS DECIMAL(10,2)) FROM scrapdata WHERE date = '{prev_date_str}' AND TIME(time) >= '15:00:00' AND stockname IN ({cand_strs}) AND isvalid='TRUE'")
    res = cursor.fetchall()
    prev_close_df = pd.DataFrame(res, columns=['clean_stock', 'prev_close']).groupby('clean_stock').last().reset_index() if res else pd.DataFrame(columns=['clean_stock', 'prev_close'])

    # 2. PREMARKET
    cursor.execute(f"SELECT stockname, CAST(price AS DECIMAL(10,2)) FROM scrapdata WHERE date = '{today_str}' AND TIME(time) = '09:07:00' AND stockname IN ({cand_strs}) AND isvalid='TRUE'")
    res2 = cursor.fetchall()
    premarket_df = pd.DataFrame(res2, columns=['clean_stock', 'premarket_price']).groupby('clean_stock').last().reset_index() if res2 else pd.DataFrame(columns=['clean_stock', 'premarket_price'])

    # 3. OPEN
    cursor.execute(f"SELECT stockname, CAST(open AS DECIMAL(10,2)) FROM scrapdata WHERE date = '{today_str}' AND TIME(time) = '09:15:00' AND stockname IN ({cand_strs}) AND isvalid='TRUE'")
    res3 = cursor.fetchall()
    opens_df = pd.DataFrame(res3, columns=['clean_stock', 'open_0915']).groupby('clean_stock').last().reset_index() if res3 else pd.DataFrame(columns=['clean_stock', 'open_0915'])

    cursor.close()
    conn.close()
    
    live_df = live_df.merge(prev_close_df, on='clean_stock', how='inner')
    
    # Merge premarket (fallback to open_0915 if missing)
    live_df = live_df.merge(premarket_df, on='clean_stock', how='left')
    live_df = live_df.merge(opens_df, on='clean_stock', how='inner')
    
    float_cols = ['prev_close', 'premarket_price', 'open_0915']
    for col in float_cols:
        if col in live_df.columns:
            live_df[col] = live_df[col].astype(float)

    live_df['premarket_price'] = live_df['premarket_price'].fillna(live_df['open_0915'])
    
    # Calculate Gaps & Arcs
    live_df['Gap_Pct'] = ((live_df['premarket_price'] - live_df['prev_close']) / live_df['prev_close']) * 100
    live_df['gap_abs'] = live_df['Gap_Pct'].abs()
    
    live_df['open_0915'] = live_df['prev_close'] * (1 + (live_df['Gap_Pct'] / 100))
    live_df['price_0940'] = live_df['open_0915'] * (1 + (live_df['morning_return'] / 100))
    live_df['morning_high_calc'] = live_df['price_0940'] + (live_df['open_0915'] * (live_df['morning_range'] / 100)) * (1 - (live_df['morning_range_pos'] / 100))
    
    live_df['spike_from_prev_close_pct'] = ((live_df['morning_high_calc'] - live_df['prev_close']) / live_df['prev_close']) * 100
    live_df['fade_from_high_pct'] = ((live_df['morning_high_calc'] - live_df['price_0940']) / live_df['morning_high_calc']) * 100
    live_df['positive_half_circle_prev_close'] = live_df['spike_from_prev_close_pct'] * live_df['fade_from_high_pct']
    
    live_df['gap_fade_completion'] = (live_df['open_0915'] - live_df['price_0940']) / (live_df['open_0915'] - live_df['prev_close'] + 1e-9)
    live_df['stagnancy_prev_to_0940_pct'] = ((live_df['price_0940'] - live_df['prev_close']) / live_df['prev_close']) * 100
    live_df['abs_stagnancy_prev_to_0940'] = live_df['stagnancy_prev_to_0940_pct'].abs()
    live_df['arc_shape_intensity'] = live_df['morning_range'] * (50 - live_df['morning_range_pos']) / 50.0 
    live_df['stagnancy_0907_to_0940_pct'] = live_df['stagnancy_prev_to_0940_pct']
    live_df['abs_stagnancy_0907_to_0940'] = live_df['abs_stagnancy_prev_to_0940']

    # 5. Extract Days to Expiry using Exact Kotak File
    exact_expiry_date = get_active_expiry(today)
    live_df['days_to_expiry'] = (exact_expiry_date - today.date()).days

    # 6. Extract R1/R3 Stats directly from the SHORT SELL Master Dataset
    short_data_path = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_shortsell940_2026/data/short_sell_ml_dataset_v2.csv'
    if os.path.exists(short_data_path):
        short_df = pd.read_csv(short_data_path, low_memory=False)
        short_df['is_win'] = (short_df['short_pnl_net'] > 0).astype(int)
        stats_df = short_df.groupby('clean_stock').agg(
            hist_count=('short_pnl_net', 'count'),
            hist_avg_pnl=('short_pnl_net', 'mean'),
            hist_win_rate=('is_win', 'mean')
        ).reset_index()
        live_df = live_df.merge(stats_df, on='clean_stock', how='left')
    
    live_df['hist_count'] = live_df.get('hist_count', pd.Series(100)).fillna(100)
    live_df['hist_avg_pnl'] = live_df.get('hist_avg_pnl', pd.Series(0)).fillna(0)
    live_df['hist_win_rate'] = live_df.get('hist_win_rate', pd.Series(0.50)).fillna(0.50)

    # 7. Make Predictions
    print("Loading LightGBM Model...")
    model_path = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_shortsell940_2026/models/sarang_shortsell_0940_production.pkl'
    model = joblib.load(model_path)
    
    expected_cols = model.feature_name_
    for c in expected_cols:
        if c not in live_df.columns:
            if c.startswith('prev_'):
                live_df[c] = live_df[c.replace('prev_', '')] if c.replace('prev_', '') in live_df else 0
            else:
                live_df[c] = 0
            
    X_live = live_df[expected_cols]
    live_df['ml_prob'] = model.predict_proba(X_live)[:, 1]
    
    live_df['daily_rank'] = live_df['ml_prob'].rank(method='first', ascending=False)
    sel = live_df.sort_values('daily_rank').head(5).copy()
    
    tg_lines = []
    tg_lines.append("📉 <b>09:40 SHORT SELL ALGO (GOLDEN 2026 BOOST MODEL)</b> 📉")
    tg_lines.append(f"📅 <b>Date</b>: {today_str} | Entry: 09:42 AM IST")
    tg_lines.append("────────────────────────────")
    
    if sel.empty:
        tg_lines.append("⚠️ <b>No Short Sell candidates met the criteria today.</b>")
    else:
        tg_lines.append("🎯 <b>TOP 5 EXECUTABLE SHORT TARGETS (RANKS 1 to 5)</b>\n")
        for _, row in sel.iterrows():
            rk = int(row['daily_rank'])
            stk = row['clean_stock']
            prob = row['ml_prob']
            gap = row.get('Gap_Pct', 0.0)
            
            if rk == 1:
                label = "🌟 <b>RANK #1 (STAR TRAILING RUNNER)</b>"
                rule = "SL 5.0% | Act 1.5% | Floor 1.0% | Giveback 0.3%"
            elif rk in [2, 3, 4]:
                label = f"⚡ <b>RANK #{rk} (SCALP TARGET / BLEED TRAILING)</b>"
                rule = "Scalp TP 1.5% (SL 4.0%) / Bleed Trailing"
            else:
                label = f"🔹 <b>RANK #{rk}</b>"
                rule = "Scalp TP 1.5% (SL 4.0%)"
                
            tg_lines.append(f"{label}\n  • Stock: <b>{stk}</b> | Prob: <code>{prob:.3f}</code> | Gap: <code>{gap:+.2f}%</code>\n  • Exit Rule: <i>{rule}</i>\n")

    tg_msg = "\n".join(tg_lines)
    print("\nGenerated Telegram Message:")
    print(tg_msg)
    send_telegram_alert(tg_msg)
    
    out_file = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_shortsell940_2026/output/todays_short_targets.csv'
    sel.to_csv(out_file, index=False)
    print(f"\nTargets saved successfully to {out_file}!")

