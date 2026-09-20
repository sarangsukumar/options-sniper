import pandas as pd
import numpy as np
import sys
sys.path.append('/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/historical_models')
from dynamic_threshold import load_pnl, build_features, BASE_FEATURE_COLS, days_to_next_expiry
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

print("Loading data and computing features...")
df = load_pnl()
df_feats = build_features(df)
df_feats['days_to_expiry'] = days_to_next_expiry(df_feats['dt_parsed'])

# Drop NaNs
df_feats = df_feats.dropna(subset=BASE_FEATURE_COLS + ['days_to_expiry', 'pnl']).copy()

def print_model_importance(name, features, target='pnl', residual_target=None):
    X = df_feats[features].values
    if residual_target is None:
        y = df_feats[target].values
    else:
        y = residual_target
        
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    model = Ridge(alpha=5.0, random_state=42)
    model.fit(X_scaled, y)

    importances = np.abs(model.coef_)
    total_importance = np.sum(importances)
    pct_importances = (importances / total_importance) * 100

    feat_imp = pd.DataFrame({
        'Feature': features,
        'Importance': importances,
        'Pct_Weight': pct_importances,
        'Coefficient': model.coef_
    }).sort_values(by='Importance', ascending=False)

    print(f"\n==========================================")
    print(f"     {name} MODEL FEATURE IMPORTANCE   ")
    print(f"==========================================")
    for _, row in feat_imp.iterrows():
        print(f"{row['Feature']:<25} | {row['Pct_Weight']:5.1f}% | Raw: {row['Coefficient']:7.4f}")
        
    return y - model.predict(X_scaled)

# T1
feats_t1 = [f for f in BASE_FEATURE_COLS if f != 'days_to_expiry']
res_t1 = print_model_importance("T1 (BASE)", feats_t1)

# T3 (Skipping T2 because features are dynamic walk-forward)
feats_t3 = ['days_to_expiry']
_ = print_model_importance("T3 (EXPIRY TOWER)", feats_t3, residual_target=res_t1)

print("==========================================")
