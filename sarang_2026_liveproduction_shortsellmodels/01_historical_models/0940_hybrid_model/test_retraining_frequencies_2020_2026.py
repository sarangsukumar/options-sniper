#!/usr/bin/env python3
import os
import math
import time
import warnings
import numpy as np
import pandas as pd
import lightgbm as lgb
import pyarrow.parquet as pq
import pymysql
from compare_103L_vs_current_all_metrics import (
    PARQUET_TICKS,
    get_taxes,
    sim_s3_4stage_detailed,
    sim_s1_3min_detailed,
    compute_metrics
)

warnings.filterwarnings('ignore')

HIST_DATASET = '/home/ubuntu/sarang_verified_shorsellalgo_0940/data/0940_hybrid_dataset_from_scrapdata.csv'
PARQUET_NIFTY = '/home/ubuntu/trading2026/sarang_verified_shorsellalgo_0940/data/nifty50_ticks_cache.parquet'

PURE_DB_FEATURES = [
    'gap_0907_pct', 'gap_fade_0907_to_940_pct',
    'prev_intraday_vwap_gap', 'prev_intraday_return', 'prev_intraday_roc_last_hour',
    'morn_range_pct', 'rejection_wick',
    'ret_0940_vs_prev_close', 'crash_dip_bounce_risk', 'dip_zone_flag', 'rebound_interaction',
    'bear_mom_acceleration'
]

def select_option_a_picks(df_scored, nifty_vs_prev_close, min_price=50.0):
    picks = []
    for d_str, day_df in df_scored.groupby('date_str', sort=True):
        day_cands = day_df[day_df['short_entry_price'] >= min_price].sort_values('pred_return', ascending=False).reset_index(drop=True)
        if day_cands.empty:
            continue
        nifty_pct = nifty_vs_prev_close.get(d_str, 0.0)
        orig_top4 = day_cands.iloc[:4]
        passed = []
        r1_dropped = 0
        for idx, r in orig_top4.iterrows():
            spct = r['stock_pct_940']
            if spct < -1.5:
                r1_dropped += 1
                continue
            if nifty_pct < -0.5 and spct < -0.5:
                continue
            passed.append((int(r['year']), d_str, r['clean_stock'], float(r['short_entry_price'])))

        reps_allowed = min(4 - len(passed), r1_dropped)
        if reps_allowed > 0 and len(day_cands) > 4:
            reps_taken = 0
            for r_idx in range(4, min(6, len(day_cands))):
                cand = day_cands.iloc[r_idx]
                spct = cand['stock_pct_940']
                if spct < -0.5:
                    continue
                if nifty_pct < -0.5 and spct < -0.5:
                    continue
                passed.append((int(cand['year']), d_str, cand['clean_stock'], float(cand['short_entry_price'])))
                reps_taken += 1
                if reps_taken == reps_allowed or len(passed) == 4:
                    break
        picks.extend(passed)
    return picks

def main():
    t0 = time.time()
    print("1. Loading historical feature dataset & Nifty baseline...")
    df_feat = pd.read_csv(HIST_DATASET, low_memory=False)
    df_feat['clean_stock'] = df_feat['clean_stock'].astype(str).str.strip().str.upper()
    df_feat['date_dt'] = pd.to_datetime(df_feat['date_str'])
    df_feat['year'] = df_feat['date_dt'].dt.year
    df_feat['month'] = df_feat['date_dt'].dt.month
    df_feat['day'] = df_feat['date_dt'].dt.day
    df_feat = df_feat[df_feat['date_dt'].dt.dayofweek != 0].copy()  # Strict Monday exclusion
    df_feat['short_entry_price'] = pd.to_numeric(df_feat['short_entry_price'], errors='coerce').fillna(0.0)
    df_feat = df_feat[df_feat['short_entry_price'] >= 30.0].copy()  # Training universe >= Rs 30

    for c in ['gap_0907_pct', 'gap_fade_0907_to_940_pct', 'prev_intraday_return']:
        df_feat[c] = pd.to_numeric(df_feat[c], errors='coerce').fillna(0.0)
    df_feat['ret_0940_vs_prev_close'] = ((1.0 + df_feat['gap_0907_pct']/100.0) * (1.0 + df_feat['gap_fade_0907_to_940_pct']/100.0) - 1.0) * 100.0
    df_feat['crash_dip_bounce_risk'] = np.where((df_feat['prev_intraday_return'] < -2.5) & (df_feat['ret_0940_vs_prev_close'] < 0.0), 1.0, 0.0)
    df_feat['dip_zone_flag'] = np.where((df_feat['ret_0940_vs_prev_close'] >= -2.0) & (df_feat['ret_0940_vs_prev_close'] <= -1.0), 1.0, 0.0)
    df_feat['rebound_interaction'] = df_feat['prev_intraday_return'] * df_feat['ret_0940_vs_prev_close']
    df_feat['bear_mom_acceleration'] = df_feat['prev_intraday_return'] * df_feat['gap_fade_0907_to_940_pct']

    for f in PURE_DB_FEATURES:
        df_feat[f] = pd.to_numeric(df_feat[f], errors='coerce').fillna(0.0)
    df_feat['short_target'] = pd.to_numeric(df_feat['short_pct_return'], errors='coerce').fillna(0.0)
    df_feat['stock_pct_940'] = df_feat['gap_0907_pct'] + df_feat['gap_fade_0907_to_940_pct']

    # Nifty baseline
    df_nifty = pq.read_table(PARQUET_NIFTY).to_pandas()
    df_nifty['date_str'] = df_nifty['date_str'].astype(str)
    df_nifty['time_str'] = df_nifty['time_str'].astype(str)
    conn = pymysql.connect(host='localhost', user='root', password='root', database='markets', cursorclass=pymysql.cursors.DictCursor)
    with conn.cursor() as cur:
        cur.execute("SELECT date, time, open, close FROM scrapdata WHERE stockname = 'NIFTY 50' AND date >= '2026-10-12' ORDER BY date ASC, time ASC")
        db_nifty = pd.DataFrame(cur.fetchall())
    if not db_nifty.empty:
        db_nifty['date_str'] = db_nifty['date'].astype(str)
        db_nifty['time_str'] = pd.to_datetime(db_nifty['time']).dt.strftime('%H:%M:%S')
        df_nifty = pd.concat([df_nifty, db_nifty[['date_str', 'time_str', 'open', 'close']]], ignore_index=True)

    nifty_vs_prev_close = {}
    prev_nifty_close = None
    for d_str in sorted(df_nifty['date_str'].unique()):
        g = df_nifty[df_nifty['date_str'] == d_str].sort_values('time_str')
        open_p = float(g.iloc[0]['open'])
        close_p = float(g.iloc[-1]['close'])
        t940 = g[g['time_str'] >= '09:40:00']
        if len(t940) > 0:
            p940 = float(t940.iloc[0]['close'])
            if prev_nifty_close and prev_nifty_close > 0:
                nifty_vs_prev_close[d_str] = ((p940 - prev_nifty_close) / prev_nifty_close * 100.0)
            else:
                nifty_vs_prev_close[d_str] = ((p940 - open_p) / open_p * 100.0) if open_p > 0 else 0.0
        else:
            nifty_vs_prev_close[d_str] = 0.0
        prev_nifty_close = close_p

    # Define period keys for each retraining schedule across 2020-2026
    df_feat['half_id'] = df_feat['year'].astype(str) + '_H' + np.where(df_feat['month'] <= 6, '1', '2')
    df_feat['quarter_id'] = df_feat['year'].astype(str) + '_Q' + ((df_feat['month'] - 1) // 3 + 1).astype(str)
    df_feat['month_id'] = df_feat['date_str'].str.slice(0, 7)
    df_feat['biweek_id'] = df_feat['date_str'].str.slice(0, 7) + np.where(df_feat['day'] <= 15, '_B1', '_B2')

    schedules = [
        ("F1_YEARLY_EXP",    "Yearly Expanding (Jan 1 | 7 Retrains)",                  'year',       None, None),
        ("F2_HALFYEAR_EXP",  "Half-Yearly Expanding (6-Mo | 14 Retrains)",             'half_id',    None, None),
        ("F3_QUARTERLY_EXP", "Quarterly Expanding (3-Mo | 28 Retrains)",               'quarter_id', None, None),
        ("F4_MONTHLY_EXP",   "Monthly Expanding (1-Mo | 82 Retrains - Live Setup)",    'month_id',   None, None),
        ("F5_BIWEEKLY_EXP",  "Bi-Weekly Expanding (15-Day | 164 Retrains)",            'biweek_id',  None, None),
        ("F6_MONTHLY_ROLL4Y","Monthly 4-Yr Rolling Window (No Decay | 82 Retrains)",   'month_id',   4,    None),
        ("F7_MONTHLY_DECAY", "Monthly Expanding + 2-Yr Exp. Recency Weighting",        'month_id',   None, 730.0),
    ]

    lgb_params = dict(objective='regression', n_estimators=100, learning_rate=0.05, max_depth=5, random_state=42, n_jobs=-1, verbose=-1)

    schedule_picks = {}
    all_needed_keys = set()

    df_test_all = df_feat[df_feat['year'] >= 2020].copy()

    for key, label, grp_col, roll_yrs, half_life in schedules:
        t_s = time.time()
        periods = sorted(df_test_all[grp_col].unique())
        scored_chunks = []
        for p_val in periods:
            p_df = df_test_all[df_test_all[grp_col] == p_val].copy()
            min_dt = p_df['date_dt'].min()
            if roll_yrs is not None:
                cutoff_dt = min_dt - pd.Timedelta(days=int(roll_yrs * 365.25))
                tr_df = df_feat[(df_feat['date_dt'] < min_dt) & (df_feat['date_dt'] >= cutoff_dt)]
            else:
                tr_df = df_feat[df_feat['date_dt'] < min_dt]

            if tr_df.empty:
                continue

            mod = lgb.LGBMRegressor(**lgb_params)
            if half_life is not None:
                days_old = (min_dt - tr_df['date_dt']).dt.days.to_numpy(dtype=np.float64)
                weights = np.exp(-days_old / half_life)
                mod.fit(tr_df[PURE_DB_FEATURES], tr_df['short_target'], sample_weight=weights)
            else:
                mod.fit(tr_df[PURE_DB_FEATURES], tr_df['short_target'])

            p_df['pred_return'] = mod.predict(p_df[PURE_DB_FEATURES])
            scored_chunks.append(p_df)

        df_scored = pd.concat(scored_chunks, ignore_index=True)
        picks = select_option_a_picks(df_scored, nifty_vs_prev_close, min_price=50.0)
        schedule_picks[key] = picks
        for _, d_str, stk, _ in picks:
            all_needed_keys.add((d_str, stk))
        print(f"   ✔ {key:<18} ({len(periods):3d} fits in {time.time()-t_s:4.1f}s) -> {len(picks):,} trades selected")

    print(f"\n2. Total unique (date, stock) pairs across all 7 schedules: {len(all_needed_keys):,}")
    ticks_table = pq.read_table(PARQUET_TICKS, columns=['date_str', 'stock', 'time_str', 'open', 'high', 'low', 'close'])
    df_ticks = ticks_table.to_pandas()
    df_ticks['stock'] = df_ticks['stock'].astype(str).str.strip().str.upper()
    df_ticks['date_str'] = df_ticks['date_str'].astype(str)
    df_ticks = df_ticks[df_ticks['time_str'] >= '09:42:00'].copy()

    ticks_dict = {}
    for (d_str, stk), g in df_ticks.groupby(['date_str', 'stock']):
        if (d_str, stk) in all_needed_keys:
            g_sorted = g.sort_values('time_str')
            ticks_dict[(d_str, stk)] = (
                g_sorted['time_str'].to_numpy(),
                g_sorted['close'].to_numpy(dtype=np.float64),
                g_sorted['high'].to_numpy(dtype=np.float64),
                g_sorted['low'].to_numpy(dtype=np.float64)
            )

    missing_keys = all_needed_keys - set(ticks_dict.keys())
    print(f"   • Found {len(ticks_dict):,} in parquet cache; fetching {len(missing_keys):,} missing pairs from MySQL scrapdata...")

    if missing_keys:
        by_date = {}
        for d_str, stk in missing_keys:
            by_date.setdefault(d_str, []).append(stk)
        with conn.cursor() as cur:
            for idx_d, (d_str, stks) in enumerate(sorted(by_date.items())):
                placeholders = ','.join(['%s'] * len(stks))
                q = (
                    f"SELECT TRIM(stockname) as stock, TIME_FORMAT(TIME(time), '%%H:%%i:00') as min_tm, "
                    f"CAST(SUBSTRING_INDEX(GROUP_CONCAT( close ORDER BY time ASC ), ',', 1) AS DOUBLE) as o, "
                    f"MAX(CAST(price AS DOUBLE)) as h, "
                    f"MIN(CAST(price AS DOUBLE)) as l, "
                    f"CAST(SUBSTRING_INDEX(GROUP_CONCAT( price ORDER BY time DESC ), ',', 1) AS DOUBLE) as c "
                    f"FROM scrapdata WHERE date=%s AND stockname IN ({placeholders}) AND TIME(time) >= '09:42:00' AND TIME(time) <= '15:30:00' "
                    f"GROUP BY stockname, TIME_FORMAT(TIME(time), '%%H:%%i:00') ORDER BY min_tm ASC"
                )
                cur.execute(q, [d_str] + stks)
                rows = cur.fetchall()
                if rows:
                    df_r = pd.DataFrame(rows)
                    for stk_r, g in df_r.groupby('stock'):
                        stk_clean = str(stk_r).strip().upper()
                        ticks_dict[(d_str, stk_clean)] = (
                            g['min_tm'].to_numpy(),
                            g['c'].to_numpy(dtype=np.float64),
                            g['h'].to_numpy(dtype=np.float64),
                            g['l'].to_numpy(dtype=np.float64)
                        )
    conn.close()
    print(f"   ✔ Loaded ticks for {len(ticks_dict):,} / {len(all_needed_keys):,} pairs (Elapsed: {time.time()-t0:.1f}s)")

    # Pre-simulate every unique (date_str, stk) once for both 1B (11:00/12:30) and 1A (10:30/11:15)
    sim_cache_1B = {}
    sim_cache_1A = {}
    for d_str, stk in all_needed_keys:
        tks = ticks_dict.get((d_str, stk))
        if not tks or len(tks[0]) == 0:
            continue
        times, closes, highs, lows = tks
        ep = float(closes[0])
        if ep <= 0:
            continue
        q10 = max(1, int(1000000.0 / ep))
        sim_cache_1B[(d_str, stk)] = sim_s3_4stage_detailed(times, closes, highs, lows, q10, 2.25, 1.50, 1.00, '11:00:00', '12:30:00')
        sim_cache_1A[(d_str, stk)] = sim_s3_4stage_detailed(times, closes, highs, lows, q10, 2.25, 1.50, 1.00, '10:30:00', '11:15:00')

    base_set = set((d, s) for _, d, s, _ in schedule_picks['F1_YEARLY_EXP'])

    for mode_name, sim_cache in [
        ("LIVE MONITOR 4-STAGE ENGINE (1B: 2.25->1.50->1.00 | 11:00/12:30 Cutoffs | ₹10L/Stock)", sim_cache_1B),
        ("HISTORICAL 4-STAGE ENGINE (1A: 2.25->1.50->1.00 | 10:30/11:15 Cutoffs | ₹10L/Stock)", sim_cache_1A)
    ]:
        print("\n" + "=" * 150)
        print(f"📊 RETRAINING FREQUENCY COMPARISON — {mode_name}")
        print("=" * 150)
        all_m = {}
        for key, label, *_ in schedules:
            picks = schedule_picks[key]
            rows = []
            cur_set = set()
            for yr, d_str, stk, _ in picks:
                cur_set.add((d_str, stk))
                res = sim_cache.get((d_str, stk))
                if not res:
                    continue
                net, gross, tax, ex_r, has_l2 = res
                rows.append({
                    'year': yr,
                    'date': d_str,
                    'stock': stk,
                    'net_pnl': net,
                    'gross_pnl': gross,
                    'taxes': tax,
                    'exit_reason': ex_r,
                    'has_l2': has_l2
                })
            df_res = pd.DataFrame(rows)
            m = compute_metrics(df_res)
            m['overlap_pct'] = (len(cur_set & base_set) / len(cur_set) * 100.0) if cur_set else 0.0
            all_m[key] = m

        keys = [s[0] for s in schedules]
        hdr = f"{'Metric':<36} | " + " | ".join([f"{k:>16}" for k in keys])
        print(hdr)
        print("-" * len(hdr))

        metric_rows = [
            ("Total Trades Selected",            lambda m: f"{m['n_trades']:16,d}"),
            ("Trade Overlap vs Yearly (%)",      lambda m: f"{m['overlap_pct']:15.1f}%"),
            ("Gross PnL (₹ Lakhs)",              lambda m: f"₹{m['tot_gross_L']:+14.2f}L"),
            ("Total Taxes & Charges (₹ Lakhs)",  lambda m: f"-₹{m['tot_tax_L']:13.2f}L"),
            ("Total Net PnL (₹ Lakhs)",          lambda m: f"₹{m['tot_net_L']:+14.2f}L"),
            ("Net Edge vs Yearly Baseline",      lambda m: f"₹{m['tot_net_L'] - all_m['F1_YEARLY_EXP']['tot_net_L']:+14.2f}L"),
            ("Win Rate (%)",                     lambda m: f"{m['wr']:15.2f}%"),
            ("Profit Factor",                    lambda m: f"{m['pf']:16.2f}"),
            ("Avg Net PnL / Trade (₹)",          lambda m: f"₹{m['avg_trade']:+15,.0f}"),
            ("Avg Winning Trade (₹)",            lambda m: f"₹{m['avg_win']:+15,.0f}"),
            ("Avg Losing Trade (₹)",             lambda m: f"₹{m['avg_loss']:+15,.0f}"),
            ("Profitable Trading Days (%)",      lambda m: f"{m['daily_wr']:15.2f}%"),
            ("Max Portfolio Drawdown (₹L)",      lambda m: f"-₹{m['max_dd_L']:13.2f}L"),
            ("Longest Drawdown Duration (Days)", lambda m: f"{m['max_dd_days']:11d} days"),
            ("Sharpe Ratio (Annualized)",        lambda m: f"{m['sharpe']:16.2f}"),
            ("Sortino Ratio (Annualized)",       lambda m: f"{m['sortino']:16.2f}"),
            ("Calmar Ratio (Net PnL / MaxDD)",   lambda m: f"{m['calmar']:15.1f}x"),
            ("Stage 1 SL Exits (Count)",         lambda m: f"{m['sl_cnt']:16,d}"),
            ("Stage 2 / Stage 3 Exits",          lambda m: f"{m['s2_cnt']:7,d} / {m['s3_cnt']:6,d}"),
        ]
        for m_label, fn in metric_rows:
            print(f"{m_label:<36} | " + " | ".join([fn(all_m[k]) for k in keys]))

        print("-" * len(hdr))
        for y in [2020, 2021, 2022, 2023, 2024, 2025, 2026]:
            print(f"{f'Year {y} Net PnL (₹L)':<36} | " + " | ".join([f"₹{all_m[k]['yearly'].get(y, 0.0):+14.2f}L" for k in keys]))

if __name__ == '__main__':
    main()
