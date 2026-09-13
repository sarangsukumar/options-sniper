# 🏆 Sarang 2026 Short-Sell Algorithmic Portfolio

Welcome to the centralized repository containing all **4 fully verified, audited, and production-ready short-selling algorithmic strategies**.

Every model in this repository complies with strict institutional trading standards:
1. **100% Pure MySQL Database:** Strictly zero external Yahoo Finance dependencies. All pricing, tick indicators, and pre-market metrics are drawn directly from `markets.scrapdata` and `markets.scrapdata_F1`.
2. **Exact Dynamic Contract Lot Sizes:** Mapped dynamically per contract expiry date from `historical_lotsize_new.csv` (35,205 official NSE records across 646 F&O symbols).
3. **Zero Lookahead Bias:** True expanding-window Walk-Forward Optimization (WFO) where models are trained strictly on past years ($T < \text{Test Year}$) and evaluated on completely unseen out-of-sample data.
4. **Live Execution Feasibility:** Every model features a **guaranteed $\ge$ 2-minute latency buffer** between data cutoff and trade execution.
5. **Standardized Brokerage:** Flat ₹300.00 commission deducted per trade across all years.

---

## 📁 Repository Structure

```
/home/ubuntu/sarang_2026_shortsell_algos/
├── README.md                                    # Master portfolio documentation & comparison
├── run_all_models.py                            # Master benchmarking script
├── 01_Model_V8_Scalp_0920_0940/                 # Fast 20-min morning momentum scalp (+₹27.09 L)
│   ├── run_simulation.py
│   ├── trades_log.csv
│   └── README.md
├── 02_Model_B_Extended_0920_1445/               # Full-day hold on opening 3-min ticks (+₹98.55 L)
│   ├── run_simulation.py
│   ├── trades_log.csv
│   └── README.md
├── 03_Model_V6_Single_0942_1445/                # Flagship intraday mean-reversion with 3% SL (+₹91.32 L)
│   ├── run_simulation.py
│   ├── trades_log.csv
│   └── README.md
└── 04_Model_V6_V7_Hybrid_0942_1445/             # Dual-engine titan: Reversion + Sniper (+₹214.63 L / ₹2.15 Cr)
    ├── run_simulation.py
    ├── trades_log.csv
    └── README.md
```

---

## 📊 Master Performance Comparison (2020 – 2026)

| # | Strategy Name | Time Window | Trades | Win Rate % | Profit Factor | Avg Net / Trade | Daily Sharpe | Max DD (₹ L) | Total Net PnL |
| :-: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| 1 | **Model V8 Scalp** | 09:20 $\rightarrow$ 09:40 AM | 5,087 | 54.55% | 1.28 | ₹532.56 | 1.98 | -₹3.31 L | **₹27.09 Lakhs** |
| 2 | **Model B Extended** | 09:20 $\rightarrow$ 14:45 PM | 4,844 | 59.31% | 1.50 | ₹2,034.40 | 3.42 | -₹3.88 L | **₹98.55 Lakhs** |
| 3 | **Model V6 Single** | 09:42 $\rightarrow$ 14:45 PM | 4,035 | 58.17% | 1.59 | ₹2,263.27 | 3.43 | -₹3.62 L | **₹91.32 Lakhs** |
| 4 | 👑 **Model V6/V7 Hybrid** | **09:42 $\rightarrow$ 14:45 PM** | **4,994** | **63.04%** | **2.34** | **₹4,297.66** | **4.98** | **-₹4.61 L** | 🏆 **₹214.63 Lakhs (₹2.15 Cr)** |

---

## 📅 Year-by-Year Net PnL Matrix (₹ Lakhs)

| Year | Model 1 (V8 Scalp) | Model 2 (Model B) | Model 3 (V6 Single) | 👑 Model 4 (V6/V7 Hybrid) |
| :---: | :---: | :---: | :---: | :---: |
| **2020** | — | +₹18.73 L | — | **+₹21.86 L** |
| **2021** | +₹9.32 L | +₹20.87 L | +₹10.85 L | **+₹37.11 L** |
| **2022** | +₹4.76 L | +₹23.76 L | +₹19.19 L | **+₹30.21 L** |
| **2023** | +₹0.64 L | +₹10.45 L | +₹14.71 L | **+₹37.08 L** |
| **2024** | +₹12.05 L | +₹14.97 L | +₹21.07 L | **+₹49.71 L** |
| **2025** | -₹3.03 L | +₹8.59 L | +₹13.48 L | **+₹29.07 L** |
| **2026** | +₹3.36 L | +₹1.19 L | +₹12.02 L | **+₹9.58 L** |
| **TOTAL** | **₹27.09 L** | **₹98.55 L** | **₹91.32 L** | 🏆 **₹214.63 L (₹2.15 CRORE)** |

---

## ⚡ Recommended Production Deployment: The Sequential Engine

By taking advantage of the execution timing, you can re-use 100% of your trading capital across two non-overlapping models:

1. **09:20 – 09:40 AM:** Run **Model 1 (V8 Scalp)**. Positions square off at 09:40:00 AM, releasing 100% of margin.
2. **09:42 – 14:45 PM:** Re-deploy the exact same margin into **Model 4 (V6/V7 Hybrid)**.

### Combined Sequential System Highlights:
- **Total Net PnL:** **+₹241.72 Lakhs (+₹2.42 CRORE)**
- **Daily Win Rate:** **62.45%**
- **Daily Sharpe Ratio:** **4.61**
- **Max Drawdown:** Only **-₹4.61 Lakhs**
- **Capital Needed:** **1x Margin** (Zero capital conflict).

---

## 🚀 How to Run the Centralized Suite

To run the master benchmarking and correlation audit across all 4 models:
```bash
python3 /home/ubuntu/sarang_2026_shortsell_algos/run_all_models.py
```
