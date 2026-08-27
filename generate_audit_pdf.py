import pandas as pd
import numpy as np
from fpdf import FPDF
import requests
import os
from io import StringIO
import sys

class PDF(FPDF):
    def header(self):
        self.set_font('Courier', 'B', 12)
        self.cell(0, 10, 'FEATURE MATRIX AUDIT REPORT (2026)', 0, 1, 'C')
        self.ln(5)

    def chapter_title(self, title):
        self.set_font('Courier', 'B', 12)
        self.set_fill_color(200, 220, 255)
        self.cell(0, 10, title, 0, 1, 'L', 1)
        self.ln(2)

    def chapter_body(self, body):
        self.set_font('Courier', '', 10)
        self.multi_cell(0, 5, body)
        self.ln()

def audit_file_to_text(filepath, date_col, skip_cols):
    output = []
    output.append(f"Auditing: {filepath.split('/')[-1]}")
    
    df = pd.read_csv(filepath)
    output.append(f"Loaded {len(df)} rows and {len(df.columns)} columns.")

    if date_col in df.columns:
        df_train = df[df[date_col].astype(str).str.startswith('2026')].copy()
        if len(df_train) == 0: df_train = df
    else:
        df_train = df
        
    output.append(f"Data to audit: {len(df_train)} rows.")

    constant_cols = []
    all_nan_cols = []
    near_constant_cols = []

    for col in df_train.columns:
        if col.lower() in skip_cols: continue
        col_data = df_train[col]
        
        if col_data.isna().all():
            all_nan_cols.append(col)
            continue
            
        unique_vals = col_data.dropna().unique()
        if len(unique_vals) <= 1:
            val = unique_vals[0] if len(unique_vals) == 1 else np.nan
            constant_cols.append((col, val))
            continue
            
        if pd.api.types.is_numeric_dtype(col_data):
            var_val = col_data.var(ddof=1)
            if var_val < 1e-6:
                near_constant_cols.append((col, var_val))

    output.append(f"\nFound {len(all_nan_cols)} 100% NaN columns.")
    if len(all_nan_cols) > 0: output.append(f"  -> {all_nan_cols}")
    
    output.append(f"Found {len(constant_cols)} completely constant columns.")
    if len(constant_cols) > 0: output.append(f"  -> {constant_cols}")
        
    output.append(f"Found {len(near_constant_cols)} near-constant columns (variance < 1e-6).")
    if len(near_constant_cols) > 0: output.append(f"  -> {near_constant_cols}")

    output.append("\n--- CASING MISMATCH AUDIT ---")
    lowered_cols = [str(c).lower() for c in df.columns]
    duplicates = set([c for c in lowered_cols if lowered_cols.count(c) > 1])

    if duplicates:
        output.append(f"[WARNING] Found {len(duplicates)} case-duplicate columns!")
        output.append(str(list(duplicates)[:10]))
    else:
        output.append("[OK] No casing duplicates found.")
        
    return "\n".join(output)

skip = ['date', 'stock', 'simulationdate', 'pnl', 'y', 'dt_parsed', 'stockname']
text1 = audit_file_to_text("/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/data/f11_intraday_features_all.csv", "Date", skip)
text2 = audit_file_to_text("/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/data/yahoo_finance_all_stocks_2015_2026_gap_features.csv", "Date", skip)

pdf = PDF()
pdf.add_page()
pdf.chapter_title("1. Intraday Features Audit")
pdf.chapter_body(text1)
pdf.chapter_title("2. Gap & Trend Features Audit")
pdf.chapter_body(text2)

pdf_path = "/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/reports/Feature_Matrix_Audit_Report.pdf"
os.makedirs(os.path.dirname(pdf_path), exist_ok=True)
pdf.output(pdf_path)

# Send to Telegram
BOT_TOKEN = "5350311365:AAFkTUBR4IGvgS5Z9mJngz-mgk7-HkhFEYE"
CHAT_ID = "-698073972"
with open(pdf_path, 'rb') as f:
    requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument",
        data={'chat_id': CHAT_ID, 'caption': 'Feature Matrix Audit Report (2026)'},
        files={'document': f}
    )
print("PDF generated and sent to Telegram!")
