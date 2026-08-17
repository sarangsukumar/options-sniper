import mysql.connector
import pandas as pd
from datetime import datetime, timedelta

def get_trading_days(cursor):
    cursor.execute("SELECT DISTINCT DATE(datetime) as dt FROM scrapdata_options ORDER BY dt")
    return [r['dt'] for r in cursor.fetchall()]

def get_next_trading_day(trading_days, current_date):
    for d in trading_days:
        if d > current_date:
            return d
    return None

def get_price(cursor, stock, date, strike, call_put='PE', time_type='entry'):
    if time_type == 'entry':
        time_str = '15:20:00'
    else:
        time_str = '09:25:00'
    
    dt_str = f"{date} {time_str}"
    cursor.execute("""
        SELECT close FROM scrapdata_options 
        WHERE stock_code=%s AND datetime=%s AND strike_price=%s AND `right`='Put'
        ORDER BY expiry_date ASC LIMIT 1
    """, (stock, dt_str, strike))
    res = cursor.fetchone()
    if res:
        return float(res['close']), None
    return None, None

def simulate_reversal():
    db = mysql.connector.connect(host='localhost', user='root', password='root', database='markets')
    cursor = db.cursor(dictionary=True)
    trading_days = get_trading_days(cursor)
    
    all_dfs = []
    for y in [2024, 2025, 2026]:
        try:
            df = pd.read_csv(f'experiment_targets_{y}.csv')
            all_dfs.append(df)
        except Exception as e:
            pass
            
    targets = pd.concat(all_dfs)
    targets = targets[targets['rank_type'].isin(['R1', 'R3']) & (targets['buy_price'] != 'UNKNOWN')]
    
    reversals_triggered = 0
    reversal_wins = 0
    reversal_losses = 0
    total_reversal_pnl = 0
    
    comm_per_lot = 400 # realistic cost per lot
    margin_cap = 400000
    
    print("Running Stop-and-Reverse (SAR) Threshold Optimizer...")
    print("Primary: Wide Bull Put. Reversal: Narrow Bear Put on Day 1 loss.")
    print("-" * 100)
    
    # Pre-calculate all day1 primary pnl and reversal pnl to loop thresholds quickly
    trades_data = []
    
    for _, row in targets.iterrows():
        stock = row['stock']
        buy_date = datetime.strptime(str(row['buy_date']), '%Y-%m-%d').date()
        buy_price = float(row['buy_price'])
        
        day1_exit = get_next_trading_day(trading_days, buy_date)
        day2_exit = get_next_trading_day(trading_days, day1_exit) if day1_exit else None
        
        if not day1_exit or not day2_exit: continue
        
        cursor.execute("SELECT DISTINCT strike_price FROM scrapdata_options WHERE stock_code=%s AND DATE(datetime)=%s ORDER BY strike_price DESC", (stock, buy_date))
        strikes = sorted([float(r['strike_price']) for r in cursor.fetchall()], reverse=True)
        if not strikes: continue
        
        atm_strike = min(strikes, key=lambda x: abs(x - buy_price))
        try:
            atm_idx = strikes.index(atm_strike)
            sell_strike = strikes[atm_idx - 1] # +1 ITM
            buy_strike = strikes[atm_idx + 3]  # -3 OTM Wide
        except IndexError:
            continue
            
        se, _ = get_price(cursor, stock, buy_date, sell_strike, 'PE', 'entry')
        be, _ = get_price(cursor, stock, buy_date, buy_strike, 'PE', 'entry')
        sx1, _ = get_price(cursor, stock, day1_exit, sell_strike, 'PE', 'exit')
        bx1, _ = get_price(cursor, stock, day1_exit, buy_strike, 'PE', 'exit')
        
        if None in [se, be, sx1, bx1]: continue
            
        lot_size = 500
        gap = sell_strike - buy_strike
        if gap <= 0: continue
        lots = int(margin_cap // (gap * lot_size))
        if lots < 1: lots = 1
        if lots > 20: lots = 20
        
        credit = se - be
        debit1 = sx1 - bx1
        primary_pnl = ((credit - debit1) * lot_size * lots) - (comm_per_lot * lots)
        primary_pnl_per_lot = primary_pnl / lots
        
        if primary_pnl < 0:
            d1_stock_price = buy_strike 
            rev_atm_strike = buy_strike
            try:
                rev_atm_idx = strikes.index(rev_atm_strike)
                rev_buy_strike = rev_atm_strike
                rev_sell_strike = strikes[rev_atm_idx + 2] 
            except IndexError:
                continue
                
            rev_be, _ = get_price(cursor, stock, day1_exit, rev_buy_strike, 'PE', 'exit')
            rev_se, _ = get_price(cursor, stock, day1_exit, rev_sell_strike, 'PE', 'exit')
            rev_bx2, _ = get_price(cursor, stock, day2_exit, rev_buy_strike, 'PE', 'exit')
            rev_sx2, _ = get_price(cursor, stock, day2_exit, rev_sell_strike, 'PE', 'exit')
            
            if None in [rev_be, rev_se, rev_bx2, rev_sx2]: continue
            
            rev_debit_entry = rev_be - rev_se
            rev_credit_exit = rev_bx2 - rev_sx2
            
            rev_gap = rev_buy_strike - rev_sell_strike
            rev_lots = int(margin_cap // (rev_gap * lot_size))
            if rev_lots < 1: rev_lots = 1
            if rev_lots > 20: rev_lots = 20
            
            rev_pnl = ((rev_credit_exit - rev_debit_entry) * lot_size * rev_lots) - (comm_per_lot * rev_lots)
            trades_data.append({'pnl_per_lot': primary_pnl_per_lot, 'rev_pnl': rev_pnl})
            
    print(f"{'Per-Lot Loss Threshold':<25} | {'Triggers':<8} | {'Rev Wins':<10} | {'Win Rate':<10} | {'Total Rev PnL':<15}")
    print("-" * 100)
    
    thresholds = [0, -500, -1000, -1500, -2000, -2500, -3000, -4000, -5000, -7500]
    for th in thresholds:
        triggers = 0
        wins = 0
        losses = 0
        tot_pnl = 0
        for td in trades_data:
            if td['pnl_per_lot'] < th:
                triggers += 1
                tot_pnl += td['rev_pnl']
                if td['rev_pnl'] > 0:
                    wins += 1
                else:
                    losses += 1
        
        wr = (wins / (wins + losses) * 100) if triggers > 0 else 0
        th_label = f"Loss > ₹{-th}/lot" if th < 0 else "Any Loss"
        print(f"{th_label:<25} | {triggers:<8} | {wins:<10} | {wr:>6.1f}%    | ₹{tot_pnl:,.2f}")

    db.close()

if __name__ == "__main__":
    simulate_reversal()
