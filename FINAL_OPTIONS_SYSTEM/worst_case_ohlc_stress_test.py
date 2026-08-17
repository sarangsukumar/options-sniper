"""
WORST-CASE OHLC STRESS TEST
============================
For every trade, we simulate the absolute worst possible tick-level execution:

ENTRY (15:25 IST candle):
  - Sell put (collect credit) → use LOW  (minimum premium we'd collect)
  - Buy  put (pay debit)      → use HIGH (maximum premium we'd pay)
  ∴ Entry Credit = LOW(sell_strike) - HIGH(buy_strike)  ← minimized

EXIT (09:29 IST next morning candle):
  - Buy back sold put (pay to close) → use HIGH (maximum cost to close)
  - Sell back bought put (receive)   → use LOW  (minimum received)
  ∴ Exit Debit = HIGH(sell_strike) - LOW(buy_strike)    ← maximized

PnL = (Entry Credit  -  Exit Debit) * lot_size * lots  -  commissions

This is the FLOOR — real trading can only do EQUAL or BETTER than this.
"""

import mysql.connector
import pandas as pd
from collections import Counter
from backtest_experiment import get_lot_size

# ─── DB ──────────────────────────────────────────────────────────────────────
db     = mysql.connector.connect(host='localhost', user='root', password='root', database='markets')
cursor = db.cursor(dictionary=True)

# ─── Get real step size from DB chain ────────────────────────────────────────
def get_real_step(stock, date):
    cursor.execute(
        "SELECT DISTINCT strike_price FROM scrapdata_options "
        "WHERE stock_code=%s AND DATE(datetime)=%s AND `right`='Put' ORDER BY strike_price",
        (stock, date)
    )
    rows = cursor.fetchall()
    if len(rows) < 2: return None
    strikes = sorted([float(r['strike_price']) for r in rows])
    diffs   = [round(strikes[i+1] - strikes[i], 2) for i in range(len(strikes)-1) if strikes[i+1] - strikes[i] > 0]
    if not diffs: return None
    step    = Counter(diffs).most_common(1)[0][0]
    return step, strikes

# ─── Get OHLC for a strike at a given minute window ──────────────────────────
def get_ohlc(stock, date, strike, mode):
    """
    mode='entry' → 15:24–15:28 window (last ~5 minutes before close)
    mode='exit'  → 09:27–09:31 window (first ~5 minutes after open)
    Returns dict with open/high/low/close or None
    """
    if mode == 'entry':
        times = ["15:25:00","15:26:00","15:24:00","15:27:00","15:28:00","15:23:00"]
    else:
        times = ["09:29:00","09:28:00","09:30:00","09:27:00","09:31:00","09:26:00"]

    for t in times:
        cursor.execute(
            "SELECT open, high, low, close FROM scrapdata_options "
            "WHERE stock_code=%s AND datetime=%s AND strike_price=%s AND `right`='Put' LIMIT 1",
            (stock, f"{date} {t}", strike)
        )
        r = cursor.fetchone()
        if r and r['high'] and r['low']:
            return {k: float(v) for k, v in r.items() if v is not None}
    return None

# ─── Next trading day ─────────────────────────────────────────────────────────
def get_next_day(stock, date):
    cursor.execute(
        "SELECT MIN(DATE(datetime)) as nd FROM scrapdata_options WHERE stock_code=%s AND DATE(datetime)>%s",
        (stock, date)
    )
    r = cursor.fetchone()
    return str(r['nd']) if r and r['nd'] else None

# ─── Load targets ─────────────────────────────────────────────────────────────
df_list = []
for y in range(2024, 2027):
    try:
        df = pd.read_csv(f'experiment_targets_{y}.csv')
        df_list.append(df)
    except: pass

targets = pd.concat(df_list, ignore_index=True)
r1r3    = targets[(targets['rank_type'].isin(['R1','R3'])) & (targets['buy_price'] != 'UNKNOWN')].copy()
print(f"R1/R3 signals: {len(r1r3)}")

# ─── Main Simulation ─────────────────────────────────────────────────────────
results          = []
skipped_no_chain = 0
skipped_no_ohlc  = 0
completed        = 0

for _, row in r1r3.iterrows():
    stock = row['stock']
    date  = row['buy_date']
    price = float(row['buy_price'])

    exit_date  = get_next_day(stock, date)
    if not exit_date:
        skipped_no_chain += 1
        continue

    chain_info = get_real_step(stock, date)
    if not chain_info:
        skipped_no_chain += 1
        continue
    step, available_strikes = chain_info

    atm          = min(available_strikes, key=lambda x: abs(x - price))
    sell_target  = atm + step
    buy_target   = atm - (step * 3)
    sell_strike  = min(available_strikes, key=lambda x: abs(x - sell_target))
    buy_strike   = min(available_strikes, key=lambda x: abs(x - buy_target))

    if sell_strike <= buy_strike:
        skipped_no_chain += 1
        continue

    # Get OHLC for entry and exit candles
    entry_sell_ohlc = get_ohlc(stock, date,      sell_strike, 'entry')
    entry_buy_ohlc  = get_ohlc(stock, date,      buy_strike,  'entry')
    exit_sell_ohlc  = get_ohlc(stock, exit_date, sell_strike, 'exit')
    exit_buy_ohlc   = get_ohlc(stock, exit_date, buy_strike,  'exit')

    if None in [entry_sell_ohlc, entry_buy_ohlc, exit_sell_ohlc, exit_buy_ohlc]:
        skipped_no_ohlc += 1
        continue

    # ── WORST CASE prices ────────────────────────────────────────────────────
    # Entry: sell at LOW (less credit), buy at HIGH (more debit)
    entry_sell_px = entry_sell_ohlc['low']    # worst: minimum premium collected
    entry_buy_px  = entry_buy_ohlc['high']    # worst: maximum premium paid

    # Exit:  buy back at HIGH (most expensive), sell back at LOW (least received)
    exit_sell_px  = exit_sell_ohlc['high']    # worst: maximum to buy back
    exit_buy_px   = exit_buy_ohlc['low']      # worst: minimum received when closing

    entry_credit  = entry_sell_px - entry_buy_px   # should be positive (credit spread)
    exit_debit    = exit_sell_px  - exit_buy_px    # can be negative (gain) or positive (loss)

    lot_size      = get_lot_size(stock, date)
    spread        = sell_strike - buy_strike
    margin_per_lot = spread * lot_size
    if margin_per_lot <= 0: continue
    lots = min(int(400000 // margin_per_lot), 20)
    if lots < 1: lots = 1

    # Also compute realistic (close/open) for comparison
    real_entry_credit = entry_sell_ohlc.get('close', entry_sell_px) - entry_buy_ohlc.get('close', entry_buy_px)
    real_exit_debit   = exit_sell_ohlc.get('open',  exit_sell_px)  - exit_buy_ohlc.get('open',  exit_buy_px)
    real_pnl          = ((real_entry_credit - real_exit_debit) * lot_size * lots) - (400 * lots)

    worst_pnl = ((entry_credit - exit_debit) * lot_size * lots) - (400 * lots)

    completed += 1
    results.append({
        'month':        date[:7],
        'stock':        stock,
        'date':         date,
        'step':         step,
        'sell_strike':  sell_strike,
        'buy_strike':   buy_strike,
        'entry_credit': round(entry_credit, 2),
        'exit_debit':   round(exit_debit, 2),
        'lots':         lots,
        'worst_pnl':    round(worst_pnl, 2),
        'real_pnl':     round(real_pnl, 2),
        'win_worst':    worst_pnl > 0,
        'win_real':     real_pnl > 0,
    })

# ─── Report ───────────────────────────────────────────────────────────────────
print(f"\nCompleted: {completed}  |  Skipped (no chain): {skipped_no_chain}  |  Skipped (no OHLC): {skipped_no_ohlc}")

df = pd.DataFrame(results)
df.to_csv('worst_case_ohlc_results.csv', index=False)

worst_total   = df['worst_pnl'].sum()
real_total    = df['real_pnl'].sum()
worst_wr      = df['win_worst'].mean() * 100
real_wr       = df['win_real'].mean() * 100

monthly_w     = df.groupby('month')['worst_pnl'].sum().reset_index()
monthly_r     = df.groupby('month')['real_pnl'].sum().reset_index()
mwr_w         = (monthly_w['worst_pnl'] > 0).mean() * 100
mwr_r         = (monthly_r['real_pnl']  > 0).mean() * 100
avg_w         = monthly_w['worst_pnl'].mean()
avg_r         = monthly_r['real_pnl'].mean()
worst_month_w = monthly_w.loc[monthly_w['worst_pnl'].idxmin()]
worst_month_r = monthly_r.loc[monthly_r['real_pnl'].idxmin()]

print("\n" + "="*72)
print("  OHLC WORST-CASE STRESS TEST vs REALISTIC (Close/Open)")
print("="*72)
print(f"{'Metric':<30} {'WORST CASE':>18} {'REALISTIC':>18}")
print("-"*72)
print(f"{'Total PnL':<30} ₹{worst_total:>16,.2f} ₹{real_total:>16,.2f}")
print(f"{'Trade Win Rate':<30} {worst_wr:>17.1f}% {real_wr:>17.1f}%")
print(f"{'Monthly Win Rate':<30} {mwr_w:>17.1f}% {mwr_r:>17.1f}%")
print(f"{'Avg Monthly PnL':<30} ₹{avg_w:>16,.2f} ₹{avg_r:>16,.2f}")
wm_w = worst_month_w['worst_pnl']
wm_r = worst_month_r['real_pnl']
print(f"{'Worst Single Month':<30} ₹{wm_w:>16,.2f} ₹{wm_r:>16,.2f}")

print("="*72)

print("\n📅 Monthly PnL — Worst Case vs Realistic:")
print(f"{'Month':<10} {'WORST CASE':>14} {'REALISTIC':>14}")
print("-"*40)
for m in sorted(df['month'].unique()):
    w = monthly_w[monthly_w['month']==m]['worst_pnl'].values[0]
    r = monthly_r[monthly_r['month']==m]['real_pnl'].values[0]
    w_flag = "✅" if w > 0 else "❌"
    print(f"{m:<10} ₹{w:>10,.0f} {w_flag}  ₹{r:>10,.0f}")
