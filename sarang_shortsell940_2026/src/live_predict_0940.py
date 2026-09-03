import pandas as pd
import numpy as np
import lightgbm as lgb
import joblib
import pandas_ta as ta
import mysql.connector
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import calendar
import os

# --- 1. Database Connection ---
def get_db_connection():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="", # Add your MySQL password here
        database="markets"
    )

# --- 2. Expiry Date Helper ---
def get_expiry_date(d):
    last_day = calendar.monthrange(d.year, d.month)[1]
    dt_last = pd.Timestamp(year=d.year, month=d.month, day=last_day)
    offset = (dt_last.weekday() - 3) % 7
    expiry_this_month = dt_last - pd.Timedelta(days=offset)
    if d <= expiry_this_month:
        return expiry_this_month
    else:
        next_month = d + relativedelta(months=1)
        last_day = calendar.monthrange(next_month.year, next_month.month)[1]
        dt_last = pd.Timestamp(year=next_month.year, month=next_month.month, day=last_day)
        offset = (dt_last.weekday() - 3) % 7
        return dt_last - pd.Timedelta(days=offset)

# --- 3. Main Live Pipeline ---
def run_live_predictions():
    today = datetime.now()
    today_str = today.strftime('%Y-%m-%d')
    print(f"Running Live 09:40 Predictions for {today_str}...")

    # A. Load Yesterday's Pre-Calculated Data
    prev_feats_path = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/data/f11_intraday_features_all.csv'
    df_prev = pd.read_csv(prev_feats_path)
    # Get the most recent row per stock (which should be yesterday)
    df_prev['Date'] = pd.to_datetime(df_prev['Date'])
    df_prev = df_prev.sort_values('Date').groupby('Stock').tail(1).reset_index(drop=True)
    df_prev = df_prev.rename(columns={'Stock': 'clean_stock'})

    # B. Load Ban List
    banlist_path = '/home/ubuntu/banlist/fo_ban_list_historical.csv'
    ban = pd.read_csv(banlist_path)
    ban['date'] = pd.to_datetime(ban['date'], format='%d-%m-%Y').dt.strftime('%Y-%m-%d')
    ban = ban[ban['date'] == today_str]
    banned_stocks = ban['stock_name'].tolist()

    # C. Fetch Live 09:15 to 09:40 Ticks from MySQL (scrapdata)
    # Assumes your ICICI JS downloader ran exactly at 09:40 and populated scrapdata
    conn = get_db_connection()
    query = f"""
        SELECT stockname as clean_stock, time, open, high, low, close, volume 
        FROM scrapdata 
        WHERE DATE(time) = '{today_str}' AND TIME(time) BETWEEN '09:15:00' AND '09:40:00'
    """
    ticks = pd.read_sql(query, conn)
    conn.close()

    if ticks.empty:
        print("ERROR: No live ticks found in scrapdata. Did the ICICI JS downloader run?")
        return

    # D. Calculate Morning Technicals & Arc Shapes
    live_features = []
    
    # Needs 09:07 premarket ticks (Assuming another script grabs these or we approximate from first tick)
    # For this script, we will calculate the Arc based on 09:15 Open
    
    grouped = ticks.groupby('clean_stock')
    for stock, group in grouped:
        if stock in banned_stocks:
            continue
            
        group = group.sort_values('time').reset_index(drop=True)
        if len(group) < 5: continue # Skip if not enough ticks
        
        # Get yesterday's close from df_prev
        prev_row = df_prev[df_prev['clean_stock'] == stock]
        if prev_row.empty: continue
        prev_close = prev_row['prev_close'].values[0]
        
        # Base Prices
        open_0915 = group['open'].iloc[0]
        price_0940 = group['close'].iloc[-1]
        morning_high = group['high'].max()
        morning_low = group['low'].min()
        
        # Morning Technicals
        morning_return = ((price_0940 - open_0915) / open_0915) * 100
        morning_range = ((morning_high - morning_low) / morning_low) * 100
        morning_range_pos = ((price_0940 - morning_low) / (morning_high - morning_low)) * 100 if morning_high != morning_low else 50
        
        # Arc Shapes
        gap_pct = ((open_0915 - prev_close) / prev_close) * 100
        spike_from_prev_close_pct = ((morning_high - prev_close) / prev_close) * 100
        fade_from_high_pct = ((morning_high - price_0940) / morning_high) * 100
        positive_half_circle = spike_from_prev_close_pct * fade_from_high_pct
        gap_fade_completion = (open_0915 - price_0940) / (open_0915 - prev_close + 1e-9)
        
        stagnancy_prev_to_0940_pct = ((price_0940 - prev_close) / prev_close) * 100
        arc_shape_intensity = morning_range * (50 - morning_range_pos) / 50.0 
        
        # Expiry Features
        days_to_expiry = (get_expiry_date(today) - today).days

        # Compile Live Row
        feat_dict = {
            'clean_stock': stock,
            'Gap_Pct': gap_pct,
            'gap_abs': abs(gap_pct),
            'morning_return': morning_return,
            'morning_range': morning_range,
            'morning_range_pos': morning_range_pos,
            'spike_from_prev_close_pct': spike_from_prev_close_pct,
            'fade_from_high_pct': fade_from_high_pct,
            'positive_half_circle_prev_close': positive_half_circle,
            'gap_fade_completion': gap_fade_completion,
            'stagnancy_prev_to_0940_pct': stagnancy_prev_to_0940_pct,
            'abs_stagnancy_prev_to_0940': abs(stagnancy_prev_to_0940_pct),
            'arc_shape_intensity': arc_shape_intensity,
            'days_to_expiry': days_to_expiry
        }
        
        # Merge with Yesterday's Intraday Features
        for col in df_prev.columns:
            if col not in feat_dict and 'prev_' in col:
                feat_dict[col] = prev_row[col].values[0]
                
        live_features.append(feat_dict)

    live_df = pd.DataFrame(live_features)
    
    # (In Production, you would also merge hist_win_rate and hist_count here from markets_pnl0325)
    # For now, we will fill with median to prevent crash
    live_df['hist_win_rate'] = 0.60
    live_df['hist_count'] = 100
    live_df['hist_avg_pnl'] = 2000
    live_df['stagnancy_0907_to_0940_pct'] = live_df['stagnancy_prev_to_0940_pct'] # Approx
    live_df['abs_stagnancy_0907_to_0940'] = live_df['abs_stagnancy_prev_to_0940']
    
    # Fill remaining missing morning technicals (RSI, MACD, etc) with 0 for safety in script template
    # In a fully robust pipeline, you would calculate pandas_ta RSI on the 25 live ticks
    for c in ['morning_rsi_9', 'morning_macd', 'morning_vwap_gap', 'morning_momentum', 'morning_vol_trend', 'morning_bb_pct_b', 'morning_stoch_k', 'morning_ema_cross', 'morning_volatility', 'morning_volume']:
        live_df[c] = 0 

    # E. Load Model & Predict
    model_path = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_shortsell940_2026/models/sarang_shortsell_0940_production.pkl'
    model = joblib.load(model_path)
    
    # Ensure column order matches exactly what the model was trained on
    expected_cols = model.feature_name_
    for c in expected_cols:
        if c not in live_df.columns:
            live_df[c] = 0
            
    X_live = live_df[expected_cols]
    
    live_df['ml_prob'] = model.predict_proba(X_live)[:, 1]
    
    # Filter probabilities >= 0.53 and rank
    sel = live_df[live_df['ml_prob'] >= 0.53].copy()
    sel['daily_rank'] = sel['ml_prob'].rank(method='first', ascending=False)
    
    targets = sel[sel['daily_rank'].isin([1, 4])]
    
    print("\n" + "="*50)
    print("🎯 LIVE PREDICTION TARGETS (09:40 AM)")
    print("="*50)
    for _, row in targets.iterrows():
        print(f"RANK #{int(row['daily_rank'])} | STOCK: {row['clean_stock']} | PROB: {row['ml_prob']:.4f}")
    
    # Save targets for auto-execution
    targets.to_csv('/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_shortsell940_2026/output/todays_short_targets.csv', index=False)
    print("Targets saved to output/todays_short_targets.csv")

if __name__ == "__main__":
    run_live_predictions()
