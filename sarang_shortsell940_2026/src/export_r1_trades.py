import pandas as pd
import lightgbm as lgb
import os
import subprocess

print("Loading dataset...")
df = pd.read_csv('/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_shortsell940_2026/data/short_sell_ml_dataset_v2.csv', low_memory=False)
df['date_str'] = pd.to_datetime(df['short_sell_date']).dt.strftime('%Y-%m-%d')
df['year'] = pd.to_datetime(df['date_str']).dt.year
df['is_win'] = (df['short_pnl_net'] > 0).astype(int)

# Arcs & features
df['gap_abs'] = df['Gap_Pct'].abs()
df['open_0915'] = df['prev_close'] * (1 + (df['Gap_Pct'] / 100))
df['price_0940'] = df['open_0915'] * (1 + (df['morning_return'] / 100))
df['morning_high_calc'] = df['price_0940'] + (df['open_0915'] * (df['morning_range'] / 100)) * (1 - (df['morning_range_pos'] / 100))
df['spike_from_prev_close_pct'] = ((df['morning_high_calc'] - df['prev_close']) / df['prev_close']) * 100
df['fade_from_high_pct'] = ((df['morning_high_calc'] - df['price_0940']) / df['morning_high_calc']) * 100
df['positive_half_circle_prev_close'] = df['spike_from_prev_close_pct'] * df['fade_from_high_pct']
df['gap_fade_completion'] = (df['open_0915'] - df['price_0940']) / (df['open_0915'] - df['prev_close'] + 1e-9)
df['stagnancy_prev_to_0940_pct'] = ((df['price_0940'] - df['prev_close']) / df['prev_close']) * 100
df['abs_stagnancy_prev_to_0940'] = df['stagnancy_prev_to_0940_pct'].abs()
df['arc_shape_intensity'] = df['morning_range'] * (50 - df['morning_range_pos']) / 50.0 
df['stagnancy_0907_to_0940_pct'] = df['stagnancy_prev_to_0940_pct']
df['abs_stagnancy_0907_to_0940'] = df['abs_stagnancy_prev_to_0940']

# Ban list
ban = pd.read_csv('/home/ubuntu/banlist/fo_ban_list_historical.csv')
ban['date_str'] = pd.to_datetime(ban['date'], format='%d-%m-%Y').dt.strftime('%Y-%m-%d')
ban = ban.rename(columns={'stock_name': 'clean_stock'})
ban['is_banned'] = 1

df = df.merge(ban[['date_str', 'clean_stock', 'is_banned']], on=['date_str', 'clean_stock'], how='left')
df = df[df['is_banned'] != 1].copy()

# Add R1/R3 Historical Features
short_df = pd.read_csv('/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_shortsell940_2026/data/short_sell_ml_dataset_v2.csv', low_memory=False)
short_df['is_win'] = (short_df['short_pnl_net'] > 0).astype(int)
short_df['date_str'] = pd.to_datetime(short_df['short_sell_date']).dt.strftime('%Y-%m-%d')
short_df = short_df.sort_values('date_str')
def calc_rolling_stats(grp):
    grp = grp.copy()
    grp['hist_count'] = grp['short_pnl_net'].expanding().count().shift(1)
    grp['hist_avg_pnl'] = grp['short_pnl_net'].expanding().mean().shift(1)
    grp['hist_win_rate'] = grp['is_win'].expanding().mean().shift(1)
    return grp
stats = short_df.groupby('clean_stock', group_keys=False).apply(calc_rolling_stats)
df = df.merge(stats[['date_str', 'clean_stock', 'hist_count', 'hist_avg_pnl', 'hist_win_rate']], on=['date_str', 'clean_stock'], how='left')
df['hist_count'] = df['hist_count'].fillna(100)
df['hist_avg_pnl'] = df['hist_avg_pnl'].fillna(0)
df['hist_win_rate'] = df['hist_win_rate'].fillna(0.50)

features = [
    'days_to_expiry', 'hist_win_rate', 'hist_count', 'hist_avg_pnl',
    'Gap_Pct', 'gap_abs', 'morning_return', 'morning_range', 'morning_rsi_9',
    'morning_macd', 'morning_vwap_gap', 'morning_stoch_k', 'morning_range_pos',
    'prev_intraday_rsi_9', 'prev_intraday_macd', 'prev_intraday_vwap_gap',
    'positive_half_circle_prev_close', 'spike_from_prev_close_pct',
    'fade_from_high_pct', 'gap_fade_completion', 'abs_stagnancy_prev_to_0940',
    'arc_shape_intensity'
]

# We don't trade Mondays in final model
df['weekday'] = pd.to_datetime(df['date_str']).dt.dayofweek
df_no_mon = df[df['weekday'] != 0].copy()

all_r1_trades = []

for test_year in range(2018, 2027):
    train_df = df_no_mon[(df_no_mon['year'] >= 2017) & (df_no_mon['year'] < test_year)]
    test_df = df_no_mon[df_no_mon['year'] == test_year].copy()
    if len(train_df) < 1000 or len(test_df) == 0: continue
    
    train_df = train_df.dropna(subset=features)
    test_df = test_df.dropna(subset=features)
    if train_df.empty or test_df.empty: continue
        
    model_wf = lgb.LGBMClassifier(objective='binary', boosting_type='gbdt', n_estimators=150, learning_rate=0.03, num_leaves=31, random_state=42, verbose=-1)
    model_wf.fit(train_df[features], train_df['is_win'])
    
    test_df['ml_prob'] = model_wf.predict_proba(test_df[features])[:, 1]
    
    sel = test_df[test_df['ml_prob'] >= 0.53].copy()
    sel['daily_rank'] = sel.groupby('date_str')['ml_prob'].rank(method='first', ascending=False)
    r1 = sel[sel['daily_rank'] == 1.0].copy()
    
    all_r1_trades.append(r1[['date_str', 'clean_stock', 'price_0940', 'short_pnl_net']])

final_r1 = pd.concat(all_r1_trades)
final_r1 = final_r1.sort_values('date_str')

out_path = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_shortsell940_2026/output/historical_Rank1_trades_with_price.csv'
final_r1.to_csv(out_path, index=False)
print(f"Exported {len(final_r1)} Rank 1 trades to {out_path}")

recent = final_r1[final_r1['date_str'] >= '2024-01-01']
print(f"Trades since 2024-01-01: {len(recent)}")

# Telegram allows ~4096 chars per message. We have ~400 trades. We will split them into 50-trade chunks.
chunks = [recent.iloc[i:i + 30] for i in range(0, len(recent), 30)]

bot_path = "/home/ubuntu/telegram_bot/New_OrderInfoBot.js"
if os.path.exists(bot_path):
    # Only send the FIRST chunk and the LAST chunk to avoid spamming the user's phone with 15 messages.
    msg1 = "🎯 *RANK 1 TRADES (2024-01-01 to 2024-03)*\n"
    for _, r in chunks[0].iterrows():
        msg1 += f"{r['date_str']} | {r['clean_stock']} | Entry: ₹{r['price_0940']:.1f} | PnL: {r['short_pnl_net']:.0f}\n"
    subprocess.run(["node", bot_path, msg1])
    
    msg_last = "🎯 *RANK 1 TRADES (LATEST)*\n"
    for _, r in chunks[-1].iterrows():
        msg_last += f"{r['date_str']} | {r['clean_stock']} | Entry: ₹{r['price_0940']:.1f} | PnL: {r['short_pnl_net']:.0f}\n"
    msg_last += "\n✅ FULL FILE (2018-2026) saved to: output/historical_Rank1_trades_with_price.csv"
    subprocess.run(["node", bot_path, msg_last])
    
    print("Telegram sent!")
