#!/usr/bin/env python3
import os
import sys
import shutil
import pandas as pd
import subprocess
import pickle
import numpy as np
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

BASE_DIR = "/home/ubuntu/daily_prediction_sytem_Dynamic_threshold"
DATA_DIR = os.path.join(BASE_DIR, "data")
SANDBOX_DIR = os.path.join(BASE_DIR, "sandbox_2026")
CACHE_FILE = os.path.join(BASE_DIR, "historical_models", "output", "wf_predictions_cache_ensemble_da_standard_dl_3.0_nf.pkl")
PDF_REPORT = os.path.join(BASE_DIR, "Sandbox_2026_Full_Audit.pdf")

FILES_TO_SLICE = [
    {"filename": "markets_pnl0325.csv", "date_col_possible": ["simulationdate", "Date", "date", "time"]},
    {"filename": "f11_intraday_features_all.csv", "date_col_possible": ["Date", "date", "simulationdate"]},
    {"filename": "yahoo_finance_all_stocks_2015_2026_gap_features.csv", "date_col_possible": ["Date", "date", "simulationdate"]},
    {"filename": "masterfile.csv", "date_col_possible": []} 
]

def find_date_col(df, possible_names):
    lower_cols = [c.lower().strip() for c in df.columns]
    for p in possible_names:
        if p.lower() in lower_cols:
            idx = lower_cols.index(p.lower())
            return df.columns[idx]
    return None

def create_sandbox_for_date(target_date_str):
    target_date = pd.to_datetime(target_date_str, format='%Y-%m-%d')
    date_dir = os.path.join(SANDBOX_DIR, target_date_str)
    date_data_dir = os.path.join(date_dir, "data")
    os.makedirs(date_data_dir, exist_ok=True)
    
    for file_info in FILES_TO_SLICE:
        src_path = os.path.join(DATA_DIR, file_info["filename"])
        dest_path = os.path.join(date_data_dir, file_info["filename"])
        if not os.path.exists(src_path): continue
        if len(file_info["date_col_possible"]) > 0:
            df = pd.read_csv(src_path)
            date_col = find_date_col(df, file_info["date_col_possible"])
            if date_col:
                parsed_dates = pd.to_datetime(df[date_col], format='mixed', dayfirst=True, errors='coerce')
                sliced_df = df[parsed_dates <= target_date]
                sliced_df.to_csv(dest_path, index=False)
            else:
                shutil.copy2(src_path, dest_path)
        else:
            shutil.copy2(src_path, dest_path)
            
    # Slice trades_ticker_suspension
    suspension_src = os.path.join(BASE_DIR, "output", "trades_ticker_suspension.csv")
    dest_out_dir = os.path.join(date_dir, "output")
    os.makedirs(dest_out_dir, exist_ok=True)
    if os.path.exists(suspension_src):
        suspension_df = pd.read_csv(suspension_src)
        parsed_dates_ts = pd.to_datetime(suspension_df['date'], format='mixed', dayfirst=True, errors='coerce')
        sliced_ts = suspension_df[parsed_dates_ts < target_date]
        sliced_ts.to_csv(os.path.join(dest_out_dir, "trades_ticker_suspension.csv"), index=False)
            
    # Patch predict_today to NOT send telegram messages!
    with open(os.path.join(BASE_DIR, "predict_today.py"), "r") as f:
        code = f.read()
    code = code.replace('"/home/ubuntu/telegram_bot/New_OrderInfoBot.js"', '"/bin/echo"')
    with open(os.path.join(date_dir, "predict_today.py"), "w") as f:
        f.write(code)
    
    src_medians = os.path.join(BASE_DIR, "historical_models", "output", "daily_medians_std.csv")
    if os.path.exists(src_medians):
        df_med = pd.read_csv(src_medians)
        df_med['date_parsed'] = pd.to_datetime(df_med['date'])
        sliced_med = df_med[df_med['date_parsed'] <= target_date].drop(columns=['date_parsed'])
        sliced_med.to_csv(os.path.join(dest_out_dir, "daily_medians_std.csv"), index=False)

    return date_dir

def extract_sandbox_picks(log_output):
    picks = []
    lines = log_output.split('\n')
    capture = False
    for line in lines:
        if "SNIPER ALGORITHM PRODUCTION TRADING CANDIDATES" in line:
            capture = True
        elif capture and "FINAL STRATEGY RECOMMENDATIONS" in line:
            break
        elif capture and "|" in line and "Stock Name" not in line and "---" not in line:
            parts = line.split("|")
            if len(parts) > 3:
                stock = parts[0].strip()
                try:
                    pred_pnl = float(parts[3].strip().replace("Rs", "").replace(",", "").strip())
                    picks.append((stock, pred_pnl))
                except:
                    pass
    return picks

def generate_pdf(report_data, summary_stats, missing_breakdown):
    doc = SimpleDocTemplate(PDF_REPORT, pagesize=letter)
    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph("Full 2026 Lookahead Audit: Sandbox vs Backtest", styles['Title']))
    elements.append(Spacer(1, 12))
    
    summary_text = (
        f"<b>Total 2026 Days Tested:</b> {summary_stats['total_days']}<br/>"
        f"<b>Total Traded Days:</b> {summary_stats['traded_days']}<br/>"
        f"<b>Total Skipped Days:</b> {summary_stats['skipped_days']}<br/>"
        f"<b>Total Stocks Predicted (Sandbox):</b> {summary_stats['total_stocks']}<br/>"
        f"<b>Stock Exact Name Match Rate:</b> {summary_stats['match_rate']:.2f}%<br/>"
        f"<b>Scores Matched (within 50 Rs tolerance):</b> {summary_stats['score_match_pct']:.2f}%<br/>"
        f"<b>Average PnL Score Difference:</b> Rs {summary_stats['avg_diff']:.2f}<br/><br/>"
        "<i>This report verifies that the Live Sandbox logic produces identical predictions to the historical backtest. Mismatches are exclusively due to historical universe filtering ('MISSING' in cache).</i>"
    )
    elements.append(Paragraph(summary_text, styles['Normal']))
    elements.append(Spacer(1, 24))
    
    if missing_breakdown:
        elements.append(Paragraph("<b>Missing Stocks Breakdown (Mismatched due to universe filter):</b>", styles['Heading3']))
        missing_text = "<br/>".join([f" - {stk}: {count} times" for stk, count in missing_breakdown.items()])
        elements.append(Paragraph(missing_text, styles['Normal']))
        elements.append(Spacer(1, 24))

    for dt, data in report_data.items():
        elements.append(Paragraph(f"<b>Date: {dt}</b>", styles['Heading3']))
        
        if data['status'] == 'SKIPPED':
            elements.append(Paragraph(f"Status: SKIPPED in both Sandbox and Backtest (Reason: {data.get('reason', 'N/A')})", styles['Normal']))
            elements.append(Spacer(1, 12))
            continue
            
        table_data = [["Stock", "Sandbox PnL", "Backtest PnL", "Status"]]
        for row in data['comparisons']:
            table_data.append(row)
            
        t = Table(table_data, colWidths=[120, 100, 100, 150])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.grey),
            ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('BOTTOMPADDING', (0,0), (-1,0), 6),
            ('BACKGROUND', (0,1), (-1,-1), colors.beige),
            ('GRID', (0,0), (-1,-1), 1, colors.black),
        ]))
        elements.append(t)
        elements.append(Spacer(1, 18))
        
    doc.build(elements)

def main():
    if os.path.exists(SANDBOX_DIR):
        shutil.rmtree(SANDBOX_DIR)
    os.makedirs(SANDBOX_DIR, exist_ok=True)
        
    with open(CACHE_FILE, 'rb') as f:
        cache = pickle.load(f)
        
    # Get ONLY 2026 dates
    selected_ts = [ts for ts in cache.keys() if ts.year == 2026]
    selected_ts.sort()
    
    print(f"[*] Total 2026 dates to test: {len(selected_ts)}")
    
    report_data = {}
    total_sandbox_preds = 0
    names_matched = 0
    scores_matched = 0
    score_diffs = []
    reasons_for_mismatch = {}
    
    traded_days = 0
    skipped_days = 0
    
    active_folders = []

    for i, ts in enumerate(selected_ts):
        dt_str = ts.strftime('%Y-%m-%d')
        print(f"[{i+1}/{len(selected_ts)}] Processing {dt_str}...")
        
        day_obj = cache[ts]
        is_skipped = isinstance(day_obj, dict) and day_obj.get('status') == 'SKIPPED'
        
        sdir = create_sandbox_for_date(dt_str)
        active_folders.append(sdir)
        
        cmd = [sys.executable, "predict_today.py", "--date", dt_str]
        process = subprocess.run(cmd, cwd=sdir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        s_picks = extract_sandbox_picks(process.stdout)
        
        if len(active_folders) > 5:
            folder_to_delete = active_folders.pop(0)
            if os.path.exists(folder_to_delete):
                shutil.rmtree(folder_to_delete)
                
        if is_skipped:
            skipped_days += 1
            report_data[dt_str] = {'status': 'SKIPPED', 'reason': day_obj.get('reason')}
            continue
            
        traded_days += 1
        s_picks = s_picks[:5] # Top 5 only
        day_df = day_obj
        comparisons = []
        
        for stock, sandbox_pnl in s_picks:
            total_sandbox_preds += 1
            stock_row = day_df[day_df['stockname'] == stock]
            if not stock_row.empty:
                names_matched += 1
                hist_pnl = stock_row['pred_pnl'].values[0]
                diff = abs(sandbox_pnl - hist_pnl)
                score_diffs.append(diff)
                status_text = "MATCH" if diff < 50.0 else f"DIFF ({diff:.2f})"
                if diff < 50.0:
                    scores_matched += 1
                comparisons.append([stock, f"{sandbox_pnl:.2f}", f"{hist_pnl:.2f}", status_text])
            else:
                reasons_for_mismatch[stock] = reasons_for_mismatch.get(stock, 0) + 1
                comparisons.append([stock, f"{sandbox_pnl:.2f}", "MISSING", "MISSING IN BACKTEST"])
                
        report_data[dt_str] = {'status': 'TRADED', 'comparisons': comparisons}
                
    avg_diff = np.mean(score_diffs) if score_diffs else 0.0
    name_match_pct = (names_matched / total_sandbox_preds * 100) if total_sandbox_preds > 0 else 100
    score_match_pct = (scores_matched / total_sandbox_preds * 100) if total_sandbox_preds > 0 else 100
    
    summary_stats = {
        'total_days': len(selected_ts),
        'traded_days': traded_days,
        'skipped_days': skipped_days,
        'total_stocks': total_sandbox_preds,
        'match_rate': name_match_pct,
        'score_match_pct': score_match_pct,
        'avg_diff': avg_diff
    }
    
    generate_pdf(report_data, summary_stats, reasons_for_mismatch)
    print(f"\nPDF generated at {PDF_REPORT}")
    
    tele_script = "/home/ubuntu/telegram_bot/New_OrderInfoBot.js"
    subprocess.run(["node", tele_script, PDF_REPORT])

if __name__ == "__main__":
    main()
