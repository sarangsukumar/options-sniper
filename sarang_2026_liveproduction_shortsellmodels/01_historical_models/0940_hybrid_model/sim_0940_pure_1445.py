#!/usr/bin/env python3
"""
Verify exact 14:45:00 end-time simulation for 09:40 Hybrid Model (2020-2026 Half-Yearly Walk-Forward):
1. Check max time_str in PARQUET_TICKS
2. Explicitly filter all intraday ticks to time_str <= '14:45:00'
3. Compare:
   - Mode 1: Pure Hold (09:42 -> 14:45:00, Zero SL, Zero Limit/Target)
   - Mode 2: Pure Hold + 14:30 Discount Limit -> 14:45:00 Hard Exit (Zero SL, No Stage 2/3 Locks)
   - Mode 3: Flat 3.00% SL Only (09:42 -> 14:45:00, Zero Limit/Target)
   - Mode 4: Flat 2.25% SL Only (09:42 -> 14:45:00, Zero Limit/Target)
   - Mode 5: Exact Live 4-Stage Engine (3.00%->1.50%->1.00% Dyn SL + Stage 2/3 Locks + 14:45:00 Hard Exit)
   - Mode 6: 4-Stage Engine (sim_s3_4stage_detailed with 14:45:00 Hard Exit)
"""
import os
import sys
import math
import warnings
import numpy as np
import pandas as pd
import lightgbm as lgb
import pyarrow.parquet as pq
import pymysql

sys.path.insert(0, "/home/ubuntu/.gemini/antigravity-cli/brain/96b1a9e1-7f3a-45b5-bd8b-547d99588db7/scratch")
from compare_103L_vs_current_all_metrics import (
    PARQUET_TICKS,
    get_taxes,
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


def sim_pure_1445(times, closes, highs, lows, qty):
    """Pure 09:42 Entry -> 14:45:00 Exit. Zero SL, Zero Limit."""
    ep = closes[0]
    ex_p = closes[-1]
    for i in range(len(times)):
        if times[i] >= '14:45:00':
            ex_p = closes[i]
            break
    gross = (ep - ex_p) * qty
    tax = get_taxes(qty, ep, ex_p)
    net = gross - tax
    return round(net, 2), round(gross, 2), round(tax, 2), 'TIME_1445', False


def sim_flat_sl_1445(times, closes, qty, sl_pct):
    """Flat SL (3-min consecutive breach) + 14:45:00 Hard Exit. Zero Limit."""
    ep = closes[0]
    sl_p = round(ep * (1.0 + sl_pct / 100.0), 2)
    breach = 0
    ex_p, ex_r = closes[-1], 'TIME_1445'
    for i in range(len(times)):
        tm = times[i]
        p = closes[i]
        if p >= sl_p:
            breach += 1
            if breach >= 3:
                ex_p, ex_r = p, 'STAGE1_SL'
                break
        else:
            breach = 0
        if tm >= '14:45:00':
            ex_p, ex_r = p, 'TIME_1445'
            break
    gross = (ep - ex_p) * qty
    tax = get_taxes(qty, ep, ex_p)
    net = gross - tax
    return round(net, 2), round(gross, 2), round(tax, 2), ex_r, False


def run_leg2_1445(times, closes, highs, lows, exit_idx, ep, leg1_exit_p, qty, end_time='14:45:00'):
    reentry_p = round(leg1_exit_p * 1.0050, 2)
    l2_idx, l2_ep = None, None
    n = len(times)
    for j in range(exit_idx + 1, n):
        if times[j] >= '14:00:00':
            break
        if highs[j] >= reentry_p:
            l2_ep = reentry_p
            l2_idx = j
            break
    if l2_ep is None:
        return 0.0, 0.0, 0.0, False
    tp2_p = round(l2_ep * (1.0 - 0.0175), 2)
    sl2_p = ep
    l2_ex_p = closes[-1]
    for k in range(l2_idx + 1, n):
        if highs[k] >= sl2_p:
            l2_ex_p = sl2_p
            break
        if lows[k] <= tp2_p:
            l2_ex_p = tp2_p
            break
        if times[k] >= end_time:
            l2_ex_p = closes[k]
            break
    gross2 = (l2_ep - l2_ex_p) * qty
    tax2 = get_taxes(qty, l2_ep, l2_ex_p)
    net2 = gross2 - tax2
    return round(net2, 2), round(gross2, 2), round(tax2, 2), True


def sim_4stage_custom_end(times, closes, highs, lows, qty, sl_t1, sl_t2, sl_t3, c1='11:00:00', c2='12:30:00', end_time='14:45:00'):
    ep = closes[0]
    stage = 1
    max_prof = 0.0
    breach = 0
    n = len(times)
    ex_p, ex_r, ex_idx, ex_tm = closes[-1], 'TIME_EXIT', n - 1, times[-1]
    for i in range(n):
        tm = times[i]
        p = closes[i]
        h = highs[i]
        l = lows[i]

        if stage == 1:
            if tm < c1:
                sl_pct = sl_t1
            elif tm < c2:
                sl_pct = sl_t2
            else:
                sl_pct = sl_t3
            sl_p = round(ep * (1.0 + sl_pct / 100.0), 2)
            if p >= sl_p:
                breach += 1
                if breach >= 3:
                    ex_p, ex_r, ex_idx, ex_tm = p, 'STAGE1_SL', i, tm
                    break
            else:
                breach = 0
        elif stage == 2:
            breach = 0
            lock_p = round(ep * (1.0 - 0.0010), 2)
            if h >= lock_p:
                ex_p, ex_r, ex_idx, ex_tm = lock_p, 'STAGE2_LOCK', i, tm
                break
        elif stage == 3:
            breach = 0
            trail_floor = max(1.75, max_prof - 0.50)
            trail_p = round(ep * (1.0 - trail_floor / 100.0), 2)
            if h >= trail_p:
                ex_p, ex_r, ex_idx, ex_tm = trail_p, 'STAGE3_TRAIL', i, tm
                break

        peak_prof = ((ep - l) / ep) * 100.0
        if peak_prof > max_prof:
            max_prof = peak_prof
        if stage == 1 and max_prof >= 1.25:
            stage = 2
        if stage in (1, 2) and max_prof >= 2.00:
            stage = 3

        if tm >= end_time:
            ex_p, ex_r, ex_idx, ex_tm = p, 'TIME_EXIT', i, tm
            break

    gross1 = (ep - ex_p) * qty
    tax1 = get_taxes(qty, ep, ex_p)
    net1 = round(gross1 - tax1, 2)
    net2, gross2, tax2, has_l2 = 0.0, 0.0, 0.0, False
    if ex_r == 'STAGE3_TRAIL' and ex_tm < '14:00:00':
        net2, gross2, tax2, has_l2 = run_leg2_1445(times, closes, highs, lows, ex_idx, ep, ex_p, qty, end_time=end_time)
    return round(net1 + net2, 2), round(gross1 + gross2, 2), round(tax1 + tax2, 2), ex_r, has_l2


def main():
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
            df_0907 = pd.DataFrame(cur.fetchall())

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

    ticks_table = pq.read_table(
        PARQUET_TICKS,
        columns=['date_str', 'stock', 'time_str', 'open', 'high', 'low', 'close']
    )
    df_ticks = ticks_table.to_pandas()
    print(f"PARQUET_TICKS min time: {df_ticks['time_str'].min()} | max time: {df_ticks['time_str'].max()}")
    df_ticks['stock'] = df_ticks['stock'].astype(str).str.strip().str.upper()
    df_ticks['date_str'] = df_ticks['date_str'].astype(str)
    # Strictly filter 09:42:00 <= time_str <= 14:45:00
    df_ticks = df_ticks[(df_ticks['time_str'] >= '09:42:00') & (df_ticks['time_str'] <= '14:45:00')].copy()

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
                    f"FROM scrapdata WHERE date=%s AND stockname IN ({placeholders}) AND TIME(time) >= '09:42:00' AND TIME(time) <= '14:45:00' "
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

    modes = {
        '1_PURE_1445_NO_SL_NO_LIM': [],
        '2_FLAT_3PCT_SL_1445':      [],
        '3_FLAT_225_SL_1445':       [],
        '4_4STAGE_1430_EXIT':       [],
        '5_4STAGE_1445_EXIT':       [],
    }

    raw_returns_pct = []
    max_adverse_pct = []
    max_favorable_pct = []

    for yr, d_str, stk, _ in picks:
        tks = ticks_dict.get((d_str, stk))
        if not tks or len(tks[0]) == 0:
            continue
        times, closes, highs, lows = tks
        ep = float(closes[0])
        if ep <= 0:
            continue
        q10 = max(1, int(1000000.0 / ep))

        r_pure = sim_pure_1445(times, closes, highs, lows, q10)
        eod_p = ep - (r_pure[1] / q10)
        raw_returns_pct.append((ep - eod_p) / ep * 100.0)
        max_adverse_pct.append((np.max(highs) - ep) / ep * 100.0)
        max_favorable_pct.append((ep - np.min(lows)) / ep * 100.0)

        r_3sl = sim_flat_sl_1445(times, closes, q10, 3.00)
        r_225sl = sim_flat_sl_1445(times, closes, q10, 2.25)
        r_4stg_1430 = sim_4stage_custom_end(times, closes, highs, lows, q10, 3.00, 1.50, 1.00, '11:00:00', '12:30:00', end_time='14:30:00')
        r_4stg_1445 = sim_4stage_custom_end(times, closes, highs, lows, q10, 3.00, 1.50, 1.00, '11:00:00', '12:30:00', end_time='14:45:00')

        for k, res in [
            ('1_PURE_1445_NO_SL_NO_LIM', r_pure),
            ('2_FLAT_3PCT_SL_1445',      r_3sl),
            ('3_FLAT_225_SL_1445',       r_225sl),
            ('4_4STAGE_1430_EXIT',       r_4stg_1430),
            ('5_4STAGE_1445_EXIT',       r_4stg_1445),
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

    raw_arr = np.array(raw_returns_pct)
    adv_arr = np.array(max_adverse_pct)
    fav_arr = np.array(max_favorable_pct)

    print("\n" + "=" * 145)
    print("🔬 PURE 09:42 -> 14:45:00 BASELINE STATS (ZERO STOP-LOSS, ZERO LIMIT/TARGET)")
    print("=" * 145)
    print(f"• Total OOS Trades (2020-2026)                : {len(raw_arr):,d}")
    print(f"• Gross Win Rate (09:42 -> 14:45)             : {(raw_arr > 0).mean()*100:.2f}% | Net Win Rate (after Kotak taxes) = {metrics['1_PURE_1445_NO_SL_NO_LIM']['wr']:.2f}%")
    print(f"• Avg Unstopped Return (09:42 -> 14:45)       : Gross = {raw_arr.mean():+.3f}% (+{raw_arr.mean()*100:.1f} bps) | Median = {np.median(raw_arr):+.3f}%")
    print(f"• Intraday MFE (Max Favorable Drop <= 14:45)  : Mean = +{fav_arr.mean():.2f}% | Median = +{np.median(fav_arr):.2f}% | % Reaching +1.25% Drop = {(fav_arr >= 1.25).mean()*100:.1f}% | % Reaching +2.00% Drop = {(fav_arr >= 2.00).mean()*100:.1f}%")
    print(f"• Intraday MAE (Max Adverse Spike <= 14:45)   : Mean = +{adv_arr.mean():.2f}% | 95th Pct = +{np.percentile(adv_arr, 95):.2f}% | 99th Pct = +{np.percentile(adv_arr, 99):.2f}% | Max = +{adv_arr.max():.2f}%")

    print("\n" + "=" * 145)
    print("📊 7-YEAR OOS COMPARISON WITH 14:45:00 END TIME (2020-2026 | ₹10L/Stock)")
    print("=" * 145)
    keys = list(modes.keys())
    hdr = f"{'Metric':<34} | " + " | ".join([f"{k:>24}" for k in keys])
    print(hdr)
    print("-" * len(hdr))
    rows_to_print = [
        ("Total OOS Trades (2020-2026)",     lambda m: f"{m['n_trades']:24,d}"),
        ("Gross PnL Before Taxes (₹ Lakhs)", lambda m: f"₹{m['tot_gross_L']:+22.2f}L"),
        ("Total Kotak Taxes (₹ Lakhs)",      lambda m: f"-₹{m['tot_tax_L']:21.2f}L"),
        ("Total Net PnL (₹ Lakhs)",          lambda m: f"₹{m['tot_net_L']:+22.2f}L"),
        ("Net PnL @ ₹7.5L Live Scale (₹L)",  lambda m: f"₹{m['tot_net_L']*0.75:+22.2f}L"),
        ("Net Trade Win Rate (%)",           lambda m: f"{m['wr']:23.2f}%"),
        ("Profit Factor",                    lambda m: f"{m['pf']:24.2f}"),
        ("Avg Net PnL / Trade (₹)",          lambda m: f"₹{m['avg_trade']:+23,.0f}"),
        ("Avg Winning Trade (₹)",            lambda m: f"₹{m['avg_win']:+23,.0f}"),
        ("Avg Losing Trade (₹)",             lambda m: f"₹{m['avg_loss']:+23,.0f}"),
        ("Worst Single Trade Loss (₹)",      lambda m: f"₹{m['max_loss']:+23,.0f}"),
        ("Profitable Trading Days (%)",      lambda m: f"{m['daily_wr']:23.2f}%"),
        ("Worst Single Day PnL (₹)",         lambda m: f"₹{m['worst_day']:+23,.0f}"),
        ("Max Portfolio Drawdown (₹L)",      lambda m: f"-₹{m['max_dd_L']:21.2f}L"),
        ("Longest Drawdown Duration (Days)", lambda m: f"{m['max_dd_days']:19d} days"),
        ("Sharpe Ratio (Annualized)",        lambda m: f"{m['sharpe']:24.2f}"),
        ("Sortino Ratio (Annualized)",       lambda m: f"{m['sortino']:24.2f}"),
        ("Calmar Ratio (Net PnL / MaxDD)",   lambda m: f"{m['calmar']:23.1f}x"),
    ]
    for label, fn in rows_to_print:
        print(f"{label:<34} | " + " | ".join([fn(metrics[k]) for k in keys]))

    print("-" * len(hdr))
    for yr in range(2020, 2027):
        vals = []
        for k in keys:
            y_net = dfs[k][dfs[k]['year'] == yr]['net_pnl'].sum() / 1e5
            y_wr = (dfs[k][dfs[k]['year'] == yr]['net_pnl'] > 0).mean() * 100.0
            vals.append(f"₹{y_net:+7.2f}L ({y_wr:4.1f}%)")
        print(f"{f'Year {yr} Net PnL (₹10L) [WR%]':<34} | " + " | ".join([f"{v:>24}" for v in vals]))

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
        print(f"{p_label:<34} | " + " | ".join([f"{v:>24}" for v in vals]))

if __name__ == '__main__':
    main()
