import pandas as pd
import pymysql
import sys

def verify_pnl(model_dir):
    print(f"\nVerifying {model_dir}...")
    try:
        df = pd.read_csv(f"{model_dir}/auditor_pnl_sheet.csv")
    except Exception as e:
        print(f"Error reading CSV: {e}")
        return
        
    db = pymysql.connect(host='localhost', user='root', password='root', database='markets', cursorclass=pymysql.cursors.DictCursor)
    cur = db.cursor()
    
    sample = df.sample(5, random_state=42)
    mismatches = 0
    
    for idx, row in sample.iterrows():
        d = row['date']
        s = row['stockname']
        csv_entry_price = row['entry_price']
        csv_exit_price = row['exit_price']
        
        # We assume the time window depends on the model.
        # Let's extract the time window from the entry_time and exit_time strings if possible, or we can just look up the exact times
        entry_time_val = row['entry_time']
        exit_time_val = row['exit_time']
        
        # Direct lookup of the price at that exact second recorded in the sheet
        cur.execute(f"SELECT price FROM scrapdata WHERE date='{d}' AND stockname='{s}' AND time='{entry_time_val}'")
        en_res = cur.fetchone()
        
        cur.execute(f"SELECT price FROM scrapdata WHERE date='{d}' AND stockname='{s}' AND time='{exit_time_val}'")
        ex_res = cur.fetchone()
        
        db_entry_price = en_res['price'] if en_res else None
        db_exit_price = ex_res['price'] if ex_res else None
        
        match = (db_entry_price == csv_entry_price) and (db_exit_price == csv_exit_price)
        if not match:
            mismatches += 1
            print(f"Mismatch for {s} on {d}: CSV Entry {csv_entry_price}, DB Entry {db_entry_price} | CSV Exit {csv_exit_price}, DB Exit {db_exit_price}")
            
    if mismatches == 0:
        print(f"Sample verification PASSED for {model_dir}. Database prices match PnL sheet.")
    else:
        print(f"Sample verification FAILED for {model_dir}. Found {mismatches} mismatches.")

verify_pnl('Model_1_0940_to_1445_All_Day')
verify_pnl('Model_2_0920_to_1445_Apex')
verify_pnl('Model_3_0920_to_0940_Scalp')
