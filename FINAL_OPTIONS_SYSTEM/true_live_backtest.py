"""
TRUE LIVE-STYLE BACKTEST
========================
Instead of using hardcoded naive step sizes, this script:
1. Queries actual available strikes from scrapdata_options per stock/date (like live does)
2. Infers real NSE step size from the chain
3. Selects +1 ITM / -3 OTM using the REAL step
4. Gets actual option prices and computes PnL

This gives the most accurate picture of what live trading will produce.
"""

import mysql.connector
import pandas as pd
from collections import Counter
from backtest_experiment import get_lot_size

# ─── DB Connection ────────────────────────────────────────────────────────────
db = mysql.connector.connect(host='localhost', user='root', password='root', database='markets')
cursor = db.cursor(dictionary=True)

# ─── Helper: Get real step size from DB for a stock on a date ─────────────────
def get_real_step(stock, date):
    cursor.execute(
        "SELECT DISTINCT strike_price FROM scrapdata_options "
        "WHERE stock_code=%s AND DATE(datetime)=%s AND `right`='Put' "
        "ORDER BY strike_price",
        (stock, date)
    )
    rows = cursor.fetchall()
    if len(rows) < 2:
        return None
    strikes = sorted([float(r['strike_price']) for r in rows])
    diffs = [round(strikes[i+1] - strikes[i], 2) for i in range(len(strikes)-1) if strikes[i+1] - strikes[i] > 0]
    if not diffs:
        return None
    step = Counter(diffs).most_common(1)[0][0]
    return step, strikes

# ─── Helper: Get option price ─────────────────────────────────────────────────
def get_price(stock, date, strike, mode):
    if mode == 'entry':
        times = ["15:26:00","15:25:00","15:27:00","15:24:00","15:28:00","15:23:00"]
        col = 'close'
    else:
        times = ["09:29:00","09:28:00","09:30:00","09:27:00","09:31:00","09:26:00"]
        col = 'open'
    for t in times:
        cursor.execute(
            f"SELECT {col} as px FROM scrapdata_options "
            f"WHERE stock_code=%s AND datetime=%s AND strike_price=%s AND `right`='Put' LIMIT 1",
            (stock, f"{date} {t}", strike)
        )
        r = cursor.fetchone()
        if r and r['px']:
            return float(r['px'])
    return None

# ─── Helper: Next trading day ─────────────────────────────────────────────────
def get_next_trading_day(stock, date):
    cursor.execute(
        "SELECT MIN(DATE(datetime)) as nd FROM scrapdata_options "
        "WHERE stock_code=%s AND DATE(datetime)>%s",
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
    except:
        pass

if not df_list:
    print("No experiment_targets_YYYY.csv files found!")
    exit(1)

targets = pd.concat(df_list, ignore_index=True)
r1r3 = targets[(targets['rank_type'].isin(['R1','R3'])) & (targets['buy_price'] != 'UNKNOWN')].copy()
print(f"Total R1/R3 signals to simulate: {len(r1r3)}")

# ─── Main Simulation ─────────────────────────────────────────────────────────
results = []
skipped_no_chain = 0
skipped_no_price = 0
completed = 0

for _, row in r1r3.iterrows():
    stock    = row['stock']
    date     = row['buy_date']
    price    = float(row['buy_price'])

    # 1. Get exit date
    exit_date = get_next_trading_day(stock, date)
    if not exit_date:
        skipped_no_chain += 1
        continue

    # 2. Get real step size from DB
    chain_info = get_real_step(stock, date)
    if not chain_info:
        skipped_no_chain += 1
        continue
    step, available_strikes = chain_info

    # 3. Find ATM (closest strike to buy price)
    atm = min(available_strikes, key=lambda x: abs(x - price))

    # 4. +1 ITM / -3 OTM using real step
    sell_target = atm + step        # +1 ITM
    buy_target  = atm - (step * 3)  # -3 OTM

    # 5. Find closest available strikes in chain
    sell_strike = min(available_strikes, key=lambda x: abs(x - sell_target))
    buy_strike  = min(available_strikes, key=lambda x: abs(x - buy_target))

    if sell_strike <= buy_strike:
        skipped_no_chain += 1
        continue

    # 6. Get option prices
    se = get_price(stock, date,      sell_strike, 'entry')
    be = get_price(stock, date,      buy_strike,  'entry')
    sx = get_price(stock, exit_date, sell_strike, 'exit')
    bx = get_price(stock, exit_date, buy_strike,  'exit')

    if None in [se, be, sx, bx]:
        skipped_no_price += 1
        continue

    # 7. Compute PnL
    lot_size = get_lot_size(stock, date)
    spread   = sell_strike - buy_strike
    margin_per_lot = spread * lot_size
    if margin_per_lot <= 0:
        continue
    lots = min(int(400000 // margin_per_lot), 20)
    if lots < 1:
        lots = 1

    credit = se - be
    debit  = sx - bx
    pnl    = ((credit - debit) * lot_size * lots) - (400 * lots)

    completed += 1
    results.append({
        'month':       date[:7],
        'stock':       stock,
        'date':        date,
        'atm':         atm,
        'step':        step,
        'sell_strike': sell_strike,
        'buy_strike':  buy_strike,
        'credit':      round(credit, 2),
        'debit':       round(debit, 2),
        'lots':        lots,
        'pnl':         round(pnl, 2),
        'win':         pnl > 0
    })

# ─── Report ───────────────────────────────────────────────────────────────────
print(f"\nCompleted: {completed} trades")
print(f"Skipped (no chain data): {skipped_no_chain}")
print(f"Skipped (no price data): {skipped_no_price}")

if not results:
    print("No trades completed — check DB data.")
    exit(0)

df_res = pd.DataFrame(results)
df_res.to_csv('true_live_backtest_results.csv', index=False)

total_pnl    = df_res['pnl'].sum()
win_rate     = df_res['win'].mean() * 100
avg_pnl      = df_res['pnl'].mean()
monthly      = df_res.groupby('month')['pnl'].sum().reset_index()
monthly_wr   = (monthly['pnl'] > 0).mean() * 100
avg_monthly  = monthly['pnl'].mean()
best_month   = monthly.loc[monthly['pnl'].idxmax()]
worst_month  = monthly.loc[monthly['pnl'].idxmin()]

print("\n" + "="*70)
print("  TRUE LIVE-STYLE BACKTEST — +1 ITM / -3 OTM (Real NSE Strikes)")
print("="*70)
print(f"  Total Trades Completed : {completed}")
print(f"  Total PnL              : ₹{total_pnl:>12,.2f}")
print(f"  Per-Trade Avg PnL      : ₹{avg_pnl:>12,.2f}")
print(f"  Trade Win Rate         : {win_rate:.1f}%")
print(f"  Monthly Win Rate       : {monthly_wr:.1f}%")
print(f"  Avg Monthly PnL        : ₹{avg_monthly:>12,.2f}")
print(f"  Best Month             : {best_month['month']}  ₹{best_month['pnl']:,.2f}")
print(f"  Worst Month            : {worst_month['month']}  ₹{worst_month['pnl']:,.2f}")
print("="*70)

print("\n📅 Monthly PnL Breakdown:")
print(f"{'Month':<10} {'PnL':>12} {'Win?':>6}")
print("-"*30)
for _, m in monthly.sort_values('month').iterrows():
    flag = "✅" if m['pnl'] > 0 else "❌"
    print(f"{m['month']:<10} ₹{m['pnl']:>10,.0f}  {flag}")
