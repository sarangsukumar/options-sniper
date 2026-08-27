import pathlib
from md2pdf.core import md2pdf
import requests

pdf_path = pathlib.Path('AI_Options_Target_Experiment_2026.pdf')
md_path = pathlib.Path('experiment_report.md')

with open(md_path, 'r') as f:
    raw_content = f.read()

md2pdf(pdf_path, raw=raw_content)

token = "5350311365:AAFkTUBR4IGvgS5Z9mJngz-mgk7-HkhFEYE"
chat_ids = [-698073972] # Status and warning group chat ID

for chat_id in chat_ids:
    try:
        url = f"https://api.telegram.org/bot{token}/sendDocument"
        with open(pdf_path, 'rb') as f:
            files = {'document': f}
            data = {
                'chat_id': chat_id,
                'caption': "🧪 *AI Target Selection Edge Experiment (2024-2026)*\n📉 Compares Options performance of ML R1+R3 vs R2+R4 vs Random Stocks.",
                'parse_mode': 'Markdown'
            }
            requests.post(url, data=data, files=files, timeout=60)
    except: pass
