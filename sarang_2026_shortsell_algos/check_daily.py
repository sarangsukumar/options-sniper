import pymysql
conn = pymysql.connect(host='localhost', user='root', password='root', database='markets')
cur = conn.cursor()
cur.execute("SHOW TABLES")
print(cur.fetchall())
