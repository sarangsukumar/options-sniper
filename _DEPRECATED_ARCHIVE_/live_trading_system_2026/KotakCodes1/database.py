import sqlite3
import pandas as pd
from sqlalchemy import create_engine
import traceback
import mysql.connector
from datetime import datetime
def dataframe(table_name,stock_types,filtering_logic):
    #engine = create_engine('sqlite:///Orderstable.db', echo=False)
    mydb = mysql.connector.connect(host = "localhost",user = "root",password = "root",database="markets")
    cursor = mydb.cursor()
    print(cursor)
    #cursor.execute("show tables")
    # df=pd.read_excel("table.XLSX")
    # df.to_sql('Orderstable_createorders', con=engine)
    # df=pd.read_excel("table-polling.XLSX")
    # df.to_sql('orderstable_Polling', con=engine)
    todaydate= datetime.today().strftime('%Y-%m-%d')
    #print(todaydate)
    # and isvalid ='TRUE'
    query=(("select * from {} where simulationtime like '{}%' and type in({}) {} order by cretime").format(table_name,todaydate,stock_types,filtering_logic))
    #query=("select * from {} where simulationtime like '2021-11-25%' and type in({})".format(table_name,stock_types))
    print(query)
    df_trade=pd.read_sql(query,mydb)
    if(filtering_logic=="and isvalid ='TRUE'"):
        print(df_trade)
    #amr
    #print ("AMR")
    #cursor.execute("update "+table_name+" set isvalid='FALSE'")
    #mydb.commit()
    mydb.close()
    #record = cursor.fetchone()
    return df_trade

