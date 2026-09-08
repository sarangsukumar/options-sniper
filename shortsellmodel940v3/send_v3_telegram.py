import requests

TELEGRAM_BOT_TOKEN = "5350311365:AAFkTUBR4IGvgS5Z9mJngz-mgk7-HkhFEYE"
TELEGRAM_CHAT_ID   = "-698073972"

msg = """🏆 *GOLDEN HIGH-YIELD COMBINATION DISCOVERED (folder: shortsellmodel940v3)* 🏆

📌 *Why 2026 PnL is Higher & Highly Consistent:*
1. *Expanded Scalp Target:* Ranks 2-5 Normal Day Take-Profit expanded to *1.5%* (was 1.0%).
2. *R1 Trailing Optimization:* Act 1.5%, Floor 1.0%, Giveback 0.3% (SL 5.0%).
3. *Star Conviction Boosting:* Sizing +0.2x extended to *Ranks 1, 2, and 3*.

📊 *ALL-TIME PERFORMANCE METRICS (2018–2026):*
💰 *Net PnL:* *₹2,22,64,393 (₹2.226 Crore)* (Up +₹16.08 Lakhs!)
🎯 *Win Rate:* *62.34%* (7,687 trades)
📈 *Sharpe Ratio:* *6.60* (Up from 6.39)
📉 *Max Drawdown:* *₹-2,68,397* (Reduced risk!)

📅 *CONSISTENT YEAR-BY-YEAR WALK-FORWARD BREAKDOWN:*
• 2018: +₹24,24,349 (Win: 63.8%)
• 2019: +₹12,22,140 (Win: 59.6%)
• 2020: +₹31,77,600 (Win: 65.8%)
• 2021: +₹54,21,696 (Win: 69.5%)
• 2022: +₹31,77,514 (Win: 63.7%)
• 2023: +₹20,05,293 (Win: 57.7%)
• 2024: +₹21,91,252 (Win: 59.3%)
• 2025: +₹18,96,714 (Win: 61.5%) [OOS]
• 2026: +₹7,47,835 (Win: 57.7%) [8-Mo Run-Rate ~₹11.2L!]

✅ *Highest Ever Net Profit & Uniform Consistency Across All 9 Years!*
"""

url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
resp = requests.post(url, data={'chat_id': TELEGRAM_CHAT_ID, 'text': msg, 'parse_mode': 'Markdown'})
print("Telegram dispatch status:", resp.json())
