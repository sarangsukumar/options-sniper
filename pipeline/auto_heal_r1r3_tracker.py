import pandas as pd
import os
import glob
from datetime import datetime, timedelta
import subprocess

BASE_DIR = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold'
SIM_DIR = os.path.join(BASE_DIR, 'output', 'simulation_results')
TRACKER_PATH = os.path.join(BASE_DIR, 'output', 'trades_dynamic_threshold.csv')
BOT_SCRIPT = '/home/ubuntu/telegram_bot/New_OrderInfoBot.js'
NODE_BIN = '/usr/bin/node'

def send_telegram(msg):
    try:
        subprocess.run([NODE_BIN, BOT_SCRIPT, msg], check=True, capture_output=True)
    except Exception as e:
        print(f"Telegram alert failed: {e}")

def main():
    print(f"Starting Weekly R1+R3 Tracker Auto-Heal Check at {datetime.now()}")
    if not os.path.exists(TRACKER_PATH):
        print(f"Tracker not found: {TRACKER_PATH}")
        return

    tracker = pd.read_csv(TRACKER_PATH)
    # Convert date to string to avoid mixed types when checking
    tracker['date_str'] = pd.to_datetime(tracker['date'], errors='coerce').dt.strftime('%Y-%m-%d')
    
    today = datetime.now().date()
    # Check the last 15 days to comfortably cover the previous week
    check_dates = [(today - timedelta(days=i)) for i in range(1, 16)]
    
    new_rows = []
    fixed_dates = []

    for dt in check_dates:
        d_str = dt.strftime('%Y-%m-%d')
        # Skip if date is already in tracker
        if d_str in tracker['date_str'].values:
            continue
        
        # Look for simulation folders for this date (sim might run same day or next morning)
        found_picks = False
        for delta in [0, 1]:
            run_dt = dt + timedelta(days=delta)
            matches = glob.glob(f'{SIM_DIR}/simulation_results_{run_dt.strftime("%Y%m%d")}_*')
            if matches:
                folder = sorted(matches)[-1]  # Get the latest run if multiple exist
                pred_f = os.path.join(folder, 'markets_pnl_predicted.csv')
                if os.path.exists(pred_f):
                    df = pd.read_csv(pred_f)
                    if len(df) > 0:
                        df['pnl'] = pd.to_numeric(df['pnl'], errors='coerce')
                        for _, row in df.iterrows():
                            new_rows.append({
                                'date': d_str,
                                'day': dt.strftime('%A'),
                                'stock': row['stockname'],
                                'pred_pnl': 0.0,
                                'actual_pnl': round(row['pnl'], 2) if pd.notna(row['pnl']) else 0.0,
                                'threshold_used': None,
                                'multiplier_used': None,
                                'qty': None,
                                'year': dt.year,
                                'month': dt.month
                            })
                        found_picks = True
                break # Found a valid simulation folder for this date, stop checking delta=1
        
        if found_picks:
            fixed_dates.append(d_str)

    if new_rows:
        new_df = pd.DataFrame(new_rows)
        # Reload clean tracker to concatenate without the temp date_str column
        tracker_clean = pd.read_csv(TRACKER_PATH)
        tracker_updated = pd.concat([tracker_clean, new_df], ignore_index=True)
        
        # Sort properly
        tracker_updated['temp_date'] = pd.to_datetime(tracker_updated['date'], errors='coerce')
        tracker_updated = tracker_updated.sort_values('temp_date').drop(columns=['temp_date'])
        
        # Save back
        tracker_updated.to_csv(TRACKER_PATH, index=False)
        
        msg = (f"🔧 <b>Weekly Auto-Healer: Tracker Fixed</b>\n\n"
               f"Recovered {len(new_rows)} missing trades from {len(fixed_dates)} dates:\n"
               f"<code>{', '.join(fixed_dates)}</code>\n\n"
               f"Master tracker is now fully up to date.")
        print(msg)
        send_telegram(msg)
    else:
        print("All good. No missing trades found in the last 15 days.")

if __name__ == "__main__":
    main()
