import mysql.connector
import pandas as pd
import numpy as np
from backtest_experiment import get_lot_size

# Connect to database
db = mysql.connector.connect(host='localhost', user='root', password='root', database='markets')
cursor = db.cursor(dictionary=True)

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
    strikes = [atm + step*i for i in range(2, -7, -1)]
    return strikes[1], strikes[5]  # +1 ITM sell, -3 OTM buy (WIDE SPREAD)

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

def get_trading_days(cursor, stock, start_date):
    cursor.execute(
        "SELECT DISTINCT DATE(datetime) as d FROM scrapdata_options "
        "WHERE stock_code=%s AND DATE(datetime) > %s ORDER BY d ASC LIMIT 5",
        (stock, start_date)
    )
    rows = cursor.fetchall()
    return [str(r['d']) for r in rows]

# Load targets
df_list = []
for y in [2024, 2025, 2026]:
    try:
        df = pd.read_csv(f'experiment_targets_{y}.csv')
        df['target_year'] = y
        df_list.append(df)
    except: pass
targets = pd.concat(df_list)
r1_r3 = targets[(targets['rank_type'].isin(['R1','R3'])) & (targets['buy_price'] != 'UNKNOWN')].copy()

trade_records = []

for _, row in r1_r3.iterrows():
    stock = row['stock']
    buy_date = row['buy_date']
    price = float(row['buy_price'])
    y = row['target_year']
    expiry_str = str(row['expiry_date']).split('T')[0]
    
    future_dates = get_trading_days(cursor, stock, buy_date)
    if len(future_dates) < 2: continue
    
    day1_exit = future_dates[0]
    day2_exit = future_dates[1]
    
    # Anti-expiry rule
    can_hold_d2 = True
    if expiry_str and expiry_str != 'None':
        if day2_exit > expiry_str or day1_exit >= expiry_str:
            can_hold_d2 = False
            
    sell_strike, buy_strike = generate_strikes(price)
    lot_size = get_lot_size(stock, buy_date)
    margin = (sell_strike - buy_strike) * lot_size
    lots = min(int(400000 // margin), 20) if margin > 0 else 0
    if lots == 0: continue
    
    se = get_price(cursor, stock, buy_date, sell_strike, 'entry')
    be = get_price(cursor, stock, buy_date, buy_strike, 'entry')
    sx1 = get_price(cursor, stock, day1_exit, sell_strike, 'exit')
    bx1 = get_price(cursor, stock, day1_exit, buy_strike, 'exit')
    
    if None in [se, be, sx1, bx1]: continue
    
    credit = se - be
    debit1 = sx1 - bx1
    comm = 200 * lots * 2  # ₹200/lot/leg = ₹400/lot round-trip (₹90 statutory + ₹310 slippage)
    pnl1 = ((credit - debit1) * lot_size * lots) - comm
    pnl1_per_lot = pnl1 / lots
    
    # Check if Day 2 hold is triggered: Loss worse than ₹3,000 / lot on safe non-expiry day
    hold_triggered = (pnl1_per_lot <= -1000) and can_hold_d2
    
    if hold_triggered:
        sx2 = get_price(cursor, stock, day2_exit, sell_strike, 'exit')
        bx2 = get_price(cursor, stock, day2_exit, buy_strike, 'exit')
        if not (None in [sx2, bx2]):
            debit2 = sx2 - bx2
            final_pnl = ((credit - debit2) * lot_size * lots) - comm
            exit_day = "Day 2"
        else:
            final_pnl = pnl1
            exit_day = "Day 1 (fallback)"
    else:
        final_pnl = pnl1
        exit_day = "Day 1"
        
    trade_records.append({
        'year': y, 'stock': stock, 'buy_date': buy_date,
        'day1_pnl': pnl1, 'final_pnl': final_pnl,
        'exit_day': exit_day, 'lots': lots,
        'margin_used': margin * lots
    })

df_perf = pd.DataFrame(trade_records)

# --- Compute Institutional Performance Metrics ---
total_trades = len(df_perf)
pnls = df_perf['final_pnl'].values

winning_trades = pnls[pnls > 0]
losing_trades = pnls[pnls < 0]
scratch_trades = pnls[pnls == 0]

win_count = len(winning_trades)
loss_count = len(losing_trades)
scratch_count = len(scratch_trades)

win_rate = (win_count / total_trades) * 100
loss_rate = (loss_count / total_trades) * 100

total_profit = winning_trades.sum()
total_loss = abs(losing_trades.sum())
net_pnl = pnls.sum()

profit_factor = (total_profit / total_loss) if total_loss > 0 else np.inf
avg_trade = pnls.mean()
avg_win = winning_trades.mean() if win_count > 0 else 0
avg_loss = losing_trades.mean() if loss_count > 0 else 0
win_loss_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else np.inf

# Drawdown Calculation
cumulative = np.cumsum(pnls)
running_max = np.maximum.accumulate(cumulative)
drawdowns = running_max - cumulative
max_drawdown = drawdowns.max()

# Expectancy per Trade
expectancy = (win_rate/100 * avg_win) + (loss_rate/100 * avg_loss)

# Sharpe & Calmar Ratios (Assuming 252 trading days/year)
std_dev = pnls.std()
sharpe_trade = (avg_trade / std_dev) if std_dev > 0 else 0
annualized_sharpe = sharpe_trade * np.sqrt(100) # Approx 100 trades/year
calmar_ratio = (net_pnl / max_drawdown) if max_drawdown > 0 else np.inf

# Capital ROI
initial_capital = 400000.0
total_capital = initial_capital + net_pnl
roi = (net_pnl / initial_capital) * 100

print("\n" + "="*80)
print("=== INSTITUTIONAL TEARSHEET: FINAL PRODUCTION STRATEGY ===")
print("=== (R1+R3, +1 ITM / -3 OTM WIDE SPREAD, Max 20 Lots, Per-Lot Day 2 Hold Optimization) ===")
print("="*80)
print(f"Total Completed Trades:         {total_trades}")
print(f"Winning Trades:                 {win_count} ({win_rate:.2f}%)")
print(f"Losing Trades:                  {loss_count} ({loss_rate:.2f}%)")
print(f"Scratch Trades:                 {scratch_count} ({(scratch_count/total_trades)*100:.2f}%)")
print("-" * 80)
print(f"Total Gross Profits:            ₹{total_profit:,.2f}")
print(f"Total Gross Losses:             ₹-{total_loss:,.2f}")
print(f"NET PRODUCTION PNL:             ₹{net_pnl:,.2f} (~₹{net_pnl/100000:.2f} Lakhs)")
print("-" * 80)
print(f"Profit Factor:                  {profit_factor:.2f}")
print(f"Average Trade Return:           ₹{avg_trade:,.2f}")
print(f"Average Winning Trade:          ₹{avg_win:,.2f}")
print(f"Average Losing Trade:           ₹{avg_loss:,.2f}")
print(f"Win/Loss Payoff Ratio:          {win_loss_ratio:.2f} : 1")
print(f"Mathematical Expectancy:        ₹{expectancy:,.2f} per trade")
print("-" * 80)
print(f"Max Portfolio Drawdown (₹):     ₹{max_drawdown:,.2f}")
print(f"Calmar Ratio (Return / DD):     {calmar_ratio:.2f}")
print(f"Annualized Sharpe Ratio:        {annualized_sharpe:.2f}")
print("-" * 80)
print(f"Initial Margin Allocation:      ₹{initial_capital:,.2f}")
print(f"Total Accumulated Capital:      ₹{total_capital:,.2f} (~₹{total_capital/100000:.2f} Lakhs)")
print(f"Total Return on Capital (ROI):  +{roi:,.2f}% ({total_capital/initial_capital:.2f}x Growth)")
print("=" * 80)

# Year-by-year tearsheet
print("\n" + "="*80)
print("=== YEAR-BY-YEAR PERFORMANCE BREAKDOWN ===")
print("="*80)
print(f"{'Year':<6} | {'Trades':<8} | {'Win Rate':<10} | {'Net PnL (₹)':<16} | {'Max Drawdown (₹)':<18} | {'Profit Factor':<14}")
print("-" * 80)

for y in [2024, 2025, 2026]:
    df_y = df_perf[df_perf['year'] == y]
    if len(df_y) == 0: continue
    y_pnls = df_y['final_pnl'].values
    y_wins = y_pnls[y_pnls > 0]
    y_losses = y_pnls[y_pnls < 0]
    y_wr = (len(y_wins) / len(y_pnls)) * 100
    y_net = y_pnls.sum()
    y_pf = (y_wins.sum() / abs(y_losses.sum())) if len(y_losses) > 0 and y_losses.sum() != 0 else np.inf
    
    y_cum = np.cumsum(y_pnls)
    y_max = np.maximum.accumulate(y_cum)
    y_dd = (y_max - y_cum).max()
    
    print(f"{y:<6} | {len(df_y):<8} | {y_wr:5.2f}%     | ₹{y_net:>13,.2f} | ₹{y_dd:>15,.2f} | {y_pf:>10.2f}")

print("="*80)

# Multi-timeframe Win Rate Calculation
df_perf['buy_date'] = pd.to_datetime(df_perf['buy_date'])
df_perf['day'] = df_perf['buy_date'].dt.strftime('%Y-%m-%d')
df_perf['week'] = df_perf['buy_date'].dt.strftime('%Y-W%U')
df_perf['month'] = df_perf['buy_date'].dt.strftime('%Y-%m')
df_perf['quarter'] = df_perf['buy_date'].dt.to_period('Q').astype(str)

def get_tf_stats(df, col_group):
    grp = df.groupby(col_group)['final_pnl'].sum().reset_index()
    tot = len(grp)
    wins = (grp['final_pnl'] > 0).sum()
    losses = (grp['final_pnl'] < 0).sum()
    wr = (wins / tot) * 100 if tot > 0 else 0
    return tot, wins, losses, wr

d_tot, d_w, d_l, d_wr = get_tf_stats(df_perf, 'day')
w_tot, w_w, w_l, w_wr = get_tf_stats(df_perf, 'week')
m_tot, m_w, m_l, m_wr = get_tf_stats(df_perf, 'month')
q_tot, q_w, q_l, q_wr = get_tf_stats(df_perf, 'quarter')

print("\n" + "="*80)
print("=== MULTI-TIMEFRAME WIN RATE SUMMARY ===")
print("="*80)
print(f"1. PER TRADE WIN RATE:   {win_rate:5.2f}% ({win_count} Wins / {loss_count} Losses out of {total_trades} Trades)")
print(f"2. DAILY WIN RATE:       {d_wr:5.2f}% ({d_w} Win Days / {d_l} Loss Days out of {d_tot} Trading Days)")
print(f"3. WEEKLY WIN RATE:      {w_wr:5.2f}% ({w_w} Win Weeks / {w_l} Loss Weeks out of {w_tot} Trading Weeks)")
print(f"4. MONTHLY WIN RATE:     {m_wr:5.2f}% ({m_w} Win Months / {m_l} Loss Months out of {m_tot} Months)")
print(f"5. QUARTERLY WIN RATE:   {q_wr:5.2f}% ({q_w} Win Quarters / {q_l} Loss Quarters out of {q_tot} Quarters)")
print("="*80)

cursor.close()
db.close()

