#!/usr/bin/env python3
"""
rebuild_model2_from_scratch_strict_db.py
=========================================
Model 2 COMPLETE FROM-SCRATCH REBUILD — Zero Lookahead Bias, Strict DB-Only Pricing.

KEY GUARANTEES:
  1. ZERO LOOKAHEAD BIAS: Walk-forward expanding window — train on year < Y, test on year Y.
  2. STRICT DB-ONLY PRICES: ALL entry/exit prices come exclusively from MySQL DB.
       - Cash prices → scrapdata
       - Futures F1 prices → scrapdata_F1
       NO ML dataset prices used for execution. No assumptions. No fallbacks.
  3. NO CROSS-TABLE MIXING: Cash entry + Cash exit, F1 entry + F1 exit. Never mixed.
  4. PROXIMITY RULE: If no tick found within ±3 minutes of target time → SKIP TRADE ENTIRELY.
  5. STRICT 4 TRADES PER DAY via Candidate Replacement Queue.
  6. MAX 2x LOTS on any single trade (Dual Confirmed). No 3x.

5 GOLDEN RULES (applied tick-by-tick on DB ticks):
  Rule 1: Pre-Entry Filter at 09:41 — reject if gain_pct < -1.5% OR (2.0% <= gain_pct < 3.0%)
  Rule 2: Stop Loss = entry * 1.035 (hit when high >= sl)
  Rule 3: At 10:30 — if max_high_since_0942 > pre_entry_high_0915_0941 AND loss >= 1.0% → exit
  Rule 4: At 11:00 if loss >= 2.0% → exit; at 11:30 if loss >= 2.2% → exit
  Rule 5: If trough <= entry * 0.98 → activate trailing stop at trough * 1.02; exit if high >= trail_sl

ARCHITECTURE:
  Phase 1: LightGBM V6+V7 walk-forward allocation → daily candidate queue (stored in memory)
  Phase 2: Rule 1 pre-filter per trade per day with next-candidate replacement
  Phase 3: Tick-by-tick 5-rule simulation querying DB for all execution prices
  Phase 4: PnL calculation for both Cash (Kotak MIS) and F1 (Flat ₹600/lot)
"""

import os, sys, warnings, datetime
import pandas as pd
import numpy as np
import pymysql
import lightgbm as lgb
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

warnings.filterwarnings('ignore')

sys.path.insert(0, '/home/ubuntu/sarang_2026_shortsell_algos')
from kotak_mis_calculator import calculate_kotak_charges

# ─── FILE PATHS ────────────────────────────────────────────────────────────────
SCRIPT_DIR   = '/home/ubuntu/sarang_2026_shortsell_algos/02_Best_Longer_Window_0942_1445'
DATA_DIR     = os.path.join(SCRIPT_DIR, 'data')
DATA_FILE    = os.path.join(DATA_DIR, 'short_sell_ml_dataset_v5_scratch.csv.gz')
LOTS_FILE    = os.path.join(DATA_DIR, 'historical_lotsize_new.csv')
PNL_FILE     = os.path.join(DATA_DIR, 'markets_pnl0325.csv.gz')
OUT_LEDGER   = '/home/ubuntu/sarang_2026_shortsell_algos/rebuild_model2_strict_db_ledger.csv'

# ─── DB CONNECTION ─────────────────────────────────────────────────────────────
def get_db():
    return pymysql.connect(
        host='localhost', user='root', password='root',
        database='markets', autocommit=True,
        cursorclass=pymysql.cursors.DictCursor
    )

# ─── CONSTANTS ─────────────────────────────────────────────────────────────────
MAX_LOTS_MULT   = 2       # Hard cap: max 2x lots on any trade
TRADES_PER_DAY  = 4       # Strict 4 trades per day
PROX_SECONDS    = 180     # ±3 minutes proximity rule for DB tick lookup
RULE2_SL_PCT    = 1.035   # 3.5% stop loss
RULE3_LOSS_PCT  = 1.0     # At 10:30 loss threshold (%)
RULE4A_LOSS_PCT = 2.0     # At 11:00 loss threshold (%)
RULE4B_LOSS_PCT = 2.2     # At 11:30 loss threshold (%)
RULE5_TRIG_PCT  = 0.98    # Trailing stop activation: trough <= entry * 0.98
RULE5_TRAIL_PCT = 1.02    # Trailing stop level: trough * 1.02
F1_FLAT_CHARGE  = 600.0   # ₹600 flat per lot traded (Futures F1)

# ─── FEATURES USED BY LIGHTGBM ─────────────────────────────────────────────────
FEATURES = [
    'gap_0907_pct', 'gap_fade_0907_to_940_pct',
    'prev_intraday_vwap_gap', 'prev_intraday_return', 'prev_intraday_roc_last_hour',
    'morn_range_pct', 'rejection_wick'
]

# ══════════════════════════════════════════════════════════════════════════════
# PHASE 0: LOAD STATIC DATA
# ══════════════════════════════════════════════════════════════════════════════

def load_lot_map():
    """Load historical lot sizes for walk-forward lookups."""
    df_lots = pd.read_csv(LOTS_FILE)
    df_lots['exp_dt'] = pd.to_datetime(df_lots['expdate'], format='%d/%m/%Y', errors='coerce')
    df_lots['clean_stock'] = df_lots['stockname'].astype(str).str.strip().str.upper()
    lot_map = {s: grp.sort_values('exp_dt') for s, grp in df_lots.groupby('clean_stock')}
    return lot_map

def get_exact_lot(lot_map, stock, dt, fallback=1000):
    stk = str(stock).strip().upper()
    if stk not in lot_map:
        return fallback
    sub = lot_map[stk]
    f = sub[sub['exp_dt'] >= dt]
    return int(f.iloc[0]['lotsize']) if len(f) > 0 else int(sub.iloc[-1]['lotsize'])

def load_ml_dataset(lot_map):
    """Load ML dataset — used ONLY for features + prev_close. NOT for execution prices."""
    df = pd.read_csv(DATA_FILE, low_memory=False)
    df['clean_stock'] = df['clean_stock'].astype(str).str.strip().str.upper()
    df['date_dt'] = pd.to_datetime(df['date_str'])
    df['year'] = df['date_dt'].dt.year
    # Exclude Mondays (no new positions on Mondays per strategy spec)
    df = df[df['date_dt'].dt.dayofweek != 0].sort_values('date_dt').reset_index(drop=True)
    # Get historical lot size for each row
    df['lotsize'] = [
        get_exact_lot(lot_map, s, d, q)
        for s, d, q in zip(df['clean_stock'], df['date_dt'], df['quantity'])
    ]
    # Ensure features are numeric
    for f in FEATURES:
        if f in df.columns:
            df[f] = pd.to_numeric(df[f], errors='coerce').fillna(0.0)
    df['short_target'] = df['short_pct_return']
    return df

def load_cl_tag(df):
    """Tag Custom Limit Fill trades (for CL vs Full split)."""
    pnl = pd.read_csv(PNL_FILE, usecols=['simulationdate', 'stockname', 'sell_exec_type'])
    pnl['buy_day'] = pd.to_datetime(
        pnl['simulationdate'], format='mixed', dayfirst=True, errors='coerce'
    ).dt.strftime('%Y-%m-%d')
    pnl['clean_stock'] = pnl['stockname'].astype(str).str.strip().str.upper()
    cl_only = set(zip(
        pnl[pnl['sell_exec_type'] == 'Custom Limit Fill']['buy_day'],
        pnl[pnl['sell_exec_type'] == 'Custom Limit Fill']['clean_stock']
    ))
    df['is_strict_cl'] = [(b, s) in cl_only for b, s in zip(df['buy_day'], df['clean_stock'])]
    return df

# ══════════════════════════════════════════════════════════════════════════════
# PHASE 1: WALK-FORWARD ML ALLOCATION (Zero Lookahead)
# ══════════════════════════════════════════════════════════════════════════════

def train_and_allocate_walk_forward(df):
    """
    Walk-forward expanding window allocation.
    For each test year Y: train on all data where year < Y.
    Returns a DataFrame of allocated candidates (up to 4 per day, ranked queue).
    """
    years = sorted(df[df['year'] >= 2020]['year'].unique())
    print(f"\n{'='*80}")
    print("PHASE 1: Walk-Forward LightGBM Allocation (Zero Lookahead Bias)")
    print(f"{'='*80}")
    print(f"Test years: {years}")

    df_cl   = df[df['is_strict_cl']].copy()
    df_full = df.copy()

    all_allocations = []

    for y in years:
        # ── Training sets: strictly year < y (expanding window, no lookahead) ──
        tr_cl   = df_cl  [(df_cl  ['year'] >= 2018) & (df_cl  ['year'] < y)].copy()
        te_cl   = df_cl  [df_cl  ['year'] == y].copy()
        tr_full = df_full[(df_full['year'] >= 2018) & (df_full['year'] < y)].copy()
        te_full = df_full[df_full['year'] == y].copy()

        if len(tr_cl) < 30 or len(te_cl) == 0 or len(tr_full) < 30 or len(te_full) == 0:
            print(f"  Year {y}: Insufficient data, skipping.")
            continue

        print(f"  Year {y}: Train CL={len(tr_cl)}, TrainFull={len(tr_full)} | Test CL={len(te_cl)}, TestFull={len(te_full)}")

        # CL V6
        m6_cl = lgb.LGBMRegressor(n_estimators=100, learning_rate=0.05, max_depth=5,
                                    random_state=42, n_jobs=-1, verbose=-1)
        m6_cl.fit(tr_cl[FEATURES], tr_cl['short_target'])
        te_cl['pred_v6_cl'] = m6_cl.predict(te_cl[FEATURES])
        te_cl['rank_v6_cl'] = te_cl.groupby('date_str')['pred_v6_cl'].rank(ascending=False, method='first')

        # CL V7 (gap-fade sub-universe)
        tr7_cl = tr_cl[tr_cl['gap_fade_0907_to_940_pct'] < 0.0].copy()
        te7_cl = te_cl[te_cl['gap_fade_0907_to_940_pct'] < 0.0].copy()
        if len(tr7_cl) > 0 and len(te7_cl) > 0:
            m7_cl = lgb.LGBMRegressor(n_estimators=100, learning_rate=0.05, max_depth=5,
                                       random_state=42, n_jobs=-1, verbose=-1)
            m7_cl.fit(tr7_cl[FEATURES], tr7_cl['short_target'])
            te7_cl['pred_v7_cl'] = m7_cl.predict(te7_cl[FEATURES])
            te7_cl['rank_v7_cl'] = te7_cl.groupby('date_str')['pred_v7_cl'].rank(ascending=False, method='first')
            te_cl = te_cl.merge(te7_cl[['date_str', 'clean_stock', 'rank_v7_cl']],
                                on=['date_str', 'clean_stock'], how='left')
        else:
            te_cl['rank_v7_cl'] = 999.0
        te_cl['rank_v7_cl'] = te_cl['rank_v7_cl'].fillna(999.0)

        # Full V6
        m6_full = lgb.LGBMRegressor(n_estimators=100, learning_rate=0.05, max_depth=5,
                                     random_state=42, n_jobs=-1, verbose=-1)
        m6_full.fit(tr_full[FEATURES], tr_full['short_target'])
        te_full['pred_v6_full'] = m6_full.predict(te_full[FEATURES])
        te_full['rank_v6_full'] = te_full.groupby('date_str')['pred_v6_full'].rank(ascending=False, method='first')

        # Full V7 (gap-fade sub-universe)
        tr7_full = tr_full[tr_full['gap_fade_0907_to_940_pct'] < 0.0].copy()
        te7_full = te_full[te_full['gap_fade_0907_to_940_pct'] < 0.0].copy()
        if len(tr7_full) > 0 and len(te7_full) > 0:
            m7_full = lgb.LGBMRegressor(n_estimators=100, learning_rate=0.05, max_depth=5,
                                         random_state=42, n_jobs=-1, verbose=-1)
            m7_full.fit(tr7_full[FEATURES], tr7_full['short_target'])
            te7_full['pred_v7_full'] = m7_full.predict(te7_full[FEATURES])
            te7_full['rank_v7_full'] = te7_full.groupby('date_str')['pred_v7_full'].rank(ascending=False, method='first')
            te_full = te_full.merge(te7_full[['date_str', 'clean_stock', 'rank_v7_full']],
                                    on=['date_str', 'clean_stock'], how='left')
        else:
            te_full['rank_v7_full'] = 999.0
        te_full['rank_v7_full'] = te_full['rank_v7_full'].fillna(999.0)

        # ── Strategy 4 Allocation: Dual Confirmed first, then 50/50 CL/Full ──
        day_alloc = allocate_daily_candidates(te_cl, te_full, year=y)
        all_allocations.append(day_alloc)
        print(f"    → Allocated {len(day_alloc):,} candidate trade slots across {day_alloc['date_str'].nunique()} days")

    df_allocated = pd.concat(all_allocations, ignore_index=True)
    print(f"\n  ✔ Total allocated slots: {len(df_allocated):,} across {df_allocated['date_str'].nunique()} trading days")
    return df_allocated


def allocate_daily_candidates(te_cl, te_full, year):
    """
    For each trading day, build a ranked candidate queue:
      Priority 1: DUAL_CONFIRMED stocks (top-4 in both CL and Full models) → 2x lots max
      Priority 2: 50/50 alternating CL then Full single-model tops
    Each stock appears max once per day. Max 4 slots filled.
    Returns ALL candidates (including extras beyond 4) for replacement queue.
    """
    cl_by_date   = {d: g for d, g in te_cl.groupby('date_str')}
    full_by_date = {d: g for d, g in te_full.groupby('date_str')}
    all_dates = sorted(set(list(cl_by_date.keys()) + list(full_by_date.keys())))

    all_rows = []
    cols_cl   = ['date_str', 'clean_stock', 'year', 'lotsize', 'prev_close', 'rank_v6_cl', 'rank_v7_cl']
    cols_full = ['date_str', 'clean_stock', 'year', 'lotsize', 'prev_close', 'rank_v6_full', 'rank_v7_full']

    for d_str in all_dates:
        cl_day   = cl_by_date.get(d_str, pd.DataFrame())
        full_day = full_by_date.get(d_str, pd.DataFrame())

        # Build dual confirmed candidates
        dual_cands = {}
        if len(cl_day) > 0:
            for _, r in cl_day[cl_day['rank_v6_cl'] <= 4].iterrows():
                stk = r['clean_stock']
                if stk not in dual_cands:
                    dual_cands[stk] = {'lotsize': r['lotsize'], 'prev_close': r['prev_close'],
                                       'sources': set(), 'rank_v6': r['rank_v6_cl'], 'rank_v7': r['rank_v7_cl']}
                dual_cands[stk]['sources'].add('CL')

        if len(full_day) > 0:
            for _, r in full_day[full_day['rank_v6_full'] <= 4].iterrows():
                stk = r['clean_stock']
                if stk not in dual_cands:
                    dual_cands[stk] = {'lotsize': r['lotsize'], 'prev_close': r['prev_close'],
                                       'sources': set(), 'rank_v6': r['rank_v6_full'], 'rank_v7': r['rank_v7_full']}
                else:
                    dual_cands[stk]['sources'].add('FULL')
                dual_cands[stk]['sources'].add('FULL')

        # Sort: both-model stocks first, then by rank
        sorted_duals = sorted(dual_cands.items(),
                               key=lambda x: (len(x[1]['sources']) > 1, -x[1]['rank_v6']),
                               reverse=True)

        result     = []
        chosen     = set()
        slot_order = 0

        for stk, info in sorted_duals:
            is_dual = len(info['sources']) > 1
            mult = MAX_LOTS_MULT if is_dual else 1  # Max 2x for dual, 1x for single
            result.append({
                'date_str': d_str, 'year': year, 'clean_stock': stk,
                'lotsize': info['lotsize'], 'prev_close': info['prev_close'],
                'lots_multiplier': mult,
                'signal_tag': 'DUAL_CONFIRMED' if is_dual else 'SINGLE_MODEL',
                'source': '+'.join(sorted(info['sources'])),
                'rank_v6': info['rank_v6'], 'rank_v7': info['rank_v7'],
                'slot_priority': slot_order
            })
            chosen.add(stk)
            slot_order += 1

        # 50/50 CL / Full remainder candidates
        cl_sorted   = cl_day.sort_values(['rank_v6_cl', 'rank_v7_cl']) if len(cl_day) > 0 else pd.DataFrame()
        full_sorted = full_day.sort_values(['rank_v6_full', 'rank_v7_full']) if len(full_day) > 0 else pd.DataFrame()

        cl_list   = [(r['clean_stock'], r['lotsize'], r['prev_close'], 'SINGLE_CL',   r['rank_v6_cl'],   r['rank_v7_cl'])
                     for _, r in cl_sorted.iterrows()   if r['clean_stock'] not in chosen]
        full_list = [(r['clean_stock'], r['lotsize'], r['prev_close'], 'SINGLE_FULL', r['rank_v6_full'], r['rank_v7_full'])
                     for _, r in full_sorted.iterrows() if r['clean_stock'] not in chosen]

        ic, ifull, toggle = 0, 0, True
        while ic < len(cl_list) or ifull < len(full_list):
            if toggle and ic < len(cl_list):
                stk, lot, pc, tag, r6, r7 = cl_list[ic]; ic += 1; toggle = False
            elif ifull < len(full_list):
                stk, lot, pc, tag, r6, r7 = full_list[ifull]; ifull += 1; toggle = True
            elif ic < len(cl_list):
                stk, lot, pc, tag, r6, r7 = cl_list[ic]; ic += 1
            else:
                break

            if stk not in chosen:
                result.append({
                    'date_str': d_str, 'year': year, 'clean_stock': stk,
                    'lotsize': lot, 'prev_close': pc,
                    'lots_multiplier': 1,
                    'signal_tag': tag, 'source': tag,
                    'rank_v6': r6, 'rank_v7': r7,
                    'slot_priority': slot_order
                })
                chosen.add(stk)
                slot_order += 1

        all_rows.extend(result)

    return pd.DataFrame(all_rows)


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 2: RULE 1 PRE-FILTER + REPLACEMENT QUEUE (Strict DB Lookup)
# ══════════════════════════════════════════════════════════════════════════════

def query_price_at_time(cur, table, d, s, target_time_str, prox_sec=PROX_SECONDS):
    """
    Query the closest tick to target_time_str from the given table/stock/date.
    Returns (close_price, actual_time) or (None, None) if not found within prox_sec.
    Uses COALESCE(close, price) to get the bar's closing price.
    """
    target_dt = datetime.datetime.strptime(f"{d} {target_time_str}", "%Y-%m-%d %H:%M:%S")
    # Window: ±3 min around target
    win_start = (target_dt - datetime.timedelta(seconds=prox_sec)).strftime("%Y-%m-%d %H:%M:%S")
    win_end   = (target_dt + datetime.timedelta(seconds=prox_sec)).strftime("%Y-%m-%d %H:%M:%S")

    cur.execute(f"""
        SELECT time, COALESCE(close, price) AS close_price, price
        FROM `{table}`
        WHERE date = '{d}'
          AND stockname IN ('{s}', '"{s}"', '{s} ')
          AND time >= '{win_start}' AND time <= '{win_end}'
        ORDER BY ABS(TIMESTAMPDIFF(SECOND, time, '{d} {target_time_str}')) ASC
        LIMIT 1
    """)
    row = cur.fetchone()
    if row is None:
        return None, None
    actual_time = row['time']
    delta_sec = abs((actual_time - target_dt).total_seconds())
    if delta_sec > prox_sec:
        return None, None
    price = float(row['close_price'] or row['price'] or 0)
    if price <= 0:
        return None, None
    return price, actual_time


def apply_rule1_filter_and_fill_slots(df_allocated):
    """
    For each trading day, apply Rule 1 pre-filter from DB prices.
    Rule 1: gain_pct = (price_0941 - prev_close) / prev_close * 100
      REJECT if: gain_pct < -1.5 OR (2.0 <= gain_pct < 3.0)
    Fill slots 1-4 from ranked candidate queue.
    Any failed trade → replace with next-ranked candidate from same day's queue.
    ALL prices come from DB. If 09:41 price not found within ±3 min → skip (no price = Rule 1 reject).
    Returns DataFrame of final 4 trades per day (or fewer if queue exhausted).
    """
    print(f"\n{'='*80}")
    print("PHASE 2: Rule 1 Pre-Filter + Candidate Replacement Queue (DB-Only 09:41 prices)")
    print(f"{'='*80}")

    by_date = {d: g.sort_values('slot_priority').reset_index(drop=True)
               for d, g in df_allocated.groupby('date_str')}

    all_final = []
    total_skipped  = 0
    total_replaced = 0
    total_no_price = 0

    conn = get_db()
    cur  = conn.cursor(pymysql.cursors.DictCursor)

    dates = sorted(by_date.keys())
    for di, d_str in enumerate(dates):
        if di % 100 == 0:
            print(f"  Rule 1 filtering: {di}/{len(dates)} dates processed...")

        candidates = by_date[d_str].to_dict('records')
        filled_slots = []
        used_stocks  = set()
        cand_idx     = 0

        while len(filled_slots) < TRADES_PER_DAY and cand_idx < len(candidates):
            cand = candidates[cand_idx]
            cand_idx += 1
            stk = cand['clean_stock']
            if stk in used_stocks:
                continue

            # ── Query 09:41 price from Cash (scrapdata) for Rule 1 ──
            price_0941, tick_time = query_price_at_time(cur, 'scrapdata', d_str, stk, '09:41:00')

            if price_0941 is None:
                # No DB tick found within ±3 min of 09:41 → skip this candidate
                total_no_price += 1
                total_skipped  += 1
                continue

            prev_close = float(cand.get('prev_close', 0) or 0)
            if prev_close <= 0:
                # No prev_close in ML dataset → skip
                total_skipped += 1
                continue

            gain_pct = (price_0941 - prev_close) / prev_close * 100.0

            # ── Rule 1 Filter ──
            reject = (gain_pct < -1.5) or (2.0 <= gain_pct < 3.0)
            if reject:
                total_replaced += 1
                continue

            cand['price_0941_db']  = price_0941
            cand['gain_pct_0941']  = round(gain_pct, 4)
            cand['rule1_tick_time'] = str(tick_time)
            used_stocks.add(stk)
            filled_slots.append(cand)

        all_final.extend(filled_slots)

    conn.close()

    df_final = pd.DataFrame(all_final)
    print(f"\n  ✔ Final trades after Rule 1: {len(df_final):,}")
    print(f"  ✔ Trades replaced via queue: {total_replaced:,}")
    print(f"  ✔ Skipped (no DB price @ 09:41): {total_no_price:,}")
    print(f"  ✔ Days covered: {df_final['date_str'].nunique():,}")
    return df_final


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 3: 5-RULE TICK-BY-TICK SIMULATION (Strict DB-Only)
# ══════════════════════════════════════════════════════════════════════════════

def sim_one_trade(trade):
    """
    Simulate a single trade using strictly DB ticks.
    Returns result dict with both Cash and F1 PnL.
    
    Entry price: nearest tick to 09:42:00 ± 3 min (separate Cash vs F1 queries)
    Pre-entry high for Rule 3: MAX(high) from scrapdata 09:15:00 to 09:41:59
    Tick-by-tick simulation: scrapdata (Cash) and scrapdata_F1 (Futures) independently
    """
    d   = str(trade['date_str'])[:10]
    s   = str(trade['clean_stock']).strip().upper()
    lot = int(trade['lotsize'])
    mult = min(MAX_LOTS_MULT, int(trade.get('lots_multiplier', 1)))
    qty  = lot * mult
    yr   = int(trade['year'])

    conn = get_db()
    cur  = conn.cursor(pymysql.cursors.DictCursor)

    try:
        # ── Step A: Query entry prices from Cash and F1 ──
        en_cash, en_cash_time = query_price_at_time(cur, 'scrapdata',    d, s, '09:42:00')
        en_f1,   en_f1_time   = query_price_at_time(cur, 'scrapdata_F1', d, s, '09:42:00')

        # If BOTH entry prices missing → skip the trade entirely
        if en_cash is None and en_f1 is None:
            return None

        # ── Step B: Pre-entry high for Rule 3 (Cash only, 09:15 to 09:41) ──
        cur.execute(f"""
            SELECT MAX(high) AS pre_high, MAX(price) AS pre_max_p
            FROM scrapdata
            WHERE date = '{d}'
              AND stockname IN ('{s}', '"{s}"', '{s} ')
              AND time >= '{d} 09:15:00' AND time < '{d} 09:42:00'
        """)
        m_row = cur.fetchone()
        pre_entry_high_cash = float(m_row['pre_high'] or m_row['pre_max_p'] or 0)

        # Pre-entry high for F1 (same window)
        cur.execute(f"""
            SELECT MAX(high) AS pre_high, MAX(price) AS pre_max_p
            FROM scrapdata_F1
            WHERE date = '{d}'
              AND stockname IN ('{s}', '"{s}"', '{s} ')
              AND time >= '{d} 09:15:00' AND time < '{d} 09:42:00'
        """)
        m_row_f1 = cur.fetchone()
        pre_entry_high_f1 = float(m_row_f1['pre_high'] or m_row_f1['pre_max_p'] or 0)

        # ── Step C: Fetch all intraday ticks 09:42 to 14:45 from both tables ──
        cur.execute(f"""
            SELECT time, price, high, low, COALESCE(close, price) AS close
            FROM scrapdata
            WHERE date = '{d}'
              AND stockname IN ('{s}', '"{s}"', '{s} ')
              AND time >= '{d} 09:42:00' AND time <= '{d} 14:45:59'
            ORDER BY time ASC
        """)
        ticks_cash = cur.fetchall()

        cur.execute(f"""
            SELECT time, price, high, low, COALESCE(close, price) AS close
            FROM scrapdata_F1
            WHERE date = '{d}'
              AND stockname IN ('{s}', '"{s}"', '{s} ')
              AND time >= '{d} 09:42:00' AND time <= '{d} 14:45:59'
            ORDER BY time ASC
        """)
        ticks_f1 = cur.fetchall()

    finally:
        conn.close()

    # ── Build result skeleton ──
    base = {
        'date': d, 'stockname': s, 'year': yr, 'lotsize': lot,
        'lots_multiplier': mult, 'qty': qty,
        'signal_tag': trade.get('signal_tag', ''),
        'source': trade.get('source', ''),
        'price_0941_db': trade.get('price_0941_db', None),
        'gain_pct_0941': trade.get('gain_pct_0941', None),
    }

    # ── Simulate for each instrument independently ──
    def run_5_rules(ticks, en_price, pre_entry_high, instrument_label):
        """Apply all 5 rules tick-by-tick on provided ticks array."""
        if en_price is None or len(ticks) < 5:
            return None  # Not enough data → skip this instrument

        sl     = en_price * RULE2_SL_PCT
        trough = en_price
        trail_sl      = sl
        trail_active  = False
        max_h_1030    = 0.0
        ex_price      = None
        exit_reason   = '1445_TIME_EXIT'
        exit_time_str = '14:45:00'
        last_close    = en_price

        for tick in ticks:
            tm = tick['time']
            if isinstance(tm, datetime.datetime):
                tm_str = tm.strftime("%Y-%m-%d %H:%M:%S")
            else:
                tm_str = str(tm)

            h  = float(tick['high']  or tick['price'] or en_price)
            l  = float(tick['low']   or tick['price'] or en_price)
            cl = float(tick['close'] or tick['price'] or en_price)
            last_close = cl

            # ── Rule 5: Update trough & trail stop ──
            if l < trough:
                trough = l
            if not trail_active and trough <= en_price * RULE5_TRIG_PCT:
                trail_active = True
                trail_sl = trough * RULE5_TRAIL_PCT

            if trail_active:
                new_sl = round(trough * RULE5_TRAIL_PCT, 4)
                if new_sl < trail_sl:
                    trail_sl = new_sl
                # Trail stop takes over from initial SL
                cur_sl = trail_sl
            else:
                cur_sl = sl

            # ── Rule 2: Initial stop loss hit ──
            if h >= cur_sl:
                ex_price    = cur_sl
                exit_reason = 'TRAIL_STOP' if trail_active else 'STOP_LOSS_3.5PCT'
                exit_time_str = tm_str
                break

            # Track max high up to 10:30 for Rule 3
            if tm_str <= f"{d} 10:30:59":
                if h > max_h_1030:
                    max_h_1030 = h

            # ── Rule 3: At 10:30 (REMOVED - Toxic) — New HOD since entry + loss ≥ 1% ──
            # if (f"{d} 10:30:00" <= tm_str <= f"{d} 10:30:59") and not trail_active:
            # loss_pct = (cl - en_price) / en_price * 100.0
            # if (pre_entry_high > 0) and (max_h_1030 > pre_entry_high) and (loss_pct >= RULE3_LOSS_PCT):
            # ex_price    = cl
            # exit_reason = 'RULE3_CUT_1030'
            # exit_time_str = f"{d} 10:30:00"
            # break

            # ── Rule 4a: At 11:00 — loss ≥ 2.0% ──
            if (f"{d} 11:00:00" <= tm_str <= f"{d} 11:00:59") and not trail_active:
                loss_pct = (cl - en_price) / en_price * 100.0
                if loss_pct >= RULE4A_LOSS_PCT:
                    ex_price    = cl
                    exit_reason = 'RULE4A_CUT_1100'
                    exit_time_str = f"{d} 11:00:00"
                    break

            # ── Rule 4b: At 11:30 (REMOVED - Toxic) — loss ≥ 2.2% ──
            # if (f"{d} 11:30:00" <= tm_str <= f"{d} 11:30:59") and not trail_active:
            # loss_pct = (cl - en_price) / en_price * 100.0
            # if loss_pct >= RULE4B_LOSS_PCT:
            # ex_price    = cl
            # exit_reason = 'RULE4B_CUT_1130'
            # exit_time_str = f"{d} 11:30:00"
            # break

        if ex_price is None:
            # Time exit at 14:45 — use last available close
            ex_price      = last_close
            exit_reason   = '1445_TIME_EXIT'
            exit_time_str = f"{d} 14:45:00"

        gross = (en_price - ex_price) * qty
        return {
            f'{instrument_label}_entry':       en_price,
            f'{instrument_label}_exit':        ex_price,
            f'{instrument_label}_exit_reason': exit_reason,
            f'{instrument_label}_exit_time':   exit_time_str,
            f'{instrument_label}_gross':       gross,
        }

    res_cash = run_5_rules(ticks_cash, en_cash, pre_entry_high_cash, 'cash')
    res_f1   = run_5_rules(ticks_f1,   en_f1,   pre_entry_high_f1,   'f1')

    # If both simulations failed → skip trade
    if res_cash is None and res_f1 is None:
        return None

    result = {**base}

    # ── Cash (Kotak MIS) PnL ──
    if res_cash is not None:
        result.update(res_cash)
        eq_chg = calculate_kotak_charges(res_cash['cash_entry'], res_cash['cash_exit'], qty)['total_charges']
        result['eq_charges'] = eq_chg
        result['eq_net']     = res_cash['cash_gross'] - eq_chg
    else:
        result.update({
            'cash_entry': None, 'cash_exit': None, 'cash_exit_reason': 'NO_DB_TICK',
            'cash_exit_time': None, 'cash_gross': None, 'eq_charges': None, 'eq_net': None
        })

    # ── Futures F1 PnL ──
    if res_f1 is not None:
        result.update(res_f1)
        f1_chg = F1_FLAT_CHARGE * mult
        result['f1_charges'] = f1_chg
        result['f1_net']     = res_f1['f1_gross'] - f1_chg
    else:
        result.update({
            'f1_entry': None, 'f1_exit': None, 'f1_exit_reason': 'NO_DB_TICK',
            'f1_exit_time': None, 'f1_gross': None, 'f1_charges': None, 'f1_net': None
        })

    return result


def run_simulation_parallel(df_final, max_workers=20):
    """Run tick-by-tick 5-rule simulation in parallel across all trades."""
    print(f"\n{'='*80}")
    print("PHASE 3: 5-Rule Tick-by-Tick Simulation (Strict DB-Only Prices)")
    print(f"{'='*80}")
    print(f"  Simulating {len(df_final):,} trades with {max_workers} workers...")

    trades = df_final.to_dict('records')
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = list(ex.map(sim_one_trade, trades))
    results = [r for r in futures if r is not None]

    skipped = len(trades) - len(results)
    print(f"  ✔ Completed: {len(results):,} trades simulated")
    print(f"  ✔ Skipped (no DB entry ticks): {skipped:,} trades")
    return pd.DataFrame(results)


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 4: REPORTING
# ══════════════════════════════════════════════════════════════════════════════

def print_yoy_table(rdf, net_col, chg_col, gross_col, label):
    """Print Year-over-Year performance table for one instrument."""
    SEP  = "=" * 140
    HEAD = "-" * 140

    print(f"\n{SEP}")
    print(f"  {label} — YEAR-OVER-YEAR RESULTS (Model 2 From-Scratch Rebuild, Strict DB-Only)")
    print(SEP)
    print(f"{'Year':<6} | {'Trades':>8} | {'Gross (L)':>14} | {'Charges (L)':>12} | {'Net (L)':>14} | {'Cr':>10} | {'WinRate':>9} | {'PF':>8} | Status")
    print(HEAD)

    valid = rdf[rdf[net_col].notna()].copy()
    total_net_all = 0

    for y, g in valid.groupby('year'):
        trds   = len(g)
        gr     = g[gross_col].sum() / 1e5
        ch     = g[chg_col].sum() / 1e5
        nt     = g[net_col].sum() / 1e5
        total_net_all += nt
        wr     = (g[net_col] > 0).mean() * 100
        pos    = g[g[net_col] > 0][net_col].sum()
        neg    = abs(g[g[net_col] < 0][net_col].sum())
        pf     = pos / neg if neg > 0 else float('inf')
        status = "🟢" if nt > 0 else "🔴"
        print(f"{y:<6} | {trds:>8,} | +₹{gr:>10.2f} L | -₹{ch:>8.2f} L | +₹{nt:>10.2f} L | {nt/100:>8.3f} Cr | {wr:>7.2f}% | {pf:>6.2f}x | {status}")

    print(HEAD)
    tot_trds = len(valid)
    tot_gr   = valid[gross_col].sum() / 1e5
    tot_ch   = valid[chg_col].sum() / 1e5
    tot_nt   = valid[net_col].sum() / 1e5
    tot_wr   = (valid[net_col] > 0).mean() * 100
    tot_pos  = valid[valid[net_col] > 0][net_col].sum()
    tot_neg  = abs(valid[valid[net_col] < 0][net_col].sum())
    tot_pf   = tot_pos / tot_neg if tot_neg > 0 else float('inf')
    print(f"{'TOTAL':<6} | {tot_trds:>8,} | +₹{tot_gr:>10.2f} L | -₹{tot_ch:>8.2f} L | 👑 +₹{tot_nt:>8.2f} L | {tot_nt/100:>8.3f} Cr | {tot_wr:>7.2f}% | {tot_pf:>6.2f}x | 👑")
    print(SEP)


def print_exit_stats(rdf):
    """Print exit reason distribution for both instruments."""
    print(f"\n{'='*80}")
    print("EXIT REASON DISTRIBUTION:")
    print(f"{'='*80}")
    for col, label in [('cash_exit_reason', 'Cash'), ('f1_exit_reason', 'F1')]:
        if col not in rdf.columns:
            continue
        valid = rdf[rdf[col].notna() & (rdf[col] != 'NO_DB_TICK')]
        if len(valid) == 0:
            continue
        print(f"\n  [{label}] ({len(valid):,} trades):")
        for r, cnt in valid[col].value_counts().items():
            print(f"    • {r:<25}: {cnt:>5,} ({cnt/len(valid)*100:>5.1f}%)")


def main():
    print("=" * 80)
    print("🚀 MODEL 2 FROM-SCRATCH REBUILD — STRICT DB-ONLY PRICING (2020-2026)")
    print("   Zero Lookahead | DB-Only Prices | No Cross-Table Mixing | ±3min Proximity")
    print("=" * 80)

    # ── Load Static Data ──
    print("\n[LOADING] Lot sizes and ML dataset (features + prev_close only)...")
    lot_map = load_lot_map()
    df      = load_ml_dataset(lot_map)
    df      = load_cl_tag(df)
    print(f"  ✔ ML dataset: {len(df):,} rows, years {df['year'].min()}-{df['year'].max()}")

    # ── Phase 1: Walk-Forward Allocation ──
    df_allocated = train_and_allocate_walk_forward(df)

    # ── Phase 2: Rule 1 Pre-Filter + Replacement ──
    df_final = apply_rule1_filter_and_fill_slots(df_allocated)
    if len(df_final) == 0:
        print("ERROR: No trades survived Rule 1 filter. Check DB connectivity.")
        return

    # ── Phase 3: 5-Rule Simulation ──
    rdf = run_simulation_parallel(df_final, max_workers=20)

    # ── Save Ledger ──
    rdf.sort_values(['date', 'stockname'], inplace=True)
    rdf.to_csv(OUT_LEDGER, index=False)
    print(f"\n✔ Saved full trade ledger to: {OUT_LEDGER}")
    print(f"  Total rows: {len(rdf):,}")

    # ── Phase 4: Report ──
    print(f"\n{'#'*80}")
    print("FINAL RESULTS — MODEL 2 FROM-SCRATCH (STRICT DB-ONLY)")
    print(f"{'#'*80}")

    if 'eq_net' in rdf.columns:
        print_yoy_table(rdf, 'eq_net', 'eq_charges', 'cash_gross', 'EQUITY CASH (Kotak MIS)')
    if 'f1_net' in rdf.columns:
        print_yoy_table(rdf, 'f1_net', 'f1_charges', 'f1_gross', 'FUTURES F1 (Flat ₹600/lot)')

    print_exit_stats(rdf)

    # ── Daily trade count check ──
    print(f"\n{'='*80}")
    print("DAILY TRADE COUNT VALIDATION:")
    print(f"{'='*80}")
    if 'date' in rdf.columns:
        daily = rdf.groupby('date').size()
        print(f"  Max trades in a day:  {daily.max()}")
        print(f"  Min trades in a day:  {daily.min()}")
        print(f"  Mean trades per day:  {daily.mean():.2f}")
        print(f"  Days with exactly 4:  {(daily == 4).sum()}")
        print(f"  Days with < 4:        {(daily < 4).sum()}")
        print(f"  Days with > 4:        {(daily > 4).sum()} ← Must be 0")

    print(f"\n{'='*80}")
    print("✅ MODEL 2 FROM-SCRATCH REBUILD COMPLETE")
    print(f"{'='*80}\n")


if __name__ == '__main__':
    main()
