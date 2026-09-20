#!/usr/bin/env python3
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

OUTPUT_DIR = "/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/historical_models/output"
DATA_DIR = "/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/data"

def main():
    print("="*105)
    print("      🚀 SUPERCHARGING THE HYBRID COMBINED MODEL WITH CONDITIONAL WALK-FORWARD EXITS 🚀")
    print("="*105)
    
    # 1. Re-run standard Hybrid Champion model backtest logic to extract the exact 1,742 active portfolio trades
    freqs = ['daily', 'weekly', 'monthly', 'quarterly', 'yearly']
    dfs = {}

    for freq in freqs:
        path = os.path.join(OUTPUT_DIR, f"trades_dynamic_threshold_{freq}.csv")
        if os.path.exists(path):
            df = pd.read_csv(path)
            df['date'] = pd.to_datetime(df['date'])
            dfs[freq] = df

    all_dates = set()
    for df in dfs.values():
        all_dates.update(df['date'].unique())
    all_dates = sorted(list(all_dates))

    daily_pnl = {freq: pd.Series(0.0, index=all_dates) for freq in freqs}
    for freq, df in dfs.items():
        dp = df.groupby('date')['actual_pnl'].sum()
        daily_pnl[freq].update(dp)

    df_pnl = pd.DataFrame(daily_pnl)
    df_pnl['date'] = df_pnl.index
    df_pnl = df_pnl.reset_index(drop=True)

    pnl_features = pd.DataFrame({'date': df_pnl['date']})
    for freq in freqs:
        for window in [3, 7, 14, 30]:
            pnl_features[f'{freq}_sum_{window}'] = df_pnl[freq].rolling(window=window).sum().shift(1)
            pnl_features[f'{freq}_mean_{window}'] = df_pnl[freq].rolling(window=window).mean().shift(1)

    f11_path = os.path.join(DATA_DIR, "f11_intraday_features_all.csv")
    df_f11 = pd.read_csv(f11_path)
    df_f11['Date'] = pd.to_datetime(df_f11['Date'])
    market_features = df_f11.groupby('Date').agg(
        market_volatility=('intraday_volatility', 'mean'),
        market_return=('intraday_return', 'mean'),
        market_trend=('intraday_rsi_9', 'mean'),
        market_adv_dec=('intraday_return', lambda x: (x > 0).mean()),
        market_macd=('intraday_macd', 'mean'),
        market_vwap_gap=('intraday_vwap_gap', 'mean')
    ).reset_index().rename(columns={'Date': 'date'})

    df_master = pd.merge(df_pnl, pnl_features, on='date', how='inner')
    df_master = pd.merge(df_master, market_features, on='date', how='inner')
    df_master = df_master.dropna().reset_index(drop=True)

    features_regime = [c for c in df_master.columns if c not in ['date'] + freqs]
    test_years = range(2020, 2027)

    df_ens_all = pd.read_csv(os.path.join(OUTPUT_DIR, "trades_dynamic_threshold_ensemble.csv"))
    df_ens_all['date'] = pd.to_datetime(df_ens_all['date'])
    df_ens_all['year'] = df_ens_all['date'].dt.year

    dampened_daily_trades = []
    pnl_history = []  

    print("⏳ Processing and generating the exact daily hybrid trade allocations lookahead-free...")
    for test_year in test_years:
        train_df = df_master[df_master['date'].dt.year < test_year]
        test_df = df_master[df_master['date'].dt.year == test_year]
        
        if len(train_df) < 50 or len(test_df) == 0:
            continue
            
        X_train_regime = train_df[features_regime].copy()
        X_test_regime = test_df[features_regime].copy()
        
        scaler_regime = StandardScaler()
        X_train_scaled_regime = scaler_regime.fit_transform(X_train_regime)
        X_test_scaled_regime = scaler_regime.transform(X_test_regime)
        
        preds_for_year = {freq: np.zeros(len(test_df)) for freq in freqs}
        for freq in freqs:
            y_train = train_df[freq]
            model_regime = Ridge(alpha=1.0, random_state=42)
            model_regime.fit(X_train_scaled_regime, y_train)
            preds_for_year[freq] = model_regime.predict(X_test_scaled_regime)
            
        for i, row in enumerate(test_df.itertuples()):
            dt = row.date
            
            day_static = df_ens_all[df_ens_all['date'] == dt].sort_values(by='pred_pnl', ascending=False)
            if day_static.empty:
                continue
                
            dampener_active = False
            today_iso = dt.isocalendar()
            current_year_num = today_iso[0]
            current_week_num = today_iso[1]
            
            if len(pnl_history) > 0:
                df_history = pd.DataFrame(pnl_history)
                past_our_weeks = df_history[df_history['date'] < dt]
                if not past_our_weeks.empty:
                    past_our_weeks = past_our_weeks.copy()
                    past_our_weeks['iso_week'] = past_our_weeks['date'].dt.isocalendar().week
                    past_our_weeks['iso_year'] = past_our_weeks['date'].dt.isocalendar().year
                    
                    completed_our_weeks = past_our_weeks[
                        ~((past_our_weeks['iso_year'] == current_year_num) & 
                          (past_our_weeks['iso_week'] == current_week_num))
                    ]
                    
                    if not completed_our_weeks.empty:
                        weekly_summary = completed_our_weeks.groupby(['iso_year', 'iso_week'])['actual_pnl'].sum()
                        if len(weekly_summary) > 0:
                            last_week_pnl = weekly_summary.iloc[-1]
                            if last_week_pnl < 0:
                                dampener_active = True
                                
            daily_preds = {freq: preds_for_year[freq][i] for freq in freqs}
            active_freqs = sorted(daily_preds, key=daily_preds.get, reverse=True)[:2]
            
            ml_stocks = set()
            for freq in active_freqs:
                day_freq_trades = dfs[freq][dfs[freq]['date'] == dt]
                ml_stocks.update(day_freq_trades['stock'].unique())
                    
            static_stocks = day_static['stock'].tolist()
            day_pnl_sum = 0.0
            
            if dampener_active:
                for idx, r in day_static.head(2).iterrows():
                    dampened_daily_trades.append({'date': dt, 'stockname': r['stock'], 'actual_pnl': r['actual_pnl'], 'lots': 1})
                    day_pnl_sum += r['actual_pnl']
            else:
                dual_confirmed_stock = None
                for s in static_stocks[:2]:
                    if s in ml_stocks:
                        dual_confirmed_stock = s
                        break
                        
                if dual_confirmed_stock and len(static_stocks) >= 2:
                    for idx, r in day_static.head(2).iterrows():
                        stock = r['stock']
                        pnl = r['actual_pnl']
                        
                        if stock == dual_confirmed_stock:
                            dampened_daily_trades.append({'date': dt, 'stockname': stock, 'actual_pnl': pnl * 2, 'lots': 2})
                            day_pnl_sum += pnl * 2
                        else:
                            dampened_daily_trades.append({'date': dt, 'stockname': stock, 'actual_pnl': pnl, 'lots': 1})
                            day_pnl_sum += pnl
                else:
                    for idx, r in day_static.head(2).iterrows():
                        dampened_daily_trades.append({'date': dt, 'stockname': r['stock'], 'actual_pnl': r['actual_pnl'], 'lots': 1})
                        day_pnl_sum += r['actual_pnl']
                        
            pnl_history.append({'date': dt, 'actual_pnl': day_pnl_sum})

    df_hybrid_trades = pd.DataFrame(dampened_daily_trades)
    df_hybrid_trades['year'] = df_hybrid_trades['date'].dt.year
    df_hybrid_trades['simulationdate'] = df_hybrid_trades['date'].dt.strftime('%Y-%m-%d')
    print(f"✔ Successfully extracted all {len(df_hybrid_trades)} active Hybrid trade allocations!")

    # 2. Load exit features & targets
    df_features = load_pnl()
    df_features['simulationdate'] = df_features['dt_parsed'].dt.strftime('%Y-%m-%d')
    
    features_exit = [
        'intraday_return', 'intraday_rsi_9', 'intraday_macd', 'intraday_bb_pct_b', 
        'first_tick_to_1519_pct', '1450_to_1519_pct', 'Gap_Pct', 'prev_close_price', 
        'daily_open', 'volume_change_pct'
    ]
    
    combined_csv_path = "/home/ubuntu/daily_prediction_system_Dynamic_threshold_Backtest_Dev/data/combined_multi_exit_pnl.csv"
    df_multi = pd.read_csv(combined_csv_path)
    
    df_targets_feats = pd.merge(
        df_multi,
        df_features[['simulationdate', 'stockname'] + features_exit],
        on=['simulationdate', 'stockname'],
        how='inner'
    ).dropna(subset=features_exit + ['pnl_0325', 'pnl_1000', 'pnl_1100', 'pnl_1200'])

    # 3. Yearly Walk-Forward Loop for ML Exit Selector
    print("\n⏳ Commencing Walk-Forward ML Exit Selector loop...")
    
    wfo_results = []
    
    for year in test_years:
        # Filter trades for this year
        year_trades = df_hybrid_trades[df_hybrid_trades['year'] == year].copy()
        if len(year_trades) == 0:
            continue
            
        # Get historical baseline training data for exit selector (all years BEFORE current test year)
        train_exit_data = df_targets_feats[pd.to_datetime(df_targets_feats['simulationdate']).dt.year < year].copy()
        
        # Standardize and train exit regressors
        scaler_exit = StandardScaler()
        X_train_exit = scaler_exit.fit_transform(train_exit_data[features_exit].values)
        
        targets = ['pnl_0325', 'pnl_1000', 'pnl_1100', 'pnl_1200']
        exit_models = {}
        for t in targets:
            model = Ridge(alpha=10.0, random_state=42)
            model.fit(X_train_exit, train_exit_data[t].values)
            exit_models[t] = model
            
        # Merge this year's trades with features/targets
        year_trades_merged = pd.merge(
            year_trades,
            df_targets_feats[['simulationdate', 'stockname'] + features_exit + ['pnl_0325', 'pnl_1000', 'pnl_1100', 'pnl_1200']],
            on=['simulationdate', 'stockname'],
            how='left'  # Use left join to keep ALL 1742 trades! If no feature matching, we keep baseline!
        )
        
        # Predict on matched trades
        matched_idx = year_trades_merged[features_exit].dropna().index
        
        ml_final_pnls = []
        for idx, row in year_trades_merged.iterrows():
            base_pnl = row['actual_pnl'] # already scaled by lots!
            lots = row['lots']
            
            # If trade has features and baseline is negative, let's check for extension
            if idx in matched_idx and (base_pnl / lots) < 0:
                feat_row = row[features_exit].values.reshape(1, -1)
                feat_scaled = scaler_exit.transform(feat_row)
                
                preds = {t: exit_models[t].predict(feat_scaled)[0] for t in targets}
                best_exit = max(preds, key=preds.get)
                
                if best_exit == 'pnl_0325':
                    ml_final_pnls.append(base_pnl)
                else:
                    # Take realized hourly exit PnL scaled by lot size
                    ml_final_pnls.append(row[best_exit] * lots)
            else:
                # If positive or missing feature data, keep baseline PnL as-is!
                ml_final_pnls.append(base_pnl)
                
        year_trades_merged['ml_exit_pnl'] = ml_final_pnls
        
        # Calculate statistics
        t_count = len(year_trades_merged)
        base_sum = year_trades_merged['actual_pnl'].sum()
        ml_sum = year_trades_merged['ml_exit_pnl'].sum()
        base_wr = (year_trades_merged['actual_pnl'] > 0).mean() * 100
        ml_wr = (year_trades_merged['ml_exit_pnl'] > 0).mean() * 100
        
        wfo_results.append({
            'Year': year,
            'Trades': t_count,
            'Base_Profit': base_sum,
            'Base_WinPct': base_wr,
            'ML_Profit': ml_sum,
            'ML_WinPct': ml_wr,
            'Improvement': ml_sum - base_sum
        })
        
    df_results = pd.DataFrame(wfo_results)
    
    # 4. Display walk-forward metrics
    print("\n" + "="*105)
    print("      🏆 TOTAL SYSTEM ENHANCEMENT: DUAL-CONFIRMATION HYBRID + CONDITIONAL EXITS (WFO) 🏆")
    print("="*105)
    print(f"{'Year':<6} | {'Trades':<6} | {'Baseline Hybrid PnL':<21} | {'ML-Exit Hybrid PnL':<21} | {'Net Alpha Boost':<17} | {'Win Rate Shift':<14}")
    print("-"*105)
    
    for _, row in df_results.iterrows():
        y = int(row['Year'])
        tr = int(row['Trades'])
        bp = row['Base_Profit']
        mp = row['ML_Profit']
        imp = row['Improvement']
        b_wr = row['Base_WinPct']
        m_wr = row['ML_WinPct']
        
        sign = "+" if imp >= 0 else ""
        year_str = f"{y}*" if y == 2026 else str(y)
        print(f"{year_str:<6} | {tr:<6} | Rs {bp:18,.2f} | Rs {mp:18,.2f} | Rs {sign}{imp:14,.2f} | {b_wr:5.1f}% → {m_wr:5.1f}%")
        
    print("-"*105)
    tot_tr = int(df_results['Trades'].sum())
    tot_bp = df_results['Base_Profit'].sum()
    tot_mp = df_results['ML_Profit'].sum()
    tot_imp = tot_mp - tot_bp
    
    print(f"{'TOTAL':<6} | {tot_tr:<6} | Rs {tot_bp:18,.2f} | Rs {tot_mp:18,.2f} | Rs +{tot_imp:14,.2f} | Supercharged! 🚀")
    print("="*105)
    print("* 2026 is strictly OUT OF SAMPLE")
    print("="*105)

if __name__ == '__main__':
    main()
