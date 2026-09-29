# 🛡️ 09:42 Hybrid Short Sell Model — Safety Filter Research & Implementation

## Overview

After 7 years of historical backtesting (2020–2026), we identified 3 zero-look-ahead safety
filter rules that improve net PnL by **+₹10.27 Lakhs** without re-training the underlying
LightGBM model.

The filters are applied to the **original top-4 ML predictions only** — blocked stocks are
skipped entirely, NOT replaced with lower-ranked stocks (replacements were proven to hurt PnL).

---

## ✅ 3 Approved Filter Rules

| Rule | Condition | Trades Skipped | PnL Impact |
|------|-----------|---------------|------------|
| **Rule 1** | Stock's gap from prev close at 09:40 < **-1.0%** | 381 / 5,579 (6.8%) | +₹2,70,697 |
| **Rule 2** | Nifty 09:40 % < **-0.5%** AND Stock % < **-0.5%** (Crash Day) | 78 more (1.4%) | +₹3,05,937 |
| **Rule 3** | **Monday** AND Stock % < **-0.5%** (Monday Danger) | 88 more (1.6%) | +₹4,50,351 |
| **Total** | All 3 combined | 547 / 5,579 (**9.8%**) | **+₹10,26,985** |

---

## 📊 Year-Over-Year Results (₹10L capital per trade)

| Year | Baseline PnL | Filtered PnL | Delta |
|------|-------------|-------------|-------|
| 2020 | ₹20.38L | ₹21.14L | +₹75,996 |
| 2021 | ₹17.88L | ₹20.21L | +₹2,32,724 |
| 2022 | ₹12.35L | ₹12.07L | -₹28,343 ← Only loss |
| 2023 | ₹17.46L | ₹18.95L | +₹1,48,695 |
| 2024 | ₹6.50L  | ₹10.07L | +₹3,56,918 🚀 |
| 2025 | ₹10.09L | ₹10.69L | +₹59,477 |
| 2026 OOS | ₹3.00L | ₹4.82L | +₹1,81,517 🚀 |
| **TOTAL** | **₹87.70L** | **₹97.97L** | **+₹10.27L** |

---

## 📁 Filter Research Scripts

All analysis scripts used to derive the approved rules (no look-ahead bias):

| Script | Purpose |
|--------|---------|
| `filter_experiment.py` | Initial bucket analysis: stock % vs PnL |
| `sweep_filters.py` | Grid search of % thresholds |
| `rebuild_filter_sim.py` | Replacement vs no-replacement simulation |
| `nifty_filter_experiment.py` | Nifty gap vs PnL split analysis |
| `monday_analysis.py` | Monday effect by stock % bucket |
| `principled_rules.py` | Hypothesis-first testing (post-bloodbath, gap-fade) |
| `isolate_rules.py` | Individual rule contribution (7-year) |
| `final_approved_rules.py` | Stacked baseline → R1 → R1+R2 → R1+R2+R3 |

### Rules Explicitly REJECTED
- **Tailwind Pardon** (allow all trades when Nifty -0.5% to 0%) — sample too small, possibly overfitted
- **Post-Bloodbath Bounce Risk** (skip when Nifty prev day < -1%) — both IS and OOS got worse
- **2-Day Consecutive Drop** — both IS and OOS got worse
- **Previous Day Strong Close** — mixed signal, too many trades skipped for tiny gain

---

## 🔌 Live Implementation

Filters are injected into `live_0940_hybrid_pipeline.py` in the `train_and_predict_single()` function.

### Key Design Decisions
1. **Nifty % from DB** — Uses `scrapdata_F1` table (live Nifty 09:40 price vs yesterday's last tick), NOT Yahoo Finance overnight gap
2. **Stock % from features** — `gap_0907_pct + gap_fade_0907_to_940_pct` (already computed in the pipeline)
3. **No replacements** — If 2 of 4 top picks are blocked, only 2 trades fire that day. Historical backtest (`rebuild_filter_sim.py`) proved replacements hurt PnL.
4. **DB audit trail** — Blocked stocks written to `shortsell_orders` with `isvalid='FALSE'`. Kotak order placer only picks up `isvalid='TRUE'` rows.

### Telegram Alert Format
Each morning the Telegram alert shows all 4 original ML predictions:
- ✅ Traded stocks — with entry price, qty, SL
- ⛔ Skipped stocks — same details + skip reason
- 📊 Market status — CRASH DAY / MONDAY / NORMAL DAY

---

## 📅 Adding New Features to the ML Model

We tested adding `nifty_940_pct`, `stock_940_pct`, and `day_of_week` as direct features
to the LightGBM model. Result:
- `nifty_940_pct` immediately became the **#1 most important feature** (4x stronger than any other)
- OOS 2026 improved marginally (+₹1.79L)
- But 2025 dropped sharply (-₹13.4L), making the 7-year total slightly worse
- **Conclusion:** Hard filters are more robust than letting the model learn these patterns

The current production setup uses the **original model + hard filters** as a safety net.
