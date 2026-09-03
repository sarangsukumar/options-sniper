# 🚀 Sarang Short Sell 09:40 (2026 Edition)

## 📌 Strategy Overview
This is the ultimate LightGBM (Gradient Boosting) machine learning model designed to short sell gap-up stocks at **09:40 AM IST** based on extreme retail exhaustion. 

It was built strictly without look-ahead bias and utilizes advanced feature engineering, specifically **"Arc Shapes"** (tracking the Spike and Fade trajectory of the morning gap) and **"R1/R3 Historical Profiling"** (tracking days to expiry and strict historical win rates).

**Performance Record (Walk-Forward Out of Sample):**
* **Total Profit:** ₹ 99.92 Lakhs (~ ₹ 1 Crore)
* **Overall Win Rate:** 60.7%
* **2026 Average PnL:** ₹ 5,093.65 per trade
* **Selected Ranks:** The model only trades the **Rank #1** and **Rank #4** highest probability predictions each day.

---

## 📁 Required Data Files
To run this on another server, place the following files into the `data/` directory:
1. `short_sell_ml_dataset_v2.csv` (Base intraday technicals dataset)
2. `premarket_ticks.csv` (09:07 AM pre-open auction prices)
3. `fo_ban_list_historical.csv` (Daily F&O Ban list to filter out restricted stocks)

---

## ⚙️ Core Architecture (The ML Edge)

### 1. The Ban List Filter
Any stock inside the F&O Ban Period is instantly removed from the dataset. These stocks are restricted from new positions, making their morning gaps highly susceptible to extreme crashes. While they look like great shorts, they cannot be traded in reality.

### 2. The "Arc" Features (Half-Circle Logic)
The model tracks the trajectory of the price from Yesterday's Close to the 09:40 AM entry:
* `positive_half_circle_prev_close`: Measures if a stock spiked massively from yesterday's close but has faded all the way back down by 09:40 (Pure Exhaustion).
* `gap_fade_completion`: Measures exactly what percentage of the overnight gap has already evaporated.

### 3. R1/R3 Heritage Features
* `days_to_expiry`: Calculated dynamically based on the exact trade date relative to the last Thursday of the month.
* `hist_win_rate` & `hist_count`: An expanding, shifted mathematical window that tracks the stock's exact historical success rate for this specific strategy, completely blinding the model to future results (No Look Ahead).

---

## 🚀 Execution Scripts
* **`src/train_walk_forward.py`**: The main research script. It takes the datasets, builds the features, and runs the chronological Walk-Forward Validation (Training on Year N-1, predicting Year N) to prove the strategy works out-of-sample.
* **`src/train_production_model.py`**: Trains the final LightGBM model on ALL available data (2018-2026) and saves it to the `models/` folder as `sarang_shortsell_0940.pkl` for live daily execution.

