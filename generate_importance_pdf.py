import pandas as pd
import numpy as np
from fpdf import FPDF
import requests
import os
import sys

sys.path.append('/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/historical_models')
from dynamic_threshold import load_pnl, build_features, BASE_FEATURE_COLS, days_to_next_expiry
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

class PDF(FPDF):
    def header(self):
        self.set_font('Courier', 'B', 12)
        self.cell(0, 10, 'FEATURE IMPORTANCE MATRICES (RIDGE ENSEMBLE)', 0, 1, 'C')
        self.ln(5)

    def chapter_title(self, title):
        self.set_font('Courier', 'B', 11)
        self.set_fill_color(200, 220, 255)
        self.cell(0, 10, title, 0, 1, 'L', 1)
        self.ln(2)

    def chapter_body(self, body):
        self.set_font('Courier', '', 9)
        self.multi_cell(0, 5, body)
        self.ln()

print("Loading data...")
df = load_pnl()
df_feats = build_features(df)
df_feats['days_to_expiry'] = days_to_next_expiry(df_feats['dt_parsed'])

# Compute T2 Features globally (approximation for importance scaling)
df_feats['month'] = df_feats['dt_parsed'].dt.month
monthly_stats = df_feats.groupby(['stockname', 'month'])['pnl'].agg(
    month_hist_avg='mean',
    month_hist_wr=lambda x: (x > 0).mean() * 100
).reset_index()
df_feats = df_feats.merge(monthly_stats, on=['stockname', 'month'], how='left')

# Drop NaNs
all_feats = BASE_FEATURE_COLS + ['days_to_expiry', 'month_hist_avg', 'month_hist_wr']
df_feats = df_feats.dropna(subset=all_feats + ['pnl']).copy()

def get_model_importance(features, target='pnl', residual_target=None):
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
        'Pct_Weight': pct_importances,
        'Coefficient': model.coef_
    }).sort_values(by='Pct_Weight', ascending=False)

    lines = []
    lines.append(f"{'#':<3} | {'Feature Name':<28} | {'Weight %':<10} | {'Raw Coef'}")
    lines.append("-" * 70)
    for i, (_, row) in enumerate(feat_imp.iterrows(), start=1):
        lines.append(f"{i:<3} | {row['Feature']:<28} | {row['Pct_Weight']:5.2f}%    | {row['Coefficient']:8.4f}")
        
    return "\n".join(lines), y - model.predict(X_scaled)

feats_t1 = [f for f in BASE_FEATURE_COLS if f != 'days_to_expiry']
text_t1, res_t1 = get_model_importance(feats_t1)

feats_t2 = ['month_hist_avg', 'month_hist_wr']
text_t2, res_t2 = get_model_importance(feats_t2, residual_target=res_t1)

feats_t3 = ['days_to_expiry']
text_t3, _ = get_model_importance(feats_t3, residual_target=res_t2)

pdf = PDF()
pdf.add_page()
pdf.chapter_title("T1 (BASE MODEL) FEATURE IMPORTANCE [Full List]")
pdf.chapter_body(text_t1)

pdf.add_page()
pdf.chapter_title("T2 (MONTHLY CALENDAR TOWER) FEATURE IMPORTANCE")
pdf.chapter_body("T2 models calendar-specific seasonal anomalies.\n\n" + text_t2)

pdf.chapter_title("T3 (EXPIRY TOWER) FEATURE IMPORTANCE")
pdf.chapter_body("T3 explicitly targets days-to-expiry theta decay.\n\n" + text_t3)

pdf_path = "/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/reports/Feature_Importance_Full_Report.pdf"
os.makedirs(os.path.dirname(pdf_path), exist_ok=True)
pdf.output(pdf_path)

# Send to Telegram
BOT_TOKEN = "5350311365:AAFkTUBR4IGvgS5Z9mJngz-mgk7-HkhFEYE"
CHAT_ID = "-698073972"
with open(pdf_path, 'rb') as f:
    requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument",
        data={'chat_id': CHAT_ID, 'caption': 'Feature Importance Report (T1, T2, T3) - All Features'},
        files={'document': f}
    )
print("PDF generated and sent to Telegram!")
