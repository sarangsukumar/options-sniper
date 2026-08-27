"""
TICK SLIPPAGE STRESS TEST
=========================
Base prices are REALISTIC (Close for entry, Open for exit).
We apply a 2-tick (₹0.10) penalty against us on every single leg execution.

ENTRY:
  - Sell put (collect) → Close - ₹0.10 (receive less)
  - Buy put (pay)      → Close + ₹0.10 (pay more)

EXIT:
  - Buy back (pay)     → Open + ₹0.10 (pay more to close)
  - Sell back (collect)→ Open - ₹0.10 (receive less to close)

Total slippage per trade = 4 legs * 2 ticks = 8 ticks = ₹0.40 per spread.
"""

import mysql.connector
import pandas as pd
from collections import Counter
from backtest_experiment import get_lot_size

# ─── DB ──────────────────────────────────────────────────────────────────────
db     = mysql.connector.connect(host='localhost', user='root', password='root', database='markets')
cursor = db.cursor(dictionary=True)

TICK_SLIPPAGE = 0.10  # 2 ticks of 0.05

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

def get_price(stock, date, strike, mode):
    times = ["15:25:00","15:26:00","15:24:00","15:27:00","15:28:00","15:23:00"] if mode == 'entry' else ["09:29:00","09:28:00","09:30:00","09:27:00","09:31:00","09:26:00"]
    col = 'close' if mode == 'entry' else 'open'
    for t in times:
        cursor.execute(
            f"SELECT {col} FROM scrapdata_options WHERE stock_code=%s AND datetime=%s AND strike_price=%s AND `right`='Put' LIMIT 1",
            (stock, f"{date} {t}", strike)
        )
        r = cursor.fetchone()
        if r and r[col]: return float(r[col])
    return None

def get_next_day(stock, date):
    cursor.execute("SELECT MIN(DATE(datetime)) as nd FROM scrapdata_options WHERE stock_code=%s AND DATE(datetime)>%s", (stock, date))
    r = cursor.fetchone()
    return str(r['nd']) if r and r['nd'] else None

# Load
df_list = []
for y in range(2024, 2027):
    try:
        df_list.append(pd.read_csv(f'experiment_targets_{y}.csv'))
    except: pass

targets = pd.concat(df_list, ignore_index=True)
r1r3    = targets[(targets['rank_type'].isin(['R1','R3'])) & (targets['buy_price'] != 'UNKNOWN')]

results = []
for _, row in r1r3.iterrows():
    stock = row['stock']
    date  = row['buy_date']
    price = float(row['buy_price'])

    exit_date  = get_next_day(stock, date)
    if not exit_date: continue

    chain_info = get_real_step(stock, date)
    if not chain_info: continue
    step, available_strikes = chain_info

    atm          = min(available_strikes, key=lambda x: abs(x - price))
    sell_strike  = min(available_strikes, key=lambda x: abs(x - (atm + step)))
    buy_strike   = min(available_strikes, key=lambda x: abs(x - (atm - (step * 3))))

    if sell_strike <= buy_strike: continue

    entry_sell = get_price(stock, date,      sell_strike, 'entry')
    entry_buy  = get_price(stock, date,      buy_strike,  'entry')
    exit_sell  = get_price(stock, exit_date, sell_strike, 'exit')
    exit_buy   = get_price(stock, exit_date, buy_strike,  'exit')

    if None in [entry_sell, entry_buy, exit_sell, exit_buy]: continue

    # Realistic base execution
    base_entry_credit = entry_sell - entry_buy
    base_exit_debit   = exit_sell - exit_buy

    # 2 Ticks Slippage Execution
    slip_entry_sell = max(entry_sell - TICK_SLIPPAGE, 0.05) # Can't go below 0.05
    slip_entry_buy  = entry_buy + TICK_SLIPPAGE
    slip_exit_sell  = exit_sell + TICK_SLIPPAGE
    slip_exit_buy   = max(exit_buy - TICK_SLIPPAGE, 0.05)

    slip_entry_credit = slip_entry_sell - slip_entry_buy
    slip_exit_debit   = slip_exit_sell - slip_exit_buy

    lot_size = get_lot_size(stock, date)
    margin_per_lot = (sell_strike - buy_strike) * lot_size
    if margin_per_lot <= 0: continue
    lots = min(int(400000 // margin_per_lot), 20)
    if lots < 1: lots = 1

    real_pnl = ((base_entry_credit - base_exit_debit) * lot_size * lots) - (400 * lots)
    slip_pnl = ((slip_entry_credit - slip_exit_debit) * lot_size * lots) - (400 * lots)

    results.append({
        'date':     date,
        'stock':    stock,
        'month':    date[:7],
        'real_pnl': real_pnl,
        'slip_pnl': slip_pnl
    })

df = pd.DataFrame(results)
df.to_csv('tick_slippage_results.csv', index=False)

print("="*65)
print("  2-TICK SLIPPAGE STRESS TEST (Against Close/Open Prices)")
print("="*65)
print(f"Total Trades: {len(df)}")
print(f"REALISTIC PnL : ₹{df['real_pnl'].sum():,.2f}  (Win Rate: {(df['real_pnl']>0).mean()*100:.1f}%)")
print(f"SLIPPAGE PnL  : ₹{df['slip_pnl'].sum():,.2f}  (Win Rate: {(df['slip_pnl']>0).mean()*100:.1f}%)")
print("-"*65)

monthly = df.groupby('month').sum().reset_index()
print(f"{'Month':<10} {'REALISTIC PnL':>18} {'SLIPPAGE PnL':>18}")
print("-"*65)
for _, r in monthly.iterrows():
    print(f"{r['month']:<10} ₹{r['real_pnl']:>15,.0f}   ₹{r['slip_pnl']:>15,.0f}")
