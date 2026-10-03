import pandas as pd
import pymysql

print("================================================================================")
print(" MICROSCOPIC TRADE-BY-TRADE RULE DEEP DIVE (Zero Assumptions)")
print("================================================================================\n")

df = pd.read_csv('/home/ubuntu/sarang_2026_shortsell_algos/rebuild_model2_strict_db_ledger.csv')

# Exclude normal time exits
early_exits = df[df['cash_exit_reason'] != '1445_TIME_EXIT']

print(f"Total Early Exit Trades to Analyze: {len(early_exits)} (out of {len(df)} total trades)\n")

conn = pymysql.connect(host='localhost', user='root', password='root', database='markets', cursorclass=pymysql.cursors.DictCursor)
cur = conn.cursor()

results = {}

for _, row in early_exits.iterrows():
    rule = row['cash_exit_reason']
    if rule not in results:
        results[rule] = {'saved_count': 0, 'saved_val': 0.0, 'cost_count': 0, 'cost_val': 0.0, 'missing_db': 0}
        
    d = row['date']
    s = row['stockname']
    en = row['cash_entry']
    ex = row['cash_exit']
    qty = row['qty']
    
    # 1. Actual profit realized by the early exit rule
    actual_gross = (en - ex) * qty
    
    # 2. Query exact DB tick at 14:45 to see what WOULD have happened
    cur.execute(f"SELECT close, price FROM scrapdata WHERE date='{d}' AND stockname='{s}' AND time<='{d} 14:45:59' ORDER BY time DESC LIMIT 1")
    res = cur.fetchone()
    
    if not res:
        results[rule]['missing_db'] += 1
        continue
        
    hold_price = res['close'] if res['close'] else res['price']
    hold_gross = (en - hold_price) * qty
    
    # 3. Difference (Positive = Rule Saved Profit, Negative = Rule Cost Profit)
    diff = actual_gross - hold_gross
    
    if diff > 0:
        results[rule]['saved_count'] += 1
        results[rule]['saved_val'] += diff
    elif diff < 0:
        results[rule]['cost_count'] += 1
        results[rule]['cost_val'] += diff

# Print Report
for rule, stats in sorted(results.items()):
    saved_lakhs = stats['saved_val'] / 100000
    cost_lakhs = stats['cost_val'] / 100000
    net_lakhs = saved_lakhs + cost_lakhs
    
    print(f"--- {rule} ---")
    print(f"  Trades where rule SAVED profit: {stats['saved_count']:>4}  (+₹ {saved_lakhs:>7.2f} L)")
    print(f"  Trades where rule COST profit:  {stats['cost_count']:>4}  (-₹ {abs(cost_lakhs):>7.2f} L)")
    if stats['missing_db'] > 0:
        print(f"  (Skipped {stats['missing_db']} trades due to missing 14:45 DB tick)")
        
    status = "👑 NET POSITIVE (KEEPER)" if net_lakhs > 0 else "❌ NET NEGATIVE (HURTING)"
    print(f"  NET TRUE IMPACT:                {net_lakhs:>7.2f} L  --> {status}\n")

conn.close()
print("================================================================================")
print(" DEEP DIVE COMPLETE")
print("================================================================================")
