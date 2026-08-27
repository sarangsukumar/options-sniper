#!/usr/bin/env python3
"""
Full YoY Analysis: Combined Model vs Dual-Confirmed Only
=========================================================
Runs for MAX_ORDERS = 2, 3, 4 per day.
Per-trade stats: Win Rate, Avg PnL/Trade, Total PnL, # Trades
Generates:  (1) Markdown report
            (2) PDF report via ReportLab
            (3) Sends PDF via Telegram bot
"""

import os, sys, time, json, urllib.request, urllib.parse
import pandas as pd
import numpy as np
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                Paragraph, Spacer, HRFlowable)
from reportlab.lib.enums import TA_CENTER, TA_LEFT

# ── Paths ──────────────────────────────────────────────────────────────────────
_THIS_DIR  = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(_THIS_DIR, "output")
DATA_DIR   = os.path.join(_THIS_DIR, "../data")
REPORT_DIR = os.path.join(_THIS_DIR, "reports")
os.makedirs(REPORT_DIR, exist_ok=True)

# ── Telegram ────────────────────────────────────────────────────────────────────
BOT_TOKEN = "5350311365:AAFkTUBR4IGvgS5Z9mJngz-mgk7-HkhFEYE"
CHAT_ID   = "-698073972"

# ── Core helpers ───────────────────────────────────────────────────────────────
def load_freq_data(freqs):
    dfs = {}
    for freq in freqs:
        path = os.path.join(OUTPUT_DIR, f"trades_dynamic_threshold_{freq}.csv")
        if os.path.exists(path):
            df = pd.read_csv(path)
            df['date'] = pd.to_datetime(df['date'])
            dfs[freq] = df
    return dfs

def build_master(dfs, freqs):
    # Frequency CSV dates (up to Dec 2025 after rebuild)
    all_dates = set()
    for df in dfs.values(): all_dates.update(df['date'].unique())

    # ── EXTEND to 2026: pull dates from ensemble CSV ──────────────────────────
    ens_path = os.path.join(OUTPUT_DIR, "trades_dynamic_threshold_ensemble.csv")
    if os.path.exists(ens_path):
        df_ens_dates = pd.read_csv(ens_path, usecols=['date'])
        df_ens_dates['date'] = pd.to_datetime(df_ens_dates['date'])
        ens_2026 = df_ens_dates[df_ens_dates['date'].dt.year == 2026]['date'].unique()
        all_dates.update(ens_2026)
        if len(ens_2026) > 0:
            print(f"[INFO] Extended master table with {len(ens_2026)} 2026 dates from ensemble CSV")

    all_dates = sorted(list(all_dates))

    # Freq PnL = 0 for 2026 dates (no frequency model signals; Ridge uses rolling 2025 tail)
    daily_pnl = {freq: pd.Series(0.0, index=all_dates) for freq in freqs}
    for freq, df in dfs.items():
        dp = df.groupby('date')['actual_pnl'].sum()
        daily_pnl[freq].update(dp)

    df_pnl = pd.DataFrame(daily_pnl)
    df_pnl['date'] = df_pnl.index
    df_pnl = df_pnl.reset_index(drop=True)

    pnl_features = pd.DataFrame({'date': df_pnl['date']})
    for freq in freqs:
        for window in [3, 7, 14, 30]:
            pnl_features[f'{freq}_sum_{window}']  = df_pnl[freq].rolling(window).sum().shift(1)
            pnl_features[f'{freq}_mean_{window}'] = df_pnl[freq].rolling(window).mean().shift(1)

    df_f11 = pd.read_csv(os.path.join(DATA_DIR, "f11_intraday_features_all.csv"))
    df_f11['Date'] = pd.to_datetime(df_f11['Date'])
    mkt = df_f11.groupby('Date').agg(
        market_volatility=('intraday_volatility','mean'),
        market_return    =('intraday_return','mean'),
        market_trend     =('intraday_rsi_9','mean'),
        market_adv_dec   =('intraday_return', lambda x: (x>0).mean()),
        market_macd      =('intraday_macd','mean'),
        market_vwap_gap  =('intraday_vwap_gap','mean'),
    ).reset_index().rename(columns={'Date':'date'})

    # Use left join so 2026 dates are retained even if not in freq CSVs
    df_master = pd.merge(df_pnl, pnl_features, on='date', how='inner')
    df_master = pd.merge(df_master, mkt, on='date', how='left')
    # Fill NaN market features for any missing dates with forward-fill
    df_master = df_master.fillna(method='ffill').dropna().reset_index(drop=True)
    return df_master

def run_analysis(max_orders):
    freqs      = ['daily','weekly','monthly','quarterly','yearly']
    dfs        = load_freq_data(freqs)
    df_master  = build_master(dfs, freqs)
    features   = [c for c in df_master.columns if c not in ['date'] + freqs]
    test_years = range(2020, 2027)

    df_ens = pd.read_csv(os.path.join(OUTPUT_DIR, "trades_dynamic_threshold_ensemble.csv"))
    df_ens['date'] = pd.to_datetime(df_ens['date'])

    combined_trades  = []
    dual_conf_trades = []
    pnl_history      = []

    for test_year in test_years:
        train_df = df_master[df_master['date'].dt.year <  test_year]
        test_df  = df_master[df_master['date'].dt.year == test_year]
        if len(train_df) < 50 or len(test_df) == 0: continue

        scaler = StandardScaler()
        X_tr   = scaler.fit_transform(train_df[features])
        X_te   = scaler.transform(test_df[features])

        preds = {freq: np.zeros(len(test_df)) for freq in freqs}
        for freq in freqs:
            m = Ridge(alpha=1.0, random_state=42)
            m.fit(X_tr, train_df[freq])
            preds[freq] = m.predict(X_te)

        for i, row in enumerate(test_df.itertuples()):
            dt = row.date
            day_static = df_ens[df_ens['date'] == dt].sort_values('pred_pnl', ascending=False)
            if day_static.empty: continue

            # Adaptive Dampener
            dampener = False
            iso = dt.isocalendar(); cyr, cwk = iso[0], iso[1]
            if pnl_history:
                ph = pd.DataFrame(pnl_history)
                past = ph[ph['date'] < dt].copy()
                if not past.empty:
                    past['isoyr'] = past['date'].dt.isocalendar().year
                    past['isowk'] = past['date'].dt.isocalendar().week
                    done = past[~((past['isoyr']==cyr)&(past['isowk']==cwk))]
                    if not done.empty:
                        wkpnl = done.groupby(['isoyr','isowk'])['actual_pnl'].sum()
                        if len(wkpnl)>0 and wkpnl.iloc[-1]<0:
                            dampener = True

            # ML stocks
            dp = {freq: preds[freq][i] for freq in freqs}
            active = sorted(dp, key=dp.get, reverse=True)[:2]
            ml_stocks = set()
            for freq in active:
                ml_stocks.update(dfs[freq][dfs[freq]['date']==dt]['stock'].unique())

            static_stocks = day_static['stock'].tolist()

            # Dual-confirmed stock
            dual = None
            if not dampener:
                for s in static_stocks[:3]:
                    if s in ml_stocks:
                        dual = s; break

            day_pnl_sum = 0.0

            if dampener:
                for _, r in day_static.head(max_orders).iterrows():
                    t = {'date':dt,'year':dt.year,'stock':r['stock'],
                         'actual_pnl':r['actual_pnl'],'is_dual':False,'dampener':True}
                    combined_trades.append(t)
                    day_pnl_sum += r['actual_pnl']
            else:
                if dual and len(static_stocks) >= 2:
                    # Drop lowest-ranked non-dual
                    drop = None
                    for s in reversed(static_stocks):
                        if s != dual: drop = s; break
                    selected = [s for s in static_stocks if s != drop][:max_orders]
                    for _, r in day_static.iterrows():
                        if r['stock'] not in selected: continue
                        mult   = 2 if r['stock'] == dual else 1
                        pnl    = r['actual_pnl'] * mult
                        is_d   = (r['stock'] == dual)
                        t = {'date':dt,'year':dt.year,'stock':r['stock'],
                             'actual_pnl':pnl,'is_dual':is_d,'dampener':False}
                        combined_trades.append(t)
                        if is_d: dual_conf_trades.append(t)
                        day_pnl_sum += pnl
                else:
                    for _, r in day_static.head(max_orders).iterrows():
                        t = {'date':dt,'year':dt.year,'stock':r['stock'],
                             'actual_pnl':r['actual_pnl'],'is_dual':False,'dampener':False}
                        combined_trades.append(t)
                        day_pnl_sum += r['actual_pnl']

            pnl_history.append({'date':dt,'actual_pnl':day_pnl_sum})

    return pd.DataFrame(combined_trades), pd.DataFrame(dual_conf_trades)

def stats(df, years):
    rows = []
    for y in years:
        d = df[df['year']==y]
        n = len(d)
        if n == 0:
            rows.append({'year':y,'wr':0,'avg':0,'tot':0,'n':0})
            continue
        wr  = (d['actual_pnl']>0).sum()/n*100
        tot = d['actual_pnl'].sum()
        rows.append({'year':y,'wr':wr,'avg':tot/n,'tot':tot,'n':n})
    # Total
    d = df[df['year'].isin(years)]
    n = len(d)
    if n > 0:
        rows.append({'year':'TOTAL','wr':(d['actual_pnl']>0).sum()/n*100,
                     'avg':d['actual_pnl'].sum()/n,'tot':d['actual_pnl'].sum(),'n':n})
    else:
        rows.append({'year':'TOTAL','wr':0,'avg':0,'tot':0,'n':0})
    return rows

# ── Markdown builder ───────────────────────────────────────────────────────────
def build_markdown(all_results, test_years):
    ts = time.strftime("%Y-%m-%d %H:%M IST")
    lines = [
        f"# Champion Strategy — Full YoY Analysis",
        f"*Generated: {ts}*",
        "",
        "## Strategy Rules",
        "- **Dual Confirmed** = stock appears in both Static Ensemble top picks AND ML frequency models → **2× lot size**",
        "- **Others** = Static Ensemble picks not ML-confirmed → **1× lot size**",
        "- **Adaptive Dampener** = if previous ISO week PnL < 0, revert to flat 1× lots (no ML shifting)",
        "- **Per-trade stats**: each individual stock position = 1 trade (dual trades already include 2× PnL)",
        "",
        "---",
    ]

    for max_ord, (df_c, df_d) in all_results.items():
        lines += [
            f"",
            f"## Max Orders = {max_ord} per Day",
            f"",
            f"### Combined Model (all trades)",
            "",
            f"| Year  | Win Rate % | Avg PnL/Trade (Rs) | Total PnL (Rs) | Trades |",
            f"|-------|-----------|---------------------|----------------|--------|",
        ]
        for r in stats(df_c, test_years):
            yr = f"{r['year']}*" if r['year']==2026 else str(r['year'])
            lines.append(f"| {yr:<5} | {r['wr']:.1f}%     | {r['avg']:>18,.0f} | {r['tot']:>14,.0f} | {r['n']:>6} |")

        lines += [
            "",
            f"### Dual-Confirmed Trades Only (2× lot)",
            "",
            f"| Year  | Win Rate % | Avg PnL/Trade (Rs) | Total PnL (Rs) | Trades |",
            f"|-------|-----------|---------------------|----------------|--------|",
        ]
        for r in stats(df_d, test_years):
            yr = f"{r['year']}*" if r['year']==2026 else str(r['year'])
            lines.append(f"| {yr:<5} | {r['wr']:.1f}%     | {r['avg']:>18,.0f} | {r['tot']:>14,.0f} | {r['n']:>6} |")

        # Summary callout
        tc = stats(df_c, test_years)[-1]
        td = stats(df_d, test_years)[-1]
        dual_pct = td['tot']/tc['tot']*100 if tc['tot']!=0 else 0
        trade_pct= td['n']/tc['n']*100 if tc['n']!=0 else 0
        lines += [
            "",
            f"> **Max {max_ord} Summary**: Dual-confirmed trades are {trade_pct:.0f}% of all trades "
            f"but contribute {dual_pct:.0f}% of total PnL. "
            f"Avg PnL per dual trade: **Rs {td['avg']:,.0f}** vs Rs {tc['avg']:,.0f} for all trades.",
            "",
            "---",
        ]

    lines += [
        "",
        "## Notes",
        "- `*` 2026 is strictly Out-Of-Sample (OOS)",
        "- Dual trade PnL already reflects the 2× lot multiplier",
        "- Dampener weeks revert all trades to 1× (no ML shifting) — these show under Combined only",
    ]
    return "\n".join(lines)

# ── PDF builder ────────────────────────────────────────────────────────────────
def build_pdf(all_results, test_years, pdf_path):
    doc = SimpleDocTemplate(pdf_path, pagesize=A4,
                            leftMargin=1.5*cm, rightMargin=1.5*cm,
                            topMargin=2*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    story  = []

    # Title
    title_style = ParagraphStyle('title', parent=styles['Title'],
                                 fontSize=18, spaceAfter=6, textColor=colors.HexColor('#1a1a2e'))
    sub_style   = ParagraphStyle('sub', parent=styles['Normal'],
                                 fontSize=10, textColor=colors.grey, spaceAfter=16)
    h1_style    = ParagraphStyle('h1', parent=styles['Heading1'],
                                 fontSize=13, textColor=colors.HexColor('#16213e'), spaceBefore=14, spaceAfter=6)
    h2_style    = ParagraphStyle('h2', parent=styles['Heading2'],
                                 fontSize=11, textColor=colors.HexColor('#0f3460'), spaceBefore=10, spaceAfter=4)
    note_style  = ParagraphStyle('note', parent=styles['Normal'],
                                 fontSize=9, textColor=colors.HexColor('#444444'),
                                 backColor=colors.HexColor('#f0f4ff'),
                                 borderPadding=6, spaceAfter=10)

    ts_str = time.strftime("%d %b %Y, %H:%M IST")
    story.append(Paragraph("Champion Strategy — Full YoY Analysis", title_style))
    story.append(Paragraph(f"Generated: {ts_str} &nbsp;|&nbsp; Per-trade breakdown &nbsp;|&nbsp; Max Orders: 2, 3, 4", sub_style))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#cccccc'), spaceAfter=10))

    # Rules box
    rules = (
        "<b>Strategy Rules:</b> Dual Confirmed = top Static Ensemble stock also confirmed by ML model → <b>2× lot</b>. "
        "Others = 1× lot. Adaptive Dampener: if prior week PnL &lt; 0 → revert to flat 1× (no ML shifting). "
        "Per-trade: each stock position = 1 trade; dual trades already include 2× PnL."
    )
    story.append(Paragraph(rules, note_style))
    story.append(Spacer(1, 8))

    tbl_header_style = [
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#16213e')),
        ('TEXTCOLOR',  (0,0), (-1,0), colors.white),
        ('FONTNAME',   (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE',   (0,0), (-1,-1), 8),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#f7f9ff')]),
        ('GRID',       (0,0), (-1,-1), 0.4, colors.HexColor('#dddddd')),
        ('ALIGN',      (1,0), (-1,-1), 'RIGHT'),
        ('ALIGN',      (0,0), (0,-1), 'CENTER'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('TOPPADDING',    (0,0), (-1,-1), 4),
        ('ROWBACKGROUNDS', (0,-1), (-1,-1), [colors.HexColor('#e8ecf4')]),
        ('FONTNAME',   (0,-1), (-1,-1), 'Helvetica-Bold'),
    ]

    def make_table(data_rows, col_widths):
        t = Table(data_rows, colWidths=col_widths)
        t.setStyle(TableStyle(tbl_header_style))
        return t

    for max_ord, (df_c, df_d) in all_results.items():
        story.append(Paragraph(f"Max Orders = {max_ord} per Day", h1_style))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor('#aaaaaa'), spaceAfter=6))

        for label, df in [("Combined Model — All Trades", df_c),
                           ("Dual-Confirmed Trades Only (2× lot)", df_d)]:
            story.append(Paragraph(label, h2_style))
            rows_data = [["Year", "Win Rate %", "Avg PnL/Trade (Rs)", "Total PnL (Rs)", "Trades"]]
            for r in stats(df, test_years):
                yr = f"{r['year']}*" if r['year']==2026 else str(r['year'])
                rows_data.append([
                    yr,
                    f"{r['wr']:.1f}%",
                    f"Rs {r['avg']:>12,.0f}",
                    f"Rs {r['tot']:>13,.0f}",
                    f"{r['n']:,}",
                ])
            cw = [1.5*cm, 2.2*cm, 4.5*cm, 4.5*cm, 2.2*cm]
            story.append(make_table(rows_data, cw))
            story.append(Spacer(1, 8))

        # Summary callout
        tc = stats(df_c, test_years)[-1]
        td = stats(df_d, test_years)[-1]
        dual_pct  = td['tot']/tc['tot']*100 if tc['tot']!=0 else 0
        trade_pct = td['n']/tc['n']*100 if tc['n']!=0 else 0
        summary = (
            f"<b>Max {max_ord} Summary:</b> Dual-confirmed = {trade_pct:.0f}% of trades "
            f"→ {dual_pct:.0f}% of total PnL. "
            f"Avg dual trade: <b>Rs {td['avg']:,.0f}</b> vs Rs {tc['avg']:,.0f} (all trades)."
        )
        story.append(Paragraph(summary, note_style))
        story.append(Spacer(1, 12))

    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor('#cccccc'), spaceAfter=6))
    story.append(Paragraph("* 2026 is strictly Out-Of-Sample (OOS). Dual trade PnL already reflects 2× lot multiplier.", 
                            ParagraphStyle('footnote', parent=styles['Normal'], fontSize=8, textColor=colors.grey)))
    doc.build(story)
    print(f"[PDF] Saved → {pdf_path}")

# ── Telegram sender ────────────────────────────────────────────────────────────
def send_telegram_message(text):
    url  = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({'chat_id': CHAT_ID, 'text': text, 'parse_mode': 'Markdown'}).encode()
    try:
        urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=30)
        print("[TG] Message sent")
    except Exception as e:
        print(f"[TG] Message failed: {e}")

def send_telegram_file(file_path, caption=""):
    filename = os.path.basename(file_path)
    with open(file_path, 'rb') as f:
        file_data = f.read()
    boundary = f"TGBoundary{int(time.time())}"
    parts = []
    for name, val in [('chat_id', CHAT_ID.encode()), ('caption', caption.encode())]:
        parts += [f"--{boundary}".encode(),
                  f'Content-Disposition: form-data; name="{name}"'.encode(), b'', val]
    parts += [f"--{boundary}".encode(),
              f'Content-Disposition: form-data; name="document"; filename="{filename}"'.encode(),
              b'Content-Type: application/octet-stream', b'', file_data,
              f"--{boundary}--".encode(), b'']
    body = b'\r\n'.join(parts)
    req  = urllib.request.Request(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument", data=body)
    req.add_header('Content-Type', f'multipart/form-data; boundary={boundary}')
    req.add_header('Content-Length', len(body))
    try:
        res = json.loads(urllib.request.urlopen(req, timeout=120).read())
        if res.get('ok'):
            print(f"[TG] File sent: {filename}")
        else:
            print(f"[TG] File send failed: {res}")
    except Exception as e:
        print(f"[TG] File send error: {e}")

# ── Main ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    TEST_YEARS  = range(2020, 2027)
    MAX_ORDERS  = [2, 3, 4]

    print("=" * 70)
    print("  CHAMPION STRATEGY — FULL YoY ANALYSIS")
    print(f"  Max Orders: {MAX_ORDERS} | Per-Trade Stats")
    print("=" * 70)

    send_telegram_message("⏳ *Champion Strategy Analysis Started*\nRunning for Max Orders = 2, 3, 4...\nThis will take ~2 minutes.")

    all_results = {}
    for mo in MAX_ORDERS:
        print(f"\n[{mo}/4] Running backtest for Max Orders = {mo}...")
        df_c, df_d = run_analysis(mo)
        all_results[mo] = (df_c, df_d)

        # Print to console
        print(f"\n{'='*70}")
        print(f"  MAX ORDERS = {mo} | COMBINED MODEL")
        print(f"{'='*70}")
        print(f"{'Year':<6} {'Win%':>7} {'Avg PnL/Trade':>16} {'Total PnL':>16} {'Trades':>8}")
        print("-"*55)
        for r in stats(df_c, TEST_YEARS):
            yr = f"{r['year']}*" if r['year']==2026 else str(r['year'])
            print(f"{yr:<6} {r['wr']:>6.1f}% {'Rs {:>12,.0f}'.format(r['avg']):>16} {'Rs {:>12,.0f}'.format(r['tot']):>16} {r['n']:>8,}")

        print(f"\n  MAX ORDERS = {mo} | DUAL-CONFIRMED ONLY")
        print("-"*55)
        for r in stats(df_d, TEST_YEARS):
            yr = f"{r['year']}*" if r['year']==2026 else str(r['year'])
            print(f"{yr:<6} {r['wr']:>6.1f}% {'Rs {:>12,.0f}'.format(r['avg']):>16} {'Rs {:>12,.0f}'.format(r['tot']):>16} {r['n']:>8,}")

    # Build markdown
    ts       = time.strftime("%Y%m%d_%H%M")
    md_path  = os.path.join(REPORT_DIR, f"champion_yoy_{ts}.md")
    pdf_path = os.path.join(REPORT_DIR, f"champion_yoy_{ts}.pdf")

    md_text = build_markdown(all_results, TEST_YEARS)
    with open(md_path, 'w') as f:
        f.write(md_text)
    print(f"\n[MD] Saved → {md_path}")

    # Build PDF
    build_pdf(all_results, TEST_YEARS, pdf_path)

    # Send via Telegram
    tc2 = stats(all_results[2][0], TEST_YEARS)[-1]
    td2 = stats(all_results[2][1], TEST_YEARS)[-1]
    summary_msg = (
        f"✅ *Champion Strategy YoY Analysis Complete*\n\n"
        f"*Max 2 Orders/Day — Combined Model (All Trades):*\n"
        f"  Win Rate: `{tc2['wr']:.1f}%`\n"
        f"  Avg PnL/Trade: `Rs {tc2['avg']:,.0f}`\n"
        f"  Total PnL: `Rs {tc2['tot']:,.0f}`\n"
        f"  Trades: `{tc2['n']:,}`\n\n"
        f"*Max 2 — Dual-Confirmed Only:*\n"
        f"  Win Rate: `{td2['wr']:.1f}%`\n"
        f"  Avg PnL/Trade: `Rs {td2['avg']:,.0f}`\n"
        f"  Total PnL: `Rs {td2['tot']:,.0f}`\n"
        f"  Trades: `{td2['n']:,}`\n\n"
        f"_Full breakdown (Max 2/3/4) in PDF below ↓_"
    )
    send_telegram_message(summary_msg)
    send_telegram_file(pdf_path, caption="Champion Strategy — YoY Analysis (Max Orders 2, 3, 4)")
    send_telegram_file(md_path,  caption="Markdown report (open in any MD viewer)")

    print("\n✅ All done! PDF + MD sent via Telegram.")
