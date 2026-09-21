"""
STEP 1: Build Meta-Decision Dataset
=====================================
For every 09:20 scalp trade, at 09:40 we compute:
  - Current unrealized PnL
  - Price momentum since entry
  - Distance from stop loss
  - Whether the 09:42 model also flagged this stock
  - PnL if we EXIT at 09:40 (scalp)
  - PnL if we HOLD till 14:45 (with SL enforcement)
  - TARGET: 1 = Hold was better, 0 = Exit was better
"""

import os
import pymysql
import pandas as pd
from concurrent.futures import ThreadPoolExecutor

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)

def get_taxes(qty, sell_price, buy_price):
    turnover = (qty * sell_price) + (qty * buy_price)
    stt = round(qty * sell_price * 0.00025)
    txn = turnover * 0.0000322
    sebi = turnover * 0.000001
    stamp = round(qty * buy_price * 0.00003)
    gst = (40.0 + txn + sebi) * 0.18
    return round(40.0 + stt + txn + sebi + stamp + gst, 2)

def build_meta_row(args):
    row, pred_942_map = args
    d = str(row['Date'])[:10]
    s = str(row['Stock'])
    entry_price = float(row['Sell_Price'])
    qty = int(row['Qty'])
    sl_price = round(entry_price * 1.03, 2)
    original_prob = float(row.get('prob', 0.5))

    conn = pymysql.connect(host='localhost', user='root', password='root',
                           database='markets', cursorclass=pymysql.cursors.DictCursor)
    with conn.cursor() as cur:
        # Pull ticks from 09:40 to 14:50
        cur.execute(f"""SELECT time, price, high FROM scrapdata
                        WHERE date='{d}' AND stockname LIKE '%{s}%'
                        AND time>='{d} 09:40:00' AND time<='{d} 14:50:00'
                        ORDER BY time ASC""")
        ticks = cur.fetchall()
    conn.close()

    if not ticks:
        return None

    # ---- PRICE AT 09:40 (Exit scenario) ----
    price_0940 = float(ticks[0]['price'] or 0)
    if price_0940 <= 0:
        return None

    # ---- Features at 09:40 ----
    move_pct = ((entry_price - price_0940) / entry_price) * 100.0   # positive = stock fell = good for short
    unrealized_pnl = (entry_price - price_0940) * qty
    sl_distance_pct = ((sl_price - price_0940) / entry_price) * 100.0  # how close to SL
    
    # 09:42 model signal for this stock on this day
    key = (d, s.upper())
    pred_942 = pred_942_map.get(key, 0.0)
    has_942_signal = 1 if key in pred_942_map else 0

    # ---- PnL if EXIT at 09:40 ----
    exit_pnl_0940 = ((entry_price - price_0940) * qty) - get_taxes(qty, entry_price, price_0940)

    # ---- PnL if HOLD till 14:45 (simulate with SL from 09:40 onwards) ----
    hold_buy_price = None
    for t in ticks:
        t_time = str(t['time'])
        h = float(t['high'] or t['price'] or 0)
        if h >= sl_price:
            hold_buy_price = sl_price
            break
        if t_time >= f"{d} 14:45:00":
            hold_buy_price = float(t['price'] or 0)
            break
    if not hold_buy_price:
        hold_buy_price = float(ticks[-1]['price'] or 0)

    exit_pnl_1445 = ((entry_price - hold_buy_price) * qty) - get_taxes(qty, entry_price, hold_buy_price)

    # ---- TARGET: 1 = Hold was better, 0 = Exit at 09:40 was better ----
    target = 1 if exit_pnl_1445 > exit_pnl_0940 else 0

    return {
        'date': d,
        'stock': s,
        'entry_price': entry_price,
        'price_0940': price_0940,
        'qty': qty,
        'sl_price': sl_price,
        'move_pct': round(move_pct, 4),
        'unrealized_pnl': round(unrealized_pnl, 2),
        'sl_distance_pct': round(sl_distance_pct, 4),
        'pred_942': pred_942,
        'has_942_signal': has_942_signal,
        'original_prob': original_prob,
        'exit_pnl_0940': round(exit_pnl_0940, 2),
        'exit_pnl_1445': round(exit_pnl_1445, 2),
        'target': target
    }

print("1. Loading 09:20 verified trades...")
df_920 = pd.read_csv(os.path.join(ROOT_DIR, '01_0920_Scalp_Model/0920_verified_pnl_sheet.csv'))
df_920['Date'] = pd.to_datetime(df_920['Date']).dt.strftime('%Y-%m-%d')
print(f"   Total 09:20 trades: {len(df_920)}")

print("2. Loading 09:42 model predictions for signal mapping...")
df_942_preds = pd.read_csv(os.path.join(ROOT_DIR, '02_0942_Hybrid_Model/0942_predictions.csv'))
df_942_preds['clean_stock'] = df_942_preds['clean_stock'].astype(str).str.strip().str.upper()
pred_942_map = {(str(r['date_str'])[:10], r['clean_stock']): float(r['pred'])
                for _, r in df_942_preds.iterrows()}
print(f"   09:42 signals loaded: {len(pred_942_map)}")

# Also load original 09:20 probabilities
df_920_preds = pd.read_csv(os.path.join(ROOT_DIR, '01_0920_Scalp_Model/0920_predictions.csv'))
df_920_preds['clean_stock'] = df_920_preds['clean_stock'].astype(str).str.strip().str.upper()
prob_map = {(str(r['short_date'])[:10], r['clean_stock']): float(r['prob'])
            for _, r in df_920_preds.iterrows()}
df_920['Stock'] = df_920['Stock'].astype(str).str.strip().str.upper()
df_920['prob'] = df_920.apply(lambda r: prob_map.get((r['Date'], r['Stock']), 0.5), axis=1)

print("3. Building meta-decision dataset (querying DB for 09:40 prices)...")
args_list = [(row, pred_942_map) for _, row in df_920.iterrows()]

results = []
with ThreadPoolExecutor(max_workers=5) as ex:
    for i, res in enumerate(ex.map(build_meta_row, args_list)):
        if res:
            results.append(res)
        if (i + 1) % 200 == 0:
            print(f"   Processed {i+1}/{len(df_920)}...", flush=True)

meta_df = pd.DataFrame(results)
out_path = os.path.join(BASE_DIR, 'meta_dataset.csv')
meta_df.to_csv(out_path, index=False)
print(f"\n✅ Meta dataset built! {len(meta_df)} rows saved to {out_path}")
print(f"   Hold is better: {meta_df['target'].sum()} trades ({meta_df['target'].mean()*100:.1f}%)")
print(f"   Exit at 09:40 is better: {(1-meta_df['target']).sum()} trades ({(1-meta_df['target'].mean())*100:.1f}%)")
