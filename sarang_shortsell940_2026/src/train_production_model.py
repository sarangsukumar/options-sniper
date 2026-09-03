import pandas as pd
import lightgbm as lgb
import os
import joblib
from train_walk_forward import build_features

if __name__ == "__main__":
    df_path = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_shortsell940_2026/data/short_sell_ml_dataset_v2.csv'
    premarket_path = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_shortsell940_2026/data/premarket_ticks.csv'
    banlist_path = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_shortsell940_2026/data/fo_ban_list_historical.csv'
    
    print("Preparing final dataset for production training...")
    df = build_features(df_path, premarket_path, banlist_path)
    
    # Target and Features setup
    df_no_mon = df[df['short_sell_date'].dt.day_name() != 'Monday'].copy()
    
    new_arc_cols = ['stagnancy_prev_to_0940_pct', 'abs_stagnancy_prev_to_0940', 'stagnancy_0907_to_0940_pct', 'abs_stagnancy_0907_to_0940', 'arc_shape_intensity', 'spike_from_prev_close_pct', 'fade_from_high_pct', 'positive_half_circle_prev_close', 'gap_fade_completion']
    new_r1r3_cols = ['days_to_expiry', 'hist_avg_pnl', 'hist_win_rate', 'hist_count']
    morning_feat_cols = ['morning_return','morning_range','morning_rsi_9','morning_macd','morning_vwap_gap','morning_momentum','morning_vol_trend','morning_bb_pct_b','morning_stoch_k','morning_ema_cross','morning_range_pos','morning_volatility','morning_volume'] + new_arc_cols + new_r1r3_cols
    prev_day_feat_cols = ['Gap_Pct','gap_abs','prev_open','prev_high','prev_low','prev_close','prev_num_bars','prev_intraday_return','prev_intraday_rsi_9','prev_intraday_macd','prev_intraday_ema_cross','prev_intraday_bb_pct_b','prev_intraday_vwap_gap','prev_intraday_stoch_k','prev_intraday_range_pos','prev_intraday_volume_ratio','prev_intraday_high_low_ratio','prev_intraday_volatility','prev_intraday_twap_crosses','prev_intraday_roc_last_hour','prev_intraday_orb_pos','prev_first_tick_to_1519_pct','prev_1450_to_1519_pct']

    feature_cols = [c for c in (morning_feat_cols + prev_day_feat_cols) if c in df.columns]

    for col in feature_cols:
        df_no_mon[col] = df_no_mon[col].fillna(df_no_mon[col].median())
    
    df_no_mon['target'] = (df_no_mon['short_pnl_net'] > 0).astype(int)

    print("Training final LightGBM model on all data (2018-2026)...")
    model = lgb.LGBMClassifier(objective='binary', boosting_type='gbdt', n_estimators=150, learning_rate=0.03, num_leaves=31, random_state=42, verbose=-1)
    model.fit(df_no_mon[feature_cols], df_no_mon['target'])
    
    model_path = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_shortsell940_2026/models/sarang_shortsell_0940_production.pkl'
    joblib.dump(model, model_path)
    print(f"Production Model successfully saved to {model_path}!")
