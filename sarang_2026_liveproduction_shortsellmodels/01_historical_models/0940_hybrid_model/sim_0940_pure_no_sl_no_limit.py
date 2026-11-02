#!/usr/bin/env python3
"""
Simulate Pure Baseline Performance of the 09:40 Hybrid Model (Half-Yearly Expanding Walk-Forward, 2020-2026):
1. PURE_HOLD_EOD (No Stop-Loss, No Limit/Target, No Profit Locks: Pure 09:42 Entry -> 15:24 EOD Exit)
2. FLAT_3PCT_SL  (3.0% Stop-Loss Only, No Limit/Target, Hold to 15:24 EOD)
3. FLAT_225_SL   (2.25% Stop-Loss Only, No Limit/Target, Hold to 15:24 EOD)
4. ACTIVE_4STAGE (4-Stage Exit Engine + 3.0% -> 1.5% -> 1.0% Dynamic SL at 11:00/12:30)
Also compares against the Unfiltered Universe Average (shorting all candidate stocks 09:42 -> 15:24).
"""
import os
import sys
import warnings
import numpy as np
import pandas as pd
import lightgbm as lgb
import pyarrow.parquet as pq
import pymysql

sys.path.insert(0, "/home/ubuntu/.gemini/antigravity-cli/brain/96b1a9e1-7f3a-45b5-bd8b-547d99588db7/scratch")
from compare_103L_vs_current_all_metrics import (
    PARQUET_TICKS,
    sim_s3_4stage_detailed,
    sim_s1_3min_detailed,
    compute_metrics
)
from test_retraining_frequencies_2020_2026 import (
    HIST_DATASET,
    PARQUET_NIFTY,
    PURE_DB_FEATURES,
    select_option_a_picks
)
sys.path.insert(0, "/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_shortsell_t1_2026/02_0942_Hybrid_Model/live_production")
from live_0940_hybrid_pipeline import compute_features

warnings.filterwarnings('ignore')


def sim_pure_eod_no_sl_no_limit(times, closes, qty):
    """Pure 09:42 Entry -> 15:24 EOD Exit. Zero SL (999%), Zero Limit/Target."""
    return sim_s1_3min_detailed(times, closes, qty, 999.0, 999.0, 999.0)


def main():
    print("1. Loading 2018-2026 feature dataset & appending latest Oct 2026 dates...")
    df_feat = pd.read_csv(HIST_DATASET, low_memory=False)
    df_feat['clean_stock'] = df_feat['clean_stock'].astype(str).str.strip().str.upper()
    df_feat['date_dt'] = pd.to_datetime(df_feat['date_str'])
    df_feat = df_feat[df_feat['date_dt'].dt.dayofweek != 0].copy()
    df_feat['short_entry_price'] = pd.to_numeric(df_feat['short_entry_price'], errors='coerce').fillna(0.0)
    df_feat = df_feat[df_feat['short_entry_price'] >= 30.0].copy()

    for c in ['gap_0907_pct', 'gap_fade_0907_to_940_pct', 'prev_intraday_return']:
        df_feat[c] = pd.to_numeric(df_feat[c], errors='coerce').fillna(0.0)
    df_feat['ret_0940_vs_prev_close'] = ((1.0 + df_feat['gap_0907_pct']/100.0) * (1.0 + df_feat['gap_fade_0907_to_940_pct']/100.0) - 1.0) * 100.0
    df_feat['crash_dip_bounce_risk'] = np.where((df_feat['prev_intraday_return'] < -2.5) & (df_feat['ret_0940_vs_prev_close'] < 0.0), 1.0, 0.0)
    df_feat['dip_zone_flag'] = np.where((df_feat['ret_0940_vs_prev_close'] >= -2.0) & (df_feat['ret_0940_vs_prev_close'] <= -1.0), 1.0, 0.0)
    df_feat['rebound_interaction'] = df_feat['prev_intraday_return'] * df_feat['ret_0940_vs_prev_close']
    df_feat['bear_mom_acceleration'] = df_feat['prev_intraday_return'] * df_feat['gap_fade_0907_to_940_pct']
    df_feat['stock_pct_940'] = df_feat['gap_0907_pct'] + df_feat['gap_fade_0907_to_940_pct']
    df_feat['short_target'] = pd.to_numeric(df_feat['short_pct_return'], errors='coerce').fillna(0.0)

    conn = pymysql.connect(host='localhost', user='root', password='root', database='markets', cursorclass=pymysql.cursors.DictCursor)
    max_hist_dt = str(df_feat['date_str'].max())
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT date FROM scrapdata WHERE date > %s ORDER BY date ASC", (max_hist_dt,))
        extra_dates = [str(r['date']) for r in cur.fetchall()]

    extra_dfs = []
    for t_dt in extra_dates:
        if pd.to_datetime(t_dt).dayofweek == 0:
            continue
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(date) as dt FROM scrapdata WHERE date < %s", (t_dt,))
            prev_dt = str(cur.fetchone()['dt'])
            cur.execute(f"""
                SELECT TRIM(BOTH '\"' FROM TRIM(BOTH \"'\" FROM TRIM(stockname))) as clean_stock,
                       time, CAST(price AS DECIMAL(10,2)) as price
                FROM scrapdata
                WHERE date = '{prev_dt}' AND isvalid = 'TRUE'
                  AND stockname NOT IN ('NIFTY 50', 'NIFTY BANK', 'NIFTY', 'BANKNIFTY', 'FINNIFTY')
                ORDER BY time ASC
            """)
            df_prev_ticks = pd.DataFrame(cur.fetchall())

            cur.execute(f"""
                SELECT TRIM(BOTH '\"' FROM TRIM(BOTH \"'\" FROM TRIM(stockname))) as clean_stock,
                       CAST(price AS DECIMAL(10,2)) as price_0907
                FROM scrapdata
                WHERE date = '{t_dt}' AND TIME(time) < '09:15:00' AND isvalid = 'TRUE'
            """)
            df_0907 = pd.DataFrame(cursor_rows := cur.fetchall())

            cur.execute(f"""
                SELECT TRIM(BOTH '\"' FROM TRIM(BOTH \"'\" FROM TRIM(stockname))) as clean_stock,
                       time, CAST(price AS DECIMAL(10,2)) as price
                FROM scrapdata
                WHERE date = '{t_dt}' AND TIME(time) >= '09:15:00' AND TIME(time) <= '09:40:00'
                  AND isvalid = 'TRUE'
                  AND stockname NOT IN ('NIFTY 50', 'NIFTY BANK', 'NIFTY', 'BANKNIFTY', 'FINNIFTY')
                ORDER BY time ASC
            """)
            df_morn_ticks = pd.DataFrame(cur.fetchall())

        macro = {'nifty_gap': 0.0, 'sp500_overnight_ret': 0.0, 'nikkei_gap': 0.0, 'nifty_vs_sp500_gap': 0.0, 'nifty_vs_nikkei_gap': 0.0}
        df_f = compute_features(df_prev_ticks, df_0907, df_morn_ticks, t_dt, set(), macro)
        df_f['short_entry_price'] = df_f['entry_price_0940']
        df_f['stock_pct_940'] = pd.to_numeric(df_f['actual_stock_pct_940'], errors='coerce').fillna(0.0)
        df_f['date_dt'] = pd.to_datetime(df_f['date_str'])
        df_f['short_target'] = 0.0
        extra_dfs.append(df_f)

    if extra_dfs:
        df_feat = pd.concat([df_feat, pd.concat(extra_dfs, ignore_index=True)], ignore_index=True)

    df_feat['year'] = pd.to_datetime(df_feat['date_str']).dt.year
    df_feat['month'] = pd.to_datetime(df_feat['date_str']).dt.month
    for f in PURE_DB_FEATURES:
        df_feat[f] = pd.to_numeric(df_feat[f], errors='coerce').fillna(0.0)

    # Unfiltered universe baseline stats (2020-2026)
    df_univ_20_26 = df_feat[(df_feat['year'] >= 2020) & (df_feat['short_entry_price'] >= 50.0) & (df_feat['date_str'] <= '2026-10-23')].copy()
    univ_wr = (df_univ_20_26['short_target'] > 0).mean() * 100.0
    univ_avg_ret = df_univ_20_26['short_target'].mean()

    # Nifty @ 09:40
    df_nifty = pq.read_table(PARQUET_NIFTY).to_pandas()
    df_nifty['date_str'] = df_nifty['date_str'].astype(str)
    df_nifty['time_str'] = df_nifty['time_str'].astype(str)
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

    print("2. Training Half-Yearly (6M) Walk-Forward 09:40 Model across 2020-2026...")
    lgb_params = dict(objective='regression', n_estimators=100, learning_rate=0.05, max_depth=5, random_state=42, n_jobs=-1, verbose=-1)
    oos_chunks = []
    for yr in range(2020, 2027):
        for h_idx, (m_start, m_end, cutoff_str) in enumerate([
            (1, 6, f"{yr}-01-01"),
            (7, 12, f"{yr}-07-01")
        ], start=1):
            tr = df_feat[df_feat['date_str'] < cutoff_str]
            te = df_feat[(df_feat['year'] == yr) & (df_feat['month'] >= m_start) & (df_feat['month'] <= m_end)].copy()
            if len(tr) == 0 or len(te) == 0:
                continue
            mod = lgb.LGBMRegressor(**lgb_params)
            mod.fit(tr[PURE_DB_FEATURES], tr['short_target'])
            te['pred_return'] = mod.predict(te[PURE_DB_FEATURES])
            oos_chunks.append(te)

    df_oos = pd.concat(oos_chunks, ignore_index=True)
    picks = select_option_a_picks(df_oos, nifty_vs_prev_close, min_price=50.0)
    needed_keys = set((d, s) for _, d, s, _ in picks)

    print(f"3. Loading 1-minute ticks for {len(needed_keys):,} selected OOS trades (2020-2026)...")
    ticks_table = pq.read_table(
        PARQUET_TICKS,
        columns=['date_str', 'stock', 'time_str', 'open', 'high', 'low', 'close']
    )
    df_ticks = ticks_table.to_pandas()
    df_ticks['stock'] = df_ticks['stock'].astype(str).str.strip().str.upper()
    df_ticks['date_str'] = df_ticks['date_str'].astype(str)
    df_ticks = df_ticks[df_ticks['time_str'] >= '09:42:00'].copy()

    ticks_dict = {}
    for (d_str, stk), g in df_ticks.groupby(['date_str', 'stock']):
        if (d_str, stk) in needed_keys:
            g_sorted = g.sort_values('time_str')
            ticks_dict[(d_str, stk)] = (
                g_sorted['time_str'].to_numpy(),
                g_sorted['close'].to_numpy(dtype=np.float64),
                g_sorted['high'].to_numpy(dtype=np.float64),
                g_sorted['low'].to_numpy(dtype=np.float64)
            )

    missing_keys = needed_keys - set(ticks_dict.keys())
    if missing_keys:
        by_date = {}
        for d_str, stk in missing_keys:
            by_date.setdefault(d_str, []).append(stk)
        with conn.cursor() as cur:
            for d_str, stks in sorted(by_date.items()):
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

    # Simulate all 4 exit modes for the exact same Half-Yearly ML picks
    modes = {
        '1_PURE_NO_SL_NO_LIMIT': [],
        '2_FLAT_3PCT_SL_ONLY':   [],
        '3_FLAT_225_SL_ONLY':    [],
        '4_ACTIVE_4STAGE_3PCT':  [],
    }

    raw_returns_pct = []
    max_adverse_pct = []

    for yr, d_str, stk, _ in picks:
        tks = ticks_dict.get((d_str, stk))
        if not tks or len(tks[0]) == 0:
            continue
        times, closes, highs, lows = tks
        ep = float(closes[0])
        if ep <= 0:
            continue
        q10 = max(1, int(1000000.0 / ep))

        # 1. Pure Hold 09:42 -> 15:24 (Zero SL, Zero Limit)
        r_pure = sim_pure_eod_no_sl_no_limit(times, closes, q10)
        # Track raw unstopped return % and worst intraday spike %
        eod_p = ep - (r_pure[1] / q10)
        raw_returns_pct.append((ep - eod_p) / ep * 100.0)
        max_adverse_pct.append((np.max(highs) - ep) / ep * 100.0)

        # 2. Flat 3.0% SL (3-min / bar close, no profit locks)
        r_3sl = sim_s1_3min_detailed(times, closes, q10, 3.00, 3.00, 3.00)
        # 3. Flat 2.25% SL (3-min / bar close, no profit locks)
        r_225sl = sim_s1_3min_detailed(times, closes, q10, 2.25, 2.25, 2.25)
        # 4. Active 4-Stage + 3.0% -> 1.5% -> 1.0% Dynamic SL
        r_4stg = sim_s3_4stage_detailed(times, closes, highs, lows, q10, 3.00, 1.50, 1.00, '11:00:00', '12:30:00')

        for k, res in [
            ('1_PURE_NO_SL_NO_LIMIT', r_pure),
            ('2_FLAT_3PCT_SL_ONLY',   r_3sl),
            ('3_FLAT_225_SL_ONLY',    r_225sl),
            ('4_ACTIVE_4STAGE_3PCT',  r_4stg),
        ]:
            modes[k].append({
                'year': yr,
                'date': d_str,
                'stock': stk,
                'net_pnl': res[0],
                'gross_pnl': res[1],
                'taxes': res[2],
                'exit_reason': res[3],
                'has_l2': res[4]
            })

    dfs = {k: pd.DataFrame(v) for k, v in modes.items()}
    metrics = {k: compute_metrics(dfs[k]) for k in modes.keys()}

    print("\n" + "=" * 135)
    print("🔬 LAYER 1: UNFILTERED MARKET UNIVERSE vs 09:40 ML MODEL PURE DIRECTIONAL ALPHA (09:42 -> 15:24, ZERO SL, ZERO LIMIT)")
    print("=" * 135)
    raw_arr = np.array(raw_returns_pct)
    adv_arr = np.array(max_adverse_pct)
    print(f"• Unfiltered F&O Universe (241,000+ stock-days, 09:42->15:24): Win Rate = {univ_wr:.2f}% | Avg Short Return = {univ_avg_ret:+.4f}%/trade")
    print(f"• 09:40 ML Top-4 Selection (5,263 trades, 09:42->15:24 Pure) : Gross Win Rate = {(raw_arr>0).mean()*100:.2f}% | Net Win Rate (after taxes) = {metrics['1_PURE_NO_SL_NO_LIMIT']['wr']:.2f}%")
    print(f"• 09:40 ML Pure Unstopped Return per Trade (09:42->15:24)    : Avg Gross = {raw_arr.mean():+.3f}% (+{raw_arr.mean()*100:.1f} bps) | Median = {np.median(raw_arr):+.3f}%")
    print(f"• Tail Risk Without SL (Max Intraday Squeeze vs Entry)       : 95th Pct = +{np.percentile(adv_arr, 95):.2f}% | 99th Pct = +{np.percentile(adv_arr, 99):.2f}% | Worst Single Squeeze = +{adv_arr.max():.2f}% (Net Loss ₹{dfs['1_PURE_NO_SL_NO_LIMIT']['net_pnl'].min():,.0f})")

    print("\n" + "=" * 135)
    print("📊 LAYER 2: 7-YEAR OOS COMPARISON (2020-2026 | ₹10L/Stock): PURE NO-SL/NO-LIMIT vs FLAT SL vs 4-STAGE DYNAMIC SL")
    print("=" * 135)
    keys = list(modes.keys())
    hdr = f"{'Metric':<36} | " + " | ".join([f"{k:>22}" for k in keys])
    print(hdr)
    print("-" * len(hdr))
    rows_to_print = [
        ("Total OOS Trades (2020-2026)",     lambda m: f"{m['n_trades']:22,d}"),
        ("Gross PnL Before Taxes (₹ Lakhs)", lambda m: f"₹{m['tot_gross_L']:+20.2f}L"),
        ("Total Kotak Taxes (₹ Lakhs)",      lambda m: f"-₹{m['tot_tax_L']:19.2f}L"),
        ("Total Net PnL (₹ Lakhs)",          lambda m: f"₹{m['tot_net_L']:+20.2f}L"),
        ("Net PnL @ ₹7.5L Live Scale (₹L)",  lambda m: f"₹{m['tot_net_L']*0.75:+20.2f}L"),
        ("Net Trade Win Rate (%)",           lambda m: f"{m['wr']:21.2f}%"),
        ("Profit Factor",                    lambda m: f"{m['pf']:22.2f}"),
        ("Avg Net PnL / Trade (₹)",          lambda m: f"₹{m['avg_trade']:+21,.0f}"),
        ("Avg Winning Trade (₹)",            lambda m: f"₹{m['avg_win']:+21,.0f}"),
        ("Avg Losing Trade (₹)",             lambda m: f"₹{m['avg_loss']:+21,.0f}"),
        ("Profitable Trading Days (%)",      lambda m: f"{m['daily_wr']:21.2f}%"),
        ("Max Portfolio Drawdown (₹L)",      lambda m: f"-₹{m['max_dd_L']:19.2f}L"),
        ("Longest Drawdown Duration (Days)", lambda m: f"{m['max_dd_days']:17d} days"),
        ("Sharpe Ratio (Annualized)",        lambda m: f"{m['sharpe']:22.2f}"),
        ("Sortino Ratio (Annualized)",       lambda m: f"{m['sortino']:22.2f}"),
        ("Calmar Ratio (Net PnL / MaxDD)",   lambda m: f"{m['calmar']:21.1f}x"),
    ]
    for label, fn in rows_to_print:
        print(f"{label:<36} | " + " | ".join([fn(metrics[k]) for k in keys]))

    print("-" * len(hdr))
    for yr in range(2020, 2027):
        vals = []
        for k in keys:
            y_net = dfs[k][dfs[k]['year'] == yr]['net_pnl'].sum() / 1e5
            y_wr = (dfs[k][dfs[k]['year'] == yr]['net_pnl'] > 0).mean() * 100.0
            vals.append(f"₹{y_net:+7.2f}L ({y_wr:4.1f}%)")
        print(f"{f'Year {yr} Net PnL (₹10L) [WR%]':<36} | " + " | ".join([f"{v:>22}" for v in vals]))

    print("-" * len(hdr))
    for p_label, start_d in [
        ("2026-H2 OOS (Jul 1 - Oct 30)", "2026-07-01"),
        ("Last Week (Oct 27 - Oct 30)",  "2026-10-27"),
    ]:
        vals = []
        for k in keys:
            sub = dfs[k][dfs[k]['date'] >= start_d]
            p_net = sub['net_pnl'].sum() / 1e5
            p_wr = (sub['net_pnl'] > 0).mean() * 100.0
            vals.append(f"₹{p_net:+7.2f}L ({p_wr:4.1f}%)")
        print(f"{p_label:<36} | " + " | ".join([f"{v:>22}" for v in vals]))

if __name__ == '__main__':
    main()
