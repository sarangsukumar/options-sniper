import pandas as pd
import lightgbm as lgb
import os
from train_walk_forward import build_features

df_path = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_shortsell940_2026/data/short_sell_ml_dataset_v2.csv'
premarket_path = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_shortsell940_2026/data/premarket_ticks.csv'
banlist_path = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_shortsell940_2026/data/fo_ban_list_historical.csv'

df = build_features(df_path, premarket_path, banlist_path)

new_arc_cols = ['stagnancy_prev_to_0940_pct', 'abs_stagnancy_prev_to_0940', 'stagnancy_0907_to_0940_pct', 'abs_stagnancy_0907_to_0940', 'arc_shape_intensity', 'spike_from_prev_close_pct', 'fade_from_high_pct', 'positive_half_circle_prev_close', 'gap_fade_completion']
new_r1r3_cols = ['days_to_expiry', 'hist_avg_pnl', 'hist_win_rate', 'hist_count']
morning_feat_cols = ['morning_return','morning_range','morning_rsi_9','morning_macd','morning_vwap_gap','morning_momentum','morning_vol_trend','morning_bb_pct_b','morning_stoch_k','morning_ema_cross','morning_range_pos','morning_volatility','morning_volume'] + new_arc_cols + new_r1r3_cols
prev_day_feat_cols = ['Gap_Pct','gap_abs','prev_open','prev_high','prev_low','prev_close','prev_num_bars','prev_intraday_return','prev_intraday_rsi_9','prev_intraday_macd','prev_intraday_ema_cross','prev_intraday_bb_pct_b','prev_intraday_vwap_gap','prev_intraday_stoch_k','prev_intraday_range_pos','prev_intraday_volume_ratio','prev_intraday_high_low_ratio','prev_intraday_volatility','prev_intraday_twap_crosses','prev_intraday_roc_last_hour','prev_intraday_orb_pos','prev_first_tick_to_1519_pct','prev_1450_to_1519_pct']

feature_cols = [c for c in (morning_feat_cols + prev_day_feat_cols) if c in df.columns]

df_no_mon = df[df['short_sell_date'].dt.day_name() != 'Monday'].copy()
for col in feature_cols:
    df_no_mon[col] = df_no_mon[col].fillna(df_no_mon[col].median())
df_no_mon['target'] = (df_no_mon['short_pnl_net'] > 0).astype(int)

df_no_mon['Year'] = df_no_mon['short_sell_date'].dt.year

all_selected = []
for test_year in range(2018, 2027):
    train_df = df_no_mon[(df_no_mon['Year'] >= min(df_no_mon['Year'])) & (df_no_mon['Year'] < test_year)]
    test_df = df_no_mon[df_no_mon['Year'] == test_year].copy()
    if len(train_df) < 1000 or len(test_df) == 0: continue
        
    model_wf = lgb.LGBMClassifier(objective='binary', boosting_type='gbdt', n_estimators=150, learning_rate=0.03, num_leaves=31, random_state=42, verbose=-1)
    model_wf.fit(train_df[feature_cols], train_df['target'])
    test_df['ml_prob'] = model_wf.predict_proba(test_df[feature_cols])[:, 1]
    
    sel = test_df[test_df['ml_prob'] >= 0.53].copy()
    sel['daily_rank'] = sel.groupby('date_str')['ml_prob'].rank(method='first', ascending=False)
    
    # Store ranks 1 through 5
    sel_top5 = sel[sel['daily_rank'].isin([1, 2, 3, 4, 5])]
    for _, row in sel_top5.iterrows():
        all_selected.append({'Year': test_year, 'Rank': row['daily_rank'], 'PnL': row['short_pnl_net']})

res_df = pd.DataFrame(all_selected)
print("="*60)
print("🏆 INDIVIDUAL RANK PERFORMANCE (WITH R1/R3 + ARC FEATURES)")
print("="*60)
for rank in range(1, 6):
    r_df = res_df[res_df['Rank'] == rank]
    if len(r_df) > 0:
        win_rate = (r_df['PnL'] > 0).mean() * 100
        avg_pnl = r_df['PnL'].mean()
        total_pnl = r_df['PnL'].sum()
        print(f"RANK #{rank} | Trades: {len(r_df):<4} | Win: {win_rate:>5.1f}% | Avg PnL: ₹{avg_pnl:,.0f} | Total: ₹{total_pnl:,.0f}")
