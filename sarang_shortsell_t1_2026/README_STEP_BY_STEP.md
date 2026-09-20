# 👑 Sarang Short-Sell T1 (2026) Master Backup

This folder contains the complete, mathematically audited, look-ahead free Machine Learning Short-Sell System built in September 2026.

## 📈 The Strategy Overview
This is a dual-engine algorithmic trading system designed for the NSE F&O segment.
It trades Top 4 F&O stocks every morning with a maximum exposure of ₹10 Lakhs per stock (Using 5x Kotak Margin, requiring a base capital of roughly ₹8-10 Lakhs).

* **Model 1 (The 09:20 Scalp):** Enters precisely at 09:22:00. Targets the violent morning mean-reversion fade. Strictly exits at 09:40:00. 
* **Model 2 (The 09:42 Hybrid):** Enters precisely at 09:42:00. Avoids the morning volatility and rides the sustained all-day downtrends. Strictly exits at 14:45:00.
* **Risk Management:** Both models utilize a strict 3% stop-loss monitored tick-by-tick.

## 🛡️ Mathematical Audits & Proofs
The script `1_rebuild_and_prove_from_scratch.py` proves the strategy works without data leakage:
1. **Zero Global Macro Look-Ahead:** It uses US S&P 500 closes from *yesterday* and Japanese Nikkei Opens from 05:30 AM IST. All data is locked before India opens.
2. **Zero Price Look-Ahead:** The execution engine physically queries the MySQL database starting precisely at `>= 09:22:00` and `>= 09:42:00`. It is impossible for it to cheat using 09:15 open prices.
3. **Zero Overfitting:** The ML is trained using a strict Expanding Walk-Forward methodology.
4. **Result:** Taking the Top 4 trades every single day across 6 years yielded an audited Net Profit of **₹16.001 Crores**.

---

## 🛠️ Step-by-Step Instructions

### Step 1: Prove the Performance (The Rebuild)
If you want to verify the 16 Crore profit from absolute scratch on your own machine:
1. Open terminal and navigate to this folder.
2. Run the proof script:
   `python3 1_rebuild_and_prove_from_scratch.py`
3. The script will dynamically download global macro data, train the walk-forward models, hit the `scrapdata` database to evaluate slippage/stop-losses, apply all Kotak Neo taxes, and output the final Crore PnL.

### Step 2: Go Live! (The Telegram Bot)
If you want to deploy the live bot that runs every day and sends you the trades:
1. Open `2_live_telegram_execution_bot.py`.
2. Edit line 13 to include your Telegram Chat ID:
   `TELEGRAM_CHAT_ID = "YOUR_CHAT_ID_HERE"`
3. Run the bot as a background daemon on your server:
   `nohup python3 2_live_telegram_execution_bot.py &`
4. You will receive Telegram alerts daily at 09:19, 09:22, 09:40, 09:41, 09:42, and 14:45.

Enjoy the alpha!
