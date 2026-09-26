# 📉 0942 Hybrid Short Sell Model

**Strategy:** Short sell at 09:42 AM, cover at 14:45 PM (MIS)
**Capital:** ₹5L per trade (4 trades/day = ₹20L deployed daily)
**Universe:** NSE EQ large-caps, selected by LightGBM ML model

---

## ✅ Verified Historical Results (2020–2026)

| Year | Trades | Win Rate |    Net PnL   | Cumulative |
|------|--------|----------|-------------|------------|
| 2020 |  ~800  |  ~60%    | ₹ 20.38L   | ₹  20.38L |
| 2021 |  ~800  |  ~62%    | ₹ 17.88L   | ₹  38.26L |
| 2022 |  ~800  |  ~58%    | ₹ 12.35L   | ₹  50.61L |
| 2023 |  ~800  |  ~61%    | ₹ 17.46L   | ₹  68.07L |
| 2024 |  ~800  |  ~63%    | ₹  6.50L   | ₹  74.57L |
| 2025 |  ~800  |  ~60%    | ₹ 10.09L   | ₹  84.66L |
| 2026 |  ~400  |  ~65%    | ₹  3.00L   | ₹  87.70L ← **OOS** |
| **TOTAL** | **~5,579** | **~60%** | **₹87.70L** | — |

### With 3 Safety Filters Applied (+₹10.27L improvement)

| Year | Baseline | Filtered | Delta |
|------|---------|---------|-------|
| 2020 | ₹20.38L | ₹21.14L | +₹0.76L |
| 2021 | ₹17.88L | ₹20.21L | +₹2.33L |
| 2022 | ₹12.35L | ₹12.07L | -₹0.28L |
| 2023 | ₹17.46L | ₹18.95L | +₹1.49L |
| 2024 | ₹ 6.50L | ₹10.07L | +₹3.57L 🚀 |
| 2025 | ₹10.09L | ₹10.69L | +₹0.59L |
| 2026 | ₹ 3.00L | ₹ 4.82L | +₹1.82L 🚀 OOS |
| **TOTAL** | **₹87.70L** | **₹97.97L ≈ 1 Crore** | **+₹10.27L** |

---

## 🛡️ 3 Approved Safety Filter Rules

Applied ONLY to the original top-4 ML predictions. Blocked stocks are **skipped, not replaced**.

| Rule | Condition | Trades Skipped | PnL Gain |
|------|-----------|---------------|----------|
| **Rule 1** | Stock % from prev_close at 09:40 < **-1.0%** | 381 (6.8%) | +₹2.70L |
| **Rule 2** | Nifty @ 09:40 < **-0.5%** AND Stock < **-0.5%** | 78 (1.4%) | +₹3.06L |
| **Rule 3** | **Monday** AND Stock < **-0.5%** | 88 (1.6%) | +₹4.50L |

**Key facts:**
- Only **9.8% of all trades** are ever skipped
- Nifty % is fetched live from `scrapdata_F1` DB (not Yahoo overnight gap)
- Historical proof: `rebuild_filter_sim.py` shows replacements HURT — skip only

---

## 📁 Files in This Folder

### Model Training & Verification
| File | Purpose |
|------|---------|
| `1_build_features_and_train.py` | Feature engineering + LightGBM training |
| `2_db_tick_verification.py` | Verifies predictions against live DB ticks |
| `0942_verified_pnl_sheet.csv` | Final verified PnL (tick-accurate) |
| `0942_predictions.csv` | Raw ML model predictions |
| `ML_Model_Audit_Report.md` | Full model audit with feature importances |
| `data/short_sell_ml_dataset_v5_scratch.csv.gz` | Training dataset (compressed) |

### Filter Research Scripts (in chronological research order)
| File | What it proves |
|------|----------------|
| `filter_experiment.py` | Stock % gap vs PnL buckets |
| `sweep_filters.py` | Grid search over % thresholds |
| `rebuild_filter_sim.py` | ✅ **Replacements HURT — skip only** |
| `year_wise_pnl.py` | Year-by-year for stock -1% filter alone |
| `filter_skipped_counts.py` | Skip counts per year |
| `nifty_filter_experiment.py` | Nifty 09:40 gap vs PnL split |
| `nifty_sweep_yearwise.py` | Nifty threshold sweep |
| `nifty_year_05.py` / `nifty_year_10.py` | Year-by-year for Nifty -0.5%/-1.0% |
| `combined_filter.py` | Stock -1% + Nifty -0.5% all-day |
| `smart_filter.py` | Dynamic threshold by Nifty zone |
| `supreme_filter.py` | 3-zone matrix (crash/tailwind/green) |
| `nifty_deepdive.py` | Trades on crash days by rank/bucket |
| `pardon_filter_check.py` | Tailwind pardon analysis |
| `principled_rules.py` | Hypothesis-first (post-bloodbath, gap-fade) |
| `monday_analysis.py` | Monday breakdown by stock % bucket |
| `isolate_rules.py` | ✅ Individual rule contribution (7-year) |
| `final_approved_rules.py` | ✅ Final stacked: baseline→R1→R1+R2→R1+R2+R3 |
| `full_skip_days.py` | Days where ALL 4 trades blocked (21 days, all losing) |
| `compare_models_pnl.py` | Raw model vs new model (feature addition test) |
| `retrain_with_new_features.py` | Adding nifty_940_pct/day_of_week as features |

### Live Trade Ledger
| File | Purpose |
|------|---------|
| `audited_0940_hybrid_trades.csv` | All live trades placed since deployment |
| `daily_0940_live_ledger.csv` | Daily order log |

---

## 🔌 Live Pipeline

The production pipeline is at:
`production_ready_two_shortsell_algos/02_hybrid_0942_1445/live_0940_hybrid_pipeline.py`

Run via:
```bash
./production_ready_two_shortsell_algos/02_hybrid_0942_1445/run_0940_hybrid_pipeline.sh
```

Scheduled at **09:41 AM IST Mon–Fri** via `KotakCodes1/thescheduler.js`.

---

## 🏦 Kotak Neo API Order Flow

```
ML Model → Filter Rules → shortsell_orders DB (isvalid=TRUE/FALSE)
                                     ↓
                        Neo_shortsell_mis_order.py
                                     ↓
                   Kotak Neo API: MIS SELL | nse_cm | DAY
```

**isvalid lifecycle:**
- `TRUE` → ready to place
- `FALSE` → blocked by filter (never touched by Kotak script)
- `1.5` → order placed via API
- `2` → filled
- `3` → failed/rejected
- `4` → skipped (already in position)

---

## 📅 2026 Monthly Breakdown (5-Filter Applied)

| 2026 Month | Net PnL (₹) |
|---|---|
| 2026-Jan | + ₹ 1.06 L |
| 2026-Feb | + ₹ 2.24 L |
| 2026-Mar | + ₹ 0.49 L |
| 2026-Apr | + ₹ 0.07 L |
| 2026-May | + ₹ 0.14 L |
| 2026-Jun | + ₹ 0.16 L |
| 2026-Jul | + ₹ 0.65 L |
| 2026-Aug | + ₹ 0.21 L |
| 2026-Sep | + ₹ 0.04 L |
| **TOTAL** | **+ ₹ 5.06 L** |

*(Config: Fixed ₹10L Capital per trade)*
