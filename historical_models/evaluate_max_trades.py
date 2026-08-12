import os
import pandas as pd
import numpy as np
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(_THIS_DIR, "output")
DATA_DIR = os.path.join(os.path.dirname(_THIS_DIR), 'data')

def run_backtest(max_trades):
    freqs = ['daily', 'weekly', 'monthly', 'quarterly', 'yearly']
    dfs = {}
    
    # Load all frequency trades
    for freq in freqs:
        path = os.path.join(OUTPUT_DIR, f'trades_dynamic_threshold_{freq}.csv')
        df = pd.read_csv(path)
        df['date'] = pd.to_datetime(df['date'])
        dfs[freq] = df

    # Load Static Ensemble base
    static_df = pd.read_csv(os.path.join(OUTPUT_DIR, 'trades_dynamic_threshold_ensemble.csv'))
    static_df['date'] = pd.to_datetime(static_df['date'])
    
    # Ensure all dataframes share the exact same dates
    valid_dates = set(static_df['date'])
    for freq in freqs:
        valid_dates.intersection_update(dfs[freq]['date'])
    
    valid_dates = sorted(list(valid_dates))
    for freq in freqs:
        dfs[freq] = dfs[freq][dfs[freq]['date'].isin(valid_dates)].copy()
    static_df = static_df[static_df['date'].isin(valid_dates)].copy()
    
    # Build PnL history dataframe
    pnl_hist = {freq: dfs[freq].groupby('date')['actual_pnl'].sum() for freq in freqs}
    df_pnl = pd.DataFrame(pnl_hist).reset_index()
    df_pnl = df_pnl.sort_values('date').reset_index(drop=True)
    
    # Pre-calculate rolling features
    feats = pd.DataFrame({'date': df_pnl['date']})
    for freq in freqs:
        for w in [3, 7, 14, 30]:
            feats[f'{freq}_sum_{w}'] = df_pnl[freq].rolling(w).sum().shift(1)
            feats[f'{freq}_mean_{w}'] = df_pnl[freq].rolling(w).mean().shift(1)
            
    # Load f11 market features
    f11_path = os.path.join(DATA_DIR, 'f11_intraday_features_all.csv')
    df_f11 = pd.read_csv(f11_path)
    df_f11['Date'] = pd.to_datetime(df_f11['Date'], format='mixed', dayfirst=True)
    mkt_feats = df_f11.groupby('Date').agg(
        market_volatility=('intraday_volatility', 'mean') if 'intraday_volatility' in df_f11.columns else ('intraday_return', 'std'),
        market_return=('intraday_return', 'mean'),
        market_trend=('intraday_rsi_9', 'mean'),
        market_adv_dec=('intraday_return', lambda x: (x > 0).mean())
    ).reset_index().rename(columns={'Date': 'date'})
    
    df_master = pd.merge(df_pnl, feats, on='date', how='inner')
    df_master = pd.merge(df_master, mkt_feats, on='date', how='inner')
    df_master = df_master.dropna().reset_index(drop=True)
    feature_cols = [c for c in df_master.columns if c not in ['date'] + freqs]
    
    test_years = range(2020, 2027)
    all_trades = []
    pnl_history = []
    
    for yr in test_years:
        df_train = df_master[df_master['date'].dt.year < yr].copy()
        df_test = df_master[df_master['date'].dt.year == yr].copy()
        
        if len(df_train) < 100:
            continue
            
        X_tr = df_train[feature_cols].values
        X_te = df_test[feature_cols].values
        
        scaler = StandardScaler()
        X_tr = scaler.fit_transform(X_tr)
        X_te = scaler.transform(X_te)
        
        preds_for_year = {}
        for freq in freqs:
            y_tr = df_train[freq].values
            model = Ridge(alpha=1.0, random_state=42)
            model.fit(X_tr, y_tr)
            preds_for_year[freq] = model.predict(X_te)
            
        test_dates = df_test['date'].tolist()
        for i, dt in enumerate(test_dates):
            # Limit the static picks to max_trades!
            day_static_full = static_df[static_df['date'] == dt].sort_values('pred_pnl', ascending=False)
            day_static = day_static_full.head(max_trades)
            
            if day_static.empty:
                continue
                
            dampener_active = False
            if len(pnl_history) > 0:
                df_hist = pd.DataFrame(pnl_history)
                df_hist['iso_year'] = df_hist['date'].dt.isocalendar().year
                df_hist['iso_week'] = df_hist['date'].dt.isocalendar().week
                today_iso = dt.isocalendar()
                curr_yr, curr_wk = today_iso[0], today_iso[1]
                
                completed_our_weeks = df_hist[~((df_hist['iso_year'] == curr_yr) & (df_hist['iso_week'] == curr_wk))]
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
            day_trades = []
            
            if dampener_active:
                for idx, r in day_static.iterrows():
                    day_trades.append({'date': dt, 'stock': r['stock'], 'lots': 1, 'actual_pnl': r['actual_pnl']})
                    day_pnl_sum += r['actual_pnl']
            else:
                dual_confirmed_stock = None
                for s in static_stocks[:3]:
                    if s in ml_stocks:
                        dual_confirmed_stock = s
                        break
                        
                if dual_confirmed_stock and len(static_stocks) >= 2:
                    stock_to_drop = None
                    for s in reversed(static_stocks):
                        if s != dual_confirmed_stock:
                            stock_to_drop = s
                            break
                            
                    for idx, r in day_static.iterrows():
                        stock = r['stock']
                        pnl = r['actual_pnl']
                        
                        if stock == dual_confirmed_stock:
                            day_trades.append({'date': dt, 'stock': stock, 'lots': 2, 'actual_pnl': pnl * 2})
                            day_pnl_sum += pnl * 2
                        elif stock != stock_to_drop:
                            day_trades.append({'date': dt, 'stock': stock, 'lots': 1, 'actual_pnl': pnl})
                            day_pnl_sum += pnl
                else:
                    for idx, r in day_static.iterrows():
                        day_trades.append({'date': dt, 'stock': r['stock'], 'lots': 1, 'actual_pnl': r['actual_pnl']})
                        day_pnl_sum += r['actual_pnl']
                        
            all_trades.extend(day_trades)
            pnl_history.append({'date': dt, 'actual_pnl': day_pnl_sum})

    return pd.DataFrame(all_trades)

if __name__ == "__main__":
    mt = 4  # The dual confirmed trades are the same regardless of max_trades (as long as >= 2)
    print(f"\n==============================================")
    print(f" PERFORMANCE OF DUAL CONFIRMED TRADES (2x LOTS)")
    print(f"==============================================")
    df_trades = run_backtest(mt)
    
    # Filter for ONLY dual confirmed trades
    df_dual = df_trades[df_trades['lots'] == 2].copy()
    
    df_dual['year'] = df_dual['date'].dt.year
    df_dual['win'] = df_dual['actual_pnl'] > 0
    
    total_pnl = df_dual['actual_pnl'].sum()
    total_win = df_dual['win'].mean() * 100
    
    print(f"OVERALL SUMMARY: Total PnL: Rs {total_pnl:,.0f} | Win Rate: {total_win:.1f}% | Total Dual Confirmed Trades: {len(df_dual)}")
    print("-" * 75)
    print(f"{'Year':<6} | {'Trades':<8} | {'Win Rate':<10} | {'Avg PnL (2x)':<15} | {'Total PnL'}")
    print("-" * 75)
    for yr in sorted(df_dual['year'].unique()):
        df_yr = df_dual[df_dual['year'] == yr]
        trades = len(df_yr)
        wr = df_yr['win'].mean() * 100
        avg_pnl = df_yr['actual_pnl'].mean()
        tot_pnl = df_yr['actual_pnl'].sum()
        print(f"{yr:<6} | {trades:<8} | {wr:>7.1f}%   | Rs {avg_pnl:>9,.0f}    | Rs {tot_pnl:>9,.0f}")
    print("-" * 75)
