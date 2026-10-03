# 🏗️ Clean Scratch Rebuild (09:20 & 09:42)

This folder contains the absolute source of truth for the Dual-Model system. 

### 🛡️ The Look-Ahead Bias Guarantee
To mathematically guarantee that **zero 09:15 data leakage** occurs, the PnL generation scripts in this folder do NOT rely on pre-calculated CSV targets. 

Instead, they dynamically connect to your live MySQL `scrapdata` database and enforce strict time-based queries for every single trade:

**Model 1 (09:20 Scalp):**
* **Entry:** `SELECT time, price ... WHERE time >= '09:20:00' ASC LIMIT 1`
* **Exit:** Scans for 3% SL or 5% TP between 09:20 and 09:40. If none, forces exit at `>= 09:40:00`.

**Model 2 (09:42 Trend):**
* **Entry:** `SELECT time, price ... WHERE time >= '09:42:00' ASC LIMIT 1`
* **Exit:** Scans for 3% SL or 5% TP between 09:42 and 14:45. If none, forces exit at `>= 14:45:00`.

### 🚀 How to Rebuild
Simply run the two generation scripts. They will train the Machine Learning models, simulate the Walk-Forward predictions over 6 years, and query the database for the exact entry and exit ticks to generate the final PnL sheets.

```bash
python3 1_generate_0920_model_and_pnl.py
python3 2_generate_0942_model_and_pnl.py
```

The resulting `model1_0920_pnl_sheet.csv` and `model2_0942_pnl_sheet.csv` will contain the exact Buy/Square-off times for manual auditing.
