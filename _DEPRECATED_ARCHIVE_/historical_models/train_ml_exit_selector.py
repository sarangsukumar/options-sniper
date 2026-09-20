import os
import sys
import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import StandardScaler
import pickle

# Add parent dir to path so we can import predict_today
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PARENT_DIR = os.path.dirname(_THIS_DIR)
sys.path.append(_PARENT_DIR)

from predict_today import load_pnl

def main():
    print("="*80)
    print("        🧠 TRAINING ADAPTIVE MACHINE LEARNING EXIT SELECTOR 🧠")
    print("="*80)
    
    # 1. Load baseline features
    df_features = load_pnl()
    df_features['simulationdate'] = df_features['dt_parsed'].dt.strftime('%Y-%m-%d')
    
    features = [
        'intraday_return', 'intraday_rsi_9', 'intraday_macd', 'intraday_bb_pct_b', 
        'first_tick_to_1519_pct', '1450_to_1519_pct', 'Gap_Pct', 'prev_close_price', 
        'daily_open', 'volume_change_pct'
    ]
    
    # 2. Load multi-exit merged targets
    combined_csv_path = "/home/ubuntu/daily_prediction_system_Dynamic_threshold_Backtest_Dev/data/combined_multi_exit_pnl.csv"
    df_multi = pd.read_csv(combined_csv_path)
    
    targets = ['pnl_0325', 'pnl_1000', 'pnl_1100', 'pnl_1200']
    
    # 3. Merge features and targets
    print("\n⏳ Merging features and targets...")
    merged_df = pd.merge(
        df_multi,
        df_features[['simulationdate', 'stockname'] + features],
        on=['simulationdate', 'stockname'],
        how='inner'
    ).dropna(subset=features + targets)
    
    print(f"Data ready! Total rows: {len(merged_df)}")
    
    # 4. Split Train vs Test (OOS) to prevent any look-ahead bias
    # Train: 2015 to 2024, Test: 2025 to 2026
    merged_df['year'] = pd.to_datetime(merged_df['simulationdate']).dt.year
    train_df = merged_df[merged_df['year'] < 2025].copy()
    test_df = merged_df[merged_df['year'] >= 2025].copy()
    
    print(f"📁 Training set (2015-2024) rows: {len(train_df)}")
    print(f"📁 Out-Of-Sample Test set (2025-2026) rows: {len(test_df)}")
    
    X_train = train_df[features].values
    X_test = test_df[features].values
    
    targets = ['pnl_0325', 'pnl_1000', 'pnl_1100', 'pnl_1200']
    
    # Scale features
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)
    
    # 5. Train Parallel Regressors for each exit time
    models = {}
    print("\n🚀 Training parallel regressor models (Random Forest) for each exit target...")
    for t in targets:
        print(f"  → Training model for target exit: '{t}'...")
        # Use fast, robust RF settings (50 trees, max_depth=12 for quick and highly generalizable fit)
        rf = RandomForestRegressor(n_estimators=50, max_depth=12, random_state=42, n_jobs=-1)
        rf.fit(X_train_scaled, train_df[t].values)
        models[t] = rf
        
    # 6. Evaluate on Out-of-Sample Test Set (2025-2026)
    print("\n🔮 Generating Out-of-Sample predictions for 2025-2026...")
    predicted_pnls = {}
    for t in targets:
        predicted_pnls[t] = models[t].predict(X_test_scaled)
        
    # Combine predictions
    pred_df = pd.DataFrame(predicted_pnls, index=test_df.index)
    
    # Select the exit that has the HIGHEST predicted PnL
    best_exit_pred = pred_df.idxmax(axis=1)
    
    # Calculate the actual realized PnL of this ML selection
    realized_pnl = []
    for idx, row in test_df.iterrows():
        selected_target = best_exit_pred.loc[idx]
        realized_pnl.append(row[selected_target])
        
    test_df['ml_selected_exit'] = best_exit_pred
    test_df['ml_realized_pnl'] = realized_pnl
    
    # 7. Compare Performance Metrics
    print("\n" + "="*80)
    print("      🏆 OUT-OF-SAMPLE (2025-2026) PERFORMANCE COMPARISON 🏆")
    print("="*80)
    
    for t in targets:
        total_pnl = test_df[t].sum()
        avg_pnl = test_df[t].mean()
        win_rate = (test_df[t] > 0).mean() * 100
        print(f"Exit Strategy: {t:<10} | Total PnL: Rs {total_pnl:14,.2f} | Avg: Rs {avg_pnl:8.2f} | WR: {win_rate:5.1f}%")
        
    # ML Selected performance
    ml_total = test_df['ml_realized_pnl'].sum()
    ml_avg = test_df['ml_realized_pnl'].mean()
    ml_win_rate = (test_df['ml_realized_pnl'] > 0).mean() * 100
    print("-"*80)
    print(f"ML ADAPTIVE EXIT    | Total PnL: Rs {ml_total:14,.2f} | Avg: Rs {ml_avg:8.2f} | WR: {ml_win_rate:5.1f}% 🌟")
    print("="*80)
    
    # Save models and scaler
    model_export = {
        'scaler': scaler,
        'models': models,
        'features': features
    }
    export_path = os.path.join(_THIS_DIR, "output", "adaptive_exit_selector_models.pkl")
    os.makedirs(os.path.dirname(export_path), exist_ok=True)
    with open(export_path, 'wb') as f:
        pickle.dump(model_export, f)
    print(f"💾 Saved fully trained ML exit models to {export_path}")

if __name__ == '__main__':
    main()
