import pandas as pd
import numpy as np
import sys
sys.path.append('/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/historical_models')
from dynamic_threshold import load_pnl, build_features, BASE_FEATURE_COLS
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

print("Loading data and computing features...")
df = load_pnl()
df_feats = build_features(df)
df_feats = df_feats.dropna(subset=BASE_FEATURE_COLS + ['pnl']).copy()

# Features for T1 Model
features = [f for f in BASE_FEATURE_COLS if f != 'days_to_expiry']
X = df_feats[features].values
y = df_feats['pnl'].values

scaler = StandardScaler()
X_scaled = scaler.fit_transform(X)

print("Training Global Ridge Model...")
model = Ridge(alpha=5.0, random_state=42)
model.fit(X_scaled, y)

importances = np.abs(model.coef_)
feat_imp = pd.DataFrame({
    'Feature': features,
    'Importance': importances,
    'Coefficient': model.coef_
})
feat_imp = feat_imp.sort_values(by='Importance', ascending=False)

print("\n==========================================")
print("     T1 MODEL FEATURE IMPORTANCE RANKING   ")
print("==========================================")
for _, row in feat_imp.iterrows():
    print(f"{row['Feature']:<30} | Rank Weight: {row['Importance']:.4f}  (Raw Coef: {row['Coefficient']:.4f})")
print("==========================================")
