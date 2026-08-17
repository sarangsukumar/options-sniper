#!/usr/bin/env python3
"""
YoY Performance: Combined Model vs Dual-Confirmed Trades Only
=============================================================
Per-trade breakdown with MAX 2 ORDERS PER DAY cap.

Logic:
- Combined Model  : All trades taken by the champion strategy (max 2/day)
- Dual-Confirmed  : Only the trade(s) where a stock was BOTH in the Static
                    Ensemble top picks AND confirmed by the ML frequency models.

Metrics per group:
  - Win Rate (%)        = % of individual trades with actual_pnl > 0
  - Avg PnL / Trade     = total PnL / number of individual trades
  - Total PnL (Rs)
  - Number of Trades
"""

import os
import sys
import pandas as pd
import numpy as np
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

_THIS_DIR  = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(_THIS_DIR, "output")
DATA_DIR   = os.path.join(_THIS_DIR, "../data")

MAX_ORDERS_PER_DAY = 2   # ← hard cap

# ──────────────────────────────────────────────────────────────────────────────
def load_freq_data(freqs):
    dfs = {}
    for freq in freqs:
        path = os.path.join(OUTPUT_DIR, f"trades_dynamic_threshold_{freq}.csv")
        if os.path.exists(path):
            df = pd.read_csv(path)
            df['date'] = pd.to_datetime(df['date'])
            dfs[freq] = df
    return dfs


def build_master_feature_table(dfs, freqs):
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
            pnl_features[f'{freq}_sum_{window}']  = df_pnl[freq].rolling(window=window).sum().shift(1)
            pnl_features[f'{freq}_mean_{window}'] = df_pnl[freq].rolling(window=window).mean().shift(1)

    f11_path = os.path.join(DATA_DIR, "f11_intraday_features_all.csv")
    df_f11   = pd.read_csv(f11_path)
    df_f11['Date'] = pd.to_datetime(df_f11['Date'])
    market_features = df_f11.groupby('Date').agg(
        market_volatility=('intraday_volatility', 'mean'),
        market_return    =('intraday_return',     'mean'),
        market_trend     =('intraday_rsi_9',      'mean'),
        market_adv_dec   =('intraday_return',     lambda x: (x > 0).mean()),
        market_macd      =('intraday_macd',       'mean'),
        market_vwap_gap  =('intraday_vwap_gap',   'mean'),
    ).reset_index().rename(columns={'Date': 'date'})

    df_master = pd.merge(df_pnl, pnl_features,    on='date', how='inner')
    df_master = pd.merge(df_master, market_features, on='date', how='inner')
    df_master = df_master.dropna().reset_index(drop=True)
    return df_master, df_pnl


# ──────────────────────────────────────────────────────────────────────────────
def run_comparison():
    freqs      = ['daily', 'weekly', 'monthly', 'quarterly', 'yearly']
    dfs        = load_freq_data(freqs)
    df_master, df_pnl = build_master_feature_table(dfs, freqs)

    features   = [c for c in df_master.columns if c not in ['date'] + freqs]
    test_years = range(2020, 2027)

    # Static Ensemble (all stocks, each 1 lot)
    df_ens_all = pd.read_csv(os.path.join(OUTPUT_DIR, "trades_dynamic_threshold_ensemble.csv"))
    df_ens_all['date'] = pd.to_datetime(df_ens_all['date'])

    all_combined_trades  = []   # every trade taken under the champion strategy
    all_dual_conf_trades = []   # only the dual-confirmed trade(s) per day
    pnl_history          = []

    for test_year in test_years:
        train_df = df_master[df_master['date'].dt.year <  test_year]
        test_df  = df_master[df_master['date'].dt.year == test_year]

        if len(train_df) < 50 or len(test_df) == 0:
            continue

        X_train = train_df[features].copy()
        X_test  = test_df[features].copy()

        scaler          = StandardScaler()
        X_train_scaled  = scaler.fit_transform(X_train)
        X_test_scaled   = scaler.transform(X_test)

        preds_for_year = {freq: np.zeros(len(test_df)) for freq in freqs}
        for freq in freqs:
            y_train = train_df[freq]
            model   = Ridge(alpha=1.0, random_state=42)
            model.fit(X_train_scaled, y_train)
            preds_for_year[freq] = model.predict(X_test_scaled)

        for i, row in enumerate(test_df.itertuples()):
            dt = row.date

            day_static = df_ens_all[df_ens_all['date'] == dt].sort_values(
                by='pred_pnl', ascending=False
            )
            if day_static.empty:
                continue

            # ── Adaptive Dampener (lookahead-free) ──────────────────────────
            dampener_active   = False
            today_iso         = dt.isocalendar()
            current_year_num  = today_iso[0]
            current_week_num  = today_iso[1]

            if pnl_history:
                df_history   = pd.DataFrame(pnl_history)
                past_weeks   = df_history[df_history['date'] < dt].copy()
                if not past_weeks.empty:
                    past_weeks['iso_week'] = past_weeks['date'].dt.isocalendar().week
                    past_weeks['iso_year'] = past_weeks['date'].dt.isocalendar().year
                    completed = past_weeks[
                        ~((past_weeks['iso_year']  == current_year_num) &
                          (past_weeks['iso_week']  == current_week_num))
                    ]
                    if not completed.empty:
                        weekly_pnl = completed.groupby(['iso_year', 'iso_week'])['actual_pnl'].sum()
                        if len(weekly_pnl) > 0 and weekly_pnl.iloc[-1] < 0:
                            dampener_active = True

            # ── Identify Dual-Confirmed Stock ────────────────────────────────
            daily_preds  = {freq: preds_for_year[freq][i] for freq in freqs}
            active_freqs = sorted(daily_preds, key=daily_preds.get, reverse=True)[:2]

            ml_stocks = set()
            for freq in active_freqs:
                day_freq_trades = dfs[freq][dfs[freq]['date'] == dt]
                ml_stocks.update(day_freq_trades['stock'].unique())

            static_stocks = day_static['stock'].tolist()

            # Find the top static stock that is also ML-confirmed
            dual_confirmed_stock = None
            if not dampener_active:
                for s in static_stocks[:3]:
                    if s in ml_stocks:
                        dual_confirmed_stock = s
                        break

            # ── Build the day's trade list (max 2 orders/day) ────────────────
            if dampener_active:
                # Revert to static 1-lot each, pick top MAX_ORDERS_PER_DAY
                day_trades_raw = day_static.head(MAX_ORDERS_PER_DAY)
                for _, r in day_trades_raw.iterrows():
                    trade = {
                        'date'          : dt,
                        'year'          : dt.year,
                        'stock'         : r['stock'],
                        'actual_pnl'    : r['actual_pnl'],   # 1x lot
                        'is_dual'       : False,
                        'dampener'      : True,
                    }
                    all_combined_trades.append(trade)
                day_pnl_sum = day_trades_raw['actual_pnl'].sum()

            else:
                if dual_confirmed_stock and len(static_stocks) >= 2:
                    # Find the lowest-ranked stock to drop
                    stock_to_drop = None
                    for s in reversed(static_stocks):
                        if s != dual_confirmed_stock:
                            stock_to_drop = s
                            break

                    # After dropping stock_to_drop, we get 2x dual + 1x each of rest
                    # But we still cap at MAX_ORDERS_PER_DAY unique stock positions
                    selected = [s for s in static_stocks if s != stock_to_drop]
                    selected = selected[:MAX_ORDERS_PER_DAY]   # cap

                    day_pnl_sum = 0.0
                    for _, r in day_static.iterrows():
                        stock = r['stock']
                        if stock not in selected:
                            continue
                        multiplier = 2 if stock == dual_confirmed_stock else 1
                        pnl        = r['actual_pnl'] * multiplier
                        is_dual    = (stock == dual_confirmed_stock)
                        trade = {
                            'date'       : dt,
                            'year'       : dt.year,
                            'stock'      : stock,
                            'actual_pnl' : pnl,
                            'is_dual'    : is_dual,
                            'dampener'   : False,
                        }
                        all_combined_trades.append(trade)
                        if is_dual:
                            all_dual_conf_trades.append(trade)
                        day_pnl_sum += pnl
                else:
                    # No dual confirmation → 1x each, top MAX_ORDERS_PER_DAY
                    day_trades_raw = day_static.head(MAX_ORDERS_PER_DAY)
                    for _, r in day_trades_raw.iterrows():
                        trade = {
                            'date'       : dt,
                            'year'       : dt.year,
                            'stock'      : r['stock'],
                            'actual_pnl' : r['actual_pnl'],
                            'is_dual'    : False,
                            'dampener'   : False,
                        }
                        all_combined_trades.append(trade)
                    day_pnl_sum = day_trades_raw['actual_pnl'].sum()

            pnl_history.append({'date': dt, 'actual_pnl': day_pnl_sum})

    return pd.DataFrame(all_combined_trades), pd.DataFrame(all_dual_conf_trades)


# ──────────────────────────────────────────────────────────────────────────────
def stats(df):
    """Return (win_rate%, avg_pnl_per_trade, total_pnl, n_trades)"""
    if df.empty or len(df) == 0:
        return 0, 0, 0, 0
    n    = len(df)
    wins = (df['actual_pnl'] > 0).sum()
    wr   = wins / n * 100
    tot  = df['actual_pnl'].sum()
    avg  = tot / n
    return wr, avg, tot, n


def print_table(df_combined, df_dual, test_years):
    W = 118
    sep = "=" * W
    mid = "-" * W

    header = (
        f"{'Year':<6} | "
        f"{'── COMBINED MODEL (all trades) ──':^47} | "
        f"{'── DUAL CONFIRMED ONLY ──':^47}"
    )
    sub = (
        f"{'':6} | "
        f"{'WIN RATE%':<10} {'AVG PnL/Trade':>15} {'TOTAL PnL':>14} {'TRADES':>6}  | "
        f"{'WIN RATE%':<10} {'AVG PnL/Trade':>15} {'TOTAL PnL':>14} {'TRADES':>6}"
    )

    print()
    print(sep)
    print("  CHAMPION STRATEGY  |  Max Orders = 2/day  |  Per-Trade Breakdown")
    print(sep)
    print(header)
    print(sub)
    print(mid)

    for y in test_years:
        yc  = df_combined[df_combined['year'] == y]
        yd  = df_dual[df_dual['year']     == y]
        wr_c, avg_c, tot_c, n_c = stats(yc)
        wr_d, avg_d, tot_d, n_d = stats(yd)
        yr_str = f"{y}*" if y == 2026 else str(y)

        print(
            f"{yr_str:<6} | "
            f"{wr_c:<10.1f} {'Rs {:>12,.0f}'.format(avg_c):>15} {'Rs {:>11,.0f}'.format(tot_c):>14} {n_c:>6}  | "
            f"{wr_d:<10.1f} {'Rs {:>12,.0f}'.format(avg_d):>15} {'Rs {:>11,.0f}'.format(tot_d):>14} {n_d:>6}"
        )

    print(mid)
    wr_c, avg_c, tot_c, n_c = stats(df_combined[df_combined['year'].isin(test_years)])
    wr_d, avg_d, tot_d, n_d = stats(df_dual[df_dual['year'].isin(test_years)])
    print(
        f"{'TOTAL':<6} | "
        f"{wr_c:<10.1f} {'Rs {:>12,.0f}'.format(avg_c):>15} {'Rs {:>11,.0f}'.format(tot_c):>14} {n_c:>6}  | "
        f"{wr_d:<10.1f} {'Rs {:>12,.0f}'.format(avg_d):>15} {'Rs {:>11,.0f}'.format(tot_d):>14} {n_d:>6}"
    )
    print(sep)
    print("* 2026 is strictly OUT OF SAMPLE")
    print()

    print("NOTES:")
    print("  • Combined Model  = all trades taken (dual-confirmed 2x + others 1x), max 2/day")
    print("  • Dual Confirmed  = only the stock selected by BOTH Static Ensemble AND ML models")
    print("  • Dual trades use 2x lot size; their PnL above already reflects the 2x multiplier")
    print()


# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("Running champion strategy backtest (per-trade, max 2 orders/day)...")
    df_combined, df_dual = run_comparison()

    test_years = range(2020, 2027)
    print_table(df_combined, df_dual, test_years)

    # Quick sanity check
    print(f"Total combined trades : {len(df_combined):,}")
    print(f"Total dual-conf trades: {len(df_dual):,}")
    print(f"Dual as % of combined : {len(df_dual)/len(df_combined)*100:.1f}%")
