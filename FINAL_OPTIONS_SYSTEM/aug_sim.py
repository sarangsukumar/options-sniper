import mysql.connector
import pandas as pd

# --- Inline helpers (no backtest_experiment import) ---
def get_strike_step(price):
    if price > 2500: return 50
    if price > 1000: return 20
    if price > 500:  return 10
    if price > 100:  return 5
    if price > 50:   return 2.5
    return 1

def generate_strikes(buy_price):
    step = get_strike_step(buy_price)
    atm = round(buy_price / step) * step
    return [atm + step*i for i in range(2, -7, -1)]  # descending

def get_price(cursor, stock, date, strike, mode):
    if mode == 'entry':
        times = ["15:26:00","15:25:00","15:27:00","15:24:00","15:28:00",
                 "09:56:00","09:55:00","09:57:00","09:54:00","09:58:00"]
        col = 'close'
    else:
        times = ["09:29:00","09:28:00","09:30:00","09:27:00","09:31:00",
                 "03:59:00","03:58:00","04:00:00","03:57:00","04:01:00"]
        col = 'open'
    for t in times:
        cursor.execute(
            f"SELECT {col} as px FROM scrapdata_options "
            f"WHERE stock_code=%s AND DATE(datetime)=%s AND TIME(datetime)=%s "
            f"AND strike_price=%s AND `right`='Put' LIMIT 1",
            (stock, date, t, strike)
        )
        r = cursor.fetchone()
        if r and r['px'] and float(r['px']) > 0:
            return float(r['px'])
    return None

LOT_SIZES = {
    'MUTHOOTFIN':275,'GRASIM':250,'GODREJCP':500,'LTF':2250,
    'POWERGRID':3200,'TRENT':175,'MUTHOOTFIN':275,'SHREECEM':25,
    'MANAPPURAM':2000,'BAJFINANCE':125
}
def get_lot_size(stock):
    return LOT_SIZES.get(stock, 500)

# --- Main ---
db = mysql.connector.connect(host='localhost',user='root',password='root',database='markets')
cursor = db.cursor(dictionary=True)

targets = pd.read_csv('experiment_targets_2026.csv')
aug = targets[
    targets['rank_type'].isin(['R1','R3']) &
    (targets['buy_price'] != 'UNKNOWN') &
    targets['buy_date'].str.startswith('2026-08')
].copy()

print(f"{'Date':<12} {'Stock':<14} {'Sell':>6} {'Buy':>6} {'Lots':>5} {'PnL':>12} Status")
print('='*65)

total = 0.0
for _, row in aug.iterrows():
    stock     = row['stock']
    buy_date  = row['buy_date']
    sell_date = row['sell_date']
    price     = float(row['buy_price'])

    strikes    = generate_strikes(price)
    sell_strike = strikes[2]
    buy_strike  = strikes[4]
    lot_size   = get_lot_size(stock)
    margin     = (sell_strike - buy_strike) * lot_size
    lots       = min(int(400000 // margin), 20) if margin > 0 else 0

    se = get_price(cursor, stock, buy_date,  sell_strike, 'entry')
    be = get_price(cursor, stock, buy_date,  buy_strike,  'entry')
    sx = get_price(cursor, stock, sell_date, sell_strike, 'exit')
    bx = get_price(cursor, stock, sell_date, buy_strike,  'exit')

    if None in [se, be, sx, bx]:
        pnl, status = 0.0, "SKIP"
    else:
        gross = ((se - be) - (sx - bx)) * lot_size * lots
        pnl   = gross - (300 * lots * 2)
        status = "WIN" if pnl > 0 else "LOSS"

    total += pnl
    print(f"{buy_date:<12} {stock:<14} {sell_strike:>6.0f} {buy_strike:>6.0f} {lots:>5} {pnl:>12,.2f} {status}")

print('='*65)
print(f"{'AUGUST 2026 TOTAL':<40} {total:>12,.2f}")
cursor.close()
db.close()
