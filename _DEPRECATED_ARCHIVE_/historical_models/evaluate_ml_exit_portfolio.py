import os
import sys
import pandas as pd
import numpy as np
import pickle

# Add parent dir to path so we can import predict_today
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PARENT_DIR = os.path.dirname(_THIS_DIR)
sys.path.append(_PARENT_DIR)

from predict_today import load_pnl

def main():
    print("="*80)
    print("        🏆 PORTFOLIO SIMULATION: BASELINE vs ML ADAPTIVE EXIT 🏆")
    print("="*80)
    
    # 1. Load the actual selected portfolio trades (R1 + R3 Sniper Mode)
    # This represents the actual filtered, selective, profitable portfolio!
    portfolio_csv = os.path.join(_PARENT_DIR, 'output/trades_dynamic_threshold_CLEAN_REFERENCE_20260812.csv')
    if not os.path.exists(portfolio_csv):
        print(f"❌ Error: Could not find {portfolio_csv}")
        return
        
    print(f"⏳ Loading selective baseline portfolio from {portfolio_csv}...")
    df_port = pd.read_csv(portfolio_csv)
    df_port['date'] = pd.to_datetime(df_port['date'])
    
    # Standardize stockname
    df_port = df_port.rename(columns={'stock': 'stockname'})
    
    # 2. Apply Sniper R1 + R3 portfolio selections rule (same as run_master_backtest.py)
    day_counts = df_port.groupby('date').size().reset_index(name='daily_count')
    df_port = df_port.merge(day_counts, on='date')
    df_port['rank'] = df_port.groupby('date').cumcount() + 1
    
    mask_r1r3 = (df_port['daily_count'] >= 3) & (df_port['rank'].isin([1, 3]))
    mask_r1only = (df_port['daily_count'] < 3) & (df_port['rank'] == 1)
    df_selected = df_port[mask_r1r3 | mask_r1only].copy()
    
    # Filter for Out-of-Sample period (2025 to 2026)
    df_selected['year'] = df_selected['date'].dt.year
    df_oos = df_selected[df_selected['year'] >= 2025].copy()
    print(f"Loaded {len(df_oos)} selective portfolio trades for OOS period (2025-2026).")
    
    # 3. Load ML model features and targets (the multi-exit PnLs and standard morning features)
    df_features = load_pnl()
    df_features['simulationdate'] = df_features['dt_parsed'].dt.strftime('%Y-%m-%d')
    
    features = [
        'intraday_return', 'intraday_rsi_9', 'intraday_macd', 'intraday_bb_pct_b', 
        'first_tick_to_1519_pct', '1450_to_1519_pct', 'Gap_Pct', 'prev_close_price', 
        'daily_open', 'volume_change_pct'
    ]
    
    # Load targets sheet
    combined_csv_path = os.path.join(_PARENT_DIR, 'data/combined_multi_exit_pnl.csv')
    df_multi = pd.read_csv(combined_csv_path)
    
    # Merge targets & features
    df_targets_feats = pd.merge(
        df_multi,
        df_features[['simulationdate', 'stockname'] + features],
        on=['simulationdate', 'stockname'],
        how='inner'
    )
    
    # 4. Load the trained Ridge ML Selector model
    model_pickle_path = os.path.join(_THIS_DIR, "output", "adaptive_exit_selector_ridge_models.pkl")
    if not os.path.exists(model_pickle_path):
        print(f"❌ Error: Trained ML Exit Selector model not found at {model_pickle_path}. Run train_ml_exit_selector_fast.py first.")
        return
        
    with open(model_pickle_path, 'rb') as f:
        model_data = pickle.load(f)
        
    scaler = model_data['scaler']
    models = model_data['models']
    
    # 5. Predict best exits for our selective portfolio trades
    df_oos['simulationdate'] = df_oos['date'].dt.strftime('%Y-%m-%d')
    
    # Merge our selected portfolio trades with the features and candidate multi-exit targets
    print("⏳ Matching selective trades with morning features and candidate exit targets...")
    df_merged = pd.merge(
        df_oos,
        df_targets_feats[['simulationdate', 'stockname'] + features + ['pnl_1000', 'pnl_1100', 'pnl_1200']],
        on=['simulationdate', 'stockname'],
        how='inner'
    ).dropna(subset=features)
    
    print(f"Successfully matched features for {len(df_merged)} out of {len(df_oos)} portfolio trades.")
    
    # Generate predictions
    X_scaled = scaler.transform(df_merged[features].values)
    
    targets = ['pnl_0325', 'pnl_1000', 'pnl_1100', 'pnl_1200']
    predicted_pnls = {}
    for t in targets:
        predicted_pnls[t] = models[t].predict(X_scaled)
        
    pred_df = pd.DataFrame(predicted_pnls, index=df_merged.index)
    best_exit_pred = pred_df.idxmax(axis=1)
    
    # Map selected targets to actual outcomes
    realized_pnls = []
    baseline_pnls = []
    
    for idx, row in df_merged.iterrows():
        selected_exit = best_exit_pred.loc[idx]
        # Realized ML PnL
        if selected_exit == 'pnl_0325':
            realized_pnls.append(row['actual_pnl'])  # baseline actual_pnl
        else:
            realized_pnls.append(row[selected_exit]) # hourly PnL
            
        baseline_pnls.append(row['actual_pnl'])
        
    df_merged['ml_exit_pnl'] = realized_pnls
    df_merged['baseline_pnl'] = baseline_pnls
    df_merged['selected_exit'] = best_exit_pred
    
    # 6. Print comparative analysis
    print("\n" + "="*80)
    # Group by year
    yoy_stats = df_merged.groupby('year').agg(
        Trades=('ml_exit_pnl', 'count'),
        Base_Total=('baseline_pnl', 'sum'),
        Base_WinPct=('baseline_pnl', lambda x: (x>0).mean()*100),
        ML_Total=('ml_exit_pnl', 'sum'),
        ML_WinPct=('ml_exit_pnl', lambda x: (x>0).mean()*100)
    ).reset_index()
    
    print("           📈 YEAR-ON-YEAR PORTFOLIO ALPHA PERFORMANCE COMPARISON 📈")
    print("="*80)
    for idx, r in yoy_stats.iterrows():
        year = int(r['year'])
        improvement = r['ML_Total'] - r['Base_Total']
        print(f"📅 Year: {year}")
        print(f"   • Total Trades: {int(r['Trades'])}")
        print(f"   • Baseline Portfolio Profit: Rs {r['Base_Total']:12,.2f} (Win: {r['Base_WinPct']:.1f}%)")
        print(f"   • ML Adaptive Exit Profit:  Rs {r['ML_Total']:12,.2f} (Win: {r['ML_WinPct']:.1f}%) 🌟")
        print(f"   • 🔥 NET PORTFOLIO ALPHA ADDED:  Rs {improvement:+12,.2f} Profit Increase!")
        print("-"*80)
        
    # Overall OOS summary
    tot_trades = len(df_merged)
    base_tot = df_merged['baseline_pnl'].sum()
    ml_tot = df_merged['ml_exit_pnl'].sum()
    overall_improvement = ml_tot - base_tot
    print(f"🌟 OVERALL OUT-OF-SAMPLE (2025-2026) SUMMARY:")
    print(f"   • Total Filtered Portfolio Trades: {tot_trades}")
    print(f"   • Baseline Portfolio Profit: Rs {base_tot:12,.2f}")
    print(f"   • ML Adaptive Exit Profit:  Rs {ml_tot:12,.2f} 🌟")
    print(f"   • 🔥 TOTAL NET EXTRA PROFIT ADDED: Rs {overall_improvement:+12,.2f} Net Alpha!")
    print("="*80)

if __name__ == '__main__':
    main()
