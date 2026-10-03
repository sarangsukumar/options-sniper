import os, pymysql
import pandas as pd
import lightgbm as lgb
from concurrent.futures import ThreadPoolExecutor

def get_kotak_mis_charges(qty, sell_price, buy_price):
    sell_value = qty * sell_price
    buy_value = qty * buy_price
    turnover = sell_value + buy_value
    stt = round(sell_value * 0.00025)
    txn = turnover * 0.0000322
    sebi = turnover * 0.000001
    stamp = round(buy_value * 0.00003)
    gst = (txn + sebi) * 0.18
    return round(stt + txn + sebi + stamp + gst, 2)

def process_trade_0920(row):
    d = row['date_str']
    s = row['clean_stock']
    base_capital = 100000.0
    leveraged_capital = base_capital * 5.0
    
    conn = pymysql.connect(host='localhost', user='root', password='root', database='markets', cursorclass=pymysql.cursors.DictCursor)
    try:
        with conn.cursor() as cur:
            # STRICT ENTRY AT OR AFTER 09:20:00
            cur.execute(f"SELECT time, price, close FROM scrapdata WHERE date = '{d}' AND stockname LIKE '%{s}%' AND time >= '{d} 09:20:00' ORDER BY time ASC LIMIT 1")
            entry_tick = cur.fetchone()
            
            if not entry_tick or not float(entry_tick['price'] or entry_tick['close'] or 0) > 0:
                return None
                
            en = float(entry_tick['price'] or entry_tick['close'])
            en_time = entry_tick['time']
            qty = int(leveraged_capital // en)
            
            # SCAN FOR SL/TP
            cur.execute(f"SELECT time, price, high, low, close FROM scrapdata WHERE date = '{d}' AND stockname LIKE '%{s}%' AND time >= '{en_time}' AND time <= '{d} 09:40:59' ORDER BY time ASC")
            ticks = cur.fetchall()
            
            sl = round(en * 1.03, 2)
            tp = round(en * 0.95, 2)
            hit, ex, ex_time, reason = False, None, None, ""
            
            for t in ticks:
                high_val = float(t['high'] or t['price'] or 0)
                low_val = float(t['low'] or t['price'] or 0)
                if high_val >= sl:
                    hit, ex, ex_time, reason = True, sl, t['time'], "StopLoss 3%"
                    break
                if low_val <= tp:
                    hit, ex, ex_time, reason = True, tp, t['time'], "TakeProfit 5%"
                    break
                    
            if not hit:
                # STRICT EXIT AT OR AFTER 09:40:00
                cur.execute(f"SELECT time, price, close FROM scrapdata WHERE date = '{d}' AND stockname LIKE '%{s}%' AND time >= '{d} 09:40:00' ORDER BY time ASC LIMIT 1")
                exit_tick = cur.fetchone()
                if not exit_tick:
                    return None
                ex = float(exit_tick['close'] or exit_tick['price'])
                ex_time = exit_tick['time']
                reason = "Time Exit 09:40"
                
            gross = (en - ex) * qty
            taxes = get_kotak_mis_charges(qty, en, ex)
            net = round(gross - taxes, 2)
            
            return {
                'Date': d,
                'Stock': s,
                'Buy_Time': en_time,
                'Buy_Price': en,
                'SquareOff_Time': ex_time,
                'SquareOff_Price': ex,
                'Quantity': qty,
                'Reason': reason,
                'Net_Rs_PnL': net
            }
    finally:
        conn.close()

def main():
    print("1. Loading look-ahead-free features for 09:20 Model...")
    df = pd.read_csv('/home/ubuntu/v5_from_scratch/data/master_dual_timeline_dataset.csv', low_memory=False)
    features = ['Gap_Pct', 'gap_0907_pct', 'prev_intraday_return', 'prev_intraday_rsi_9', 'prev_intraday_macd', 'prev_intraday_vwap_gap']
    
    df['month'] = pd.to_datetime(df['date_str']).dt.to_period('M')
    eval_start = pd.Period('2021-01', 'M')
    
    # Target is any general downward drift for training
    df['target'] = (df['pnl_0915_net'] > 0).astype(int)
    
    print("2. Running Walk-Forward Training...")
    results = []
    months = sorted(df['month'].unique())
    for m in months:
        if m < eval_start: continue
        train_df = df[(df['month'] >= pd.Period('2018-01', 'M')) & (df['month'] < m)]
        test_df = df[df['month'] == m]
        if len(train_df) == 0 or len(test_df) == 0: continue
        
        model = lgb.LGBMClassifier(n_estimators=100, learning_rate=0.05, max_depth=4, random_state=42, n_jobs=-1, verbose=-1)
        model.fit(train_df[features], train_df['target'])
        
        out = test_df[['date_str', 'clean_stock']].copy()
        out['prob_win'] = model.predict_proba(test_df[features])[:, 1]
        results.append(out)
        
    res_df = pd.concat(results)
    top4 = res_df.sort_values(['date_str', 'prob_win'], ascending=[True, False]).groupby('date_str').head(4)
    
    print(f"3. Querying STRICT DB TICKS for {len(top4)} trades...")
    final_sheet = []
    with ThreadPoolExecutor(max_workers=20) as executor:
        for res in executor.map(process_trade_0920, [r for _, r in top4.iterrows()]):
            if res: final_sheet.append(res)
            
    pnl_df = pd.DataFrame(final_sheet)
    out_path = '/home/ubuntu/sarang_2026_shortsell_algos/05_Clean_Strict_Rebuild/model1_0920_pnl_sheet.csv'
    pnl_df.to_csv(out_path, index=False)
    print(f"DONE! Total Profit: Rs {pnl_df['Net_Rs_PnL'].sum():,.2f}")
    print(f"Saved strict audit sheet to: {out_path}")

if __name__ == "__main__":
    main()
