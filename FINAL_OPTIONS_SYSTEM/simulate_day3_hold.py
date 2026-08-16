import mysql.connector
import pandas as pd
import numpy as np
from backtest_experiment import get_lot_size

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
    return strikes[2], strikes[4]

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
        "WHERE stock_code=%s AND DATE(datetime) > %s ORDER BY d ASC LIMIT 6",
        (stock, start_date)
    )
    rows = cursor.fetchall()
    return [str(r['d']) for r in rows]

def run_day3_analysis():
    df_list = []
    for y in [2024, 2025, 2026]:
        try:
            df = pd.read_csv(f'experiment_targets_{y}.csv')
            df['target_year'] = y
            df_list.append(df)
        except: pass
    targets = pd.concat(df_list)
    r1_r3 = targets[(targets['rank_type'].isin(['R1','R3'])) & (targets['buy_price'] != 'UNKNOWN')].copy()

    day3_results = []

    for _, row in r1_r3.iterrows():
        stock = row['stock']
        buy_date = row['buy_date']
        price = float(row['buy_price'])
        y = row['target_year']
        expiry_str = str(row['expiry_date']).split('T')[0]
        
        future_dates = get_trading_days(cursor, stock, buy_date)
        if len(future_dates) < 3: continue
        
        day1_exit = future_dates[0]
        day2_exit = future_dates[1]
        day3_exit = future_dates[2]
        
        # Anti-expiry check
        can_hold_d2 = True
        can_hold_d3 = True
        if expiry_str and expiry_str != 'None':
            if day2_exit > expiry_str or day1_exit >= expiry_str:
                can_hold_d2 = False
                can_hold_d3 = False
            if day3_date := day3_exit:
                if day3_date > expiry_str:
                    can_hold_d3 = False
                    
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
        comm = 300 * lots * 2
        pnl1 = ((credit - debit1) * lot_size * lots) - comm
        
        # Day 2 Exit
        sx2 = get_price(cursor, stock, day2_exit, sell_strike, 'exit') if can_hold_d2 else None
        bx2 = get_price(cursor, stock, day2_exit, buy_strike, 'exit') if can_hold_d2 else None
        if can_hold_d2 and (not (None in [sx2, bx2])):
            debit2 = sx2 - bx2
            pnl2 = ((credit - debit2) * lot_size * lots) - comm
        else:
            pnl2 = pnl1
            
        # Day 3 Exit
        sx3 = get_price(cursor, stock, day3_exit, sell_strike, 'exit') if can_hold_d3 else None
        bx3 = get_price(cursor, stock, day3_exit, buy_strike, 'exit') if can_hold_d3 else None
        if can_hold_d3 and (not (None in [sx3, bx3])):
            debit3 = sx3 - bx3
            pnl3 = ((credit - debit3) * lot_size * lots) - comm
        else:
            pnl3 = pnl2
            
        day3_results.append({
            'year': y, 'stock': stock, 'buy_date': buy_date,
            'pnl1': pnl1, 'pnl2': pnl2, 'pnl3': pnl3,
            'can_hold_d2': can_hold_d2, 'can_hold_d3': can_hold_d3,
            'd1_loss': pnl1 < 0,
            'd2_still_loss': (pnl1 < 0 and pnl2 < 0)
        })

    df = pd.DataFrame(day3_results)
    
    # Analyze trades that were STILL IN LOSS on Day 2: What happened on Day 3?
    d2_losses = df[df['d2_still_loss'] == True].copy()
    
    print("\n" + "="*95)
    print("=== EXPERIMENT 2: DAY 3 HOLD ANALYSIS (TRADES STILL LOSING ON DAY 2) ===")
    print("="*95)
    print(f"Total Trades Evaluated: {len(df)}")
    print(f"Trades that were in Loss on Day 1: {len(df[df['d1_loss']==True])}")
    print(f"Trades that were STILL IN LOSS on Day 2: {len(d2_losses)}")
    
    # Day 3 behavior on those Day 2 losses
    rev_to_win = sum(d2_losses['pnl3'] > 0)
    improved = sum(d2_losses['pnl3'] > d2_losses['pnl2'])
    worse = sum(d2_losses['pnl3'] < d2_losses['pnl2'])
    same = sum(d2_losses['pnl3'] == d2_losses['pnl2'])
    
    sum_pnl2 = d2_losses['pnl2'].sum()
    sum_pnl3 = d2_losses['pnl3'].sum()
    net_d3_diff = sum_pnl3 - sum_pnl2
    
    print(f"\nOf the {len(d2_losses)} trades that remained in loss on Day 2:")
    print(f"1. Fully Reversed to WIN on Day 3:       {rev_to_win} ({rev_to_win/len(d2_losses)*100:.1f}%)")
    print(f"2. Improved PnL / Reduced Loss on Day 3: {improved} ({improved/len(d2_losses)*100:.1f}%)")
    print(f"3. Deepened / Worse Loss on Day 3:       {worse} ({worse/len(d2_losses)*100:.1f}%)")
    print(f"4. Total PnL if exited Day 2: ₹{sum_pnl2:,.2f}")
    print(f"5. Total PnL if exited Day 3: ₹{sum_pnl3:,.2f}")
    print(f"6. Net Financial Impact of Holding to Day 3: {'+₹' if net_d3_diff>=0 else '-₹'}{abs(net_d3_diff):,.2f}")
    print("="*95)

if __name__ == '__main__':
    run_day3_analysis()
