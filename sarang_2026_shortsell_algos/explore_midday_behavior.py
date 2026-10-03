#!/usr/bin/env python3
"""
explore_midday_behavior.py
Deep dive into 11:30 AM trade status and subsequent afternoon trajectory.
"""
import os, sys, pymysql
import pandas as pd
import numpy as np
from concurrent.futures import ThreadPoolExecutor

BASE_DIR = '/home/ubuntu/sarang_2026_shortsell_algos'
M2_FILE = os.path.join(BASE_DIR, '02_Best_Longer_Window_0942_1445', 'audited_0940_hybrid_trades.csv')

def get_db():
    return pymysql.connect(host='localhost', user='root', password='root', database='markets', autocommit=True)

def analyze_trade(trade):
    d = trade['date']
    s = trade['stockname']
    qty = int(trade['total_quantity'])
    lots = int(trade['lots_to_trade'])
    yr = int(d[:4])
    
    conn = get_db()
    cur = conn.cursor(pymysql.cursors.DictCursor)
    
    # Near-month Futures F1
    cur.execute(f"""
    SELECT time, price 
    FROM scrapdata_F1 
    WHERE date = '{d}' AND stockname IN ('{s}', '\"{s}\"', '{s} ') 
      AND time >= '{d} 09:42:00' AND time <= '{d} 14:45:59' 
    ORDER BY time ASC
    """)
    ticks_f1 = cur.fetchall()
    conn.close()
    
    res = {'date': d, 'stockname': s, 'year': yr, 'qty': qty, 'lots': lots}
    
    if ticks_f1:
        prices = [float(t['price']) for t in ticks_f1 if t['price'] is not None]
        times = [str(t['time']) for t in ticks_f1 if t['price'] is not None]
        
        if len(prices) >= 10:
            en = prices[0]
            sl3 = round(en * 1.03, 2)
            
            # Divide into Morning (<= 11:30) and Afternoon (> 11:30)
            m_prices = [p for t, p in zip(times, prices) if t <= f"{d} 11:30:59"]
            m_times = [t for t, p in zip(times, prices) if t <= f"{d} 11:30:59"]
            
            # Checkpoints
            p_1030 = en
            p_1100 = en
            p_1130 = m_prices[-1] if m_prices else en
            
            for t, p in zip(m_times, m_prices):
                if t <= f"{d} 10:30:59":
                    p_1030 = p
                if t <= f"{d} 11:00:59":
                    p_1100 = p
            
            # Baseline exit with 3% SL
            ex_base = prices[-1]
            sl_hit_base = False
            sl_time_base = ""
            for t, p in zip(times, prices):
                if p >= sl3:
                    ex_base = sl3
                    sl_hit_base = True
                    sl_time_base = t
                    break
            
            # SL hit before 11:30?
            sl_hit_morning = (sl_hit_base and sl_time_base <= f"{d} 11:30:59")
            
            # Morning stats
            loss_pct_1130 = ((p_1130 - en) / en) * 100.0  # Positive means in LOSS for short
            time_in_loss_pct = (sum(1 for p in m_prices if p > en) / len(m_prices)) * 100.0
            max_morning_price = max(m_prices)
            max_morning_loss_pct = ((max_morning_price - en) / en) * 100.0
            
            # Structural uptrend: 11:30 > 11:00 > 10:30 > entry
            is_uptrend = bool(p_1130 > p_1100 > p_1030 > en)
            
            # Near morning high (within 0.3% of morning high)
            at_morning_high = bool((p_1130 >= max_morning_price * 0.997) and (p_1130 > en))
            
            # Persistent loss (spent > 85% of morning in loss)
            persistent_loss = bool((time_in_loss_pct >= 85.0) and (p_1130 > en))
            always_in_loss = bool(time_in_loss_pct >= 99.0)
            
            # Subsequent afternoon performance (11:30 to end)
            # Recovery = ex_base < en
            recovered_to_profit = bool(ex_base < en)
            further_loss = bool(ex_base > p_1130)  # exit price higher than 11:30 price
            
            res.update({
                'f1_en': en,
                'f1_p_1030': p_1030,
                'f1_p_1100': p_1100,
                'f1_p_1130': p_1130,
                'f1_ex_base': ex_base,
                'f1_sl_hit_base': sl_hit_base,
                'f1_sl_hit_morning': sl_hit_morning,
                'f1_loss_pct_1130': loss_pct_1130,
                'f1_time_in_loss_pct': time_in_loss_pct,
                'f1_max_loss_pct_morning': max_morning_loss_pct,
                'f1_is_uptrend': is_uptrend,
                'f1_at_morning_high': at_morning_high,
                'f1_persistent_loss': persistent_loss,
                'f1_always_in_loss': always_in_loss,
                'f1_recovered_to_profit': recovered_to_profit,
                'f1_further_loss': further_loss,
                'f1_gross_base': (en - ex_base) * qty,
                'f1_gross_exit_1130': (en - p_1130) * qty,
                'f1_save_by_cut': (ex_base - p_1130) * qty
            })
            
    return res

def main():
    df = pd.read_csv(M2_FILE)
    df = df[df['status'] == 'COMPLETED'].copy()
    trades = df.to_dict('records')
    print(f"Analyzing {len(trades):,} trades...")
    
    with ThreadPoolExecutor(max_workers=24) as ex:
        results = list(ex.map(analyze_trade, trades))
        
    rdf = pd.DataFrame(results)
    rdf = rdf[rdf['f1_en'].notna()].copy()
    print(f"Valid F1 trades analyzed: {len(rdf):,}")
    
    # Filter out trades that already hit 3% SL before 11:30
    active_at_1130 = rdf[rdf['f1_sl_hit_morning'] == False].copy()
    print(f"Trades still open at 11:30 AM (didn't hit 3% SL early): {len(active_at_1130):,}")
    
    # 1. DISTRIBUTION OF LOSS AT 11:30 AM
    in_loss = active_at_1130[active_at_1130['f1_loss_pct_1130'] > 0].copy()
    print(f"\nTrades in LOSS at 11:30 AM: {len(in_loss):,} ({len(in_loss)/len(active_at_1130)*100:.1f}%)")
    
    # Group by Loss Bucket at 11:30
    bins = [0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 100.0]
    labels = ['0.0 - 0.5%', '0.5 - 1.0%', '1.0 - 1.5%', '1.5 - 2.0%', '2.0 - 2.5%', '2.5 - 3.0%', '> 3.0%']
    in_loss['bucket'] = pd.cut(in_loss['f1_loss_pct_1130'], bins=bins, labels=labels)
    
    print("\n" + "=" * 115)
    print(f"{'Loss Bucket @ 11:30':<18} | {'Count':<6} | {'Recover %':<10} | {'Further Loss %':<15} | {'Base Gross (L)':<15} | {'Cut Gross (L)':<15} | {'Delta Saved (L)':<15}")
    print("=" * 115)
    
    for b in labels:
        sub = in_loss[in_loss['bucket'] == b]
        if len(sub) == 0:
            continue
        rec_pct = sub['f1_recovered_to_profit'].mean() * 100
        fur_pct = sub['f1_further_loss'].mean() * 100
        base_g = sub['f1_gross_base'].sum() / 1e5
        cut_g = sub['f1_gross_exit_1130'].sum() / 1e5
        saved = (cut_g - base_g)
        print(f"{b:<18} | {len(sub):<6} | {rec_pct:>8.1f}% | {fur_pct:>13.1f}% | {base_g:>13.2f} L | {cut_g:>13.2f} L | {saved:>+13.2f} L")
    print("=" * 115)
    
    # 2. EVALUATING STRUCTURAL FILTERS AT 11:30 AM
    print("\n" + "=" * 115)
    print("🔬 TESTING CANDIDATE MIDDAY LOSS-CONTROL CRITERIA (CUT AT 11:30 AM)")
    print("=" * 115)
    
    rules = [
        ("1. Cut ALL trades in loss at 11:30", active_at_1130['f1_loss_pct_1130'] > 0),
        ("2. Loss in 11:00 & 11:30 (User original)", (active_at_1130['f1_p_1100'] > active_at_1130['f1_en']) & (active_at_1130['f1_loss_pct_1130'] > 0)),
        ("3. Severe Loss >= 1.5%", active_at_1130['f1_loss_pct_1130'] >= 1.5),
        ("4. Severe Loss >= 1.8%", active_at_1130['f1_loss_pct_1130'] >= 1.8),
        ("5. Severe Loss >= 2.0%", active_at_1130['f1_loss_pct_1130'] >= 2.0),
        ("6. Severe Loss >= 2.2%", active_at_1130['f1_loss_pct_1130'] >= 2.2),
        ("7. Severe Loss >= 2.5%", active_at_1130['f1_loss_pct_1130'] >= 2.5),
        ("8. Uptrend (P1130 > P1100 > P1030 > En)", active_at_1130['f1_is_uptrend']),
        ("9. Uptrend AND Loss >= 0.8%", active_at_1130['f1_is_uptrend'] & (active_at_1130['f1_loss_pct_1130'] >= 0.8)),
        ("10. Uptrend AND Loss >= 1.0%", active_at_1130['f1_is_uptrend'] & (active_at_1130['f1_loss_pct_1130'] >= 1.0)),
        ("11. Uptrend AND Loss >= 1.2%", active_at_1130['f1_is_uptrend'] & (active_at_1130['f1_loss_pct_1130'] >= 1.2)),
        ("12. Persistent Loss (>85% morning in loss)", active_at_1130['f1_persistent_loss']),
        ("13. Always in Loss (100% morning in loss)", active_at_1130['f1_always_in_loss']),
        ("14. Always in Loss AND Loss >= 1.0%", active_at_1130['f1_always_in_loss'] & (active_at_1130['f1_loss_pct_1130'] >= 1.0)),
        ("15. Always in Loss AND Loss >= 1.5%", active_at_1130['f1_always_in_loss'] & (active_at_1130['f1_loss_pct_1130'] >= 1.5)),
        ("16. At Morning High AND Loss >= 1.0%", active_at_1130['f1_at_morning_high'] & (active_at_1130['f1_loss_pct_1130'] >= 1.0)),
        ("17. At Morning High AND Loss >= 1.5%", active_at_1130['f1_at_morning_high'] & (active_at_1130['f1_loss_pct_1130'] >= 1.5)),
        ("18. Hybrid A: Loss >= 2.0% OR (Uptrend & Loss >= 1.0%)", 
         (active_at_1130['f1_loss_pct_1130'] >= 2.0) | (active_at_1130['f1_is_uptrend'] & (active_at_1130['f1_loss_pct_1130'] >= 1.0))),
        ("19. Hybrid B: Loss >= 1.8% OR (Uptrend & Loss >= 1.2%)", 
         (active_at_1130['f1_loss_pct_1130'] >= 1.8) | (active_at_1130['f1_is_uptrend'] & (active_at_1130['f1_loss_pct_1130'] >= 1.2))),
        ("20. Hybrid C: Loss >= 2.0% OR (Always In Loss & Loss >= 1.2%)", 
         (active_at_1130['f1_loss_pct_1130'] >= 2.0) | (active_at_1130['f1_always_in_loss'] & (active_at_1130['f1_loss_pct_1130'] >= 1.2))),
    ]
    
    print(f"{'Rule Name':<45} | {'Trades Cut':<11} | {'Recov %':<8} | {'Base Gross':<12} | {'Cut Gross':<12} | {'Saved (₹)':<12} | {'Portfolio Impact'}")
    print("-" * 125)
    
    total_base_portfolio = rdf['f1_gross_base'].sum()
    
    for name, mask in rules:
        sub = active_at_1130[mask]
        cnt = len(sub)
        if cnt == 0:
            continue
        rec = sub['f1_recovered_to_profit'].mean() * 100
        bg = sub['f1_gross_base'].sum()
        cg = sub['f1_gross_exit_1130'].sum()
        delta = cg - bg
        
        pct_chg = (delta / total_base_portfolio) * 100
        
        print(f"{name:<45} | {cnt:>5} ({cnt/len(active_at_1130)*100:>4.1f}%) | {rec:>6.1f}% | Rs {bg/1e5:>7.2f} L | Rs {cg/1e5:>7.2f} L | {delta/1e5:>+7.2f} L    | {delta/1e5:>+6.2f} L ({pct_chg:>+4.2f}%)")
    print("=" * 125)

if __name__ == '__main__':
    main()
