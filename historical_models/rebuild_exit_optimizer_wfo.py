#!/usr/bin/env python3
import os
import sys
import pandas as pd
import numpy as np
import mysql.connector
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
import warnings
warnings.filterwarnings('ignore')

# Add paths to load official data loaders
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PARENT_DIR = os.path.dirname(_THIS_DIR)
sys.path.append(_THIS_DIR)
sys.path.append(_PARENT_DIR)

from full_yoy_analysis import load_freq_data, build_master
from predict_today import load_pnl

DB_HOST = "localhost"
DB_USER = "root"
DB_PASSWORD = "root"
DB_NAME = "markets"

def get_db_connection():
    return mysql.connector.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME
    )

def main():
    print("="*105)
    print("      🏆 REBUILDING COMPREHENSIVE WALK-FORWARD EXIT TIME OPTIMIZER MODEL 🏆")
    print("="*105)
    
    # -------------------------------------------------------------------------
    # 1. Re-run standard Hybrid Combined System simulation to extract active trades
    # -------------------------------------------------------------------------
    print("⏳ Loading hybrid trades selection...")
    freqs = ['daily', 'weekly', 'monthly', 'quarterly', 'yearly']
    dfs = load_freq_data(freqs)
    df_master = build_master(dfs, freqs)
    
    features_regime = [c for c in df_master.columns if c not in ['date'] + freqs]
    test_years = range(2020, 2027) # 2020 to 2026
    
    df_ens = pd.read_csv(os.path.join(_THIS_DIR, "output", "trades_dynamic_threshold_ensemble.csv"))
    df_ens['date'] = pd.to_datetime(df_ens['date'])
    
    df_daily = pd.read_csv(os.path.join(_THIS_DIR, "output", "trades_dynamic_threshold_daily.csv"))
    df_daily['date'] = pd.to_datetime(df_daily['date'])
    
    combined_trades = []
    
    for test_year in test_years:
        train_df = df_master[df_master['date'].dt.year < test_year]
        test_df = df_master[df_master['date'].dt.year == test_year]
        if len(train_df) < 50 or len(test_df) == 0:
            continue
            
        scaler_regime = StandardScaler()
        X_tr = scaler_regime.fit_transform(train_df[features_regime])
        X_te = scaler_regime.transform(test_df[features_regime])
        
        preds = {freq: np.zeros(len(test_df)) for freq in freqs}
        for freq in freqs:
            m = Ridge(alpha=1.0, random_state=42)
            m.fit(X_tr, train_df[freq])
            preds[freq] = m.predict(X_te)
            
        for i, row in enumerate(test_df.itertuples()):
            dt = row.date
            
            day_ens = df_ens[df_ens['date'] == dt].sort_values('pred_pnl', ascending=False)
            day_daily = df_daily[df_daily['date'] == dt].sort_values('pred_pnl', ascending=False)
            
            if day_ens.empty and day_daily.empty:
                continue
                
            # ML stocks
            dp = {freq: preds[freq][i] for freq in freqs}
            active_freqs = sorted(dp, key=dp.get, reverse=True)[:2]
            ml_stocks = set()
            for freq in active_freqs:
                ml_stocks.update(dfs[freq][dfs[freq]['date'] == dt]['stock'].unique())
                
            static_stocks = day_ens['stock'].tolist() if not day_ens.empty else []
            
            dual_stock_row = None
            if len(static_stocks) > 0:
                for rank_idx, s in enumerate(static_stocks[:3]):
                    if s in ml_stocks:
                        matching_row = day_ens[day_ens['stock'] == s].iloc[0]
                        if matching_row['pred_pnl'] >= 2800.0:
                            dual_stock_row = matching_row
                            break
            
            day_trades = []
            if dual_stock_row is not None:
                day_trades.append({
                    'date': dt,
                    'stockname': dual_stock_row['stock'],
                    'lots': 2,
                    'type': 'Dual-Confirmed (2x)'
                })
            else:
                if not day_daily.empty:
                    for _, r in day_daily.iterrows():
                        day_trades.append({
                            'date': dt,
                            'stockname': r['stock'],
                            'lots': 1,
                            'type': 'Sniper Standard (1x)'
                        })
            combined_trades.extend(day_trades)
            
    df_hybrid = pd.DataFrame(combined_trades)
    print(f"✔ Successfully extracted {len(df_hybrid)} active Hybrid Combined trades.")
    
    # -------------------------------------------------------------------------
    # 2. Match with original PnL sheet & find exit dates (Day T+1)
    # -------------------------------------------------------------------------
    print("⏳ Matching with original PnL sheet & resolving chronological trading dates...")
    pnl_df = pd.read_csv(os.path.join(_PARENT_DIR, "data/markets_pnl0325.csv"))
    pnl_df['date'] = pd.to_datetime(pnl_df['simulationdate'], format='mixed')
    
    df_hybrid['date_only'] = df_hybrid['date'].dt.date
    pnl_df['date_only'] = pnl_df['date'].dt.date
    
    df_matched = pd.merge(
        df_hybrid,
        pnl_df[['date_only', 'stockname', 'buy_price', 'quantity', 'commission_paid', 'pnl', 'sell_price']],
        on=['date_only', 'stockname'],
        how='inner'
    )
    print(f"✔ Matched {len(df_matched)} trades with original price & quantity details.")
    
    # Map each entry date T to next chronological trading day T+1
    unique_dates = sorted(df_master['date'].unique())
    date_to_next = {unique_dates[i]: unique_dates[i+1] for i in range(len(unique_dates)-1)}
    
    df_matched['exit_date'] = df_matched['date'].map(date_to_next)
    df_matched = df_matched.dropna(subset=['exit_date'])
    
    # Load daily entry features database to attach to our trades
    df_features = load_pnl()
    df_features['simulationdate'] = df_features['dt_parsed'].dt.strftime('%Y-%m-%d')
    df_matched['simulationdate'] = df_matched['date'].dt.strftime('%Y-%m-%d')
    
    features_day_t = [
        'intraday_return', 'intraday_rsi_9', 'intraday_macd', 'intraday_bb_pct_b', 
        'first_tick_to_1519_pct', '1450_to_1519_pct', 'Gap_Pct', 'volume_change_pct'
    ]
    
    df_matched = pd.merge(
        df_matched,
        df_features[['simulationdate', 'stockname'] + features_day_t],
        on=['simulationdate', 'stockname'],
        how='inner'
    ).dropna(subset=features_day_t)
    print(f"✔ Aligned Day T entry features for {len(df_matched)} trade rows.")
    
    # -------------------------------------------------------------------------
    # 3. Pull minute-by-minute prices from MySQL and construct exit day dataset
    # -------------------------------------------------------------------------
    print("⏳ Pulling minute-by-minute prices from MySQL `scrapdata_F1` for exit days...")
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    minute_records = []
    
    for idx, row in df_matched.iterrows():
        stock = row['stockname']
        exit_date_str = row['exit_date'].strftime('%Y-%m-%d')
        
        query = """
            SELECT price, time FROM markets.scrapdata_F1
            WHERE stockname = %s AND date = %s
            AND time >= %s AND time <= %s
            ORDER BY time ASC
        """
        start_time = f"{exit_date_str} 09:15:00"
        end_time = f"{exit_date_str} 15:30:00"
        
        cursor.execute(query, (stock, exit_date_str, start_time, end_time))
        ticks = cursor.fetchall()
        
        if not ticks:
            continue
            
        df_ticks = pd.DataFrame(ticks)
        df_ticks['price'] = pd.to_numeric(df_ticks['price'], errors='coerce')
        df_ticks = df_ticks.dropna(subset=['price'])
        if df_ticks.empty:
            continue
            
        df_ticks['time'] = pd.to_datetime(df_ticks['time'])
        df_ticks['minute'] = df_ticks['time'].dt.floor('min')
        
        df_min = df_ticks.groupby('minute').first().reset_index()
        if df_min.empty:
            continue
            
        open_price = float(df_min['price'].iloc[0])
        if open_price <= 0:
            continue
            
        prices_list = [float(p) for p in df_min['price'].tolist()]
        
        for m_idx, r in df_min.iterrows():
            curr_price = float(r['price'])
            curr_return = (curr_price - open_price) / open_price if open_price > 0 else 0.0
            
            prices_so_far = prices_list[:m_idx + 1]
            max_so_far = max(prices_so_far)
            min_so_far = min(prices_so_far)
            
            high_return_so_far = (max_so_far - open_price) / open_price
            low_return_so_far = (min_so_far - open_price) / open_price
            
            remaining_prices = prices_list[m_idx:]
            max_remaining = max(remaining_prices)
            target_remaining_return = (max_remaining - curr_price) / curr_price if curr_price > 0 else 0.0
            
            rec = {
                'trade_idx': idx,
                'year': row['date'].year,
                'stockname': stock,
                'exit_date': row['exit_date'],
                'minute_idx': m_idx,
                'curr_price': curr_price,
                'open_price': open_price,
                'original_buy_price': row['buy_price'],
                'original_quantity': row['quantity'],
                'commission_paid': row['commission_paid'],
                'baseline_pnl': row['pnl'],
                'lots': row['lots'],
                
                # Dynamic minute features
                'curr_return': curr_return,
                'high_return_so_far': high_return_so_far,
                'low_return_so_far': low_return_so_far,
                
                # Targets
                'target_remaining_return': target_remaining_return,
            }
            
            for f in features_day_t:
                rec[f"day_t_{f}"] = row[f]
                
            minute_records.append(rec)
            
    cursor.close()
    conn.close()
    
    df_minutes = pd.DataFrame(minute_records)
    print(f"✔ Constructed minute dataset with {len(df_minutes)} total evaluation intervals.")
    
    # -------------------------------------------------------------------------
    # 4. Walk-Forward ML Exit Optimizer Simulation
    # -------------------------------------------------------------------------
    features_ml = [
        'minute_idx', 'curr_return', 'high_return_so_far', 'low_return_so_far',
        'day_t_intraday_return', 'day_t_intraday_rsi_9', 'day_t_intraday_macd', 'day_t_intraday_bb_pct_b', 
        'day_t_first_tick_to_1519_pct', 'day_t_1450_to_1519_pct', 'day_t_Gap_Pct', 
        'day_t_volume_change_pct'
    ]
    
    print("\n⏳ Starting Walk-Forward training and simulation across years (2020-2026)...")
    
    trade_results = []
    
    for year in test_years:
        train_minutes = df_minutes[df_minutes['year'] < year].copy()
        test_minutes = df_minutes[df_minutes['year'] == year].copy()
        
        if train_minutes.empty or test_minutes.empty:
            continue
            
        scaler = StandardScaler()
        X_tr = scaler.fit_transform(train_minutes[features_ml])
        y_tr = train_minutes['target_remaining_return'].values
        
        model = Ridge(alpha=10.0, random_state=42)
        model.fit(X_tr, y_tr)
        
        X_te = scaler.transform(test_minutes[features_ml])
        test_minutes['pred_remaining_return'] = model.predict(X_te)
        
        test_trade_ids = test_minutes['trade_idx'].unique()
        for t_id in test_trade_ids:
            trade_mins = test_minutes[test_minutes['trade_idx'] == t_id].sort_values('minute_idx')
            trade_row = df_matched.loc[t_id]
            
            exit_pnl = None
            exit_minute = None
            exit_price = None
            
            for _, min_row in trade_mins.iterrows():
                curr_price = min_row['curr_price']
                pred_return = min_row['pred_remaining_return']
                
                is_last_minute = (min_row['minute_idx'] == len(trade_mins) - 1)
                
                # Rule: Sell if predicted remaining return is less than 0.05%
                if pred_return <= 0.0005 or is_last_minute:
                    qty = trade_row['quantity'] * trade_row['lots']
                    exit_pnl = (curr_price - trade_row['buy_price']) * qty - (trade_row['commission_paid'] * trade_row['lots'])
                    exit_minute = min_row['minute_idx']
                    exit_price = curr_price
                    break
            
            trade_results.append({
                'year': year,
                'stockname': trade_row['stockname'],
                'date': trade_row['date'],
                'baseline_pnl': trade_row['pnl'] * trade_row['lots'],
                'ml_exit_pnl': exit_pnl if exit_pnl is not None else trade_row['pnl'] * trade_row['lots'],
                'exit_minute': exit_minute,
                'exit_price': exit_price,
            })
            
    df_results = pd.DataFrame(trade_results)
    
    yoy_summary = df_results.groupby('year').agg(
        Trades=('ml_exit_pnl', 'count'),
        Baseline_Total_PnL=('baseline_pnl', 'sum'),
        Baseline_Win_Pct=('baseline_pnl', lambda x: (x > 0).mean() * 100),
        ML_Total_PnL=('ml_exit_pnl', 'sum'),
        ML_Win_Pct=('ml_exit_pnl', lambda x: (x > 0).mean() * 100)
    ).reset_index()
    
    print("\n" + "="*90)
    print("    📈 DETAILED COMPARATIVE YEAR-BY-YEAR ALPHA ADDED FROM THE REBUILT EXIT OPTIMIZER 📈")
    print("="*90)
    for _, r in yoy_summary.iterrows():
        year = int(r['year'])
        net_alpha = r['ML_Total_PnL'] - r['Baseline_Total_PnL']
        print(f"📅 Year: {year}")
        print(f"   • Active Trades: {int(r['Trades'])}")
        print(f"   • Baseline PnL: Rs {r['Baseline_Total_PnL']:14,.2f} ({r['Baseline_Win_Pct']:.1f}% Win)")
        print(f"   • ML Optimized:  Rs {r['ML_Total_PnL']:14,.2f} ({r['ML_Win_Pct']:.1f}% Win) 🌟")
        print(f"   • 🔥 Alpha Added: Rs {net_alpha:+14,.2f} Net Profit Gain!")
        print("-"*90)
        
    overall_base = df_results['baseline_pnl'].sum()
    overall_ml = df_results['ml_exit_pnl'].sum()
    print(f"🌟 OVERALL PORTFOLIO NET PROFIT:")
    print(f"   • Baseline Total:  Rs {overall_base:14,.2f}")
    print(f"   • ML Optimized Total: Rs {overall_ml:14,.2f}")
    print(f"   • 🔥 TOTAL EXTRA NET ALPHA GENERATED: Rs {overall_ml - overall_base:+14,.2f}!!!")
    print("="*90)

if __name__ == '__main__':
    main()
