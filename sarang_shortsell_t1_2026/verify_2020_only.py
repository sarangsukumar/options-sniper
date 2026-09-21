import os
import pymysql
import pandas as pd
from concurrent.futures import ThreadPoolExecutor

BASE_0920 = '/home/ubuntu/sarang_shortsell_t1_2026/01_0920_Scalp_Model'
BASE_0942 = '/home/ubuntu/sarang_shortsell_t1_2026/02_0942_Hybrid_Model'

def get_taxes(qty, sell_price, buy_price):
    turnover = (qty * sell_price) + (qty * buy_price)
    stt = round(qty * sell_price * 0.00025)
    txn = turnover * 0.0000322
    sebi = turnover * 0.000001
    stamp = round(qty * buy_price * 0.00003)
    gst = (40.0 + txn + sebi) * 0.18
    return round(40.0 + stt + txn + sebi + stamp + gst, 2)

def audit_0920(row):
    d, s = row['short_date'], row['clean_stock']
    conn = pymysql.connect(host='localhost', user='root', password='root', database='markets', cursorclass=pymysql.cursors.DictCursor)
    with conn.cursor() as cur:
        cur.execute(f"SELECT time, price, high FROM scrapdata WHERE date='{d}' AND stockname LIKE '%{s}%' AND time>='{d} 09:22:00' AND time<='{d} 09:45:00' ORDER BY time ASC")
        ticks = cur.fetchall()
    conn.close()
    if not ticks: return None
    sell_price = float(ticks[0]['price'] or 0)
    sell_time = str(ticks[0]['time'])
    if sell_price <= 0 or sell_time > f"{d} 09:25:59": return None
    qty = int(1000000.0 / sell_price)
    sl_price = round(sell_price * 1.03, 2)
    buy_price, buy_time = None, None
    for t in ticks:
        t_time = str(t['time'])
        h = float(t['high'] or t['price'] or 0)
        if h >= sl_price:
            buy_price, buy_time = sl_price, t_time; break
        if t_time >= f"{d} 09:40:00":
            buy_price, buy_time = float(t['price'] or 0), t_time; break
    if not buy_price:
        buy_price, buy_time = float(ticks[-1]['price'] or 0), str(ticks[-1]['time'])
    if buy_time > f"{d} 09:43:59": return None
    net_pnl = ((sell_price - buy_price) * qty) - get_taxes(qty, sell_price, buy_price)
    return {'Date': d, 'Stock': s, 'Sell_Time': sell_time, 'Sell_Price': sell_price,
            'Buy_Time': buy_time, 'Buy_Price': buy_price, 'Qty': qty,
            'Margin_Req': 1000000, 'Commission': get_taxes(qty, sell_price, buy_price), 'Net_PnL': net_pnl}

def audit_0942(row):
    d, s = row['date_str'], row['clean_stock']
    conn = pymysql.connect(host='localhost', user='root', password='root', database='markets', cursorclass=pymysql.cursors.DictCursor)
    with conn.cursor() as cur:
        cur.execute(f"SELECT time, price, high FROM scrapdata WHERE date='{d}' AND stockname LIKE '%{s}%' AND time>='{d} 09:42:00' AND time<='{d} 14:50:00' ORDER BY time ASC")
        ticks = cur.fetchall()
    conn.close()
    if not ticks: return None
    sell_price = float(ticks[0]['price'] or 0)
    sell_time = str(ticks[0]['time'])
    if sell_price <= 0 or sell_time > f"{d} 09:45:59": return None
    qty = int(1000000.0 / sell_price)
    sl_price = round(sell_price * 1.03, 2)
    buy_price, buy_time = None, None
    for t in ticks:
        t_time = str(t['time'])
        h = float(t['high'] or t['price'] or 0)
        if h >= sl_price:
            buy_price, buy_time = sl_price, t_time; break
        if t_time >= f"{d} 14:45:00":
            buy_price, buy_time = float(t['price'] or 0), t_time; break
    if not buy_price:
        buy_price, buy_time = float(ticks[-1]['price'] or 0), str(ticks[-1]['time'])
    if buy_time > f"{d} 14:48:59": return None
    net_pnl = ((sell_price - buy_price) * qty) - get_taxes(qty, sell_price, buy_price)
    return {'Date': d, 'Stock': s, 'Sell_Time': sell_time, 'Sell_Price': sell_price,
            'Buy_Time': buy_time, 'Buy_Price': buy_price, 'Qty': qty,
            'Margin_Req': 1000000, 'Commission': get_taxes(qty, sell_price, buy_price), 'Net_PnL': net_pnl}

# --- 09:20 MODEL: Only 2020 trades ---
print("=== 09:20 Scalp Model — Verifying 2020 Only ===")
preds_920 = pd.read_csv(os.path.join(BASE_0920, '0920_predictions.csv'))
preds_920_2020 = preds_920[pd.to_datetime(preds_920['short_date']).dt.year == 2020]
print(f"2020 trades to verify: {len(preds_920_2020)}")

results_920 = []
with ThreadPoolExecutor(max_workers=5) as ex:
    for res in ex.map(audit_0920, [row for _, row in preds_920_2020.iterrows()]):
        if res: results_920.append(res)

new_920 = pd.DataFrame(results_920)
existing_920 = pd.read_csv(os.path.join(BASE_0920, '0920_verified_pnl_sheet.csv'))
combined_920 = pd.concat([new_920, existing_920]).sort_values('Date').reset_index(drop=True)
combined_920.to_csv(os.path.join(BASE_0920, '0920_verified_pnl_sheet.csv'), index=False)

combined_920['year'] = pd.to_datetime(combined_920['Date']).dt.year
print(f"\n--- 09:20 Scalp Model (2020 + All Years) ---")
for y, g in combined_920.groupby('year'):
    wins = (g['Net_PnL'] > 0).sum()
    print(f"{y}: Rs {g['Net_PnL'].sum()/100000:.2f} Lakhs | {wins/len(g)*100:.2f}% Win Rate ({wins}/{len(g)})")
print(f"TOTAL: Rs {combined_920['Net_PnL'].sum()/1e7:.2f} Crores")

# --- 09:42 MODEL: Only 2020 trades ---
print("\n=== 09:42 Hybrid Model — Verifying 2020 Only ===")
preds_942 = pd.read_csv(os.path.join(BASE_0942, '0942_predictions.csv'))
preds_942_2020 = preds_942[pd.to_datetime(preds_942['date_str']).dt.year == 2020]
print(f"2020 trades to verify: {len(preds_942_2020)}")

results_942 = []
with ThreadPoolExecutor(max_workers=5) as ex:
    for res in ex.map(audit_0942, [row for _, row in preds_942_2020.iterrows()]):
        if res: results_942.append(res)

new_942 = pd.DataFrame(results_942)
existing_942 = pd.read_csv(os.path.join(BASE_0942, '0942_verified_pnl_sheet.csv'))
combined_942 = pd.concat([new_942, existing_942]).sort_values('Date').reset_index(drop=True)
combined_942.to_csv(os.path.join(BASE_0942, '0942_verified_pnl_sheet.csv'), index=False)

combined_942['year'] = pd.to_datetime(combined_942['Date']).dt.year
print(f"\n--- 09:42 Hybrid Model (2020 + All Years) ---")
for y, g in combined_942.groupby('year'):
    wins = (g['Net_PnL'] > 0).sum()
    print(f"{y}: Rs {g['Net_PnL'].sum()/100000:.2f} Lakhs | {wins/len(g)*100:.2f}% Win Rate ({wins}/{len(g)})")
print(f"TOTAL: Rs {combined_942['Net_PnL'].sum()/1e7:.2f} Crores")
