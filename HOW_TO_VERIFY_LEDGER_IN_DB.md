# 🗄️ Database Trade Ledger Verification Guide (`scrapdata`)

This document explains how anyone with access to the local MySQL database (`markets.scrapdata`) can independently audit and verify every trade execution, entry price, exit price, quantity, brokerage/statutory commission, and Net PnL across both production short-sell models (**2020–2026**).

---

## 📂 1. Standardized Trade Ledger CSV Files Included in This PR

All ledger sheets strictly follow the standardized 10-column verification schema:

| Column | Type | Description | Formula / DB Source |
| :--- | :---: | :--- | :--- |
| `date` | `YYYY-MM-DD` | Trading session date | `scrapdata.date` |
| `stockname` | `STRING` | NSE Equity / F&O Symbol | `scrapdata.stockname` |
| `qty` | `INT` | Traded share quantity (`₹10.0L Notional` = `₹2.0L Margin @ 5x MIS`) | `int(1000000 / entry_price)` |
| `entry_time` | `YYYY-MM-DD HH:MM:SS` | Exact short-sell entry timestamp | `09:25:00` (M1) / `09:42:00` (M2) |
| `entry_price` | `FLOAT` | Exact short-sell execution price | `scrapdata.close` at `entry_time` |
| `exit_time` | `YYYY-MM-DD HH:MM:SS` | Exact cover (buy-back) timestamp | `09:36:00–09:40:00` (M1) / `09:42:00–14:45:00` (M2) |
| `exit_price` | `FLOAT` | Exact cover execution price | `scrapdata.close` at `exit_time` (or SL trigger) |
| `gross_pnl` | `FLOAT` | Gross Profit/Loss in ₹ | `round((entry_price - exit_price) * qty, 2)` |
| `commission` | `FLOAT` | Statutory taxes & brokerage (STT, NSE Txn, SEBI, Stamp, GST) | ₹300–₹405 per ₹10L notional order |
| `net_pnl` | `FLOAT` | Audited Net Profit/Loss in ₹ | `round(gross_pnl - commission, 2)` |

### Ledger File Paths & Summary Metrics (`₹2.0L Margin / ₹10.0L Notional per Order`):

| Model & Sizing Configuration | CSV File Path in Repository | Total Trades | Win Rate | Gross PnL | Commission | **Verified Net PnL** |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| **Model 1 (`09:20 Daily Rolling 4-Freq`) — Top 2** *(₹4L Margin / ₹20L Notional)* | `sarang_2026_liveproduction_shortsellmodels/02_live_production_pipelines/0920_scalp_pipeline/verified_0920_rolling_4freq_top2_ledger_20L.csv` | `3,181` | **80.64%** | `+₹195.26L` | `-₹23.89L` (Kotak) | **`+₹171.37 Lakhs` (+₹1.71 Cr)** |
| **Model 1 (`09:20 Daily Rolling 4-Freq`) — Top 2** *(₹2L Margin / ₹10L Notional)* | `sarang_2026_liveproduction_shortsellmodels/02_live_production_pipelines/0920_scalp_pipeline/verified_0920_rolling_4freq_top2_ledger.csv` | `3,181` | **80.64%** | `+₹97.57L` | `-₹12.69L` (Kotak) | **`+₹84.88 Lakhs`** |
| **Model 1 (`09:20 Scalp`) — Top 2** *(₹4L Margin / day)* | `sarang_2026_liveproduction_shortsellmodels/02_live_production_pipelines/0920_scalp_pipeline/verified_0920_scalp_top2_ledger.csv` | `3,069` | **81.46%** | `+₹92.59L` | `-₹9.21L` | **`+₹83.38 Lakhs`** |
| **Model 1 (`09:20 Scalp`) — Top 4** *(₹8L Margin / day)* | `sarang_2026_liveproduction_shortsellmodels/02_live_production_pipelines/0920_scalp_pipeline/verified_0920_scalp_trade_ledger.csv` | `6,120` | **77.97%** | `+₹156.17L` | `-₹18.36L` | **`+₹137.81 Lakhs`** |
| **Model 2 (`09:40 Hybrid`) — Top 4** *(₹8L Margin / day)* | `sarang_2026_liveproduction_shortsellmodels/02_live_production_pipelines/0940_hybrid_pipeline/verified_0940_hybrid_trade_ledger.csv` | `5,285` | **55.72%** *(Static)* / **66.85%** *(4-Stage)* | `+₹122.58L` | `-₹21.48L` | **`+₹101.10 Lakhs`** *(Static)* / **`+₹114.65 Lakhs`** *(4-Stage)* |
| **Model 2 (`09:40 Hybrid`) — Top 2** *(₹4L Margin / day)* | `sarang_2026_liveproduction_shortsellmodels/02_live_production_pipelines/0940_hybrid_pipeline/verified_0940_hybrid_top2_ledger.csv` | `2,668` | **56.26%** *(Static)* / **67.27%** *(4-Stage)* | `+₹70.85L` | `-₹10.85L` | **`+₹60.00 Lakhs`** *(Static)* / **`+₹66.33 Lakhs`** *(4-Stage)* |
| **Combined Master Ledger** *(M1 Top 2 + M2 Top 4)* | `sarang_2026_liveproduction_shortsellmodels/verified_all_models_trade_ledger.csv` | `8,354` | **65.18%** *(Static)* | `+₹215.17L` | `-₹30.69L` | **`+₹184.48 Lakhs`** *(Static)* / **`+₹198.03 Lakhs`** *(4-Stage)* |

---

## 🔌 2. MySQL Database Connection Details

All historical and live market ticks are stored in the local MySQL instance:
- **Host:** `localhost` (Port `3306`)
- **Database:** `markets`
- **Primary Tick Table:** `scrapdata` (1-minute NSE Equity OHLCV ticks: `date`, `time`, `stockname`, `open`, `high`, `low`, `close`, `volume`)
- **Live Order Audit Table:** `shortsell_orders` (`trade_date`, `model_name`, `stockname`, `quantity`, `entry_price`, `stop_loss`, `isvalid`)

---

## 🔍 3. Step-by-Step SQL Queries to Verify Any Trade

### A. Verify a `09:20 Scalp` Trade in MySQL
Pick any row from `verified_0920_scalp_top2_ledger.csv` (e.g., `date = '2020-01-01'`, `stockname = 'AMBUJACEM'`, `entry_time = '2020-01-01 09:25:00'`, `exit_time = '2020-01-01 09:36:00'`):

```sql
USE markets;

-- 1. Verify Entry Price at 09:25:00 and Cadence Exit Price (09:36:00 to 09:40:00)
SELECT 
    date,
    stockname,
    TIME(time) AS tick_time,
    open,
    high,
    low,
    close AS db_price
FROM scrapdata
WHERE date = '2020-01-01'
  AND stockname = 'AMBUJACEM'
  AND TIME(time) IN ('09:25:00', '09:36:00', '09:37:00', '09:38:00', '09:39:00', '09:40:00')
ORDER BY time ASC;
```

### B. Verify a `09:40 Hybrid` Trade in MySQL
Pick any row from `verified_0940_hybrid_trade_ledger.csv` (e.g., `date = '2020-01-01'`, `stockname = 'DALBHARAT'`, `entry_time = '2020-01-01 09:42:00'`, `exit_time = '2020-01-01 14:45:00'`):

```sql
USE markets;

-- 1. Verify Entry Price at 09:42:00 and Time Exit Price at 14:45:00
SELECT 
    date,
    stockname,
    TIME(time) AS tick_time,
    close AS db_price
FROM scrapdata
WHERE date = '2020-01-01'
  AND stockname = 'DALBHARAT'
  AND TIME(time) IN ('09:42:00', '14:45:00')
ORDER BY time ASC;

-- 2. Verify whether the 2.25% Stop Loss (entry_price * 1.0225) was breached between 09:42 and 14:45
SELECT 
    MIN(TIME(time)) AS first_sl_breach_time,
    MAX(high) AS max_intraday_high
FROM scrapdata
WHERE date = '2020-01-01'
  AND stockname = 'DALBHARAT'
  AND TIME(time) >= '09:42:00'
  AND TIME(time) <= '14:45:00'
  AND high >= ROUND(809.10 * 1.0225, 2);
```

---

## 🧮 4. Instant Python Math & Schema Audit One-Liner

Anyone can verify that **100% of rows** across all ledger CSVs have zero missing values and exact mathematical parity (`gross_pnl == (entry_price - exit_price) * qty` and `net_pnl == gross_pnl - commission`) by running:

```bash
python3 -c "
import pandas as pd
for path in [
    'sarang_2026_liveproduction_shortsellmodels/02_live_production_pipelines/0920_scalp_pipeline/verified_0920_scalp_top2_ledger.csv',
    'sarang_2026_liveproduction_shortsellmodels/02_live_production_pipelines/0920_scalp_pipeline/verified_0920_scalp_trade_ledger.csv',
    'sarang_2026_liveproduction_shortsellmodels/02_live_production_pipelines/0940_hybrid_pipeline/verified_0940_hybrid_trade_ledger.csv',
    'sarang_2026_liveproduction_shortsellmodels/02_live_production_pipelines/0940_hybrid_pipeline/verified_0940_hybrid_top2_ledger.csv',
    'sarang_2026_liveproduction_shortsellmodels/verified_all_models_trade_ledger.csv'
]:
    df = pd.read_csv(path)
    gross_err = ((df['entry_price'] - df['exit_price']) * df['qty'] - df['gross_pnl']).abs().max()
    net_err = (df['gross_pnl'] - df['commission'] - df['net_pnl']).abs().max()
    print(f'{path.split(\"/\")[-1]:<42} | Rows: {len(df):<5} | WR: {(df[\"net_pnl\"]>0).mean()*100:5.2f}% | Net PnL: ₹{df[\"net_pnl\"].sum()/1e5:6.2f}L | Max Math Diff: ₹{max(gross_err, net_err):.4f}')
"
```
