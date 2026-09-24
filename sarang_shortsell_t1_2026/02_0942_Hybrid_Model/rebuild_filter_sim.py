import pandas as pd
import pymysql
import time

def get_db_connection():
    return pymysql.connect(host="localhost", user="root", password="root", database="markets", cursorclass=pymysql.cursors.DictCursor)

def get_taxes(qty, sell_price, buy_price):
    turnover = (qty * sell_price) + (qty * buy_price)
    stt = round(qty * sell_price * 0.00025)
    txn = turnover * 0.0000322
    sebi = turnover * 0.000001
    stamp = round(qty * buy_price * 0.00003)
    gst = (40.0 + txn + sebi) * 0.18
    return round(40.0 + stt + txn + sebi + stamp + gst, 2)

print("1. Loading Predictions & Dataset...")
preds = pd.read_csv('/home/ubuntu/sarang_shortsell_t1_2026/02_0942_Hybrid_Model/0942_predictions.csv')
df = pd.read_csv('/home/ubuntu/sarang_shortsell_t1_2026/02_0942_Hybrid_Model/data/short_sell_ml_dataset_v5_scratch.csv', low_memory=False)

df['clean_stock'] = df['clean_stock'].astype(str).str.strip().str.upper()
preds['clean_stock'] = preds['clean_stock'].astype(str).str.strip().str.upper()

# Merge to get prices for filter
merged = preds.merge(df[['date_str', 'clean_stock', 'prev_close', 'short_entry_price']], on=['date_str', 'clean_stock'], how='inner')
merged = merged.drop_duplicates(subset=['date_str', 'clean_stock'])

# Calculate % change
merged['pct_change'] = (merged['short_entry_price'] - merged['prev_close']) / merged['prev_close'] * 100

print(f"Total original predictions pool: {len(merged)}")

results_summary = []

for filter_threshold in [-1.0, -0.5]:
    print(f"\n========================================================")
    print(f"🚀 REBUILDING TOP 4 WITH FILTER: >= {filter_threshold}%")
    print(f"========================================================")
    
    # Apply filter FIRST
    filtered = merged[merged['pct_change'] >= filter_threshold].copy()
    
    # NOW rank and take top 4 (This ensures replacements are picked)
    filtered = filtered.sort_values(['date_str', 'pred'], ascending=[True, False])
    top4 = filtered.groupby('date_str').head(4).reset_index(drop=True)
    
    print(f"Total trades after replacements: {len(top4)}")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    gross_pnl = 0.0
    net_pnl = 0.0
    total_taxes = 0.0
    is_pnl = 0.0
    oos_pnl = 0.0
    
    start_time = time.time()
    
    for i, row in top4.iterrows():
        if i > 0 and i % 1000 == 0:
            print(f"  Processed {i} trades... elapsed: {time.time()-start_time:.1f}s")
        
        d = row['date_str']
        s = row['clean_stock']
        yr = int(d.split('-')[0])
        
        q = f"SELECT time, price, high FROM scrapdata WHERE date='{d}' AND stockname = '{s}' AND time>='{d} 09:42:00' AND time<='{d} 14:50:00' ORDER BY time ASC"
        cursor.execute(q)
        ticks = cursor.fetchall()
        
        if not ticks: continue
        
        sell_price = float(ticks[0]['price'] or 0)
        if sell_price <= 0: continue
        
        # Original baseline used 10L capital
        qty = int(1000000.0 / sell_price)
        if qty <= 0: continue
        
        sl_price = round(sell_price * 1.03, 2)
        
        buy_price = None
        for t in ticks:
            t_time = str(t['time'])
            h = float(t['high'] or t['price'] or 0)
            p = float(t['price'] or 0)
            
            if h >= sl_price:
                buy_price = sl_price
                break
            if t_time >= f"{d} 14:45:00":
                buy_price = p
                break
                
        if buy_price is None:
            buy_price = float(ticks[-1]['price'] or 0)
            
        g = (sell_price - buy_price) * qty
        t_tax = get_taxes(qty, sell_price, buy_price)
        n = g - t_tax
        
        if yr <= 2025:
            is_pnl += n
        elif yr == 2026:
            oos_pnl += n
            
    conn.close()
    
    print(f"🎯 RESULTS FOR FILTER >= {filter_threshold}%")
    print(f"   In-Sample (2020-2025) : ₹{is_pnl:,.2f}")
    print(f"   Out-Of-Sample (2026)  : ₹{oos_pnl:,.2f}")
    
    results_summary.append({'filter': filter_threshold, 'IS': is_pnl, 'OOS': oos_pnl})

print("\n📋 FINAL COMPARISON VS BASELINE")
print(f"Baseline IS : ₹8,469,482.47")
print(f"Baseline OOS: ₹300,642.41")
for r in results_summary:
    print(f"Filter >= {r['filter']}% -> IS: ₹{r['IS']:,.2f} | OOS: ₹{r['OOS']:,.2f}")

