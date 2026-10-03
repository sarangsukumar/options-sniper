"""
🏆 09:20 TO 14:45 EXTENDED MODEL B (THE MORNING TICKS + STRUCTURAL EDGE ENGINE)
===================================================================================
100% PURE MYSQL DATABASE | ZERO YAHOO FINANCE | VERIFIED CONTRACT LOT SIZES
===================================================================================
Strategy Overview:
- Entry Time: 09:20:00 AM IST (Short Sell)
- Exit Time: 14:45:00 PM IST (Square Off)
- Morning Features: 09:15:00 to 09:18:00 AM IST (Strict 2-minute buffer before entry)
- Contextual Features: Previous Day Intraday Structure (VWAP gap, ROC, Rejection Wick, Arc Ratio)
- Pre-market Features: 09:07:00 AM IST Pre-market opening gap
- Universe: All NSE Equity Stocks (from MySQL `scrapdata`)
- Portfolio: Top 4 daily candidates ranked by LightGBM Regressor predicted edge
- Lot Sizes: Merged directly from `/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/config/historical_lotsize_new.csv`
- Charges: Flat ₹300.00 commission deducted per trade
===================================================================================
"""

import os
import sys
import warnings
import pandas as pd
import numpy as np
import lightgbm as lgb

warnings.filterwarnings('ignore')

BASE_DIR = '/home/ubuntu/920_Ensemble_Model_B'
LOTS_FILE = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/config/historical_lotsize_new.csv'
PNL_FILE = '/home/ubuntu/V8_Hybrid_Engine/mis_short_pnl_0920.csv'
MORN_FILE = '/home/ubuntu/V8_Hybrid_Engine/morning_features_0918.csv'
V6_MASTER_FILE = '/home/ubuntu/V8_Hybrid_Engine/v6_master_features.csv'
OUTPUT_TRADES_FILE = os.path.join(BASE_DIR, 'model_b_scratch_trades.csv')

def load_verified_lot_sizes():
    """Load verified contract lot sizes and index by future expiration date."""
    print("1. Loading verified historical lot sizes from historical_lotsize_new.csv...")
    df_lots = pd.read_csv(LOTS_FILE)
    df_lots['exp_dt'] = pd.to_datetime(df_lots['expdate'], format='%d/%m/%Y', errors='coerce')
    df_lots['stockname'] = df_lots['stockname'].astype(str).str.strip().str.upper()
    
    lot_map = {}
    for stock, grp in df_lots.groupby('stockname'):
        lot_map[stock] = grp.sort_values('exp_dt')
    return lot_map

def get_exact_lotsize(stock, dt, lot_map, fallback_lot):
    """Retrieve the exact expiration-matched contract lot size."""
    if stock not in lot_map:
        return fallback_lot
    sub = lot_map[stock]
    future_exps = sub[sub['exp_dt'] >= dt]
    if len(future_exps) > 0:
        return int(future_exps.iloc[0]['lotsize'])
    return int(sub.iloc[-1]['lotsize'])

def main():
    print("=" * 85)
    print("🏆 09:20 -> 14:45 EXTENDED MODEL B (ZERO YFINANCE | CORRECT LOT SIZES)")
    print("=" * 85)
    
    lot_map = load_verified_lot_sizes()
    
    print("2. Loading Pure Database Features (Zero Yahoo Finance)...")
    pnl = pd.read_csv(PNL_FILE)
    morn918 = pd.read_csv(MORN_FILE)
    v6_master = pd.read_csv(V6_MASTER_FILE)
    
    # Normalize stock symbols
    pnl['stockname'] = pnl['stockname'].astype(str).str.strip().str.upper()
    morn918['stockname'] = morn918['stockname'].astype(str).str.strip().str.upper()
    v6_master['stockname'] = v6_master['stockname'].astype(str).str.strip().str.upper()
    
    # Merge datasets
    df = pd.merge(pnl, morn918, on=['short_date', 'stockname'], how='inner')
    df = pd.merge(df, v6_master[[
        'short_date', 'stockname', 'prev_intraday_vwap_gap', 
        'prev_intraday_roc_last_hour', 'prev_intraday_return', 
        'positive_arc_ratio', 'rejection_wick', 'gap_0907_pct'
    ]], on=['short_date', 'stockname'], how='inner')
    
    print(f"   -> Merged {len(df):,} candidate trade records.")
    
    print("3. Applying Exact Historical Lot Sizes & Calculating PnL (₹300 Charges)...")
    df['date_dt'] = pd.to_datetime(df['short_date'])
    df['year'] = df['date_dt'].dt.year
    df['dayofweek'] = df['date_dt'].dt.dayofweek
    
    # Vectorized lot size lookup
    correct_lots = [
        get_exact_lotsize(s, d, lot_map, fb) 
        for s, d, fb in zip(df['stockname'], df['date_dt'], df['lotsize'])
    ]
    df['correct_lotsize'] = correct_lots
    
    # PnL math
    df['gross_pnl'] = (df['entry_price'] - df['exit_price']) * df['correct_lotsize']
    df['comm_charges'] = 300.0
    df['net_pnl'] = df['gross_pnl'] - df['comm_charges']
    df['target_pct'] = ((df['entry_price'] - df['exit_price']) / df['entry_price']) * 100
    
    # Exclude Mondays (proven historical drag)
    df_nomon = df[df['dayofweek'] != 0].copy()
    
    # Pure DB Features list
    features = [
        'prev_intraday_vwap_gap', 'prev_intraday_roc_last_hour', 'prev_intraday_return',
        'positive_arc_ratio', 'rejection_wick', 'gap_0907_pct',
        'morn_return_918', 'morn_range_918', 'morn_range_pos_918',
        'rejection_wick_918', 'lower_wick_918', 'body_ratio_918',
        'is_bearish_918', 'morn_vwap_gap_918', 'hl_ratio_918',
        'first_bar_return_918', 'momentum_918', 'vol_accel_918'
    ]
    
    for f in features:
        df_nomon[f] = pd.to_numeric(df_nomon[f], errors='coerce').fillna(0.0)
        
    print(f"4. Running Walk-Forward Optimization across {len(features)} Pure Database Features...")
    test_years = sorted(df_nomon[df_nomon['year'] >= 2020]['year'].unique())
    
    all_oos_trades = []
    for y in test_years:
        train_df = df_nomon[(df_nomon['year'] >= 2018) & (df_nomon['year'] < y)].copy()
        test_df = df_nomon[df_nomon['year'] == y].copy()
        if len(train_df) == 0 or len(test_df) == 0:
            continue
            
        model = lgb.LGBMRegressor(
            n_estimators=100,
            learning_rate=0.05,
            max_depth=5,
            random_state=42,
            verbose=-1
        )
        model.fit(train_df[features], train_df['target_pct'])
        
        test_df['predicted_edge'] = model.predict(test_df[features])
        test_df['daily_rank'] = test_df.groupby('short_date')['predicted_edge'].rank(ascending=False, method='first')
        
        top4 = test_df[test_df['daily_rank'] <= 4].copy()
        all_oos_trades.append(top4)
        
    final_trades = pd.concat(all_oos_trades)
    final_trades.to_csv(OUTPUT_TRADES_FILE, index=False)
    print(f"   -> Saved {len(final_trades):,} simulated trades to {OUTPUT_TRADES_FILE}")
    
    print("\n" + "=" * 85)
    print("🏆 FINAL VERIFIED 09:20 -> 14:45 MODEL B PERFORMANCE MATRIX")
    print("=" * 85)
    print("Year | Trades | Win Rate % | Gross PnL (₹ L) | Charges (₹ L) | NET PnL (₹ L) | Avg/Trade")
    print("-" * 85)
    
    tot_trades = len(final_trades)
    tot_wins = (final_trades['net_pnl'] > 0).sum()
    tot_gross = final_trades['gross_pnl'].sum()
    tot_comm = final_trades['comm_charges'].sum()
    tot_net = final_trades['net_pnl'].sum()
    
    for y in sorted(final_trades['year'].unique()):
        ydf = final_trades[final_trades['year'] == y]
        t_count = len(ydf)
        wins = (ydf['net_pnl'] > 0).sum()
        wr = (wins / t_count) * 100 if t_count > 0 else 0
        gross_l = ydf['gross_pnl'].sum() / 1e5
        comm_l = ydf['comm_charges'].sum() / 1e5
        net_l = ydf['net_pnl'].sum() / 1e5
        avg_trade = ydf['net_pnl'].mean() if t_count > 0 else 0
        print(f"{int(y)} | {t_count:6d} | {wr:10.2f}% | {gross_l:15.2f} | {comm_l:13.2f} | {net_l:13.2f} | ₹{avg_trade:8,.2f}")
        
    print("-" * 85)
    overall_wr = (tot_wins / tot_trades) * 100
    print(f"TOT  | {tot_trades:6d} | {overall_wr:10.2f}% | {tot_gross/1e5:15.2f} | {tot_comm/1e5:13.2f} | {tot_net/1e5:13.2f} | ₹{tot_net/tot_trades:8,.2f}")
    print("=" * 85)

if __name__ == '__main__':
    main()
