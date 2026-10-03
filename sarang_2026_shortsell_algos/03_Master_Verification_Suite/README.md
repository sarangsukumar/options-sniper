# Master Verification Suite: Short Sell Algorithmic Pipeline

This suite completely rebuilds the audited PnL of the two distinct short-selling regimes from scratch, connecting directly to the MySQL tick-by-tick databases (`scrapdata` for Cash, `scrapdata_F1` for Futures). 

## The Margin Recycling Architecture
Because the two models have **zero time overlap**, you can execute both daily using the exact same baseline capital pool:
1. **09:20 ➔ 09:40 (Model 1):** Execute the volatile morning fade entirely in **Cash Equity (EQ)**. F&O liquidity is too dangerous/absent at 09:20.
2. **09:42 ➔ 14:45 (Model 2):** After capital is released at 09:40, recycle it immediately into **Futures (F1)** to ride the institutional trend all day with lower statutory taxes.

## How to Verify
Simply execute the `run_all.sh` shell script. It will read the daily historical ML predictions from the `data/` folder and strictly execute them against your local MySQL instance.

```bash
./run_all.sh
```

### Strict Simulation Rules Applied:
* **Kotak MIS Leverage:** 5x applied strictly (no excess leverage).
* **Capital Sizing:** ₹1 Lakh base capital per stock per trade. 
* **Model 1 Execution:** Cash EQ strictly between `09:20:00` and `09:40:00` (w/ 3% Stop Loss).
* **Model 2 Execution:** Futures F1 strictly between `09:42:00` and `14:45:00` (w/ 3% Stop Loss).
* **Statutory Taxes:** Budget 2024 exact Kotak STT, Brokerage, Txn, SEBI, GST, Stamp Duty dynamically calculated on every trade.
* **Futures Brokerage:** Assumes a flat high-end penalty of ₹600 per lot to be ultra-conservative.

## Expected Combined PnL (2021-2026)
* Model 1 (EQ): ~₹ 31.5 Lakhs
* Model 2 (F1): ~₹ 54.2 Lakhs
* **Master Recycled PnL:** ~₹ 85.7 Lakhs
