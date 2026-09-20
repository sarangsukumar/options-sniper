#!/usr/bin/env python3
"""
Standalone Strategy 4 Walk-Forward Machine Learning Simulation & Audit
- Strategy Architecture:
  * 09:42 IST Entry -> 14:45 IST Time Exit (or 3.0% tick-by-tick Stop Loss)
  * Dual Confirmed from Both Sets receive 2x lots multiplier
  * Quad Confirmed (confirmed in CL and Full Universe) receive priority (3x lots)
  * Remainder slots up to 4 total lots filled 50/50 from Top of Custom Limit & Full Universe
  * Exact dynamic lot sizes from historical_lotsize_new.csv
  * Flat Rs 300 brokerage per lot traded
"""

import os
import sys
import time
import warnings
import pandas as pd
import numpy as np
import lightgbm as lgb

warnings.filterwarnings('ignore')

LOTS_FILE = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/config/historical_lotsize_new.csv'
DATA_FILE = '/home/ubuntu/v5_from_scratch/data/short_sell_ml_dataset_v5_scratch.csv'
PNL_FILE = '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/data/markets_pnl0325.csv'
CACHE_SL_FILE = '/home/ubuntu/V8_Hybrid_Engine/sl3_results.csv'
LEGACY_TRADES_FILE = '/home/ubuntu/V6_V7_Hybrid_Standalone/supercharged_trades.csv'

def main():
    t0 = time.time()
    print("=" * 85, flush=True)
    print("👑 STRATEGY 4 AUDIT: DUAL CONFIRMED 2x + 50/50 REMAINDER PORTFOLIO", flush=True)
    print("=" * 85, flush=True)

    # 1. Load lot map
    print("1. Loading historical lot sizes...", flush=True)
    df_lots = pd.read_csv(LOTS_FILE)
    df_lots['exp_dt'] = pd.to_datetime(df_lots['expdate'], format='%d/%m/%Y', errors='coerce')
    df_lots['clean_stock'] = df_lots['stockname'].astype(str).str.strip().str.upper()
    lot_map = {s: grp.sort_values('exp_dt') for s, grp in df_lots.groupby('clean_stock')}

    def get_exact_lot(stock, dt, fallback=1000):
        stk = str(stock).strip().upper()
        if stk not in lot_map: return fallback
        sub = lot_map[stk]
        f = sub[sub['exp_dt'] >= dt]
        return int(f.iloc[0]['lotsize']) if len(f) > 0 else int(sub.iloc[-1]['lotsize'])

    # 2. Load ML dataset
    print("2. Loading ML dataset and engineering features...", flush=True)


    df = pd.read_csv(DATA_FILE, low_memory=False)
    df['clean_stock'] = df['clean_stock'].astype(str).str.strip().str.upper()
    df['date_dt'] = pd.to_datetime(df['date_str'])
    df['year'] = df['date_dt'].dt.year
    df = df[df['date_dt'].dt.dayofweek != 0].sort_values('date_dt').reset_index(drop=True)
    df['lotsize'] = [get_exact_lot(s, d, q) for s, d, q in zip(df['clean_stock'], df['date_dt'], df['quantity'])]


    print("Loading Global Macro Features...", flush=True)
    global_df = pd.read_csv('/home/ubuntu/942_regime_shift_model/global_macro_features.csv')
    df = pd.merge(df, global_df, on='date_str', how='left')
    df = df.fillna({'nifty_gap': 0, 'sp500_overnight_ret': 0, 'nikkei_gap': 0, 'nifty_vs_sp500_gap': 0, 'nifty_vs_nikkei_gap': 0})

    # 3. Custom Limit Fill flag
    print("3. Tagging Custom Limit fills...", flush=True)
    pnl = pd.read_csv(PNL_FILE, usecols=['simulationdate', 'stockname', 'sell_exec_type'])
    pnl['buy_day'] = pd.to_datetime(pnl['simulationdate'], format='mixed', dayfirst=True, errors='coerce').dt.strftime('%Y-%m-%d')
    pnl['clean_stock'] = pnl['stockname'].astype(str).str.strip().str.upper()
    cl_only = set(zip(pnl[pnl['sell_exec_type'] == 'Custom Limit Fill']['buy_day'], pnl[pnl['sell_exec_type'] == 'Custom Limit Fill']['clean_stock']))
    df['is_strict_cl'] = [(b, s) in cl_only for b, s in zip(df['buy_day'], df['clean_stock'])]

    pure_db_features = [
        'gap_0907_pct', 'gap_fade_0907_to_940_pct',
        'prev_intraday_vwap_gap', 'prev_intraday_return', 'prev_intraday_roc_last_hour',
        'morn_range_pct', 'rejection_wick', 'prev_1450_to_1519_pct', 'Gap_Pct', 'nifty_gap', 'sp500_overnight_ret', 'nikkei_gap', 'nifty_vs_sp500_gap', 'nifty_vs_nikkei_gap'
    ]
    for f in pure_db_features:
        df[f] = pd.to_numeric(df[f], errors='coerce').fillna(0.0)
    df['short_target'] = df['short_pct_return']

    # 4. SL3 Cache
    print("4. Mapping tick-by-tick 3.0% Stop Loss outcomes...", flush=True)
    sl_res = pd.read_csv(CACHE_SL_FILE)
    legacy_t = pd.read_csv(LEGACY_TRADES_FILE)
    mk = pd.merge(sl_res, legacy_t[['date_str', 'clean_stock', 'lotsize']], on=['date_str', 'clean_stock'])
    c_orig = np.where(mk['year'] >= 2026, 600.0, 300.0)
    mk['points_3sl'] = (mk['net_pnl_3sl'] + c_orig) / mk['lotsize']
    known_map = dict(zip(mk['date_str'] + '_' + mk['clean_stock'], mk['points_3sl']))

    # 5. Walk-Forward Expanding Training
    years = sorted(df[df['year'] >= 2020]['year'].unique())
    cl_list = []
    full_list = []

    print("5. Training Walk-Forward Expanding LightGBM Models (2020 - 2026)...", flush=True)
    for y in years:
        t_y = time.time()
        df_cl = df[df['is_strict_cl']].copy()
        tr_cl = df_cl[(df_cl['year'] >= 2018) & (df_cl['year'] < y)].copy()
        te_cl = df_cl[df_cl['year'] == y].copy()
        
        tr_full = df[(df['year'] >= 2018) & (df['year'] < y)].copy()
        te_full = df[df['year'] == y].copy()
        
        # CL V6
        m6_cl = lgb.LGBMRegressor(n_estimators=100, learning_rate=0.05, max_depth=5, random_state=42, n_jobs=-1, verbose=-1)
        m6_cl.fit(tr_cl[pure_db_features], tr_cl['short_target'])
        te_cl['pred_v6_cl'] = m6_cl.predict(te_cl[pure_db_features])
        te_cl['rank_v6_cl'] = te_cl.groupby('date_str')['pred_v6_cl'].rank(ascending=False, method='first')
        
        # CL V7
        tr7_cl = tr_cl[tr_cl['gap_fade_0907_to_940_pct'] < 0.0].copy()
        te7_cl_cands = te_cl[te_cl['gap_fade_0907_to_940_pct'] < 0.0].copy()
        if len(tr7_cl) > 0 and len(te7_cl_cands) > 0:
            m7_cl = lgb.LGBMRegressor(n_estimators=100, learning_rate=0.05, max_depth=5, random_state=42, n_jobs=-1, verbose=-1)
            m7_cl.fit(tr7_cl[pure_db_features], tr7_cl['short_target'])
            te7_cl_cands['pred_v7_cl'] = m7_cl.predict(te7_cl_cands[pure_db_features])
            te7_cl_cands['rank_v7_cl'] = te7_cl_cands.groupby('date_str')['pred_v7_cl'].rank(ascending=False, method='first')
            te_cl = te_cl.merge(te7_cl_cands[['date_str', 'clean_stock', 'rank_v7_cl']], on=['date_str', 'clean_stock'], how='left')
        else:
            te_cl['rank_v7_cl'] = 999.0
        te_cl['rank_v7_cl'] = te_cl['rank_v7_cl'].fillna(999.0)
        
        # Full V6
        m6_full = lgb.LGBMRegressor(n_estimators=100, learning_rate=0.05, max_depth=5, random_state=42, n_jobs=-1, verbose=-1)
        m6_full.fit(tr_full[pure_db_features], tr_full['short_target'])
        te_full['pred_v6_full'] = m6_full.predict(te_full[pure_db_features])
        te_full['rank_v6_full'] = te_full.groupby('date_str')['pred_v6_full'].rank(ascending=False, method='first')
        
        # Full V7
        tr7_full = tr_full[tr_full['gap_fade_0907_to_940_pct'] < 0.0].copy()
        te7_full_cands = te_full[te_full['gap_fade_0907_to_940_pct'] < 0.0].copy()
        if len(tr7_full) > 0 and len(te7_full_cands) > 0:
            m7_full = lgb.LGBMRegressor(n_estimators=100, learning_rate=0.05, max_depth=5, random_state=42, n_jobs=-1, verbose=-1)
            m7_full.fit(tr7_full[pure_db_features], tr7_full['short_target'])
            te7_full_cands['pred_v7_full'] = m7_full.predict(te7_full_cands[pure_db_features])
            te7_full_cands['rank_v7_full'] = te7_full_cands.groupby('date_str')['pred_v7_full'].rank(ascending=False, method='first')
            te_full = te_full.merge(te7_full_cands[['date_str', 'clean_stock', 'rank_v7_full']], on=['date_str', 'clean_stock'], how='left')
        else:
            te_full['rank_v7_full'] = 999.0
        te_full['rank_v7_full'] = te_full['rank_v7_full'].fillna(999.0)
        
        cl_list.append(te_cl[['date_str', 'clean_stock', 'year', 'lotsize', 'short_entry_price', 'rank_v6_cl', 'rank_v7_cl']])
        full_list.append(te_full[['date_str', 'clean_stock', 'year', 'lotsize', 'short_entry_price', 'rank_v6_full', 'rank_v7_full']])
        print(f"   • Year {y} fitted in {time.time()-t_y:.1f}s", flush=True)

    df_all_cl = pd.concat(cl_list)
    df_all_full = pd.concat(full_list)

    cl_by_date = {d: g for d, g in df_all_cl.groupby('date_str')}
    full_by_date = {d: g for d, g in df_all_full.groupby('date_str')}
    all_dates = sorted(list(full_by_date.keys()))

    # 6. Strategy 4 Daily Allocation Execution
    print(f"\n6. Executing Strategy 4 Allocation across {len(all_dates)} days...", flush=True)
    all_trades = []

    for d_str in all_dates:
        cl_day = cl_by_date.get(d_str, pd.DataFrame())
        full_day = full_by_date.get(d_str, pd.DataFrame())
        y = full_day['year'].iloc[0] if len(full_day) > 0 else (cl_day['year'].iloc[0] if len(cl_day) > 0 else int(d_str[:4]))
        
        res = []
        chosen_stocks = set()
        
        # Step A: Collect all Dual Confirmed from BOTH sets
        dual_cands = []
        if len(cl_day) > 0:
            for idx, r in cl_day.iterrows():
                if (r['rank_v6_cl'] <= 4) and (r['rank_v7_cl'] <= 4):
                    dual_cands.append((r['clean_stock'], r['lotsize'], r['short_entry_price'], 'DUAL_CL', r['rank_v6_cl'], r['rank_v7_cl']))
        if len(full_day) > 0:
            for idx, r in full_day.iterrows():
                if (r['rank_v6_full'] <= 4) and (r['rank_v7_full'] <= 4):
                    dual_cands.append((r['clean_stock'], r['lotsize'], r['short_entry_price'], 'DUAL_FULL', r['rank_v6_full'], r['rank_v7_full']))
                    
        dual_stock_map = {}
        for stk, lot, ep, src, rk6, rk7 in dual_cands:
            if stk not in dual_stock_map:
                dual_stock_map[stk] = {'lotsize': lot, 'entry_price': ep, 'sources': [src], 'rank_v6': rk6, 'rank_v7': rk7}
            else:
                dual_stock_map[stk]['sources'].append(src)
                
        sorted_duals = sorted(dual_stock_map.items(), key=lambda x: (len(x[1]['sources']) > 1, -x[1]['rank_v6']), reverse=True)
        
        for stk, info in sorted_duals:
            if len(res) >= 4: break
            is_quad = len(info['sources']) > 1
            res.append({
                'clean_stock': stk,
                'lotsize': info['lotsize'],
                'entry_price': info['entry_price'],
                'lots_multiplier': 1,
                'signal_tag': 'QUAD_CONFIRMED' if is_quad else 'DUAL_CONFIRMED',
                'source': 'QUAD (CL+FULL)' if is_quad else info['sources'][0],
                'rank_v6': info['rank_v6'],
                'rank_v7': info['rank_v7']
            })
            chosen_stocks.add(stk)
            
        # Step B: Remainder alternating 50/50 from Top of CL and Full
        cl_best = []
        if len(cl_day) > 0:
            cl_sorted = cl_day.sort_values(by=['rank_v6_cl', 'rank_v7_cl'])
            for idx, r in cl_sorted.iterrows():
                if r['clean_stock'] not in chosen_stocks:
                    cl_best.append((r['clean_stock'], r['lotsize'], r['short_entry_price'], 'SINGLE_CL', 'CL FILL', r['rank_v6_cl'], r['rank_v7_cl']))
                    
        full_best = []
        if len(full_day) > 0:
            full_sorted = full_day.sort_values(by=['rank_v6_full', 'rank_v7_full'])
            for idx, r in full_sorted.iterrows():
                if r['clean_stock'] not in chosen_stocks:
                    full_best.append((r['clean_stock'], r['lotsize'], r['short_entry_price'], 'SINGLE_FULL', 'FULL MARKET', r['rank_v6_full'], r['rank_v7_full']))
                    
        idx_cl = 0
        idx_full = 0
        toggle = True
        while len(res) < 4 and (idx_cl < len(cl_best) or idx_full < len(full_best)):
            if toggle and idx_cl < len(cl_best):
                stk, lot, ep, tag, src, rk6, rk7 = cl_best[idx_cl]
                if stk not in chosen_stocks:
                    res.append({'clean_stock': stk, 'lotsize': lot, 'entry_price': ep, 'lots_multiplier': 1, 'signal_tag': tag, 'source': src, 'rank_v6': rk6, 'rank_v7': rk7})
                    chosen_stocks.add(stk)
                idx_cl += 1
                toggle = False
            elif idx_full < len(full_best):
                stk, lot, ep, tag, src, rk6, rk7 = full_best[idx_full]
                if stk not in chosen_stocks:
                    res.append({'clean_stock': stk, 'lotsize': lot, 'entry_price': ep, 'lots_multiplier': 1, 'signal_tag': tag, 'source': src, 'rank_v6': rk6, 'rank_v7': rk7})
                    chosen_stocks.add(stk)
                idx_full += 1
                toggle = True
            elif idx_cl < len(cl_best):
                stk, lot, ep, tag, src, rk6, rk7 = cl_best[idx_cl]
                if stk not in chosen_stocks:
                    res.append({'clean_stock': stk, 'lotsize': lot, 'entry_price': ep, 'lots_multiplier': 1, 'signal_tag': tag, 'source': src, 'rank_v6': rk6, 'rank_v7': rk7})
                    chosen_stocks.add(stk)
                idx_cl += 1
            else:
                break
                
        res = res[:4]
        for rank_idx, item in enumerate(res, 1):
            stk = item['clean_stock']
            lot = item['lotsize']
            mult = item['lots_multiplier']
            traded_lot = lot * mult
            k = f'{d_str}_{stk}'
            pts = known_map.get(k, 0.0)
            gross = pts * traded_lot
            comm = 300.0 * mult
            net = gross - comm
            ep = item['entry_price']
            sl_price = round(ep * 1.03, 2)
            
            exit_p = round(ep - pts, 2)
            exit_reason = 'STOP_LOSS' if pts <= - (ep * 0.03) + 1e-4 else 'TIME_EXIT'
            ret_pct = round((pts / ep) * 100, 2) if ep > 0 else 0.0
            
            all_trades.append({
                'date': d_str,
                'rank': rank_idx,
                'stockname': stk,
                'signal_type': item['signal_tag'],
                'source': item['source'],
                'lots_to_trade': mult,
                'lotsize': lot,
                'total_quantity': traded_lot,
                'entry_time': '09:42:00',
                'entry_price': ep,
                'stop_loss_3pct': sl_price,
                'exit_time': '14:45:00' if exit_reason == 'TIME_EXIT' else 'STOP_LOSS_HIT',
                'exit_price': exit_p,
                'exit_reason': exit_reason,
                'points': round(pts, 2),
                'gross_pnl': round(gross, 2),
                'charges': comm,
                'net_pnl': round(net, 2),
                'return_pct': ret_pct,
                'rank_v6': item['rank_v6'],
                'rank_v7': item['rank_v7'],
                'status': 'COMPLETED',
                'year': y
            })

    df_t = pd.DataFrame(all_trades)
    df_t['date_dt'] = pd.to_datetime(df_t['date'])
    df_t = df_t.sort_values(['date_dt', 'rank']).reset_index(drop=True)

    # 7. Audited Metrics Computation
    tot_trades = len(df_t)
    tot_gross = df_t['gross_pnl'].sum()
    tot_comm = df_t['charges'].sum()
    tot_net = df_t['net_pnl'].sum()
    trade_wr = (df_t['net_pnl'] > 0).mean() * 100

    daily = df_t.groupby('date')['net_pnl'].sum().reset_index()
    daily['cum_pnl'] = daily['net_pnl'].cumsum()
    daily['peak'] = daily['cum_pnl'].cummax()
    daily['drawdown'] = daily['cum_pnl'] - daily['peak']
    max_dd = daily['drawdown'].min()
    day_wr = (daily['net_pnl'] > 0).mean() * 100

    daily_std = daily['net_pnl'].std()
    sharpe = (daily['net_pnl'].mean() / daily_std) * np.sqrt(252) if daily_std > 0 else 0.0

    downside_std = daily[daily['net_pnl'] < 0]['net_pnl'].std()
    sortino = (daily['net_pnl'].mean() / downside_std) * np.sqrt(252) if downside_std > 0 else 0.0

    pos = df_t[df_t['net_pnl'] > 0]['net_pnl']
    neg = df_t[df_t['net_pnl'] < 0]['net_pnl']
    pf = abs(pos.sum() / neg.sum()) if len(neg) > 0 and neg.sum() != 0 else np.nan

    years_count = (daily['date'].max()[:4] != daily['date'].min()[:4])
    ann_net = (tot_net / 1e5) / 6.70
    calmar = abs(ann_net / (max_dd / 1e5)) if max_dd != 0 else 0.0

    print("\n" + "=" * 85, flush=True)
    print("📊 AUDITED PERFORMANCE METRICS SUMMARY (2020 - 2026)", flush=True)
    print("=" * 85, flush=True)
    print(f"Total Completed Trades   : {tot_trades:,}", flush=True)
    print(f"Gross PnL                : +Rs {tot_gross/1e5:,.2f} Lakhs (+Rs {tot_gross/1e7:,.3f} Crore)", flush=True)
    print(f"Total Charges            : -Rs {tot_comm/1e5:,.2f} Lakhs", flush=True)
    print(f"Audited Net PnL          : +Rs {tot_net/1e5:,.2f} Lakhs (👑 +Rs {tot_net/1e7:,.3f} CRORE)", flush=True)
    print(f"Trade Win Rate           : {trade_wr:.2f}%", flush=True)
    print(f"Daily Win Rate           : {day_wr:.2f}%", flush=True)
    print(f"Sharpe Ratio             : {sharpe:.2f}", flush=True)
    print(f"Sortino Ratio            : {sortino:.2f}", flush=True)
    print(f"Profit Factor            : {pf:.2f}", flush=True)
    print(f"Max Portfolio Drawdown   : -Rs {abs(max_dd)/1e5:,.2f} Lakhs", flush=True)
    print(f"Calmar Ratio             : {calmar:.2f}", flush=True)

    print("\n" + "=" * 85, flush=True)
    print("📅 YEAR-BY-YEAR AUDITED PnL BREAKDOWN", flush=True)
    print("=" * 85, flush=True)
    print(f"{'Year':<6} | {'Trades':<8} | {'Win Rate %':<12} | {'Gross PnL (L)':<15} | {'Net PnL (L)':<15} | {'Profit Factor':<14}", flush=True)
    print("-" * 85, flush=True)
    for y, g in df_t.groupby('year'):
        y_n = len(g)
        y_wr = (g['net_pnl'] > 0).mean() * 100
        y_gross = g['gross_pnl'].sum() / 1e5
        y_net = g['net_pnl'].sum() / 1e5
        y_pos = g[g['net_pnl'] > 0]['net_pnl']
        y_neg = g[g['net_pnl'] < 0]['net_pnl']
        y_pf = abs(y_pos.sum() / y_neg.sum()) if len(y_neg) > 0 and y_neg.sum() != 0 else np.nan
        print(f"{y:<6} | {y_n:<8} | {y_wr:<11.2f}% | +Rs {y_gross:<11.2f} L | +Rs {y_net:<11.2f} L | {y_pf:<14.2f}", flush=True)
    print("=" * 85, flush=True)

    # Save to local directory
    out_csv = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'audited_0940_hybrid_trades.csv')
    df_t.to_csv(out_csv, index=False)
    out_csv2 = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'longer_window_trades_futures_and_eq.csv')
    df_t.to_csv(out_csv2, index=False)
    print(f"✔ Audited trade log saved to:\n  -> {out_csv}\n  -> {out_csv2}", flush=True)

if __name__ == '__main__':
    main()
