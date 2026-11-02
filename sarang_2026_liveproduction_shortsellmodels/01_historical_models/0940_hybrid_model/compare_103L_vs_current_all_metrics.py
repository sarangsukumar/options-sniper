#!/usr/bin/env python3
import math
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import pymysql

BT_CSV = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_shortsell_t1_2026/02_0942_Hybrid_Model/exact_live_pipeline_historical_backtest_2020_2026/exact_live_pipeline_backtest_2020_2026.csv'
OPTA_CSV = '/home/ubuntu/live_production0942_model/option_a_5269_4sims_comparison.csv'
PARQUET_TICKS = '/home/ubuntu/trading2026/sarang_verified_shorsellalgo_0940/data/ticks_0940_cache.parquet'

def get_taxes(qty, sell_price, buy_price):
    if qty <= 0 or sell_price <= 0 or buy_price <= 0:
        return 0.0
    sell_value = qty * sell_price
    buy_value = qty * buy_price
    turnover = sell_value + buy_value
    brokerage = 40.0
    stt = math.ceil(sell_value * 0.00025)
    txn = turnover * 0.0000322
    sebi = turnover * 0.000001
    stamp = round(buy_value * 0.00003)
    gst = (brokerage + txn + sebi) * 0.18
    return round(brokerage + stt + txn + sebi + stamp + gst, 2)

def run_leg2(times, closes, highs, lows, exit_idx, ep, leg1_exit_p, qty):
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
        if times[k] >= '14:30:00':
            l2_ex_p = closes[k]
            break
    gross2 = (l2_ep - l2_ex_p) * qty
    tax2 = get_taxes(qty, l2_ep, l2_ex_p)
    net2 = gross2 - tax2
    return round(net2, 2), round(gross2, 2), round(tax2, 2), True

def sim_s3_4stage_detailed(times, closes, highs, lows, qty, sl_t1, sl_t2, sl_t3, c1='10:30:00', c2='11:15:00'):
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
                    ex_p, ex_r, ex_idx, ex_tm = p, f'STAGE1_SL', i, tm
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

        if tm >= '14:30:00':
            ex_p, ex_r, ex_idx, ex_tm = p, 'TIME_EXIT', i, tm
            break

    gross1 = (ep - ex_p) * qty
    tax1 = get_taxes(qty, ep, ex_p)
    net1 = round(gross1 - tax1, 2)
    net2, gross2, tax2, has_l2 = 0.0, 0.0, 0.0, False
    if ex_r == 'STAGE3_TRAIL' and ex_tm < '14:00:00':
        net2, gross2, tax2, has_l2 = run_leg2(times, closes, highs, lows, ex_idx, ep, ex_p, qty)
    return round(net1 + net2, 2), round(gross1 + gross2, 2), round(tax1 + tax2, 2), ex_r, has_l2

def sim_s1_3min_detailed(times, closes, qty, sl_t1, sl_t2, sl_t3, c1='10:30:00', c2='11:15:00'):
    ep = closes[0]
    breach = 0
    n = len(times)
    ex_p, ex_r = closes[-1], 'TIME_EXIT'
    for i in range(n):
        tm = times[i]
        p = closes[i]
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
                ex_p, ex_r = p, 'STAGE1_SL'
                break
        else:
            breach = 0
        if tm >= '14:45:00':
            ex_p, ex_r = p, 'TIME_EXIT'
            break
    gross = (ep - ex_p) * qty
    tax = get_taxes(qty, ep, ex_p)
    net = gross - tax
    return round(net, 2), round(gross, 2), round(tax, 2), ex_r, False

def compute_metrics(df_res):
    pnls = df_res['net_pnl'].to_numpy()
    gross = df_res['gross_pnl'].to_numpy()
    taxes = df_res['taxes'].to_numpy()
    n_trades = len(pnls)
    wins = pnls[pnls > 0]
    losses = pnls[pnls <= 0]

    tot_net_L = pnls.sum() / 100000.0
    tot_gross_L = gross.sum() / 100000.0
    tot_tax_L = taxes.sum() / 100000.0

    wr = (len(wins) / n_trades) * 100.0
    pf = wins.sum() / abs(losses.sum()) if len(losses) > 0 and losses.sum() != 0 else 0.0
    avg_trade = pnls.mean()
    med_trade = np.median(pnls)
    avg_win = wins.mean() if len(wins) > 0 else 0.0
    avg_loss = losses.mean() if len(losses) > 0 else 0.0
    payoff = abs(avg_win / avg_loss) if avg_loss != 0 else 0.0
    max_win = pnls.max()
    max_loss = pnls.min()

    # Daily portfolio metrics
    daily = df_res.groupby('date')['net_pnl'].sum().sort_index()
    n_days = len(daily)
    win_days = (daily > 0).sum()
    daily_wr = (win_days / n_days) * 100.0
    avg_day = daily.mean()
    best_day = daily.max()
    worst_day = daily.min()

    cum = daily.cumsum()
    dd_series = cum - cum.cummax()
    max_dd_L = abs(dd_series.min()) / 100000.0

    # Max drawdown duration in trading days
    is_dd = dd_series < 0
    max_dd_days = 0
    cur_dd_days = 0
    for v in is_dd:
        if v:
            cur_dd_days += 1
            if cur_dd_days > max_dd_days:
                max_dd_days = cur_dd_days
        else:
            cur_dd_days = 0

    sharpe = (daily.mean() / daily.std()) * np.sqrt(252) if daily.std() > 0 else 0.0
    downside = daily[daily < 0]
    downside_std = np.sqrt(np.mean(np.minimum(0, daily)**2))
    sortino = (daily.mean() / downside_std) * np.sqrt(252) if downside_std > 0 else 0.0
    calmar = tot_net_L / max_dd_L if max_dd_L > 0 else 0.0

    # Exit counts
    ex_counts = df_res['exit_reason'].value_counts().to_dict()
    l2_cnt = df_res['has_l2'].sum()
    yearly = (df_res.groupby('year')['net_pnl'].sum() / 100000.0).to_dict()

    return {
        'tot_gross_L': tot_gross_L,
        'tot_tax_L': tot_tax_L,
        'tot_net_L': tot_net_L,
        'n_trades': n_trades,
        'wr': wr,
        'pf': pf,
        'avg_trade': avg_trade,
        'med_trade': med_trade,
        'avg_win': avg_win,
        'avg_loss': avg_loss,
        'payoff': payoff,
        'max_win': max_win,
        'max_loss': max_loss,
        'n_days': n_days,
        'daily_wr': daily_wr,
        'avg_day': avg_day,
        'best_day': best_day,
        'worst_day': worst_day,
        'max_dd_L': max_dd_L,
        'max_dd_days': max_dd_days,
        'sharpe': sharpe,
        'sortino': sortino,
        'calmar': calmar,
        'sl_cnt': ex_counts.get('STAGE1_SL', 0),
        's2_cnt': ex_counts.get('STAGE2_LOCK', 0),
        's3_cnt': ex_counts.get('STAGE3_TRAIL', 0),
        'time_cnt': ex_counts.get('TIME_EXIT', 0),
        'l2_cnt': l2_cnt,
        'yearly': yearly
    }

def main():
    df_bt = pd.read_csv(BT_CSV)
    df_opta = pd.read_csv(OPTA_CSV)

    ticks_table = pq.read_table(PARQUET_TICKS, columns=['date_str', 'stock', 'time_str', 'open', 'high', 'low', 'close'])
    df_ticks = ticks_table.to_pandas()
    df_ticks['stock'] = df_ticks['stock'].astype(str).str.strip().str.upper()
    df_ticks['date_str'] = df_ticks['date_str'].astype(str)
    df_ticks = df_ticks[df_ticks['time_str'] >= '09:42:00'].copy()

    ticks_dict = {}
    for (d_str, stk), g in df_ticks.groupby(['date_str', 'stock']):
        g_sorted = g.sort_values('time_str')
        ticks_dict[(d_str, stk)] = (
            g_sorted['time_str'].to_numpy(),
            g_sorted['close'].to_numpy(dtype=np.float64),
            g_sorted['high'].to_numpy(dtype=np.float64),
            g_sorted['low'].to_numpy(dtype=np.float64)
        )

    conn = pymysql.connect(host='localhost', user='root', password='root', database='markets', cursorclass=pymysql.cursors.DictCursor)
    all_keys = set(zip(df_bt['date'].astype(str), df_bt['stock'].astype(str).str.strip().str.upper())) | \
               set(zip(df_opta['date'].astype(str), df_opta['stock'].astype(str).str.strip().str.upper()))
    for d_str, stk in all_keys:
        if (d_str, stk) not in ticks_dict:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT TIME_FORMAT(TIME(time), '%%H:%%i:%%s') as time_str, CAST(close AS DOUBLE) as close, CAST(high AS DOUBLE) as high, CAST(low AS DOUBLE) as low "
                    "FROM scrapdata WHERE date=%s AND stockname=%s AND TIME(time) >= '09:42:00' ORDER BY time ASC",
                    (d_str, stk)
                )
                rows = cur.fetchall()
                if rows:
                    ticks_dict[(d_str, stk)] = (
                        np.array([r['time_str'] for r in rows]),
                        np.array([float(r['close']) for r in rows], dtype=np.float64),
                        np.array([float(r['high']) for r in rows], dtype=np.float64),
                        np.array([float(r['low']) for r in rows], dtype=np.float64)
                    )
    conn.close()

    configs = [
        ("1A_LIVE_1030",  "Current Live 4-Stage (2.25->1.50->1.00 | 10:30/11:15)", 2.25, 1.50, 1.00, '10:30:00', '11:15:00', 'S3'),
        ("1B_LIVE_1100",  "Current Live 4-Stage (2.25->1.50->1.00 | 11:00/12:30)", 2.25, 1.50, 1.00, '11:00:00', '12:30:00', 'S3'),
        ("5A_SIM1B_225",  "SIM 1B Baseline (No TP + Constant 2.25% 3m SL)",        2.25, 2.25, 2.25, '10:30:00', '11:15:00', 'S1'),
        ("5B_103L_225D",  "5B: SIM 1B + Decay SL (2.25->1.50->1.00 | Hold 14:45)", 2.25, 1.50, 1.00, '10:30:00', '11:15:00', 'S1'),
        ("5C_103L_300P",  "5C: SIM 1B + Decay SL (3.00->2.00->1.25 | Hold 14:45)", 3.00, 2.00, 1.25, '10:30:00', '11:15:00', 'S1'),
        ("5D_103L_300D",  "5D: SIM 1B + Decay SL (3.00->1.50->1.00 | Hold 14:45)", 3.00, 1.50, 1.00, '10:30:00', '11:15:00', 'S1'),
    ]

    for ds_name, df_src in [
        ("OPTION A WALK-FORWARD BENCHMARK (5,269 Trades | ₹10L/Stock)", df_opta),
        ("EXACT LIVE PIPELINE DATASET (5,263 Trades | ₹10L/Stock)", df_bt)
    ]:
        print("\n" + "=" * 140)
        print(f"📊 {ds_name}")
        print("=" * 140)
        all_m = {}
        for key, label, s1, s2, s3, c1, c2, mode in configs:
            rows = []
            for _, r in df_src.iterrows():
                d_str = str(r['date'])
                stk = str(r['stock']).strip().upper()
                tks = ticks_dict.get((d_str, stk))
                if not tks:
                    continue
                times, closes, highs, lows = tks
                ep = float(closes[0])
                q10 = max(1, int(1000000.0 / ep))
                if mode == 'S3':
                    net, gross, tax, ex_r, has_l2 = sim_s3_4stage_detailed(times, closes, highs, lows, q10, s1, s2, s3, c1, c2)
                else:
                    net, gross, tax, ex_r, has_l2 = sim_s1_3min_detailed(times, closes, q10, s1, s2, s3, c1, c2)
                rows.append({
                    'year': int(r['year']),
                    'date': d_str,
                    'stock': stk,
                    'net_pnl': net,
                    'gross_pnl': gross,
                    'taxes': tax,
                    'exit_reason': ex_r,
                    'has_l2': has_l2
                })
            df_res = pd.DataFrame(rows)
            all_m[key] = compute_metrics(df_res)

        keys = [c[0] for c in configs]
        hdr = f"{'Metric':<38} | " + " | ".join([f"{k:>15}" for k in keys])
        print(hdr)
        print("-" * len(hdr))

        metric_rows = [
            ("Gross PnL (₹ Lakhs)",              lambda m: f"₹{m['tot_gross_L']:+13.2f}L"),
            ("Total Taxes & Charges (₹ Lakhs)",  lambda m: f"-₹{m['tot_tax_L']:12.2f}L"),
            ("Total Net PnL (₹ Lakhs)",          lambda m: f"₹{m['tot_net_L']:+13.2f}L"),
            ("Net Edge vs Current Live 1A",      lambda m: f"₹{m['tot_net_L'] - all_m['1A_LIVE_1030']['tot_net_L']:+13.2f}L"),
            ("Win Rate (%)",                     lambda m: f"{m['wr']:14.2f}%"),
            ("Profit Factor",                    lambda m: f"{m['pf']:15.2f}"),
            ("Avg Net PnL / Trade (₹)",          lambda m: f"₹{m['avg_trade']:+14,.0f}"),
            ("Median Net PnL / Trade (₹)",       lambda m: f"₹{m['med_trade']:+14,.0f}"),
            ("Avg Winning Trade (₹)",            lambda m: f"₹{m['avg_win']:+14,.0f}"),
            ("Avg Losing Trade (₹)",             lambda m: f"₹{m['avg_loss']:+14,.0f}"),
            ("Payoff Ratio (Avg Win / Loss)",    lambda m: f"{m['payoff']:14.2f}x"),
            ("Largest Single Win (₹)",           lambda m: f"₹{m['max_win']:+14,.0f}"),
            ("Largest Single Loss (₹)",          lambda m: f"₹{m['max_loss']:+14,.0f}"),
            ("Profitable Trading Days (%)",      lambda m: f"{m['daily_wr']:14.2f}%"),
            ("Avg Daily Portfolio PnL (₹)",      lambda m: f"₹{m['avg_day']:+14,.0f}"),
            ("Best Trading Day (₹)",             lambda m: f"₹{m['best_day']:+14,.0f}"),
            ("Worst Trading Day (₹)",            lambda m: f"₹{m['worst_day']:+14,.0f}"),
            ("Max Portfolio Drawdown (₹L)",      lambda m: f"-₹{m['max_dd_L']:12.2f}L"),
            ("Longest Drawdown Duration (Days)", lambda m: f"{m['max_dd_days']:10d} days"),
            ("Sharpe Ratio (Annualized)",        lambda m: f"{m['sharpe']:15.2f}"),
            ("Sortino Ratio (Annualized)",       lambda m: f"{m['sortino']:15.2f}"),
            ("Calmar Ratio (Net PnL / MaxDD)",   lambda m: f"{m['calmar']:14.1f}x"),
            ("Stage 1 SL Exits (Count)",         lambda m: f"{m['sl_cnt']:15,d}"),
            ("Stage 2 Breakeven Lock Exits",     lambda m: f"{m['s2_cnt']:15,d}"),
            ("Stage 3 Trailing TP Exits",        lambda m: f"{m['s3_cnt']:15,d}"),
            ("14:30/14:45 Time Exits (Uncapped)",lambda m: f"{m['time_cnt']:15,d}"),
            ("Leg 2 Re-Entry Trades Triggered",  lambda m: f"{m['l2_cnt']:15,d}"),
        ]
        for m_label, fn in metric_rows:
            print(f"{m_label:<38} | " + " | ".join([fn(all_m[k]) for k in keys]))

        print("-" * len(hdr))
        for y in [2020, 2021, 2022, 2023, 2024, 2025, 2026]:
            print(f"{f'Year {y} Net PnL (₹L)':<38} | " + " | ".join([f"₹{all_m[k]['yearly'].get(y, 0.0):+13.2f}L" for k in keys]))

if __name__ == '__main__':
    main()
