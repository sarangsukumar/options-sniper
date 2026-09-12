# Master Shortsell 09:38 (The 4.41 Crore Baseline)

## Overview
This folder contains the raw foundational master data proving the inherent positive expectancy of the BTST Trap setup when executed at **09:38:00 AM**. 

Without any Machine Learning filters, blindly executing short sells on this universe yielded a mathematically verified **₹ 4.41 Crores** in Net Profit across 2.49 Lakh historical trades.

---

## 1. The Universe Source (`markets_pnl0325.csv`)
The universe of tradable stocks was extracted exclusively from the legacy system's output file: `markets_pnl0325.csv`.
* **Column Used for Filtering:** `sell_exec_type`
* **Filter Condition:** Must contain the exact string `"Custom Limit"`
* **Logic:** This condition proves that the stock was heavily bought on the previous day (Buy Today, Sell Tomorrow) at 15:25, and opened flat/higher on the next morning, creating the perfect psychological trap for profit-booking panic.

## 2. Execution Date Mapping
The execution of the short sell happens on the **Immediate Next Trading Day** following the date listed in `markets_pnl0325.csv`.
* **Date Column in Source:** `simulationdate` (Format: `DD-MM-YYYY`)
* **Mapping Method:** The script maps this date to the *strictly next available trading date* found in the physical MySQL `scrapdata` database to ensure no weekend or holiday overlaps.

## 3. Raw Tick Data Extraction (MySQL)
Once the exact Stock Name and Execution Date are identified, the system physically connects to the local MySQL tick database to fetch the real historical execution prices.

* **Database Name:** `markets`
* **Table Name:** `scrapdata`
* **Query Columns Used:**
  * `date`: (Matched to the mapped next trading date)
  * `stockname`: (Matched to the stock name)
  * `time`: (The exact tick time)
  * `open`: (Used as the physical execution price)

### Execution Times
* **Short Sell Entry:** The system queries `TIME(time) = '09:38:00'`. If the 09:38 tick is missing due to low liquidity, it steps forward incrementally (`09:39`, `09:40`) until a fill is found.
* **Cover Exit:** The system queries `TIME(time) = '14:45:00'`.

## 4. Lot Size Mapping (`historical_lotsize_new.csv`)
No fixed lot sizes or assumptions are used.
* The script reads `historical_lotsize_new.csv`.
* It extracts the `YYYYMM` (Year and Month) from the execution date.
* It dynamically matches the stock symbol + the `YYYYMM` against the historical NSE F&O Master file.
* If a lot size exists for that specific month, it is applied. If not, the trade is discarded.

## 5. PnL Calculation
The final PnL is calculated with strict institutional mathematical logic inside `mis_short_pnl_new.csv`.
* **Formula:** `(entry_price - exit_price) * lotsize - 300`
* **Commission:** A flat `- ₹ 300` penalty is aggressively deducted from *every single trade* regardless of win or loss to perfectly simulate slippage, STT, and brokerage drag.

---
### Final Results (Reproducible)
* **Total Executed Trades:** 249,338
* **Gross Profit:** ₹ 11.89 Crores
* **Total Commission Drag:** ₹ 7.48 Crores
* **Pure Net Profit:** ₹ 4.41 Crores
* **Raw Win Rate:** 51.50%

*(The ML Engine is designed to sit on top of this exact foundation and filter out the lowest probability trades, reducing the 7.48 Crore commission drag to almost zero).*
