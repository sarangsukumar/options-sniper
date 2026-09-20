import urllib.request
from datetime import datetime
import os.path
datedoday=datetime.today().strftime('%Y-%m-%d')
print(datedoday)

filename='/home/ubuntu/KotakCodes1/scripmaster/'+datedoday+"scripmaster.csv"

try:
  print("downloading scripmaster...")
  urllib.request.urlretrieve("https://images.5paisa.com/website/scripmaster-csv-format.csv",filename)
except Exception as error:
    # handle the exception
    print("An exception occurred:", error)
