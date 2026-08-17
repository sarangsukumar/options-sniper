import pandas as pd
import numpy as np
import os
import subprocess
from fpdf import FPDF
import sys

# Import the backtest logic
sys.path.append('/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/historical_models')
from show_champion_yoy_per_stock import run_backtest

# 1. Get the backtest results
df = run_backtest()
df['date'] = pd.to_datetime(df['date'])

# 2. Filter for 2026
df_2026 = df[df['date'].dt.year == 2026].copy()
df_2026['month'] = df_2026['date'].dt.month

# 3. Calculate metrics
total_pnl = df_2026['actual_pnl'].sum()
avg_pnl = df_2026['actual_pnl'].mean()
win_rate = (df_2026['actual_pnl'] > 0).mean() * 100
total_trades = len(df_2026)

# Monthly metrics
monthly_stats = df_2026.groupby('month')['actual_pnl'].agg(['sum', 'mean', 'count', lambda x: (x > 0).mean() * 100]).reset_index()
monthly_stats.columns = ['Month', 'Sum PnL', 'Avg PnL', 'Trades', 'Win Rate %']

# 4. Generate PDF
pdf = FPDF()
pdf.add_page()
pdf.set_font("Arial", size=15, style='B')
pdf.cell(200, 10, txt="Champion Strategy Backtest Report - 2026", ln=True, align='C')

pdf.set_font("Arial", size=12)
pdf.ln(10)
pdf.cell(200, 10, txt=f"Total Trades: {total_trades}", ln=True)
pdf.cell(200, 10, txt=f"Total Sum PnL: Rs {total_pnl:,.2f}", ln=True)
pdf.cell(200, 10, txt=f"Average PnL per Trade: Rs {avg_pnl:,.2f}", ln=True)
pdf.cell(200, 10, txt=f"Overall Win Rate: {win_rate:.2f}%", ln=True)

pdf.ln(10)
pdf.set_font("Arial", size=14, style='B')
pdf.cell(200, 10, txt="Monthly Breakdown:", ln=True)
pdf.set_font("Arial", size=10)

# Table Header
pdf.cell(25, 10, "Month", border=1)
pdf.cell(40, 10, "Sum PnL", border=1)
pdf.cell(40, 10, "Avg PnL", border=1)
pdf.cell(30, 10, "Trades", border=1)
pdf.cell(30, 10, "Win Rate %", border=1)
pdf.ln(10)

# Table Rows
month_names = {1: 'Jan', 2: 'Feb', 3: 'Mar', 4: 'Apr', 5: 'May', 6: 'Jun', 7: 'Jul', 8: 'Aug', 9: 'Sep', 10: 'Oct', 11: 'Nov', 12: 'Dec'}
for _, row in monthly_stats.iterrows():
    pdf.cell(25, 10, month_names.get(int(row['Month']), str(row['Month'])), border=1)
    pdf.cell(40, 10, f"Rs {row['Sum PnL']:,.2f}", border=1)
    pdf.cell(40, 10, f"Rs {row['Avg PnL']:,.2f}", border=1)
    pdf.cell(30, 10, str(int(row['Trades'])), border=1)
    pdf.cell(30, 10, f"{row['Win Rate %']:.1f}%", border=1)
    pdf.ln(10)

pdf_path = "/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/Champion_2026_Report.pdf"
pdf.output(pdf_path)

print(f"PDF generated successfully at: {pdf_path}")

# 5. Send to Telegram
bot_path = "/home/ubuntu/telegram_bot/New_OrderInfoBot.js"
if os.path.exists(bot_path):
    print("Sending via Telegram...")
    subprocess.run(["node", bot_path, pdf_path], check=True)
    print("Telegram alert sent.")
else:
    print(f"Bot script not found at {bot_path}")
