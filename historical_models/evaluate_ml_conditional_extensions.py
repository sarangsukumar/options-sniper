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
    print("      🔄 CONDITIONAL TRADE EXTENSION PORTFOLIO SIMULATION 🔄")
    print("="*80)
    
    # 1. Load selective baseline portfolio (Sniper R1+R3)
    portfolio_csv = os.path.join(_PARENT_DIR, 'output/trades_dynamic_threshold_CLEAN_REFERENCE_20260812.csv')
    if not os.path.exists(portfolio_csv):
        print(f"❌ Error: Could not find {portfolio_csv}")
        return
        
    df_port = pd.read_csv(portfolio_csv)
    df_port['date'] = pd.to_datetime(df_port['date'])
    df_port = df_port.rename(columns={'stock': 'stockname'})
    
    # Apply Sniper selection logic (R1+R3)
    day_counts = df_port.groupby('date').size().reset_index(name='daily_count')
    df_port = df_port.merge(day_counts, on='date')
    df_port['rank'] = df_port.groupby('date').cumcount() + 1
    
    mask_r1r3 = (df_port['daily_count'] >= 3) & (df_port['rank'].isin([1, 3]))
    mask_r1only = (df_port['daily_count'] < 3) & (df_port['rank'] == 1)
    df_selected = df_port[mask_r1r3 | mask_r1only].copy()
    
    df_selected['year'] = df_selected['date'].dt.year
    df_oos = df_selected[df_selected['year'] >= 2025].copy()
    
    # 2. Load baseline features
    df_features = load_pnl()
    df_features['simulationdate'] = df_features['dt_parsed'].dt.strftime('%Y-%m-%d')
    
    features = [
        'intraday_return', 'intraday_rsi_9', 'intraday_macd', 'intraday_bb_pct_b', 
        'first_tick_to_1519_pct', '1450_to_1519_pct', 'Gap_Pct', 'prev_close_price', 
        'daily_open', 'volume_change_pct'
    ]
    
    # Load multi-exit candidate PnLs
    combined_csv_path = os.path.join(_PARENT_DIR, 'data/combined_multi_exit_pnl.csv')
    df_multi = pd.read_csv(combined_csv_path)
    
    # Merge targets & features
    df_targets_feats = pd.merge(
        df_multi,
        df_features[['simulationdate', 'stockname'] + features],
        on=['simulationdate', 'stockname'],
        how='inner'
    )
    
    # 3. Load Ridge models
    model_pickle_path = os.path.join(_THIS_DIR, "output", "adaptive_exit_selector_ridge_models.pkl")
    if not os.path.exists(model_pickle_path):
        print(f"❌ Error: Model pickle not found. Run train_ml_exit_selector_fast.py first.")
        return
        
    with open(model_pickle_path, 'rb') as f:
        model_data = pickle.load(f)
        
    scaler = model_data['scaler']
    models = model_data['models']
    
    # 4. Merge selective trades with targets and features
    df_oos['simulationdate'] = df_oos['date'].dt.strftime('%Y-%m-%d')
    df_merged = pd.merge(
        df_oos,
        df_targets_feats[['simulationdate', 'stockname'] + features + ['pnl_1000', 'pnl_1100', 'pnl_1200']],
        on=['simulationdate', 'stockname'],
        how='inner'
    ).dropna(subset=features)
    
    # 5. Predict expected PnLs
    X_scaled = scaler.transform(df_merged[features].values)
    
    targets = ['pnl_0325', 'pnl_1000', 'pnl_1100', 'pnl_1200']
    predicted_pnls = {}
    for t in targets:
        predicted_pnls[t] = models[t].predict(X_scaled)
        
    pred_df = pd.DataFrame(predicted_pnls, index=df_merged.index)
    
    # 6. Apply Conditional Extension Logic:
    # Rule: 
    # - If baseline_pnl (actual_pnl from 0325 early exit) >= 0 -> Keep baseline_pnl.
    # - If baseline_pnl < 0 -> Query ML predictions for pnl_1000, pnl_1100, pnl_1200.
    #   Pick the exit with the highest predicted PnL. If it's a later time, take its actual realized hourly PnL.
    
    conditional_pnl = []
    actions_taken = []
    
    for idx, row in df_merged.iterrows():
        base_pnl = row['actual_pnl']
        
        if base_pnl >= 0:
            # Positive baseline trade -> Square off immediately (no extension)
            conditional_pnl.append(base_pnl)
            actions_taken.append("Locked Early Profit")
        else:
            # Negative baseline trade -> Check if we can recover by extending
            preds_for_trade = pred_df.loc[idx]
            
            # Find candidate with highest predicted PnL
            best_predicted_exit = preds_for_trade.idxmax()
            
            if best_predicted_exit == 'pnl_0325':
                # Model suggests keeping the early exit as the best/safest choice
                conditional_pnl.append(base_pnl)
                actions_taken.append("Kept Early Exit (Safe)")
            else:
                # Model suggests extending the exit!
                realized_hourly_pnl = row[best_predicted_exit]
                conditional_pnl.append(realized_hourly_pnl)
                actions_taken.append(f"Extended to {best_predicted_exit.replace('pnl_', '')}")
                
    df_merged['conditional_exit_pnl'] = conditional_pnl
    df_merged['action_taken'] = actions_taken
    
    # 7. Print Comparative Analysis
    print("\n" + "="*80)
    yoy_stats = df_merged.groupby('year').agg(
        Trades=('conditional_exit_pnl', 'count'),
        Base_Profit=('actual_pnl', 'sum'),
        Base_WinPct=('actual_pnl', lambda x: (x>0).mean()*100),
        Cond_Profit=('conditional_exit_pnl', 'sum'),
        Cond_WinPct=('conditional_exit_pnl', lambda x: (x>0).mean()*100)
    ).reset_index()
    
    print("      📈 CONDITIONAL EXTENSION vs BASELINE YoY PERFORMANCE COMPARISON 📈")
    print("="*80)
    for idx, r in yoy_stats.iterrows():
        year = int(r['year'])
        improvement = r['Cond_Profit'] - r['Base_Profit']
        print(f"📅 Year: {year}")
        print(f"   • Total Trades: {int(r['Trades'])}")
        print(f"   • Baseline Profit (Locked Early): Rs {r['Base_Profit']:12,.2f} (Win: {r['Base_WinPct']:.1f}%)")
        print(f"   • Conditional Extension Profit:  Rs {r['Cond_Profit']:12,.2f} (Win: {r['Cond_WinPct']:.1f}%) 🌟")
        print(f"   • 🔥 NET PORTFOLIO ALPHA ADDED:  Rs {improvement:+12,.2f} Profit Increase!")
        print("-"*80)
        
    # Overall summary
    tot_trades = len(df_merged)
    base_tot = df_merged['actual_pnl'].sum()
    cond_tot = df_merged['conditional_exit_pnl'].sum()
    net_alpha = cond_tot - base_tot
    
    print(f"🌟 OVERALL OUT-OF-SAMPLE (2025-2026) SUMMARY:")
    print(f"   • Total Filtered Portfolio Trades: {tot_trades}")
    print(f"   • Baseline Portfolio Profit: Rs {base_tot:12,.2f}")
    print(f"   • Conditional Extension Profit:  Rs {cond_tot:12,.2f} 🌟")
    print(f"   • 🔥 TOTAL NET EXTRA PORTFOLIO ALPHA: Rs {net_alpha:+12,.2f} Profit Increase!")
    print("="*80)
    
    # Show breakdown of actions
    print("\n📋 ACTION TAKEN BREAKDOWN ON NEGATIVE TRADES:")
    print(df_merged['action_taken'].value_counts())
    print("="*80)

if __name__ == '__main__':
    main()
