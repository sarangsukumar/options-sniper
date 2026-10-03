import pandas as pd
import numpy as np
import pymysql
import time
import os
from datetime import datetime, timedelta
from concurrent.futures import ProcessPoolExecutor, as_completed

# --- Config ---
DB_CONFIG = {'host':'localhost', 'user':'root', 'password':'root', 'database':'markets'}
PROX_SECONDS = 180

def get_db():
    return pymysql.connect(**DB_CONFIG, cursorclass=pymysql.cursors.DictCursor, connect_timeout=10)

def sim_one_trade_ablation(trade, active_rules):
    # active_rules is a dict: {'R2':True, 'R3':True, 'R4':True, 'R5':True}
    d = trade['date']
    s = trade['stockname']
    
    conn = get_db()
    cur = conn.cursor()
    
    # We only care about Equity Cash for the ablation comparison (it's representative)
    # Get 09:42 entry price
    cur.execute(f"SELECT price FROM scrapdata WHERE date='{d}' AND stockname='{s}' AND time>='{d} 09:39:00' AND time<='{d} 09:45:00' ORDER BY ABS(TIMESTAMPDIFF(SECOND, time, '{d} 09:42:00')) LIMIT 1")
    r = cur.fetchone()
    if not r:
        conn.close()
        return None
    en_cash = r['price']
    
    # Get pre-entry high
    cur.execute(f"SELECT MAX(high) as pre_hi FROM scrapdata WHERE date='{d}' AND stockname='{s}' AND time>='{d} 09:15:00' AND time<'{d} 09:42:00' AND price BETWEEN {en_cash*0.85} AND {en_cash*1.15}")
    pre_hi = cur.fetchone()['pre_hi']
    if pre_hi is None: pre_hi = en_cash
    
    # Get ticks
    cur.execute(f"SELECT time, price, high, low, close FROM scrapdata WHERE date='{d}' AND stockname='{s}' AND time>='{d} 09:42:00' AND time<='{d} 14:45:59' AND price BETWEEN {en_cash*0.85} AND {en_cash*1.15} ORDER BY time ASC")
    ticks = cur.fetchall()
    conn.close()
    
    if not ticks: return None
    
    ex_price = ticks[-1]['close'] if ticks[-1]['close'] else ticks[-1]['price']
    ex_reason = '1445_TIME_EXIT'
    
    max_hi_since = -9999
    min_low_since = 99999
    sl = en_cash * 1.035
    trail_active = False
    trail_sl = -1
    
    for t in ticks:
        tm = t['time']
        ph = t['high']
        pl = t['low']
        
        if ph > max_hi_since: max_hi_since = ph
        if pl < min_low_since: min_low_since = pl
        
        # Rule 5 check (Trail)
        if active_rules.get('R5', True):
            if min_low_since <= en_cash * 0.98:
                trail_active = True
                prop_sl = min_low_since * 1.02
                if prop_sl < trail_sl or trail_sl == -1:
                    trail_sl = prop_sl
                    
        # Rule 5 Exit
        if trail_active and ph >= trail_sl:
            ex_price = trail_sl
            ex_reason = 'TRAIL_STOP'
            break
            
        # Rule 2 Exit
        if active_rules.get('R2', True) and ph >= sl:
            ex_price = sl
            ex_reason = 'STOP_LOSS_3.5PCT'
            break
            
        # Rule 3 Exit (10:30)
        if active_rules.get('R3', True) and tm >= datetime(tm.year, tm.month, tm.day, 10, 30):
            loss_pct = (ph - en_cash) / en_cash * 100
            if max_hi_since > pre_hi and loss_pct >= 1.0:
                ex_price = max(en_cash * 1.01, t['price']) # Approx fill
                ex_reason = 'RULE3_CUT_1030'
                break
                
        # Rule 4 Exit (11:00 / 11:30)
        if active_rules.get('R4', True):
            if tm >= datetime(tm.year, tm.month, tm.day, 11, 0):
                loss_pct = (ph - en_cash) / en_cash * 100
                if loss_pct >= 2.0:
                    ex_price = max(en_cash * 1.02, t['price'])
                    ex_reason = 'RULE4A_CUT_1100'
                    break
            if tm >= datetime(tm.year, tm.month, tm.day, 11, 30):
                loss_pct = (ph - en_cash) / en_cash * 100
                if loss_pct >= 2.2:
                    ex_price = max(en_cash * 1.022, t['price'])
                    ex_reason = 'RULE4B_CUT_1130'
                    break
                    
        if tm.hour == 14 and tm.minute >= 45:
            ex_price = t['close'] if t['close'] else t['price']
            ex_reason = '1445_TIME_EXIT'
            break
            
    # Calculate PNL
    qty = trade['qty']
    gross = (en_cash - ex_price) * qty
    chg = (en_cash + ex_price) * qty * 0.0003 + 50
    net = gross - chg
    return net

def process_chunk(chunk, active_rules):
    results = []
    for _, tr in chunk.iterrows():
        net = sim_one_trade_ablation(tr, active_rules)
        if net is not None:
            results.append(net)
    return results

def run_scenario(df, name, active_rules):
    print(f"Running scenario: {name}")
    t0 = time.time()
    chunks = np.array_split(df, 16)
    all_nets = []
    with ProcessPoolExecutor(max_workers=16) as exe:
        futs = {exe.submit(process_chunk, c, active_rules): i for i, c in enumerate(chunks)}
        for fut in as_completed(futs):
            all_nets.extend(fut.result())
            
    nets = np.array(all_nets)
    tot_net = nets.sum() / 1e5
    wr = (nets > 0).mean() * 100
    pos = nets[nets > 0].sum()
    neg = abs(nets[nets < 0].sum())
    pf = pos / neg if neg > 0 else float('inf')
    avg = nets.mean()
    print(f"  → {name}: Net +Rs {tot_net:.2f}L | WR {wr:.1f}% | PF {pf:.2f} | Time: {time.time()-t0:.1f}s")
    return {'Name': name, 'Net_L': tot_net, 'WR': wr, 'PF': pf, 'Avg': avg}

if __name__ == '__main__':
    # Load the EXACT 4,805 trades from the clean ledger to isolate EXIT rules
    df = pd.read_csv('/home/ubuntu/sarang_2026_shortsell_algos/rebuild_model2_strict_db_ledger.csv')
    print(f"Loaded {len(df)} base trades for Exit Rule Ablation...")
    
    scenarios = [
        ("Baseline (All 5 Rules)", {'R2':True, 'R3':True, 'R4':True, 'R5':True}),
        ("No Rule 2 (Hard SL OFF)", {'R2':False, 'R3':True, 'R4':True, 'R5':True}),
        ("No Rule 3 (10:30 Cut OFF)", {'R2':True, 'R3':False, 'R4':True, 'R5':True}),
        ("No Rule 4 (Midday Cut OFF)", {'R2':True, 'R3':True, 'R4':False, 'R5':True}),
        ("No Rule 5 (Trailing Stop OFF)", {'R2':True, 'R3':True, 'R4':True, 'R5':False}),
        ("Hold To Close (All Exit Rules OFF)", {'R2':False, 'R3':False, 'R4':False, 'R5':False}),
    ]
    
    results = []
    for name, rules in scenarios:
        res = run_scenario(df, name, rules)
        results.append(res)
        
    print("\n" + "="*80)
    print("ABLATION STUDY RESULTS (Equity Cash)")
    print("="*80)
    base_net = results[0]['Net_L']
    
    print(f"{'Configuration':<35} | {'Net Profit':<12} | {'Value Added':<12} | {'Win Rate':<8} | {'PF':<5}")
    print("-" * 80)
    for r in results:
        net = r['Net_L']
        val_added = base_net - net if r['Name'] != 'Baseline (All 5 Rules)' else 0
        val_str = f"+{val_added:.2f} L" if val_added > 0 else f"{val_added:.2f} L"
        if r['Name'] == 'Baseline (All 5 Rules)': val_str = "-"
        print(f"{r['Name']:<35} | Rs {net:>7.2f} L | {val_str:>12} | {r['WR']:>5.1f}%   | {r['PF']:.2f}")
    
    print("\nNote: Rule 1 (Entry Filter) changes the base trade selection. Evaluating it requires a full rebuild. Above tests strictly isolate exit rules on the verified 4,805 base trades.")

