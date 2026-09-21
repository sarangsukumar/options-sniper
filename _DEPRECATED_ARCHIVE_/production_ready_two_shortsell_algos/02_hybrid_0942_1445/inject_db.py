import pandas as pd
import pymysql
import sys

def inject(target_date_str):
    df_plan = pd.read_csv('/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/production_ready_two_shortsell_algos/02_hybrid_0942_1445/live_predictions_today.csv')
    if len(df_plan) == 0:
        print("No trades to insert.")
        return
        
    conn = pymysql.connect(host='localhost', user='root', password='root', database='markets')
    cursor = conn.cursor()
    
    insert_query = """
        INSERT INTO orders (
            stockname, price, quantity, type, ismarket, stoplossprice, 
            limitprice, limitprice_original, simulationtime, credate, 
            isvalid, is_future, USER, order_rank
        ) VALUES (
            %s, %s, %s, %s, %s, %s, 
            %s, %s, %s, %s, 
            %s, %s, %s, %s
        )
    """
    
    sim_time_str = f"{target_date_str} 00:00:00"
    
    inserted = 0
    for idx, row in df_plan.iterrows():
        stockname = str(row['clean_stock']).strip().upper()
        lots = int(row['lots_to_trade'])
        if lots <= 0:
            continue
        
        # Determine order rank string based on signal type
        if "DUAL" in str(row['signal_type']).upper():
            rank_label = f"TL_{idx+1}_DUAL"
        else:
            rank_label = f"TL_{idx+1}_CL"
            
        cursor.execute(insert_query, (
            stockname, 0.0, lots, 'BUY', 'FALSE', 0.0,
            0.0, 0.0, sim_time_str, sim_time_str,
            'FALSE', 'TL', 'MANISHA', rank_label
        ))
        inserted += 1
        print(f"✔ Inserted: {stockname} (Lots: {lots}, Rank: {rank_label})")

    conn.commit()
    cursor.close()
    conn.close()
    print(f"✅ Successfully inserted {inserted} live order(s) into markets.orders table for execution!")

if __name__ == '__main__':
    inject(sys.argv[1])
