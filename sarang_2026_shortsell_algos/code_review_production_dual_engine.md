# Code Review: `run_production_dual_engine.py`
### Reviewed By: Staff Engineer · Senior Developer · Quantitative Data Analyst

> **Verdict: ⚠️ NOT READY FOR LIVE PRODUCTION — Requires Critical Fixes Before Deployment**

---

## 🔴 CRITICAL Issues

| # | Finding | Perspective | Line(s) | Category | Description | Criticality | Remediation |
|---|---------|-------------|---------|----------|-------------|-------------|-------------|
| C1 | **Root DB Credentials Hardcoded** | Staff Eng | L44–51 | Security | `user='root', password='root'` exposed in plaintext source code. Anyone with repo access has full MySQL root access. | 🔴 CRITICAL | Move to environment variables (`os.environ['DB_USER']`), `.env` file, or secrets manager (HashiCorp Vault / AWS Secrets). Never commit credentials. |
| C2 | **Lookahead Bias in Rolling T-1 Indicators** | Data Analyst | L94–101 | Data Leakage | `dist_52w_high` uses `rolling(252)` computed on the **full dataframe** before walk-forward splits. Future data (dates after the current training cutoff) is included in the rolling window, contaminating training features with forward information. Same applies to `sma20`, `rsi14`, `vol_5d`. | 🔴 CRITICAL | Recompute all rolling indicators **strictly within each walk-forward training fold**, using only data available at that cutoff date. |
| C3 | **Target Label Source Unknown / Potential Circular Reference** | Data Analyst | L141 | Data Leakage | `y_train = df_train['y'].values` — the `y` column is precomputed in `feature_matrix_0938_short.csv`. If `y` is derived from the same 09:38–14:45 PnL column used in simulation, training targets and backtest evaluation are computed from the same tick source, creating a circular reference. Origin of `y` is undocumented. | 🔴 CRITICAL | Audit `y` column construction in `step1_build_0938_feature_matrix.py`. Document it explicitly. Ensure `y` is computed from the EOD (14:45) outcome on day T, not from any data available post-09:38. |
| C4 | **Simulation Entry Price Assumption (Optimistic Fill)** | Data Analyst | L236 | Sim Bias | Entry price `ep = c_arr[e_idx]` uses the **close** of the 09:38 candle. In live trading, a short-sell market order placed at 09:38 fills at the **prevailing ask**, not the 1-minute candle close, which could be 0.1%–0.5% better or worse. For liquid F&O this matters. | 🔴 CRITICAL | Use `open_arr[e_idx + 1]` (next candle open) as realistic entry price — standard practice in intraday backtesting. Add a `SLIPPAGE_BPS = 5` parameter. |
| C5 | **Stop-Loss Fill at Exact Trigger Price (No Slippage)** | Data Analyst | L250–251, L282–284 | Sim Bias | When `h_arr[i] >= sl_p`, the exit is recorded at exactly `sl_p`. In real fast markets, stop-loss orders can trigger but fill 0.3%–1.0% worse (stop-loss slippage). Optimistic exits overstate backtest PnL. | 🔴 CRITICAL | Apply stop-loss slippage: `xp = sl_p * (1 + SLIPPAGE_BPS / 10000)` for shorts (buy-back higher than stop). |
| C6 | **No Model Persistence — Full Retrain Every Run** | Staff Eng | L144–166 | Production | All three ML models are retrained from scratch on every execution (~8 minutes). Live production requires: (a) saving models at end of day, (b) loading yesterday's model for morning signal, (c) only retraining on weekly/monthly schedule. | 🔴 CRITICAL | Use `joblib.dump(model, path)` / `joblib.load(path)`. Separate training pipeline from inference pipeline. |
| C7 | **Fallback to Pre-Computed `sellprice`/`buyprice`** | Senior Dev | L324–326, L370–371 | Data Leakage | When MySQL tick data is unavailable (`t_dict` is None), code silently falls back to `row['sellprice']` and `row['buyprice']` — columns from the pre-computed base matrix. These are the **same prices used to compute the `y` label**. This means missing-tick trades get their PnL computed without any execution uncertainty, inflating those trades' PnL artificially. | 🔴 CRITICAL | Log and **skip** trades when tick data is unavailable rather than falling back to pre-computed prices. Count missing ticks as a data quality metric. |

---

## 🟠 HIGH Severity Issues

| # | Finding | Perspective | Line(s) | Category | Description | Severity | Remediation |
|---|---------|-------------|---------|----------|-------------|----------|-------------|
| H1 | **`mkt_mean_morn_ret` Uses Full Day Universe** | Data Analyst | L77–80 | Lookahead | Cross-sectional market mean is computed across all stocks present in the data for that day — including stocks not in the live trading universe. In live production, your universe is smaller and changes daily. | 🟠 HIGH | Filter `df` to only F&O permitted, liquid, above-average-volume stocks before computing cross-sectional aggregates. |
| H2 | **`warnings.filterwarnings('ignore')`** | Senior Dev | L29 | Code Quality | Silences ALL warnings globally — including critical pandas `SettingWithCopyWarning`, LightGBM convergence warnings, and numpy overflow warnings. Real bugs are being hidden. | 🟠 HIGH | Remove. Replace with targeted suppression only for known false positives: `warnings.filterwarnings('ignore', category=UserWarning, module='lightgbm')`. |
| H3 | **No Connection Pooling or Retry Logic in MySQL Fetcher** | Staff Eng | L188–212 | Resilience | Each of 16 ThreadPoolExecutor workers opens a fresh `pymysql.connect()`. If MySQL drops a connection mid-batch (common under high load), the exception propagates unhandled, crashing the entire run with no retry. | 🟠 HIGH | Implement connection retry with exponential backoff. Use `SQLAlchemy` connection pool or `tenacity` retry decorator. |
| H4 | **Ensemble Weights Hardcoded (0.45 / 0.35 / 0.20)** | Data Analyst | L170–174 | Hardcoding | Ensemble weights are fixed constants with no empirical justification or calibration. They were likely manually tuned on the same dataset, introducing another layer of in-sample overfitting. | 🟠 HIGH | Calibrate weights using a held-out validation set (e.g., 2018–2019) or use a meta-learner (stacked generalization). Store weights in a config file. |
| H5 | **Conviction Gap Threshold (0.035) Hardcoded** | Data Analyst | L356 | Hardcoding | The `0.035` probability gap threshold for Solo Rank 1 selection was empirically tuned on the same backtest dataset. In live conditions, probability gaps from LightGBM are not calibrated and will shift with market regime. | 🟠 HIGH | Calibrate this threshold on a separate hold-out period. Use probability calibration (`CalibratedClassifierCV`) before applying hard thresholds. |
| H6 | **Ratchet Profit Lock Uses Candle LOW, Exit at CLOSE** | Data Analyst | L279, L301–303 | Sim Bias | Ratchet activation uses `candle_LOW` to compute profit (optimistic — the low isn't the traded price). But ratchet stop is triggered by `close >= ratchet_stop`. These use different prices for activation vs. exit, creating an internally inconsistent simulation. | 🟠 HIGH | Use a single consistent price for both: either mid-candle `(h+l)/2` or require both activation and stop trigger to use close prices. |
| H7 | **Combined Portfolio Double-Counts Overlapping Trades** | Data Analyst | L431–433 | Methodology | When the same stock is selected by both Algo 1 and Algo 2 on the same day, the combined portfolio runs two short positions on that stock simultaneously. The 0.5 PnL scaling makes this look like one trade but the risk exposure is actually 2×. | 🟠 HIGH | Deduplicate overlapping trades in the combined portfolio: if both algos select the same stock/date, count it once with averaged parameters. |
| H8 | **Modern Calmar Resets Equity Curve to Zero in 2020** | Data Analyst | L403–408 | Metric Bias | Computing modern drawdown by `daily_modern['cum_pnl'].cumsum()` starts from 0 in Jan 2020, ignoring accumulated equity from 2016–2019. A strategy that was deeply in drawdown entering 2020 would show an artificially low modern drawdown. | 🟠 HIGH | Either: (a) carry forward the pre-2020 cumulative PnL baseline, or (b) document clearly that Calmar is a regime-specific metric only. |

---

## 🟡 MEDIUM Severity Issues

| # | Finding | Perspective | Line(s) | Category | Description | Severity | Remediation |
|---|---------|-------------|---------|----------|-------------|----------|-------------|
| M1 | **Initial Model Probabilities Set to 0.5 (Dummy Init)** | Senior Dev | L125–127 | Init/Default | Rows in the warmup period (first 12 months) never get model probabilities; they retain the dummy `0.5` value. If any of these rows accidentally make it into evaluation (e.g., edge date cases), they'd receive random rank. | 🟡 MEDIUM | Explicitly filter out rows with `prob_lgb_standard == 0.5` as a post-training data quality check. Or flag them as `WARMUP_PERIOD = True`. |
| M2 | **`fillna(0.0)` on All Features Silently** | Senior Dev | L117–118 | Default/Assumption | Replacing all NaN feature values with `0.0` is a strong assumption. For some features (e.g., `stock_short_wr10` — win rate over last 10 trades), `0.0` means a 0% win rate, which is very different from "no data". | 🟡 MEDIUM | Use feature-specific imputation: `stock_short_wr10` → use median imputation, volatility features → use cross-sectional median. Track NaN rates as a monitoring metric. |
| M3 | **`stock_vol_5d_t1.fillna(1.0)` Arbitrary Default** | Data Analyst | L91 | Default/Assumption | A stock with no volatility history defaults to 1.0% daily volatility. This directly affects both signal scores and the synth_idio feature without any empirical basis. | 🟡 MEDIUM | Use market-wide median volatility (e.g., 1.5–2.0% for NSE F&O universe) as the imputed value, not a fixed constant. |
| M4 | **Time Parsing Inline One-Liner (Fragile)** | Senior Dev | L230, L259 | Code Quality | The time parsing is a complex one-liner that handles 3 different formats. Format assumptions could fail if MySQL returns `datetime.timedelta` objects (common with some drivers), causing silent wrong-time parsing. | 🟡 MEDIUM | Extract into a dedicated `parse_time(t) -> datetime.time` function with explicit format handling and an `else: raise ValueError(f"Unknown time format: {type(t)}")` guard. |
| M5 | **16 Hardcoded ThreadPoolExecutor Workers** | Staff Eng | L216 | Scalability | `max_workers=16` is hardcoded regardless of system CPU count or MySQL connection limits. On a 4-core machine this creates contention; on a shared DB server it could exhaust the connection pool. | 🟡 MEDIUM | Use `min(16, os.cpu_count() * 2, DB_MAX_CONNECTIONS)` dynamically. Make `MAX_WORKERS` a configurable constant. |
| M6 | **Synth_Idio Coefficient 1.2 Hardcoded** | Data Analyst | L74 | Hardcoding | The beta coefficient `1.2` in `synth_idio = tanh((stock_ret - 1.2 * nifty_ret) * 1.2)` approximates the average F&O stock beta. Real betas vary by stock and regime. Using a flat 1.2 introduces systematic bias for low-beta and high-beta stocks. | 🟡 MEDIUM | Compute per-stock rolling 60-day beta vs Nifty from `price_1525_prev` history and use that. |
| M7 | **No Logging Framework — Only `print()` Statements** | Staff Eng | Throughout | Observability | All operational output uses `print()`. In production: no log levels, no timestamps, no log file rotation, no alerting integration, no structured logging for dashboards. | 🟡 MEDIUM | Replace with Python `logging` module. Configure `INFO`/`WARNING`/`ERROR` levels. Use `logging.FileHandler` for persistent logs. |
| M8 | **`nifty_ret_1d` Threshold 0.3% for Market Sizing** | Data Analyst | L313–314 | Hardcoding | The 0.3% threshold for classifying days as "bullish" vs "neutral" vs "bearish" is arbitrary. Nifty volatility varies: 0.3% is very tight in high-vol regimes and overly broad in low-vol regimes. | 🟡 MEDIUM | Use a regime-adaptive threshold: e.g., `0.5 * rolling_std(nifty_ret_1d, 20)` so the threshold dynamically adjusts to current market volatility. |

---

## 🟢 LOW Severity Issues

| # | Finding | Perspective | Line(s) | Category | Description | Severity | Remediation |
|---|---------|-------------|---------|----------|-------------|----------|-------------|
| L1 | **`warnings.filterwarnings('ignore')` removes `SettingWithCopyWarning`** | Senior Dev | L29 | Code Quality | The code has multiple potential `SettingWithCopyWarning` sites (modifying slices of DataFrames). These are suppressed silently. | 🟢 LOW | Enable warnings during development. Use `.copy()` consistently. |
| L2 | **No Input Data Validation** | Senior Dev | L55 | Robustness | `pd.read_csv(BASE_MATRIX_CSV)` has no schema validation. If columns are missing or types change, the error surface is deep in the code at runtime. | 🟢 LOW | Add `assert set(FEATURE_COLS).issubset(df.columns)` before processing and validate key column dtypes. |
| L3 | **Combined PnL Scaling by 0.5 is NOT Capital-Equivalent** | Data Analyst | L433 | Methodology | Scaling PnL by 0.5 assumes you deploy exactly 50% of capital to each algo. But with dynamic lot sizes and varying trades per day, the real capital allocation is unequal. | 🟢 LOW | Document this assumption explicitly in code comments. Build a proper capital-weighted combination. |
| L4 | **No Unit Tests** | Staff Eng | — | Testability | Zero unit tests, zero integration tests, zero assertions. A change to any upstream CSV schema or DB query would produce wrong results silently. | 🟢 LOW | Add `pytest` tests for `sim_algo1_trade`, `sim_algo2_trade`, `compute_strategy_metrics` with known-answer inputs. |
| L5 | **`MIN_TRAIN_MONTHS = 12` Warmup May Be Too Short** | Data Analyst | L123 | Methodology | 12 months of training data (~250 trading days × ~90 stocks = ~22,500 rows) may be insufficient for LightGBM with 34 features and `num_leaves=31`. Risk of high variance in early OOS predictions. | 🟢 LOW | Benchmark warmup period sensitivity: try 18 and 24 months and compare OOS Calmar. |

---

## Production Readiness Summary

| Dimension | Current State | Required State | Gap |
|-----------|--------------|----------------|-----|
| **Security** | Root DB password in code | Secrets manager / env vars | 🔴 CRITICAL |
| **Lookahead Bias** | Rolling features computed on full data | Strict fold-by-fold computation | 🔴 CRITICAL |
| **Fill Assumptions** | Close price entry, exact stop fills | Next-open entry + slippage model | 🔴 CRITICAL |
| **Model Persistence** | Full retrain every run (~8 min) | Load pre-trained model for morning inference | 🔴 CRITICAL |
| **Tick Fallback** | Falls back to pre-computed PnL prices | Skip missing-tick trades, log/alert | 🔴 CRITICAL |
| **Fault Tolerance** | No retries, no circuit breakers | Retry with backoff, graceful degradation | 🟠 HIGH |
| **Observability** | Only print() statements | Structured logging, alerting | 🟠 HIGH |
| **Test Coverage** | Zero tests | Unit + integration tests for sim functions | 🟡 MEDIUM |
| **Configuration** | Magic numbers throughout | YAML/JSON config file | 🟡 MEDIUM |
| **Capital Accounting** | PnL × 0.5 proxy | Proper capital-weighted combination | 🟡 MEDIUM |

---

## Developer Recommendation

> **Before considering any live capital deployment:**
>
> 1. **Fix C1 immediately** — rotate the root MySQL password and remove from source code.
> 2. **Fix C2 before trusting any backtest result** — the lookahead contamination in rolling features inflates all historical metrics. The true out-of-sample performance may be materially lower.
> 3. **Fix C3 before trusting the model** — audit the `y` column construction to verify it has no post-09:38 information.
> 4. **Fix C4 + C5 (slippage)** — expect 0.5–1.0 L per year reduction in stated PnL once realistic fill assumptions are applied.
> 5. **Fix C6 (model persistence)** — the current pipeline cannot produce live morning signals in time for 09:38 execution.
> 6. **Fix C7 (fallback)** — the silent fallback to pre-computed prices is a data integrity violation.

---

## Files Reviewed

- [`run_production_dual_engine.py`](file:///c:/models2026/production_ready_two_shortsell_algos/run_production_dual_engine.py) — Main pipeline (475 lines)
- [`algo1_0938_microstructure_short.py`](file:///c:/models2026/production_ready_two_shortsell_algos/algo1_0938_microstructure_short.py) — Algo 1 standalone
- [`algo2_0938_dynamic_threshold_ratchet.py`](file:///c:/models2026/production_ready_two_shortsell_algos/algo2_0938_dynamic_threshold_ratchet.py) — Algo 2 standalone
