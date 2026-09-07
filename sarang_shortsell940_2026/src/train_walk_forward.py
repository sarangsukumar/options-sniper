import pandas as pd
import lightgbm as lgb
import os
import numpy as np
from dateutil.relativedelta import relativedelta
import calendar

def get_expiry_date(d):
    last_day = calendar.monthrange(d.year, d.month)[1]
    dt_last = pd.Timestamp(year=d.year, month=d.month, day=last_day)
    offset = (dt_last.weekday() - 3) % 7
    expiry_this_month = dt_last - pd.Timedelta(days=offset)
    if d <= expiry_this_month:
        return expiry_this_month
    else:
        next_month = d + relativedelta(months=1)
        last_day = calendar.monthrange(next_month.year, next_month.month)[1]
        dt_last = pd.Timestamp(year=next_month.year, month=next_month.month, day=last_day)
        offset = (dt_last.weekday() - 3) % 7
        return dt_last - pd.Timedelta(days=offset)

def build_features(df_path, premarket_path, banlist_path):
    print("Loading datasets...")
    df = pd.read_csv(df_path, low_memory=False)
    df['short_sell_date'] = pd.to_datetime(df['short_sell_date'], format='mixed')
    df['date_str'] = df['short_sell_date'].dt.strftime('%Y-%m-%d')
    df['gap_abs'] = df['Gap_Pct'].abs()

    pre = pd.read_csv(premarket_path)
    pre = pre.rename(columns={'date_str': 'date_str', 'clean_stock': 'clean_stock', 'premarket_price': 'premarket_price'})
    df = df.merge(pre, on=['date_str', 'clean_stock'], how='left')

    df['open_0915'] = df['prev_close'] * (1 + (df['Gap_Pct'] / 100))
    df['price_0940'] = df['open_0915'] * (1 + (df['morning_return'] / 100))

    ban = pd.read_csv(banlist_path)
    ban['date'] = pd.to_datetime(ban['date'], format='%d-%m-%Y').dt.strftime('%Y-%m-%d')
    ban = ban.rename(columns={'date': 'date_str', 'stock_name': 'clean_stock'})
    ban['is_banned'] = 1
    df = df.merge(ban, on=['date_str', 'clean_stock'], how='left')
    df['is_banned'] = df['is_banned'].fillna(0)
    df = df[df['is_banned'] == 0].copy()

    print("Building Arc Features...")
    df['stagnancy_prev_to_0940_pct'] = ((df['price_0940'] - df['prev_close']) / df['prev_close']) * 100
    df['stagnancy_0907_to_0940_pct'] = ((df['price_0940'] - df['premarket_price']) / df['premarket_price']) * 100
    df['abs_stagnancy_prev_to_0940'] = df['stagnancy_prev_to_0940_pct'].abs()
    df['abs_stagnancy_0907_to_0940'] = df['stagnancy_0907_to_0940_pct'].abs()
    df['arc_shape_intensity'] = df['morning_range'] * (50 - df['morning_range_pos']) / 50.0 
    df['morning_high_calc'] = df['price_0940'] + (df['open_0915'] * (df['morning_range'] / 100)) * (1 - (df['morning_range_pos'] / 100))
    df['spike_from_prev_close_pct'] = ((df['morning_high_calc'] - df['prev_close']) / df['prev_close']) * 100
    df['fade_from_high_pct'] = ((df['morning_high_calc'] - df['price_0940']) / df['morning_high_calc']) * 100
    df['positive_half_circle_prev_close'] = df['spike_from_prev_close_pct'] * df['fade_from_high_pct']
    df['gap_fade_completion'] = (df['open_0915'] - df['price_0940']) / (df['open_0915'] - df['prev_close'] + 1e-9)

    # ✅ Reverted: raw prices perform better on 2026 market regime
    print("Building R1/R3 Historical Features...")
    df['expiry_date'] = df['short_sell_date'].apply(get_expiry_date)
    df['days_to_expiry'] = (df['expiry_date'] - df['short_sell_date']).dt.days

    df = df.sort_values(by=['clean_stock', 'short_sell_date'])
    df['is_win'] = (df['short_pnl_net'] > 0).astype(int)
    df['hist_avg_pnl'] = df.groupby('clean_stock')['short_pnl_net'].transform(lambda x: x.shift(1).expanding().mean())
    df['hist_win_rate'] = df.groupby('clean_stock')['is_win'].transform(lambda x: x.shift(1).expanding().mean())
    df['hist_count'] = df.groupby('clean_stock').cumcount()
    df['hist_avg_pnl'] = df['hist_avg_pnl'].fillna(0)
    df['hist_win_rate'] = df['hist_win_rate'].fillna(0.5)

    df = df.sort_values('short_sell_date')
    return df

if __name__ == "__main__":
    df_path = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_shortsell940_2026/data/short_sell_ml_dataset_v2.csv'
    premarket_path = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_shortsell940_2026/data/premarket_ticks.csv'
    banlist_path = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_shortsell940_2026/data/fo_ban_list_historical.csv'
    
    df = build_features(df_path, premarket_path, banlist_path)
    
    # Define Feature List
    new_arc_cols = [
        'stagnancy_prev_to_0940_pct', 'abs_stagnancy_prev_to_0940',
        'stagnancy_0907_to_0940_pct', 'abs_stagnancy_0907_to_0940',
        'arc_shape_intensity', 'spike_from_prev_close_pct', 'fade_from_high_pct',
        'positive_half_circle_prev_close', 'gap_fade_completion'
    ]
    new_r1r3_cols = ['days_to_expiry', 'hist_avg_pnl', 'hist_win_rate', 'hist_count']
    morning_feat_cols = [
        'morning_return','morning_range','morning_rsi_9','morning_macd',
        'morning_vwap_gap','morning_momentum','morning_vol_trend',
        'morning_bb_pct_b','morning_stoch_k','morning_ema_cross',
        'morning_range_pos','morning_volatility','morning_volume'
    ] + new_arc_cols + new_r1r3_cols

    prev_day_feat_cols = [
        'Gap_Pct','gap_abs','prev_open','prev_high','prev_low','prev_close',
        'prev_num_bars','prev_intraday_return','prev_intraday_rsi_9','prev_intraday_macd',
        'prev_intraday_ema_cross','prev_intraday_bb_pct_b','prev_intraday_vwap_gap',
        'prev_intraday_stoch_k','prev_intraday_range_pos','prev_intraday_volume_ratio',
        'prev_intraday_high_low_ratio','prev_intraday_volatility','prev_intraday_twap_crosses',
        'prev_intraday_roc_last_hour','prev_intraday_orb_pos','prev_first_tick_to_1519_pct',
        'prev_1450_to_1519_pct'
    ]

    feature_cols = [c for c in (morning_feat_cols + prev_day_feat_cols) if c in df.columns]

    df_no_mon = df[df['short_sell_date'].dt.day_name() != 'Monday'].copy()
    for col in feature_cols:
        df_no_mon[col] = df_no_mon[col].fillna(df_no_mon[col].median())
    df_no_mon['target'] = (df_no_mon['short_pnl_net'] > 0).astype(int)

    df_no_mon['Year'] = df_no_mon['short_sell_date'].dt.year
    all_selected = []
    r1_trades = []
    
    print("Running LightGBM Walk-Forward Evaluation...")
    for test_year in range(2018, 2027):
        train_df = df_no_mon[(df_no_mon['Year'] >= min(df_no_mon['Year'])) & (df_no_mon['Year'] < test_year)]
        test_df = df_no_mon[df_no_mon['Year'] == test_year].copy()
        if len(train_df) < 1000 or len(test_df) == 0: continue
            
        model_wf = lgb.LGBMClassifier(objective='binary', boosting_type='gbdt', n_estimators=150, learning_rate=0.03, num_leaves=31, random_state=42, verbose=-1)
        model_wf.fit(train_df[feature_cols], train_df['target'])
        test_df['ml_prob'] = model_wf.predict_proba(test_df[feature_cols])[:, 1]
        
        sel = test_df[test_df['ml_prob'] >= 0.53].copy()
        sel['daily_rank'] = sel.groupby('date_str')['ml_prob'].rank(method='first', ascending=False)
        sel['price_0940'] = sel['prev_close'] * (1 + sel['Gap_Pct'] / 100) * (1 + sel['morning_return'] / 100)
        
        sel_1_4 = sel[sel['daily_rank'].isin([1, 4])]
        for _, row in sel_1_4.iterrows():
            all_selected.append({'Year': test_year, 'PnL': row['short_pnl_net'], 'date_str': row['date_str'], 'clean_stock': row['clean_stock'], 'ml_prob': row['ml_prob'], 'daily_rank': row['daily_rank'], 'short_pnl_net': row['short_pnl_net'], 'price_0940': row.get('price_0940', 0)})
        
        r1_sel = sel[sel['daily_rank'] == 1.0].copy()
        r1_trades.append(r1_sel)

    res_df = pd.DataFrame(all_selected)
    print("\n🏆 RANK 1 + RANK 4 COMBO (LGBM + ARC + R1/R3)")
    for year in sorted(res_df['Year'].unique()):
        y_df = res_df[res_df['Year'] == year]
        print(f" {year} | Trades: {len(y_df):<4} | Win: {(y_df['PnL']>0).mean()*100:>5.1f}% | Avg PnL: ₹{y_df['PnL'].mean():,.2f}")
    print(f"OVERALL | Trades: {len(res_df)} | Win: {(res_df['PnL'] > 0).mean()*100:.1f}% | Avg: ₹{res_df['PnL'].mean():,.2f} | Total: ₹{res_df['PnL'].sum():,.2f}")


    # Generate exact R1 list from r1_trades collected inside the loop
    import subprocess, os
    r1 = pd.concat(r1_trades).copy() if r1_trades else pd.DataFrame()

    if r1.empty:
        print("No R1 trades collected!")
    else:
        # Merge Lotsize from ICICI master
        try:
            os.makedirs('/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_shortsell940_2026/output', exist_ok=True)
            lots = pd.read_csv('/home/ubuntu/KotakCodes1/ICICImaster_options.csv')
            lots = lots[lots['series'] == 'FUTSTK'][['stockcodes', 'lotsize']].copy()
            lots['clean_stock'] = lots['stockcodes'].str.strip()
            lots = lots.rename(columns={'lotsize': 'LotSize'})
            lots = lots.drop_duplicates('clean_stock')
            r1 = r1.merge(lots[['clean_stock', 'LotSize']], on='clean_stock', how='left')
        except Exception as e:
            print("Could not merge lotsize:", e)
            r1['LotSize'] = 0

        out_path = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_shortsell940_2026/output/historical_Rank1_trades_detailed.csv'
        out_cols = ['date_str', 'clean_stock', 'price_0940', 'LotSize', 'ml_prob', 'short_pnl_net']
        out_cols = [c for c in out_cols if c in r1.columns]
        r1_sorted = r1.sort_values('date_str')
        r1_sorted[out_cols].to_csv(out_path, index=False)
        print(f"\n✅ Exported {len(r1_sorted)} R1 trades to {out_path}")

        # Send CSV file directly via Telegram
        recent = r1_sorted[r1_sorted['date_str'] >= '2024-01-01'].copy()
        recent_path = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_shortsell940_2026/output/Rank1_trades_2024_onwards.csv'
        recent[out_cols].to_csv(recent_path, index=False)
        print(f"✅ 2024+ file saved: {recent_path}")

        bot_path = "/home/ubuntu/telegram_bot/New_OrderInfoBot.js"
        subprocess.run(["node", bot_path, recent_path])
        print("✅ CSV file sent via Telegram!")
