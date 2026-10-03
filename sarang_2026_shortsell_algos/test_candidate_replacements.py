import os, sys, time, warnings
import pandas as pd
import numpy as np
import lightgbm as lgb

warnings.filterwarnings('ignore')

SCRIPT_DIR = '/home/ubuntu/sarang_2026_shortsell_algos/02_Best_Longer_Window_0942_1445'
DATA_DIR = os.path.join(SCRIPT_DIR, 'data')

LOTS_FILE = os.path.join(DATA_DIR, 'historical_lotsize_new.csv')
DATA_FILE = os.path.join(DATA_DIR, 'short_sell_ml_dataset_v5_scratch.csv.gz')
PNL_FILE = os.path.join(DATA_DIR, 'markets_pnl0325.csv.gz')
CACHE_SL_FILE = os.path.join(DATA_DIR, 'sl3_points_master.csv')
LEGACY_TRADES_FILE = os.path.join(SCRIPT_DIR, 'audited_0940_hybrid_trades.csv')

# 1. Load lots
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
df = pd.read_csv(DATA_FILE, low_memory=False)
df['clean_stock'] = df['clean_stock'].astype(str).str.strip().str.upper()
df['date_dt'] = pd.to_datetime(df['date_str'])
df['year'] = df['date_dt'].dt.year
df = df[df['date_dt'].dt.dayofweek != 0].sort_values('date_dt').reset_index(drop=True)
df['lotsize'] = [get_exact_lot(s, d, q) for s, d, q in zip(df['clean_stock'], df['date_dt'], df['quantity'])]

# Pre-filter condition
gain = ((df['short_entry_price'] - df['prev_close']) / df['prev_close']) * 100
df['passed_prefilter'] = (gain >= -1.5) & ~((gain >= 2.0) & (gain < 3.0))

# Custom Limit tag
pnl = pd.read_csv(PNL_FILE, usecols=['simulationdate', 'stockname', 'sell_exec_type'])
pnl['buy_day'] = pd.to_datetime(pnl['simulationdate'], format='mixed', dayfirst=True, errors='coerce').dt.strftime('%Y-%m-%d')
pnl['clean_stock'] = pnl['stockname'].astype(str).str.strip().str.upper()
cl_only = set(zip(pnl[pnl['sell_exec_type'] == 'Custom Limit Fill']['buy_day'], pnl[pnl['sell_exec_type'] == 'Custom Limit Fill']['clean_stock']))
df['is_strict_cl'] = [(b, s) in cl_only for b, s in zip(df['buy_day'], df['clean_stock'])]

pure_db_features = [
    'gap_0907_pct', 'gap_fade_0907_to_940_pct',
    'prev_intraday_vwap_gap', 'prev_intraday_return', 'prev_intraday_roc_last_hour',
    'morn_range_pct', 'rejection_wick'
]
for f in pure_db_features:
    df[f] = pd.to_numeric(df[f], errors='coerce').fillna(0.0)
df['short_target'] = df['short_pct_return']

# SL3 mapping
sl_master = pd.read_csv(os.path.join(SCRIPT_DIR, 'sl3_points_master.csv'))
known_map = dict(zip(sl_master['date'] + '_' + sl_master['stockname'], sl_master['points']))

years = sorted(df[df['year'] >= 2020]['year'].unique())
cl_list = []
full_list = []

for y in years:
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
    
    cols = ['date_str', 'clean_stock', 'year', 'lotsize', 'short_entry_price', 'passed_prefilter']
    cl_list.append(te_cl[cols + ['rank_v6_cl', 'rank_v7_cl']])
    full_list.append(te_full[cols + ['rank_v6_full', 'rank_v7_full']])

df_all_cl = pd.concat(cl_list)
df_all_full = pd.concat(full_list)

def run_allocation(use_prefilter_in_selection=False):
    cl_by_date = {d: g for d, g in df_all_cl.groupby('date_str')}
    full_by_date = {d: g for d, g in df_all_full.groupby('date_str')}
    all_dates = sorted(list(full_by_date.keys()))
    
    all_trades = []
    skipped_count = 0
    replacement_count = 0
    
    for d_str in all_dates:
        cl_day = cl_by_date.get(d_str, pd.DataFrame())
        full_day = full_by_date.get(d_str, pd.DataFrame())
        
        # Dual cands
        dual_cands = []
        if len(cl_day) > 0:
            for idx, r in cl_day.iterrows():
                if (r['rank_v6_cl'] <= 4) and (r['rank_v7_cl'] <= 4):
                    if use_prefilter_in_selection and not r['passed_prefilter']:
                        continue
                    dual_cands.append((r['clean_stock'], r['lotsize'], r['short_entry_price'], 'DUAL_CL', r['rank_v6_cl'], r['rank_v7_cl'], r['passed_prefilter']))
        if len(full_day) > 0:
            for idx, r in full_day.iterrows():
                if (r['rank_v6_full'] <= 4) and (r['rank_v7_full'] <= 4):
                    if use_prefilter_in_selection and not r['passed_prefilter']:
                        continue
                    dual_cands.append((r['clean_stock'], r['lotsize'], r['short_entry_price'], 'DUAL_FULL', r['rank_v6_full'], r['rank_v7_full'], r['passed_prefilter']))
                    
        dual_stock_map = {}
        for stk, lot, ep, src, rk6, rk7, pf in dual_cands:
            if stk not in dual_stock_map:
                dual_stock_map[stk] = {'lotsize': lot, 'entry_price': ep, 'sources': [src], 'rank_v6': rk6, 'rank_v7': rk7, 'passed_prefilter': pf}
            else:
                dual_stock_map[stk]['sources'].append(src)
                
        sorted_duals = sorted(dual_stock_map.items(), key=lambda x: (len(x[1]['sources']) > 1, -x[1]['rank_v6']), reverse=True)
        
        res = []
        chosen_stocks = set()
        
        for stk, info in sorted_duals:
            if len(res) >= 4: break
            is_quad = len(info['sources']) > 1
            res.append({
                'clean_stock': stk, 'lotsize': info['lotsize'], 'entry_price': info['entry_price'],
                'lots_multiplier': 3 if is_quad else 2, 'signal_tag': 'QUAD_CONFIRMED' if is_quad else 'DUAL_CONFIRMED',
                'source': 'QUAD (CL+FULL)' if is_quad else info['sources'][0],
                'rank_v6': info['rank_v6'], 'rank_v7': info['rank_v7'], 'passed_prefilter': info['passed_prefilter']
            })
            chosen_stocks.add(stk)
            
        # Remainder 50/50
        cl_best = []
        if len(cl_day) > 0:
            cl_sorted = cl_day.sort_values(by=['rank_v6_cl', 'rank_v7_cl'])
            for idx, r in cl_sorted.iterrows():
                if r['clean_stock'] not in chosen_stocks:
                    if use_prefilter_in_selection and not r['passed_prefilter']:
                        continue
                    cl_best.append((r['clean_stock'], r['lotsize'], r['short_entry_price'], 'SINGLE_CL', 'CL FILL', r['rank_v6_cl'], r['rank_v7_cl'], r['passed_prefilter']))
                    
        full_best = []
        if len(full_day) > 0:
            full_sorted = full_day.sort_values(by=['rank_v6_full', 'rank_v7_full'])
            for idx, r in full_sorted.iterrows():
                if r['clean_stock'] not in chosen_stocks:
                    if use_prefilter_in_selection and not r['passed_prefilter']:
                        continue
                    full_best.append((r['clean_stock'], r['lotsize'], r['short_entry_price'], 'SINGLE_FULL', 'FULL MARKET', r['rank_v6_full'], r['rank_v7_full'], r['passed_prefilter']))
                    
        idx_cl = 0
        idx_full = 0
        toggle = True
        while len(res) < 4 and (idx_cl < len(cl_best) or idx_full < len(full_best)):
            if toggle and idx_cl < len(cl_best):
                stk, lot, ep, tag, src, rk6, rk7, pf = cl_best[idx_cl]
                if stk not in chosen_stocks:
                    res.append({'clean_stock': stk, 'lotsize': lot, 'entry_price': ep, 'lots_multiplier': 1, 'signal_tag': tag, 'source': src, 'rank_v6': rk6, 'rank_v7': rk7, 'passed_prefilter': pf})
                    chosen_stocks.add(stk)
                idx_cl += 1
                toggle = False
            elif idx_full < len(full_best):
                stk, lot, ep, tag, src, rk6, rk7, pf = full_best[idx_full]
                if stk not in chosen_stocks:
                    res.append({'clean_stock': stk, 'lotsize': lot, 'entry_price': ep, 'lots_multiplier': 1, 'signal_tag': tag, 'source': src, 'rank_v6': rk6, 'rank_v7': rk7, 'passed_prefilter': pf})
                    chosen_stocks.add(stk)
                idx_full += 1
                toggle = True
            elif idx_cl < len(cl_best):
                stk, lot, ep, tag, src, rk6, rk7, pf = cl_best[idx_cl]
                if stk not in chosen_stocks:
                    res.append({'clean_stock': stk, 'lotsize': lot, 'entry_price': ep, 'lots_multiplier': 1, 'signal_tag': tag, 'source': src, 'rank_v6': rk6, 'rank_v7': rk7, 'passed_prefilter': pf})
                    chosen_stocks.add(stk)
                idx_cl += 1
            else:
                break
                
        for item in res[:4]:
            item['date_str'] = d_str
            item['year'] = int(d_str[:4])
            all_trades.append(item)
            
    return pd.DataFrame(all_trades)

df_no_rep = run_allocation(use_prefilter_in_selection=False)
df_with_rep = run_allocation(use_prefilter_in_selection=True)

print(f"\n--- ALLOCATION COMPARISON ---")
print(f"Original allocation total trades: {len(df_no_rep):,}")
print(f"Original trades passing prefilter: {(df_no_rep['passed_prefilter']).sum():,}")
print(f"Original trades failing prefilter: {(~df_no_rep['passed_prefilter']).sum():,}")

print(f"\nWith Pre-Filter in selection (Replacements Active):")
print(f"Total trades selected: {len(df_with_rep):,}")
print(f"All pass prefilter: {df_with_rep['passed_prefilter'].all()}")

diff = len(df_with_rep) - (df_no_rep['passed_prefilter']).sum()
print(f"Number of NEW replacement candidates picked: {diff:,}")

# Let's see which trades are replacements!
set_orig_passed = set(df_no_rep[df_no_rep['passed_prefilter']]['date_str'] + '_' + df_no_rep[df_no_rep['passed_prefilter']]['clean_stock'])
set_with_rep = set(df_with_rep['date_str'] + '_' + df_with_rep['clean_stock'])

replacements = set_with_rep - set_orig_passed
print(f"Exact count of distinct replacement trades picked: {len(replacements):,}")


df_no_rep.to_csv('/home/ubuntu/sarang_2026_shortsell_algos/df_no_rep.csv', index=False)
df_with_rep.to_csv('/home/ubuntu/sarang_2026_shortsell_algos/df_with_rep.csv', index=False)
print("Saved both CSV files successfully!")

# Let's compute PnL using sl3_points_master.csv
orig_pass = df_no_rep[df_no_rep['passed_prefilter']].copy()
orig_fail = df_no_rep[~df_no_rep['passed_prefilter']].copy()

set_orig_passed = set(orig_pass['date_str'] + '_' + orig_pass['clean_stock'])
df_with_rep['key'] = df_with_rep['date_str'] + '_' + df_with_rep['clean_stock']
replacements = df_with_rep[~df_with_rep['key'].isin(set_orig_passed)].copy()

print(f"\nExact count of replacement trades: {len(replacements):,}")

# Points mapping
orig_fail['key'] = orig_fail['date_str'] + '_' + orig_fail['clean_stock']
orig_fail['points'] = [known_map.get(k, 0.0) for k in orig_fail['key']]
orig_fail['traded_qty'] = orig_fail['lotsize'] * orig_fail['lots_multiplier']
orig_fail['gross_pnl'] = orig_fail['points'] * orig_fail['traded_qty']
orig_fail['f1_charges'] = 600.0 * orig_fail['lots_multiplier']
orig_fail['net_pnl'] = orig_fail['gross_pnl'] - orig_fail['f1_charges']

replacements['points'] = [known_map.get(k, 0.0) for k in replacements['key']]
replacements['traded_qty'] = replacements['lotsize'] * replacements['lots_multiplier']
replacements['gross_pnl'] = replacements['points'] * replacements['traded_qty']
replacements['f1_charges'] = 600.0 * replacements['lots_multiplier']
replacements['net_pnl'] = replacements['gross_pnl'] - replacements['f1_charges']

print("\n" + "=" * 80)
print(f"1. DISCARDED TOXIC TRADES ({len(orig_fail)} setups that failed 09:41 pre-filter):")
print(f"   • Gross PnL: Rs {orig_fail['gross_pnl'].sum()/1e5:+.2f} Lakhs")
print(f"   • Net PnL:   Rs {orig_fail['net_pnl'].sum()/1e5:+.2f} Lakhs")
print(f"   • Win Rate:  {(orig_fail['net_pnl'] > 0).mean()*100:.2f}%")

print(f"\n2. NEW REPLACEMENT CANDIDATES ({len(replacements)} next-in-line trades picked):")
print(f"   • Gross PnL: Rs {replacements['gross_pnl'].sum()/1e5:+.2f} Lakhs")
print(f"   • Net PnL:   Rs {replacements['net_pnl'].sum()/1e5:+.2f} Lakhs")
print(f"   • Win Rate:  {(replacements['net_pnl'] > 0).mean()*100:.2f}%")

net_edge = (replacements['net_pnl'].sum() - orig_fail['net_pnl'].sum()) / 1e5
print(f"\n3. NET SYSTEM UPGRADE BY FILLING EMPTY SLOTS WITH REPLACEMENTS:")
print(f"   • Net PnL Advantage: Rs {net_edge:+.2f} Lakhs (+Rs {net_edge*1e5:+,.0f})")
print(f"   • Win Rate Jump: +{(replacements['net_pnl'] > 0).mean()*100 - (orig_fail['net_pnl'] > 0).mean()*100:+.2f}%")
print("=" * 80)

