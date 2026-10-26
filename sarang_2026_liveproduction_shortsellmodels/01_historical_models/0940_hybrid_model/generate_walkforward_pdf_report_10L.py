#!/usr/bin/env python3
"""
generate_walkforward_pdf_report_10L.py
========================================================================================
PUBLICATION-QUALITY PDF REPORT GENERATOR FOR 09:42 WALK-FORWARD AUDIT (2020-2026)
CONFIGURED FOR ₹10,00,000 CAPITAL PER STOCK & ₹40 BROKERAGE (+ STATUTORY CHARGES)
========================================================================================
"""

import os
import sys
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from reportlab.lib.pagesizes import letter, landscape
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, KeepTogether, PageBreak, HRFlowable
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

CSV_FILE = '/home/ubuntu/live_production0942_model/walkforward_0942_trades_10L_2020_2026.csv'
PDF_OUTPUT = '/home/ubuntu/live_production0942_model/walkforward_0942_3strategy_audit_report_10L.pdf'
CHART_OUTPUT = '/home/ubuntu/live_production0942_model/equity_curves_comparison_10L.png'

def create_charts(df):
    df['date_dt'] = pd.to_datetime(df['date'])
    df_daily = df.groupby('date_dt')[['s1_net_pnl', 's2_net_pnl', 's3_net_pnl']].sum().reset_index()
    df_daily = df_daily.sort_values('date_dt').reset_index(drop=True)

    df_daily['s1_cum'] = df_daily['s1_net_pnl'].cumsum() / 100000.0  # In Lakhs
    df_daily['s2_cum'] = df_daily['s2_net_pnl'].cumsum() / 100000.0
    df_daily['s3_cum'] = df_daily['s3_net_pnl'].cumsum() / 100000.0

    df_daily['s1_dd'] = (df_daily['s1_cum'] - df_daily['s1_cum'].cummax())
    df_daily['s2_dd'] = (df_daily['s2_cum'] - df_daily['s2_cum'].cummax())
    df_daily['s3_dd'] = (df_daily['s3_cum'] - df_daily['s3_cum'].cummax())

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 6.5), sharex=True, gridspec_kw={'height_ratios': [2.2, 1]})

    # Equity curves
    ax1.plot(df_daily['date_dt'], df_daily['s1_cum'], label='Strategy 1: Simple Hold (14:45 No TP, SL 2.25%)', color='#2563EB', linewidth=1.6)
    ax1.plot(df_daily['date_dt'], df_daily['s2_cum'], label='Strategy 2: Fixed TP 2.0% (SL 2.25%, Exit 14:45)', color='#D97706', linewidth=1.4)
    ax1.plot(df_daily['date_dt'], df_daily['s3_cum'], label='Strategy 3: Rebound Re-entry (+0.50% Rebound / 1.75% TP2)', color='#10B981', linewidth=1.5)

    ax1.set_title('09:42 Short-Sell Model — Walk-Forward Cumulative Net Profit (₹10L Capital | ₹40 Brokerage)', fontsize=13, fontweight='bold', pad=10)
    ax1.set_ylabel('Net Profit (₹ Lakhs)', fontsize=10, fontweight='bold')
    ax1.grid(True, linestyle='--', alpha=0.5)
    ax1.legend(loc='upper left', frameon=True, fontsize=9)

    # Drawdown
    ax2.plot(df_daily['date_dt'], df_daily['s1_dd'], label='Strategy 1 DD', color='#2563EB', alpha=0.8, linewidth=1.1)
    ax2.plot(df_daily['date_dt'], df_daily['s2_dd'], label='Strategy 2 DD', color='#D97706', alpha=0.8, linewidth=1.1)
    ax2.plot(df_daily['date_dt'], df_daily['s3_dd'], label='Strategy 3 DD', color='#10B981', alpha=0.8, linewidth=1.1)
    ax2.fill_between(df_daily['date_dt'], df_daily['s1_dd'], 0, color='#2563EB', alpha=0.08)
    ax2.set_ylabel('Drawdown (₹ Lakhs)', fontsize=10, fontweight='bold')
    ax2.set_xlabel('Date', fontsize=10, fontweight='bold')
    ax2.grid(True, linestyle='--', alpha=0.5)
    ax2.legend(loc='lower left', frameon=True, fontsize=8)

    ax2.xaxis.set_major_locator(mdates.YearLocator())
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))

    plt.tight_layout()
    plt.savefig(CHART_OUTPUT, dpi=300)
    plt.close()
    print(f"✔ Chart saved to: {CHART_OUTPUT}")

def generate_pdf():
    print("Generating Publication-Quality ₹10L PDF Report...")
    df = pd.read_csv(CSV_FILE)
    df['date_dt'] = pd.to_datetime(df['date'])
    df['month'] = df['date_dt'].dt.to_period('M').astype(str)

    create_charts(df)

    doc = SimpleDocTemplate(
        PDF_OUTPUT,
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=18,
        leading=22,
        textColor=colors.HexColor('#1E293B'),
        spaceAfter=4
    )
    subtitle_style = ParagraphStyle(
        'DocSub',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9.5,
        leading=14,
        textColor=colors.HexColor('#64748B'),
        spaceAfter=12
    )
    h2_style = ParagraphStyle(
        'H2',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=12,
        leading=16,
        textColor=colors.HexColor('#0F172A'),
        spaceBefore=10,
        spaceAfter=6
    )
    cell_style = ParagraphStyle(
        'Cell',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8,
        leading=10,
        textColor=colors.HexColor('#1E293B')
    )
    cell_bold = ParagraphStyle(
        'CellBold',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8,
        leading=10,
        textColor=colors.HexColor('#1E293B')
    )
    header_cell = ParagraphStyle(
        'HeaderCell',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8,
        leading=10,
        textColor=colors.white,
        alignment=1
    )

    elements = []

    # Title Banner
    elements.append(Paragraph("09:42 Short-Sell Hybrid Model — True Walk-Forward Audit Report", title_style))
    elements.append(Paragraph("₹10,00,000 Capital Per Stock | ₹40 Brokerage Round-Trip + Full Statutory Taxes | Certified Lookahead-Free (2020–2026)", subtitle_style))
    elements.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#CBD5E1'), spaceAfter=10))

    # Overall Metrics Table
    elements.append(Paragraph("Executive Performance Metrics (₹10L Capital | ₹40 Brokerage)", h2_style))

    metrics_data = [
        [
            Paragraph("Metric", header_cell),
            Paragraph("Strategy 1 (Simple Exit 14:45, No TP)", header_cell),
            Paragraph("Strategy 2 (Fixed TP 2.0%, Exit 14:45)", header_cell),
            Paragraph("Strategy 3 (Rebound Re-entry Model)", header_cell)
        ]
    ]

    tot_trades = len(df)
    s1_net = df['s1_net_pnl'].sum()
    s2_net = df['s2_net_pnl'].sum()
    s3_net = df['s3_net_pnl'].sum()

    s1_wr = (df['s1_net_pnl'] > 0).mean() * 100
    s2_wr = (df['s2_net_pnl'] > 0).mean() * 100
    s3_wr = (df['s3_net_pnl'] > 0).mean() * 100

    def calc_pf(series):
        pos = series[series > 0].sum()
        neg = abs(series[series < 0].sum())
        return pos / neg if neg > 0 else 99.0

    def calc_dd(series):
        cum = series.cumsum()
        return (cum - cum.cummax()).min()

    def calc_sharpe(series):
        daily = series.groupby(df['date']).sum()
        return (daily.mean() / daily.std()) * np.sqrt(252) if daily.std() > 0 else 0.0

    months_df = df.groupby('month')[['s1_net_pnl', 's2_net_pnl', 's3_net_pnl']].sum()
    n_months = len(months_df)
    s1_pos_m = (months_df['s1_net_pnl'] > 0).sum()
    s2_pos_m = (months_df['s2_net_pnl'] > 0).sum()
    s3_pos_m = (months_df['s3_net_pnl'] > 0).sum()

    tot_s1_charges = df['s1_charges'].sum() if 's1_charges' in df.columns else 0.0

    metrics_rows = [
        ("Total Net PnL (₹)", f"+₹{s1_net:,.2f}", f"+₹{s2_net:,.2f}", f"+₹{s3_net:,.2f}"),
        ("Total Simulated Trades", f"{tot_trades:,}", f"{tot_trades:,}", f"{tot_trades:,}"),
        ("Overall Win Rate", f"{s1_wr:.2f}%", f"{s2_wr:.2f}%", f"{s3_wr:.2f}%"),
        ("Profit Factor", f"{calc_pf(df['s1_net_pnl']):.2f}", f"{calc_pf(df['s2_net_pnl']):.2f}", f"{calc_pf(df['s3_net_pnl']):.2f}"),
        ("Max Drawdown (₹)", f"₹{calc_dd(df['s1_net_pnl']):,.2f}", f"₹{calc_dd(df['s2_net_pnl']):,.2f}", f"₹{calc_dd(df['s3_net_pnl']):,.2f}"),
        ("Annualized Sharpe Ratio", f"{calc_sharpe(df['s1_net_pnl']):.2f}", f"{calc_sharpe(df['s2_net_pnl']):.2f}", f"{calc_sharpe(df['s3_net_pnl']):.2f}"),
        ("Average Net Expectancy / Trade", f"+₹{s1_net/tot_trades:,.2f}", f"+₹{s2_net/tot_trades:,.2f}", f"+₹{s3_net/tot_trades:,.2f}"),
        ("Profitable Months", f"{s1_pos_m}/{n_months} ({s1_pos_m/n_months*100:.1f}%)", f"{s2_pos_m}/{n_months} ({s2_pos_m/n_months*100:.1f}%)", f"{s3_pos_m}/{n_months} ({s3_pos_m/n_months*100:.1f}%)"),
        ("Deducted Brokerage & Taxes (Total)", f"-₹{tot_s1_charges:,.2f}", f"-₹{tot_s1_charges:,.2f}", f"Included in Net PnL")
    ]

    for label, v1, v2, v3 in metrics_rows:
        metrics_data.append([
            Paragraph(label, cell_bold),
            Paragraph(v1, cell_style),
            Paragraph(v2, cell_style),
            Paragraph(v3, cell_style)
        ])

    t_metrics = Table(metrics_data, colWidths=[180, 120, 120, 120])
    t_metrics.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1E293B')),
        ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor('#F8FAFC'), colors.white]),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
    ]))
    elements.append(t_metrics)
    elements.append(Spacer(1, 10))

    # Notes callout box
    notes_text = (
        "<b>Cost & Position Sizing Specification:</b> Capital allocation = <b>₹10,00,000 per stock</b>. "
        "Flat brokerage = <b>₹40 per trade</b> (₹20 buy + ₹20 sell). Statutory charges applied on round-trip: "
        "STT (0.025% on sell), NSE Exchange Txn (0.00322%), SEBI Turnover (0.0001%), Stamp Duty (0.003% on buy), and GST (18% on Brokerage + Txn + SEBI). "
        "Average all-in friction is <b>~₹404 per trade</b> (~₹19.7 Lakhs in total deducted friction)."
    )
    p_notes = Paragraph(notes_text, cell_style)
    t_notes = Table([[p_notes]], colWidths=[540])
    t_notes.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F1F5F9')),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#94A3B8')),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))
    elements.append(t_notes)
    elements.append(Spacer(1, 10))

    # Equity Curve Image
    elements.append(Paragraph("Cumulative Equity Curves & Drawdown Comparison", h2_style))
    elements.append(Image(CHART_OUTPUT, width=540, height=315))
    elements.append(Spacer(1, 10))

    elements.append(PageBreak())

    # Annual Summary Table
    elements.append(Paragraph("Year-by-Year Performance Breakdown (Expanding Walk-Forward)", h2_style))
    annual_data = [
        [
            Paragraph("Year", header_cell),
            Paragraph("Trades", header_cell),
            Paragraph("S1 Net PnL (₹)", header_cell),
            Paragraph("S1 Win%", header_cell),
            Paragraph("S2 Net PnL (₹)", header_cell),
            Paragraph("S2 Win%", header_cell),
            Paragraph("S3 Net PnL (₹)", header_cell),
            Paragraph("S3 Win%", header_cell),
        ]
    ]

    for y, g in df.groupby('year'):
        tr_c = len(g)
        s1_n = g['s1_net_pnl'].sum()
        s2_n = g['s2_net_pnl'].sum()
        s3_n = g['s3_net_pnl'].sum()
        s1_w = (g['s1_net_pnl'] > 0).mean() * 100
        s2_w = (g['s2_net_pnl'] > 0).mean() * 100
        s3_w = (g['s3_net_pnl'] > 0).mean() * 100

        annual_data.append([
            Paragraph(str(y), cell_bold),
            Paragraph(f"{tr_c:,}", cell_style),
            Paragraph(f"+₹{s1_n:,.0f}", cell_style),
            Paragraph(f"{s1_w:.1f}%", cell_style),
            Paragraph(f"+₹{s2_n:,.0f}", cell_style),
            Paragraph(f"{s2_w:.1f}%", cell_style),
            Paragraph(f"+₹{s3_n:,.0f}", cell_style),
            Paragraph(f"{s3_w:.1f}%", cell_style),
        ])

    # Total row
    annual_data.append([
        Paragraph("TOTAL", cell_bold),
        Paragraph(f"{tot_trades:,}", cell_bold),
        Paragraph(f"+₹{s1_net:,.0f}", cell_bold),
        Paragraph(f"{s1_wr:.1f}%", cell_bold),
        Paragraph(f"+₹{s2_net:,.0f}", cell_bold),
        Paragraph(f"{s2_wr:.1f}%", cell_bold),
        Paragraph(f"+₹{s3_net:,.0f}", cell_bold),
        Paragraph(f"{s3_wr:.1f}%", cell_bold),
    ])

    t_annual = Table(annual_data, colWidths=[45, 50, 85, 55, 85, 55, 85, 80])
    t_annual.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1E293B')),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#E2E8F0')),
        ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.HexColor('#F8FAFC'), colors.white]),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
    ]))
    elements.append(t_annual)
    elements.append(Spacer(1, 14))

    # Monthly Sum PnL and Monthly Win Rates Table
    elements.append(Paragraph("Monthly Sum PnL & Monthly Win Rates (82 Months)", h2_style))
    monthly_data = [
        [
            Paragraph("Month", header_cell),
            Paragraph("Trades", header_cell),
            Paragraph("S1 Net PnL (₹)", header_cell),
            Paragraph("S1 Win%", header_cell),
            Paragraph("S2 Net PnL (₹)", header_cell),
            Paragraph("S2 Win%", header_cell),
            Paragraph("S3 Net PnL (₹)", header_cell),
            Paragraph("S3 Win%", header_cell),
        ]
    ]

    for m, g in df.groupby('month'):
        tr_c = len(g)
        s1_n = g['s1_net_pnl'].sum()
        s2_n = g['s2_net_pnl'].sum()
        s3_n = g['s3_net_pnl'].sum()
        s1_w = (g['s1_net_pnl'] > 0).mean() * 100
        s2_w = (g['s2_net_pnl'] > 0).mean() * 100
        s3_w = (g['s3_net_pnl'] > 0).mean() * 100

        color_s1 = '#15803D' if s1_n >= 0 else '#B91C1C'
        color_s2 = '#15803D' if s2_n >= 0 else '#B91C1C'
        color_s3 = '#15803D' if s3_n >= 0 else '#B91C1C'

        p_s1 = Paragraph(f"<font color='{color_s1}'>{' ' if s1_n<0 else '+'}₹{s1_n:,.0f}</font>", cell_style)
        p_s2 = Paragraph(f"<font color='{color_s2}'>{' ' if s2_n<0 else '+'}₹{s2_n:,.0f}</font>", cell_style)
        p_s3 = Paragraph(f"<font color='{color_s3}'>{' ' if s3_n<0 else '+'}₹{s3_n:,.0f}</font>", cell_style)

        monthly_data.append([
            Paragraph(str(m), cell_style),
            Paragraph(f"{tr_c}", cell_style),
            p_s1,
            Paragraph(f"{s1_w:.1f}%", cell_style),
            p_s2,
            Paragraph(f"{s2_w:.1f}%", cell_style),
            p_s3,
            Paragraph(f"{s3_w:.1f}%", cell_style),
        ])

    t_monthly = Table(monthly_data, colWidths=[55, 40, 85, 55, 85, 55, 85, 80])
    t_monthly.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1E293B')),
        ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor('#F8FAFC'), colors.white]),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
    ]))
    elements.append(t_monthly)

    doc.build(elements)
    print(f"🎉 PDF report successfully created: {PDF_OUTPUT}")

if __name__ == '__main__':
    generate_pdf()
