import os, sys
import pandas as pd
import numpy as np
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

# Add historical_models to path to import official data loaders
sys.path.append('historical_models')
from full_yoy_analysis import load_freq_data, build_master

OUTPUT_DIR = "/home/ubuntu/daily_prediction_system_Dynamic_threshold_Backtest_Dev/historical_models/output"

def calculate_full_hybrid_metrics(capital=600000.0):
    freqs = ['daily', 'weekly', 'monthly', 'quarterly', 'yearly']
    dfs = load_freq_data(freqs)
    df_master = build_master(dfs, freqs)
    features = [c for c in df_master.columns if c not in ['date'] + freqs]
    test_years = range(2020, 2027)
    
    df_ens = pd.read_csv(os.path.join(OUTPUT_DIR, "trades_dynamic_threshold_ensemble.csv"))
    df_ens['date'] = pd.to_datetime(df_ens['date'])
    df_daily = pd.read_csv(os.path.join(OUTPUT_DIR, "trades_dynamic_threshold_daily.csv"))
    df_daily['date'] = pd.to_datetime(df_daily['date'])
    
    combined_trades = []
    pnl_history = []
    
    for test_year in test_years:
        train_df = df_master[df_master['date'].dt.year < test_year]
        test_df = df_master[df_master['date'].dt.year == test_year]
        if len(train_df) < 50 or len(test_df) == 0:
            continue
            
        scaler = StandardScaler()
        X_tr = scaler.fit_transform(train_df[features])
        X_te = scaler.transform(test_df[features])
        
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
                
            dampener = False
            iso = dt.isocalendar()
            cyr, cwk = iso[0], iso[1]
            if pnl_history:
                ph = pd.DataFrame(pnl_history)
                past = ph[ph['date'] < dt].copy()
                if not past.empty:
                    past['isoyr'] = past['date'].dt.isocalendar().year
                    past['isowk'] = past['date'].dt.isocalendar().week
                    done = past[~((past['isoyr'] == cyr) & (past['isowk'] == cwk))]
                    if not done.empty:
                        wkpnl = done.groupby(['isoyr', 'isowk'])['actual_pnl'].sum()
                        if len(wkpnl) > 0 and wkpnl.iloc[-1] < 0:
                            dampener = True
                            
            dp = {freq: preds[freq][i] for freq in freqs}
            active_freqs = sorted(dp, key=dp.get, reverse=True)[:2]
            ml_stocks = set()
            for freq in active_freqs:
                ml_stocks.update(dfs[freq][dfs[freq]['date'] == dt]['stock'].unique())
                
            static_stocks = day_ens['stock'].tolist() if not day_ens.empty else []
            
            dual_stock_row = None
            if not dampener and len(static_stocks) > 0:
                for rank_idx, s in enumerate(static_stocks[:3]):
                    if s in ml_stocks:
                        matching_row = day_ens[day_ens['stock'] == s].iloc[0]
                        if matching_row['pred_pnl'] >= 2800.0:
                            dual_stock_row = matching_row
                            break
            
            day_pnl_sum = 0.0
            day_trades = []
            if dual_stock_row is not None:
                pnl = dual_stock_row['actual_pnl'] * 2.0
                day_trades.append({'actual_pnl': pnl, 'type': 'Dual'})
                day_pnl_sum += pnl
            else:
                if not day_daily.empty:
                    for _, r in day_daily.iterrows():
                        day_trades.append({'actual_pnl': r['actual_pnl'], 'type': 'Sniper'})
                        day_pnl_sum += r['actual_pnl']
                        
            combined_trades.extend(day_trades)
            pnl_history.append({'date': dt, 'actual_pnl': day_pnl_sum})
            
    df_trades = pd.DataFrame(combined_trades)
    df_daily_pnl = pd.DataFrame(pnl_history)
    
    # Capital Requirements
    margin_per_lot = 150000.0 # Rs 1.5 Lakhs typical margin per lot in stock futures
    max_margin_util = 2 * margin_per_lot # Max 2 lots = Rs 3 Lakhs
    safety_buffer = 250000.0 # safety buffer based on max daily loss
    rec_capital = max_margin_util + safety_buffer # Rs 5.5 Lakhs
    
    # 1. Total Metrics
    total_trades = len(df_trades)
    wins = df_trades[df_trades['actual_pnl'] > 0]
    losses = df_trades[df_trades['actual_pnl'] < 0]
    win_rate = (len(wins) / total_trades) * 100
    
    gross_profits = wins['actual_pnl'].sum()
    gross_losses = abs(losses['actual_pnl'].sum())
    profit_factor = gross_profits / gross_losses if gross_losses > 0 else np.inf
    
    total_pnl = df_trades['actual_pnl'].sum()
    avg_pnl = df_trades['actual_pnl'].mean()
    
    # 2. Equity Curve and Returns
    df_daily_pnl = df_daily_pnl.sort_values('date').reset_index(drop=True)
    df_daily_pnl['equity'] = capital + df_daily_pnl['actual_pnl'].cumsum()
    df_daily_pnl['daily_return'] = df_daily_pnl['actual_pnl'] / capital
    
    # CAGR calculation (7 years from 2020-01-01 to 2026-12-31 approx)
    n_years = 7.0
    final_equity = df_daily_pnl['equity'].iloc[-1]
    cagr = ((final_equity / capital) ** (1.0 / n_years) - 1) * 100
    
    # Sharpe & Sortino
    mean_daily = df_daily_pnl['daily_return'].mean()
    std_daily = df_daily_pnl['daily_return'].std()
    ann_sharpe = (mean_daily / std_daily) * np.sqrt(252) if std_daily > 0 else 0
    
    neg_returns = df_daily_pnl[df_daily_pnl['daily_return'] < 0]['daily_return']
    downside_std = neg_returns.std()
    ann_sortino = (mean_daily / downside_std) * np.sqrt(252) if downside_std > 0 else 0
    
    # Max Drawdown
    df_daily_pnl['peak'] = df_daily_pnl['equity'].cummax()
    df_daily_pnl['drawdown'] = (df_daily_pnl['equity'] - df_daily_pnl['peak']) / df_daily_pnl['peak']
    max_dd = df_daily_pnl['drawdown'].min() * 100
    
    # Recovery Factor (Total PnL / Max Drawdown Amount)
    max_dd_amount = (df_daily_pnl['peak'] - df_daily_pnl['equity']).max()
    recovery_factor = total_pnl / max_dd_amount if max_dd_amount > 0 else np.inf
    
    print("="*60)
    print("       🔥 HYBRID COMBINED MODEL: FULL QUANTITATIVE MATRIX 🔥")
    print("="*60)
    print(f"Recommended Capital Needed   : Rs {rec_capital:,.0f} (Rounded: Rs 6,00,000)")
    print(f"  - Margin Allocated (2 Lots): Rs {max_margin_util:,.0f}")
    print(f"  - Risk Buffer              : Rs {safety_buffer:,.0f}")
    print("-"*60)
    print(f"Total Trade Count            : {total_trades}")
    print(f"Winning Trades               : {len(wins)}")
    print(f"Losing Trades                : {len(losses)}")
    print(f"Model Win Rate               : {win_rate:.2f}%")
    print(f"Average PnL / Trade          : Rs {avg_pnl:,.2f}")
    print(f"Total Realized PnL (7 Years) : Rs {total_pnl:,.2f}")
    print("-"*60)
    print(f"Compound Annual Growth (CAGR): {cagr:.2f}% (on Rs 6L capital)")
    print(f"Profit Factor                : {profit_factor:.2f}")
    print(f"Annualized Sharpe Ratio      : {ann_sharpe:.2f}")
    print(f"Annualized Sortino Ratio     : {ann_sortino:.2f}")
    print(f"Maximum Peak-to-Trough DD    : {max_dd:.2f}%")
    print(f"Recovery Factor              : {recovery_factor:.2f}")
    print("="*60)

if __name__ == '__main__':
    calculate_full_hybrid_metrics()
