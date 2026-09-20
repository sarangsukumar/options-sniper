# Absolute Re-creation Guide (Pure EQ Models)

This directory contains the exact, highly-optimized scripts required to rebuild both the **09:20 Scalp Engine (Model 1)** and the **09:42 Hybrid Engine (Model 2)** entirely from scratch using strictly Cash Equity (`scrapdata`) physical ticks. 

No Futures data (`scrapdata_F1`) is used in these pipelines.

---

## 🚀 Model 1: The 09:20 to 09:40 Scalp Engine
**Target PnL:** ~92 Lakhs | **Win Rate:** 65.5%

To recreate this model from the raw database:
1. **Extract Features:** Run `python3 01_model1_0920/1_extract_0920_features.py`
   *(Queries the DB for physical 09:15-09:19 ticks and calculates Gap/VWAP features)*
2. **Train AI & Predict:** Run `python3 01_model1_0920/2_run_0920_simulation.py`
   *(Trains a LightGBM model to target 09:20 returns and generates simulated trades)*
3. **Audit Execution:** Run `python3 01_model1_0920/3_bulletproof_db_audit_0920.py`
   *(Simulates exact tick-by-tick execution with a 3% SL and Rs 40 Flat Kotak Brokerage)*

---

## 🚀 Model 2: The 09:42 to 14:45 Hybrid Engine
**Target PnL:** ~1.01 Crores | **Win Rate:** 59.4%

To retrain the production model securely on pure Cash EQ logic (removing all historical Futures slippage "ghost trades"):
1. **Retrain on Cash EQ:** Run `python3 02_model2_0942/01_train_pure_eq_model.py`
   *(Re-maps the training target strictly to the verified physical Cash Equity returns and trains the final LightGBM model)*
2. **Verify Final Results:** Run `python3 02_model2_0942/02_verify_pure_eq_trades.py`
   *(Calculates the exact PnL and Win Rate of the newly trained EQ model against the strict Tick-by-Tick physical ledger)*

---

### Why were these scripts built?
F1 (Futures) data has massive liquidity gaps during the early morning. Training on Futures data introduces mathematical slippage and ghost triggers. By strictly executing these specific scripts, the AI trains purely on the physical realities of the Cash EQ market, producing significantly higher mathematical profit when executed via 5x MIS Margin.
