import pymysql
import pandas as pd
import time

t0 = time.time()
conn = pymysql.connect(host='localhost', user='root', password='root', database='markets')
q = """
SELECT date, stockname, price as p_0916 
FROM scrapdata 
WHERE TIME(time) = '09:16:00'
"""
df_0916 = pd.read_sql(q, conn)

q2 = """
SELECT date, stockname, price as p_0915 
FROM scrapdata 
WHERE TIME(time) = '09:15:00'
"""
df_0915 = pd.read_sql(q2, conn)

conn.close()

df_0916.to_csv('/tmp/prices_0916.csv', index=False)
df_0915.to_csv('/tmp/prices_0915.csv', index=False)
print(f"Extracted {len(df_0916)} 09:16 rows and {len(df_0915)} 09:15 rows in {time.time()-t0:.2f}s")
