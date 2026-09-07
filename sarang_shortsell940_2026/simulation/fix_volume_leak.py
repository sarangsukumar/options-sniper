import pandas as pd
import numpy as np
import lightgbm as lgb
import os

OUTPUT_DIR = '/home/ubuntu/short_sell_simulation_algo/output'
df = pd.read_csv(os.path.join(OUTPUT_DIR, 'short_sell_ml_dataset_v2.csv'), low_memory=False)
df['short_sell_date'] = pd.to_datetime(df['short_sell_date'])

global_gap = df.groupby('short_sell_date')['Gap_Pct'].mean().reset_index()
global_gap.columns = ['short_sell_date', 'global_gap']
df = pd.merge(df, global_gap, on='short_sell_date', how='left')

df['is_bank'] = df['stockname'].apply(lambda x: 1 if 'BANK' in str(x).upper() else 0)
df['target'] = (df['short_pnl_net'] > 0).astype(int)

# REMOVE THE LEAKED FEATURE
if 'Volume_Change_Pct' in df.columns:
    df.drop(columns=['Volume_Change_Pct'], inplace=True)

# ADD NEW SAFE FEATURE: morning_vol_gap_combo
# We combine the raw Gap % with the raw Morning Volume 
df['safe_vol_gap_combo'] = df['Gap_Pct'] * np.log1p(df['morning_volume'])

adv_features = [c for c in df.columns if c.startswith('prev_') or c.startswith('morning_') or c.startswith('nifty_')]
adv_features += ['Gap_Pct', 'is_bank', 'gap_abs', 'safe_vol_gap_combo']
for idx in ['^GSPC', '^DJI', '^IXIC', '^RUT', '^STOXX', '^FTSE', '^GDAXI', '^FCHI', '^N225', '^HSI', '^KS11', '^STI', '^BSESN', '^NSEI', '^MXX', '^BVSP', '^SSMI', '^AORD']:
    if idx in df.columns: adv_features.append(idx)
adv_features = list(set([c for c in adv_features if 'pnl' not in c and c != 'target' and c != 'Volume_Change_Pct' and c != 'vol_gap_combo']))

print("Training LightGBM model on all 2018-2026 data WITH LEAKAGE REMOVED to extract TRUE feature importances...")
train_data = df[df['short_sell_date'].dt.year >= 2018].copy()

for c in adv_features:
    if c in train_data.columns:
        med = train_data[c].median()
        train_data[c] = train_data[c].fillna(med)
    else:
        adv_features.remove(c)

X_train = train_data[adv_features]
y_train = train_data['target']

clf = lgb.LGBMClassifier(
    objective='binary', metric='auc', boosting_type='gbdt', 
    n_estimators=150, learning_rate=0.03, num_leaves=31, 
    random_state=42, verbose=-1, n_jobs=-1
)
clf.fit(X_train, y_train)

importances = pd.DataFrame({
    'Feature': adv_features,
    'Importance_Gain': clf.booster_.feature_importance(importance_type='gain')
})
importances['Importance_Gain_Pct'] = (importances['Importance_Gain'] / importances['Importance_Gain'].sum()) * 100
importances = importances.sort_values('Importance_Gain_Pct', ascending=False)

print("\n==================================================================================")
print("             TRUE FEATURE IMPORTANCE (LEAKAGE REMOVED)                            ")
print("==================================================================================")
for _, r in importances.head(15).iterrows():
    print(f"| {r['Feature']:<40} | {r['Importance_Gain_Pct']:>28.2f}% |")
