import os
import sys
import pandas as pd
import numpy as np
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
import warnings
warnings.filterwarnings('ignore')

# Add parent dir to path so we can import predict_today
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PARENT_DIR = os.path.dirname(_THIS_DIR)
sys.path.append(_PARENT_DIR)

from predict_today import load_pnl

def main():
    print("="*80)
    print("     🛡️ YEARLY WALK-FORWARD OPTIMIZATION: CONDITIONAL EXIT SELECTOR 🛡️")
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
    df_selected['simulationdate'] = df_selected['date'].dt.strftime('%Y-%m-%d')
    
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
    
    # Merge selective portfolio trades with targets and features
    df_merged = pd.merge(
        df_selected,
        df_targets_feats[['simulationdate', 'stockname'] + features + ['pnl_0325', 'pnl_1000', 'pnl_1100', 'pnl_1200']],
        on=['simulationdate', 'stockname'],
        how='inner'
    ).dropna(subset=features + ['pnl_0325', 'pnl_1000', 'pnl_1100', 'pnl_1200'])
    
    print(f"Total matched portfolio trades available: {len(df_merged)}")
    
    test_years = sorted(df_merged['year'].unique())
    test_years = [y for y in test_years if y >= 2020]
    
    results = []
    
    # 3. Yearly Walk-Forward Optimization Loop
    print("\n⏳ Commencing Walk-Forward simulation loop (2020 → 2026)...")
    for year in test_years:
        # Train on all years BEFORE current test year
        train_df = df_merged[df_merged['year'] < year].copy()
        # Test on current year
        test_df = df_merged[df_merged['year'] == year].copy()
        
        if len(train_df) == 0:
            print(f"⚠️ Skipping Year {year}: No training data prior to this year.")
            continue
            
        # Standardize features
        scaler = StandardScaler()
        X_train = scaler.fit_transform(train_df[features].values)
        X_test = scaler.transform(test_df[features].values)
        
        # Train parallel Ridge models for each exit candidate
        targets = ['pnl_0325', 'pnl_1000', 'pnl_1100', 'pnl_1200']
        models = {}
        for t in targets:
            model = Ridge(alpha=10.0, random_state=42)
            model.fit(X_train, train_df[t].values)
            models[t] = model
            
        # Predict on Test Year
        predicted_pnls = {}
        for t in targets:
            predicted_pnls[t] = models[t].predict(X_test)
            
        pred_df = pd.DataFrame(predicted_pnls, index=test_df.index)
        
        # Apply Conditional Extension Logic
        conditional_pnl = []
        for idx, row in test_df.iterrows():
            base_pnl = row['actual_pnl']
            
            if base_pnl >= 0:
                # Keep early morning baseline profit (no extension)
                conditional_pnl.append(base_pnl)
            else:
                # If negative, extend conditionally to best predicted hour
                preds_for_trade = pred_df.loc[idx]
                best_exit = preds_for_trade.idxmax()
                
                if best_exit == 'pnl_0325':
                    conditional_pnl.append(base_pnl)
                else:
                    conditional_pnl.append(row[best_exit])
                    
        test_df['ml_pnl'] = conditional_pnl
        
        # Compile year stats
        trades_count = len(test_df)
        base_sum = test_df['actual_pnl'].sum()
        ml_sum = test_df['ml_pnl'].sum()
        base_wr = (test_df['actual_pnl'] > 0).mean() * 100
        ml_wr = (test_df['ml_pnl'] > 0).mean() * 100
        
        results.append({
            'Year': year,
            'Trades': trades_count,
            'Base_Profit': base_sum,
            'Base_WinPct': base_wr,
            'ML_Profit': ml_sum,
            'ML_WinPct': ml_wr,
            'Improvement': ml_sum - base_sum
        })
        
    # Convert to DataFrame for presentation
    results_df = pd.DataFrame(results)
    
    # 4. Display walk-forward metrics
    print("\n" + "="*95)
    print("      🏆 TRUE OUT-OF-SAMPLE WALK-FORWARD PORTFOLIO RESULTS (2020-2026) 🏆")
    print("="*95)
    print(f"{'Year':<6} | {'Trades':<6} | {'Baseline Profit':<17} | {'ML Selector Profit':<19} | {'Net Extra Alpha':<17} | {'Win Rate Shift':<14}")
    print("-"*95)
    
    for _, row in results_df.iterrows():
        y = int(row['Year'])
        tr = int(row['Trades'])
        bp = row['Base_Profit']
        mp = row['ML_Profit']
        imp = row['Improvement']
        b_wr = row['Base_WinPct']
        m_wr = row['ML_WinPct']
        
        sign = "+" if imp >= 0 else ""
        print(f"{y:<6} | {tr:<6} | Rs {bp:14,.2f} | Rs {mp:16,.2f} | Rs {sign}{imp:14,.2f} | {b_wr:5.1f}% → {m_wr:5.1f}%")
        
    print("-"*95)
    tot_tr = int(results_df['Trades'].sum())
    tot_bp = results_df['Base_Profit'].sum()
    tot_mp = results_df['ML_Profit'].sum()
    tot_imp = tot_mp - tot_bp
    
    print(f"{'TOTAL':<6} | {tot_tr:<6} | Rs {tot_bp:14,.2f} | Rs {tot_mp:16,.2f} | Rs +{tot_imp:14,.2f} | Improvement! 🌟")
    print("="*95)
    
if __name__ == '__main__':
    main()
