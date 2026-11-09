#!/usr/bin/env python3
"""
run_0940_hybrid_amrit_options_sim.py
=============================================================================
Comprehensive 3-Year (2024-2026) Put Option Simulation for 09:40 Hybrid Model
Comparing 3 Distinct Setups under Amrit's Institutional QA Guardrails:
  1. Setup 1: Rank #1 & #2 @ 09:42 (Immediate / Unconfirmed)
  2. Setup 2: Rank #1 & #2 Confirmed Later (09:43 - 10:45 AM)
  3. Setup 3: Confirmed Only (First-2 Confirmed across Top 4 Candidates)

Capital: Strictly ₹1.0 Lakh per stock, max 2 stocks per day (₹2.0 Lakhs total capital).
Institutional Guardrails:
  - Strict ₹0.05 NSE Tick Size Rounding (Zero non-tick exits!)
  - Bid/Ask spread friction (+1 tick entry ceil, -1 tick exit floor)
  - Smart Strike Step-Up (min premium >= ₹5.00, min lot cost >= ₹8,000)
  - Soft lot cap at 15 lots (SMART_STEPUP_MAX_OPTION_LOTS = 15)
  - Realistic option statutory charges & brokerage
  - Standardized ledger generation in option_simulation_ledgers/
=============================================================================
"""

import os
import re
import math
import pickle
import numpy as np
import pandas as pd

NSE_TICK = 0.05
OUT_REPO_DIR = "/home/ubuntu/options_sniper_upgrade_07_11_2026/option_simulation_ledgers"
os.makedirs(OUT_REPO_DIR, exist_ok=True)
OUT_LEDGER_PATH = os.path.join(OUT_REPO_DIR, "SIDE_BY_SIDE_2L_CAPITAL_LEDGER_0940_HYBRID_AMRIT_COMPLIANT_2024_2026.csv")

def round_to_nse_tick(price: float, direction: str = 'floor', tick: float = NSE_TICK) -> float:
    if price is None or np.isnan(price) or price <= 0:
        return 0.05
    if direction == 'floor':
        r = math.floor(round(price, 6) / tick) * tick
    elif direction == 'ceil':
        r = math.ceil(round(price, 6) / tick) * tick
    else:
        r = round(round(price, 6) / tick) * tick
    return max(0.05, round(r, 2))

def calculate_option_lots(allocated_capital: float, premium_cmp: float, lot_size: int, max_lots: int = 15) -> int:
    if premium_cmp <= 0 or lot_size <= 0 or allocated_capital <= 0:
        return 1
    contract_cost = premium_cmp * lot_size
    theoretical_lots = int(allocated_capital / contract_cost)
    if theoretical_lots < 1:
        theoretical_lots = 1 if allocated_capital >= 0.5 * contract_cost else 0
    bounded_lots = min(theoretical_lots, max_lots)
    return max(1, bounded_lots) if theoretical_lots >= 1 else 0

def get_opt_taxes(qty, buy_prem, sell_prem):
    b_turn = qty * buy_prem
    s_turn = qty * sell_prem
    tot = b_turn + s_turn
    brok = 40.0
    stt = s_turn * 0.001
    exch = tot * 0.0003503
    sebi = tot * 0.000001
    stamp = b_turn * 0.00003
    gst = 0.18 * (brok + exch + sebi)
    return round(brok + stt + exch + sebi + stamp + gst, 2)

def get_eq_taxes(qty, sell_price, buy_price):
    turnover = (qty * sell_price) + (qty * buy_price)
    stt = round(qty * sell_price * 0.00025)
    txn = turnover * 0.0000322
    sebi = turnover * 0.000001
    stamp = round(qty * buy_price * 0.00003)
    gst = (40.0 + txn + sebi) * 0.18
    return round(40.0 + stt + txn + sebi + stamp + gst, 2)

print("1. Loading 09:40 sniper cache and underlying ticks...", flush=True)
with open('/tmp/fno_only_0940_sniper_cache.pkl', 'rb') as f:
    cache = pickle.load(f)

picks_by_d = cache['fno_picks_by_date']
ticks = cache['full_ticks']
dates = sorted([d for d in picks_by_d.keys() if d >= '2024-01-01'])
print(f"   Loaded {len(dates)} trading days from 2024-01-01 to {dates[-1]}.", flush=True)

print("2. Loading Expiry dates & ICICI contracts...", flush=True)
# Expiry dates
with open('/home/ubuntu/KotakCodes1/expiry_dates.txt', 'r') as f:
    txt = f.read()
exp_2026 = [d.strip() for d in re.search(r'"([^"]+)"', txt).group(1).split(',') if d.strip()]
df_exp_hist = pd.read_csv('/home/ubuntu/github_repo/config/master_expiry_dates.csv')
exp_hist = [str(x).strip() for x in df_exp_hist['master_expiry_date'].dropna().unique() if str(x).strip() >= '2020-01-01']
clean_exps_by_ym = {}
for e in sorted(list(set(exp_2026 + exp_hist))):
    ym = e[:7]
    if ym not in clean_exps_by_ym or e in exp_2026:
        clean_exps_by_ym[ym] = e
all_expiries = sorted(clean_exps_by_ym.values())

def get_expiry_for_date(d_str):
    for e in all_expiries:
        if e >= d_str:
            return e
    return all_expiries[-1]

# Lotsize history & ICICI Master
df_lots_hist = pd.read_csv('/home/ubuntu/updatedshortsell_model/0940_model/data/historical_lotsize_new.csv', low_memory=False)
df_lots_hist['clean_stock'] = df_lots_hist['stockname'].astype(str).str.strip().str.upper()
df_lots_hist['expdate_dt'] = pd.to_datetime(df_lots_hist['expdate'], format='%d/%m/%Y', errors='coerce')
df_lots_hist['ym'] = df_lots_hist['expdate_dt'].dt.to_period('M')
hist_lot_map = {}
for (s, ym), grp in df_lots_hist.groupby(['clean_stock', 'ym']):
    lval = pd.to_numeric(grp['lotsize'], errors='coerce').dropna()
    if len(lval) > 0:
        hist_lot_map[(s, str(ym))] = int(lval.iloc[0])

df_m1 = pd.read_csv('/home/ubuntu/ICICImaster_options.csv')
df_opt = df_m1[(df_m1['instrumentname'] == 'OPTSTK') & (df_m1['OptionType'] == 'PE')].copy()
df_opt['stockcodes'] = df_opt['stockcodes'].astype(str).str.strip().str.upper()
df_opt['scripcode'] = df_opt['scripcode'].astype(str).str.strip().str.upper()
df_opt['StrikePrice'] = pd.to_numeric(df_opt['StrikePrice'], errors='coerce')
df_opt['lotsize'] = pd.to_numeric(df_opt['lotsize'], errors='coerce')

scrip_by_stk = {}
lot_by_stk = {}
step_by_stk = {}
ref_price_by_stk = {}
for stk, grp in df_opt.groupby('stockcodes'):
    scrip_by_stk[stk] = grp['scripcode'].iloc[0]
    lot_by_stk[stk] = int(grp['lotsize'].iloc[0])
    stks = np.sort(grp['StrikePrice'].unique())
    ref_price_by_stk[stk] = float(np.median(stks))
    if len(stks) >= 3:
        diffs = np.round(np.diff(stks), 4)
        vals, cnts = np.unique(diffs, return_counts=True)
        step_by_stk[stk] = float(vals[np.argmax(cnts)])
    else:
        step_by_stk[stk] = 10.0

try:
    with open('/home/ubuntu/github_repo/config/ICICImaster.csv', 'r') as f:
        for line in f.read().splitlines():
            parts = line.split(',')
            if len(parts) >= 7:
                nse_sym = parts[6].strip().upper()
                icici_sym = parts[2].strip().upper()
                if nse_sym and icici_sym and nse_sym not in scrip_by_stk:
                    scrip_by_stk[nse_sym] = icici_sym
except Exception:
    pass

def get_lot_size(stk, d_str):
    ym = d_str[:7]
    if (stk, ym) in hist_lot_map:
        return hist_lot_map[(stk, ym)]
    return lot_by_stk.get(stk, 100)

def get_historical_step(stk, entry_price):
    step_2026 = step_by_stk.get(stk, None)
    ref_p = ref_price_by_stk.get(stk, None)
    if step_2026 and ref_p and (0.55 * ref_p <= entry_price <= 1.65 * ref_p):
        return step_2026
    if entry_price > 5000: return 100.0
    if entry_price > 2500: return 50.0
    if entry_price > 1000: return 20.0
    if entry_price > 500:  return 10.0
    if entry_price > 100:  return 5.0
    if entry_price > 50:   return 2.5
    return 1.0

print("3. Loading and indexing Put Option 1-minute bars from parquet...", flush=True)
df_p = pd.read_parquet('/tmp/scrapdata_options_puts_2024_2026.parquet')
df_p['d_str'] = df_p['d_str'].astype(str)
df_p['t_str'] = df_p['t_str'].astype(str).str.split().str[-1]
df_p['strike_price'] = pd.to_numeric(df_p['strike_price'], errors='coerce').round(2)
for c in ['open', 'high', 'low', 'close', 'volume']:
    df_p[c] = pd.to_numeric(df_p[c], errors='coerce')

opt_bars_map = {}
opt_strikes_by_day = {}
for (stk, d_str, strike), grp in df_p.groupby(['stock_code', 'd_str', 'strike_price']):
    bars = []
    seen = set()
    for tm, o, h, l, c, v in zip(grp['t_str'], grp['open'], grp['high'], grp['low'], grp['close'], grp['volume']):
        p = float(c) if (c is not None and c > 0) else float(o or 0)
        if p <= 0 or tm < '09:15:00' or tm > '15:15:00' or tm in seen:
            continue
        seen.add(tm)
        t_int = int(tm.replace(':', '')[:4])
        bars.append((tm, t_int, float(o or p), float(h or p), float(l or p), p, int(v or 0)))
    if bars:
        stk_u = str(stk).strip().upper()
        s_r = round(float(strike), 2)
        opt_bars_map[(stk_u, str(d_str), s_r)] = bars
        if len(bars) >= 90:
            opt_strikes_by_day.setdefault((stk_u, str(d_str)), []).append((s_r, len(bars)))

print(f"   Indexed {len(opt_bars_map):,} option strike-day series.", flush=True)

def get_bars(stk, icici_code, d_str, strike):
    s = round(float(strike), 2)
    b = opt_bars_map.get((stk, d_str, s))
    if not b and icici_code:
        b = opt_bars_map.get((icici_code, d_str, s))
    return b or []

def detect_confirmations(valid_ticks):
    if len(valid_ticks) < 10:
        return None
    ep_0942 = valid_ticks[0][1]
    max_p = ep_0942
    vwap_sum = ep_0942
    vwap_cnt = 1
    for idx in range(1, len(valid_ticks) - 5):
        tm, p, t_int = valid_ticks[idx]
        if t_int > 1045:
            break
        vwap_sum += p
        vwap_cnt += 1
        vwap = vwap_sum / vwap_cnt
        prev_p1 = valid_ticks[idx - 1][1]
        prev_p2 = valid_ticks[max(0, idx - 2)][1]
        ret_1m = ((p - prev_p1) / prev_p1) * 100.0
        ret_2m = ((p - prev_p2) / prev_p2) * 100.0
        move_0942 = ((p - ep_0942) / ep_0942) * 100.0
        max_bounce = ((max_p - ep_0942) / ep_0942) * 100.0
        cond_a = (max_bounce <= 0.35) and (-0.55 <= move_0942 <= -0.20) and (ret_1m < 0.0) and (p < vwap)
        cond_b = (0.25 <= max_bounce <= 1.25) and (-0.40 <= move_0942 <= -0.05) and (ret_1m < 0.0) and (ret_2m <= -0.10) and (p < vwap)
        if cond_a or cond_b:
            return idx, tm, t_int, ('DIRECT_DOWN' if cond_a else 'BOUNCE_REJ')
        max_p = max(max_p, p)
    return None

def sim_underlying_w80_detail(rem_ticks, arm1=0.35, fl1=0.08, arm2=0.65, fl2=0.18):
    if not rem_ticks or len(rem_ticks) < 2:
        return rem_ticks[0][1], rem_ticks[0][0], 'INSUFFICIENT_TICKS'
    ep = rem_ticks[0][1]
    t0_int = rem_ticks[0][2]
    t0_mins = (t0_int // 100) * 60 + (t0_int % 100)
    min_ltp = ep
    breach, s2_b, s3_b = 0, 0, 0
    exit_p = None
    floor1 = round(ep * (1.0 - fl1 / 100.0), 2)
    floor2 = round(ep * (1.0 - fl2 / 100.0), 2)
    lock_050 = round(ep * 0.9950, 2)
    for tm, p, t_int in rem_ticks[1:]:
        cur_mins = (t_int // 100) * 60 + (t_int % 100)
        elapsed = cur_mins - t0_mins
        min_ltp = min(min_ltp, p)
        max_prof_pct = ((ep - min_ltp) / ep) * 100.0
        sl_pct = (1.25 if elapsed >= 45 else 2.25) if t_int < 1100 else (1.25 if t_int < 1230 else 0.90)
        base_sl = round(ep * (1.0 + sl_pct / 100.0), 2)
        if max_prof_pct >= (2.00 if t_int >= 1230 else 2.50):
            c_fl, c_tr = (1.40, 0.75) if t_int >= 1230 else (1.60, 1.00)
            act_sl = min(round(ep * (1.0 - c_fl / 100.0), 2), round(min_ltp * (1.0 + c_tr / 100.0), 2))
            if p >= floor2:
                return floor2, tm, 'FLOOR2_LOCK'
            if p >= act_sl:
                s3_b += 1
                if s3_b >= (3 if t_int < 1230 else 1):
                    return p, tm, 'RUNNER_TRAIL'
            else:
                s3_b = 0
        elif max_prof_pct >= 1.15:
            if p >= floor2:
                return floor2, tm, 'FLOOR2_LOCK'
            if t_int >= 1230 and p >= lock_050:
                s2_b += 1
                if s2_b >= 2:
                    return p, tm, 'LOCK_050'
            else:
                s2_b = 0
        elif max_prof_pct >= arm2:
            if p >= floor2:
                return floor2, tm, 'FLOOR2_LOCK'
        elif max_prof_pct >= arm1:
            if p >= floor1:
                return floor1, tm, 'FLOOR1_LOCK'
        else:
            if p >= base_sl:
                breach += 1
                if breach >= 3:
                    return p, tm, 'SL_BREACH'
            else:
                breach = 0
        if tm >= '14:45:00':
            return p, tm, 'TIME_1445'
    return rem_ticks[-1][1], rem_ticks[-1][0], 'EOD_1445'

def get_option_entry(bars, entry_time):
    for b in bars:
        if b[0] >= entry_time:
            p = b[5] if b[5] > 0 else b[2]
            return b[0], p
    return None, 0.0

def select_strike_with_amrit_stepup(stk, icici, d_str, ep_u, step, lot_size, entry_time, min_prem=5.0, min_lot_cost=8000.0):
    atm_s = round(round(ep_u / step) * step, 2)
    otm_s = round(atm_s - step, 2)
    itm_s = round(atm_s + step, 2)

    avail = opt_strikes_by_day.get((stk, d_str), []) + opt_strikes_by_day.get((icici, d_str), [])
    valid_strikes = sorted(list(set([s for s, cnt in avail if abs(s - ep_u) / ep_u <= 0.08])))

    # 1. Check 1_OTM_PE
    b_otm = get_bars(stk, icici, d_str, otm_s)
    tm_otm, ep_otm = get_option_entry(b_otm, entry_time) if len(b_otm) >= 90 else (None, 0.0)

    # 2. Check ATM_PE
    b_atm = get_bars(stk, icici, d_str, atm_s)
    tm_atm, ep_atm = get_option_entry(b_atm, entry_time) if len(b_atm) >= 90 else (None, 0.0)

    # 3. Check 1_ITM_PE
    b_itm = get_bars(stk, icici, d_str, itm_s)
    tm_itm, ep_itm = get_option_entry(b_itm, entry_time) if len(b_itm) >= 90 else (None, 0.0)

    # Smart Strike Selection
    smart_s, smart_role, smart_bars = otm_s, '1_OTM_PE', b_otm
    if len(b_otm) >= 90 and ep_otm >= min_prem and (ep_otm * lot_size) >= min_lot_cost:
        smart_s, smart_role, smart_bars = otm_s, '1_OTM_PE', b_otm
    elif len(b_atm) >= 90 and ep_atm >= min_prem and (ep_atm * lot_size) >= min_lot_cost:
        smart_s, smart_role, smart_bars = atm_s, 'ATM_PE_STEPUP', b_atm
    elif len(b_itm) >= 90 and ep_itm >= min_prem and (ep_itm * lot_size) >= min_lot_cost:
        smart_s, smart_role, smart_bars = itm_s, '1_ITM_PE_STEPUP', b_itm
    elif len(b_atm) >= 90:
        smart_s, smart_role, smart_bars = atm_s, 'ATM_PE', b_atm
    elif len(b_itm) >= 90:
        smart_s, smart_role, smart_bars = itm_s, '1_ITM_PE', b_itm
    elif valid_strikes:
        # Fallback to closest available liquid strike
        best_cand = min(valid_strikes, key=lambda s: abs(s - ep_u))
        b_c = get_bars(stk, icici, d_str, best_cand)
        smart_s, smart_role, smart_bars = best_cand, 'FALLBACK_PE', b_c

    return {
        'smart_strike': smart_s, 'smart_role': smart_role, 'smart_bars': smart_bars,
        'atm_strike': atm_s, 'atm_bars': b_atm,
        'itm_strike': itm_s, 'itm_bars': b_itm,
        'otm_strike': otm_s, 'otm_bars': b_otm
    }

def sim_amrit_compliant_options(bars, entry_time, u_exit_time, u_exit_reason, lot_size, capital=100000.0, max_lots=15):
    ent_idx = None
    for i, b in enumerate(bars):
        if b[0] >= entry_time:
            ent_idx = i
            break
    if ent_idx is None:
        return None

    rem = [b for b in bars[ent_idx:] if b[0] <= '14:46:00']
    if len(rem) < 3:
        return None

    raw_ep = rem[0][5] if rem[0][5] > 0 else rem[0][2]
    if raw_ep <= 0.05:
        return None

    # Strict ₹0.05 NSE Tick Rounding + Bid/Ask Spread Friction (Buy at Ask)
    ep = round_to_nse_tick(raw_ep + NSE_TICK, direction='ceil')
    lots = calculate_option_lots(capital, ep, lot_size, max_lots=max_lots)
    qty = lots * lot_size
    capital_used = round(qty * ep, 2)
    if qty <= 0:
        return None

    # 1. ExactSync (Exits at exact underlying exit time)
    exact_raw, exact_tm = rem[-1][5], rem[-1][0]
    for b in rem[1:]:
        if b[0] >= u_exit_time:
            exact_raw, exact_tm = b[5], b[0]
            break
    # Exit at Bid (-1 tick friction) with NSE ₹0.05 tick floor
    exact_xp = round_to_nse_tick(exact_raw - NSE_TICK, direction='floor')
    exact_g = round((exact_xp - ep) * qty, 2)
    exact_tax = get_opt_taxes(qty, ep, exact_xp)
    exact_net = round(exact_g - exact_tax, 2)

    # 2. SmartSync / Option Ratchet (Strictly NSE ₹0.05 Tick-Compliant Floors)
    smart_raw, smart_tm, smart_rsn = rem[-1][5], rem[-1][0], 'EOD_1445'
    best_p = ep
    for idx, (tm, ti, o, h, l, c, v) in enumerate(rem[1:], start=1):
        best_p = max(best_p, c, 0.5 * (h + c))
        mg = ((best_p - ep) / ep) * 100.0

        if 'SL_BREACH' in str(u_exit_reason):
            if tm >= u_exit_time:
                smart_raw, smart_tm, smart_rsn = c, tm, 'SYNC_SL_BREACH'
                break

        # Trailing Ratchet: +6.0% -> +2.0% floor, +3.5% -> +1.2% floor
        if mg >= 6.0:
            fl_p = round_to_nse_tick(ep * 1.020, direction='floor')
            if c <= fl_p:
                smart_raw, smart_tm, smart_rsn = fl_p, tm, 'OPT_FLOOR_2.0%'
                break
        elif mg >= 3.5:
            fl_p = round_to_nse_tick(ep * 1.012, direction='floor')
            if c <= fl_p:
                smart_raw, smart_tm, smart_rsn = fl_p, tm, 'OPT_FLOOR_1.2%'
                break

        if tm >= u_exit_time:
            smart_raw, smart_tm, smart_rsn = c, tm, f"SYNC_{u_exit_reason}"
            break

        if tm >= '14:45:00':
            smart_raw, smart_tm, smart_rsn = c, tm, 'TIME_1445'
            break

    smart_xp = round_to_nse_tick(smart_raw - NSE_TICK, direction='floor')
    smart_g = round((smart_xp - ep) * qty, 2)
    smart_tax = get_opt_taxes(qty, ep, smart_xp)
    smart_net = round(smart_g - smart_tax, 2)

    return {
        'ep': ep, 'lots': lots, 'qty': qty, 'capital_used': capital_used,
        'exact_xp': exact_xp, 'exact_tm': exact_tm, 'exact_net': exact_net, 'exact_tax': exact_tax,
        'smart_xp': smart_xp, 'smart_tm': smart_tm, 'smart_rsn': smart_rsn, 'smart_net': smart_net, 'smart_tax': smart_tax,
    }

print("4. Executing simulation across all 3 Setups for 2024-2026...", flush=True)

ledger_rows = []
trade_seq = 1

for d in dates:
    yr = int(d[:4])
    mo = d[:7]
    exp_d = get_expiry_for_date(d)
    cal_days = (pd.to_datetime(exp_d) - pd.to_datetime(d)).days

    picks = picks_by_d[d]['FNO_M0_Base_Direct']

    # Evaluate confirmations and underlying trades for Top 4 picks
    cand_info = []
    for rk_i, p in enumerate(picks[:4], start=1):
        stk = str(p['clean_stock']).strip().upper()
        icici = scrip_by_stk.get(stk, stk)
        t = ticks.get((d, stk), [])
        if len(t) < 10:
            continue
        ep_0942 = t[0][1]
        lot_sz = get_lot_size(stk, d)
        step = get_historical_step(stk, ep_0942)

        # Underlying 09:42 trade
        u_0942_xp, u_0942_xtm, u_0942_rsn = sim_underlying_w80_detail(t)
        u_0942_q = max(1, int(round(500000.0 / ep_0942)))
        u_0942_net = round((ep_0942 - u_0942_xp) * u_0942_q - get_eq_taxes(u_0942_q, ep_0942, u_0942_xp), 2)

        # Underlying Confirmation check
        conf_res = detect_confirmations(t)
        conf_idx, conf_tm, conf_ti, conf_type = (None, None, None, None)
        u_conf_xp, u_conf_xtm, u_conf_rsn, u_conf_net = (None, None, None, None)
        ep_conf = None
        if conf_res is not None:
            conf_idx, conf_tm, conf_ti, conf_type = conf_res
            ep_conf = t[conf_idx][1]
            u_conf_xp, u_conf_xtm, u_conf_rsn = sim_underlying_w80_detail(t[conf_idx:])
            u_conf_q = max(1, int(round(500000.0 / ep_conf)))
            u_conf_net = round((ep_conf - u_conf_xp) * u_conf_q - get_eq_taxes(u_conf_q, ep_conf, u_conf_xp), 2)

        cand_info.append({
            'rank': rk_i, 'stock': stk, 'icici': icici, 'ticks': t,
            'lot_size': lot_sz, 'step': step,
            'ep_0942': ep_0942, 'u_0942_xp': u_0942_xp, 'u_0942_xtm': u_0942_xtm, 'u_0942_rsn': u_0942_rsn, 'u_0942_net': u_0942_net,
            'has_conf': conf_res is not None, 'conf_idx': conf_idx, 'conf_tm': conf_tm, 'conf_ti': conf_ti, 'conf_type': conf_type,
            'ep_conf': ep_conf, 'u_conf_xp': u_conf_xp, 'u_conf_xtm': u_conf_xtm, 'u_conf_rsn': u_conf_rsn, 'u_conf_net': u_conf_net,
        })

    # -------------------------------------------------------------------------
    # Setup 1: Rank #1 & #2 @ 09:42 Immediate
    # -------------------------------------------------------------------------
    for c in cand_info[:2]:
        stk, icici = c['stock'], c['icici']
        ep_u = c['ep_0942']
        u_xtm, u_xrsn = c['u_0942_xtm'], c['u_0942_rsn']
        ent_tm = '09:42:00'

        stk_meta = select_strike_with_amrit_stepup(stk, icici, d, ep_u, c['step'], c['lot_size'], ent_tm)
        sim_res = sim_amrit_compliant_options(stk_meta['smart_bars'], ent_tm, u_xtm, u_xrsn, c['lot_size'])

        ledger_rows.append({
            'Trade_ID': trade_seq,
            'Setup_Mode': 'Setup1_Rank1_Rank2_0942_Immediate',
            'Year': yr, 'Month': mo, 'Date': d,
            'Model_Rank': c['rank'], 'Stock': stk, 'ICICI_Code': icici,
            'Expiry_Date': exp_d, 'Cal_Days_To_Exp': cal_days, 'Is_Expiry_Week': cal_days <= 4,
            'Option_Lot_Size': c['lot_size'], 'Strike_Step': c['step'],
            'MIS_Entry_Time': ent_tm, 'MIS_Entry_Price': ep_u,
            'MIS_Exit_Time': u_xtm, 'MIS_Exit_Price': c['u_0942_xp'], 'MIS_Exit_Reason': u_xrsn,
            'MIS_1L_Net_PnL': c['u_0942_net'],
            'Option_Status': 'COMPLETED' if sim_res is not None else 'MISSING_TICKS',
            'Option_Strike_Role': stk_meta['smart_role'],
            'Option_Strike': stk_meta['smart_strike'],
            'Option_Entry_Time': ent_tm,
            'Option_Entry_Price': sim_res['ep'] if sim_res else np.nan,
            'Option_Lots_1L': sim_res['lots'] if sim_res else np.nan,
            'Option_Qty_1L': sim_res['qty'] if sim_res else np.nan,
            'Option_Capital_Used': sim_res['capital_used'] if sim_res else np.nan,
            'ExactSync_Exit_Time': sim_res['exact_tm'] if sim_res else None,
            'ExactSync_Exit_Price': sim_res['exact_xp'] if sim_res else np.nan,
            'ExactSync_Tax': sim_res['exact_tax'] if sim_res else np.nan,
            'ExactSync_1L_Net_PnL': sim_res['exact_net'] if sim_res else np.nan,
            'SmartSync_Exit_Time': sim_res['smart_tm'] if sim_res else None,
            'SmartSync_Exit_Price': sim_res['smart_xp'] if sim_res else np.nan,
            'SmartSync_Exit_Reason': sim_res['smart_rsn'] if sim_res else None,
            'SmartSync_Tax': sim_res['smart_tax'] if sim_res else np.nan,
            'SmartSync_1L_Net_PnL': sim_res['smart_net'] if sim_res else np.nan,
        })
        trade_seq += 1

    # -------------------------------------------------------------------------
    # Setup 2: Rank #1 & #2 Confirmed Later
    # -------------------------------------------------------------------------
    for c in cand_info[:2]:
        if not c['has_conf']:
            continue
        stk, icici = c['stock'], c['icici']
        ep_u = c['ep_conf']
        u_xtm, u_xrsn = c['u_conf_xtm'], c['u_conf_rsn']
        ent_tm = c['conf_tm']

        stk_meta = select_strike_with_amrit_stepup(stk, icici, d, ep_u, c['step'], c['lot_size'], ent_tm)
        sim_res = sim_amrit_compliant_options(stk_meta['smart_bars'], ent_tm, u_xtm, u_xrsn, c['lot_size'])

        ledger_rows.append({
            'Trade_ID': trade_seq,
            'Setup_Mode': 'Setup2_Rank1_Rank2_Confirmed_Later',
            'Year': yr, 'Month': mo, 'Date': d,
            'Model_Rank': c['rank'], 'Stock': stk, 'ICICI_Code': icici,
            'Expiry_Date': exp_d, 'Cal_Days_To_Exp': cal_days, 'Is_Expiry_Week': cal_days <= 4,
            'Option_Lot_Size': c['lot_size'], 'Strike_Step': c['step'],
            'MIS_Entry_Time': ent_tm, 'MIS_Entry_Price': ep_u,
            'MIS_Exit_Time': u_xtm, 'MIS_Exit_Price': c['u_conf_xp'], 'MIS_Exit_Reason': u_xrsn,
            'MIS_1L_Net_PnL': c['u_conf_net'],
            'Option_Status': 'COMPLETED' if sim_res is not None else 'MISSING_TICKS',
            'Option_Strike_Role': stk_meta['smart_role'],
            'Option_Strike': stk_meta['smart_strike'],
            'Option_Entry_Time': ent_tm,
            'Option_Entry_Price': sim_res['ep'] if sim_res else np.nan,
            'Option_Lots_1L': sim_res['lots'] if sim_res else np.nan,
            'Option_Qty_1L': sim_res['qty'] if sim_res else np.nan,
            'Option_Capital_Used': sim_res['capital_used'] if sim_res else np.nan,
            'ExactSync_Exit_Time': sim_res['exact_tm'] if sim_res else None,
            'ExactSync_Exit_Price': sim_res['exact_xp'] if sim_res else np.nan,
            'ExactSync_Tax': sim_res['exact_tax'] if sim_res else np.nan,
            'ExactSync_1L_Net_PnL': sim_res['exact_net'] if sim_res else np.nan,
            'SmartSync_Exit_Time': sim_res['smart_tm'] if sim_res else None,
            'SmartSync_Exit_Price': sim_res['smart_xp'] if sim_res else np.nan,
            'SmartSync_Exit_Reason': sim_res['smart_rsn'] if sim_res else None,
            'SmartSync_Tax': sim_res['smart_tax'] if sim_res else np.nan,
            'SmartSync_1L_Net_PnL': sim_res['smart_net'] if sim_res else np.nan,
        })
        trade_seq += 1

    # -------------------------------------------------------------------------
    # Setup 3: Confirmed Only (First-2 Confirmed across Top 4 Candidates)
    # -------------------------------------------------------------------------
    conf_pool = [c for c in cand_info if c['has_conf']]
    conf_pool.sort(key=lambda x: (x['conf_ti'], x['rank']))
    for c in conf_pool[:2]:
        stk, icici = c['stock'], c['icici']
        ep_u = c['ep_conf']
        u_xtm, u_xrsn = c['u_conf_xtm'], c['u_conf_rsn']
        ent_tm = c['conf_tm']

        stk_meta = select_strike_with_amrit_stepup(stk, icici, d, ep_u, c['step'], c['lot_size'], ent_tm)
        sim_res = sim_amrit_compliant_options(stk_meta['smart_bars'], ent_tm, u_xtm, u_xrsn, c['lot_size'])

        ledger_rows.append({
            'Trade_ID': trade_seq,
            'Setup_Mode': 'Setup3_Confirmed_Only_First2_Top4',
            'Year': yr, 'Month': mo, 'Date': d,
            'Model_Rank': c['rank'], 'Stock': stk, 'ICICI_Code': icici,
            'Expiry_Date': exp_d, 'Cal_Days_To_Exp': cal_days, 'Is_Expiry_Week': cal_days <= 4,
            'Option_Lot_Size': c['lot_size'], 'Strike_Step': c['step'],
            'MIS_Entry_Time': ent_tm, 'MIS_Entry_Price': ep_u,
            'MIS_Exit_Time': u_xtm, 'MIS_Exit_Price': c['u_conf_xp'], 'MIS_Exit_Reason': u_xrsn,
            'MIS_1L_Net_PnL': c['u_conf_net'],
            'Option_Status': 'COMPLETED' if sim_res is not None else 'MISSING_TICKS',
            'Option_Strike_Role': stk_meta['smart_role'],
            'Option_Strike': stk_meta['smart_strike'],
            'Option_Entry_Time': ent_tm,
            'Option_Entry_Price': sim_res['ep'] if sim_res else np.nan,
            'Option_Lots_1L': sim_res['lots'] if sim_res else np.nan,
            'Option_Qty_1L': sim_res['qty'] if sim_res else np.nan,
            'Option_Capital_Used': sim_res['capital_used'] if sim_res else np.nan,
            'ExactSync_Exit_Time': sim_res['exact_tm'] if sim_res else None,
            'ExactSync_Exit_Price': sim_res['exact_xp'] if sim_res else np.nan,
            'ExactSync_Tax': sim_res['exact_tax'] if sim_res else np.nan,
            'ExactSync_1L_Net_PnL': sim_res['exact_net'] if sim_res else np.nan,
            'SmartSync_Exit_Time': sim_res['smart_tm'] if sim_res else None,
            'SmartSync_Exit_Price': sim_res['smart_xp'] if sim_res else np.nan,
            'SmartSync_Exit_Reason': sim_res['smart_rsn'] if sim_res else None,
            'SmartSync_Tax': sim_res['smart_tax'] if sim_res else np.nan,
            'SmartSync_1L_Net_PnL': sim_res['smart_net'] if sim_res else np.nan,
        })
        trade_seq += 1

df_ledger = pd.DataFrame(ledger_rows)
print(f"5. Saving complete side-by-side ledger ({len(df_ledger):,} rows) to:\n   {OUT_LEDGER_PATH}", flush=True)
df_ledger.to_csv(OUT_LEDGER_PATH, index=False)

print("\n" + "="*140, flush=True)
print("📊 3-YEAR (2024-2026) INSTITUTIONAL QA PERFORMANCE AUDIT: 09:40 HYBRID PUT OPTION SIMULATION", flush=True)
print("   Capital: ₹1.0L / Stock | Max 2 Stocks / Day (₹2.0L Daily Capital) | Soft Lot Cap: 15 Lots | Strict ₹0.05 NSE Ticks", flush=True)
print("="*140, flush=True)

for mode in ['Setup1_Rank1_Rank2_0942_Immediate', 'Setup2_Rank1_Rank2_Confirmed_Later', 'Setup3_Confirmed_Only_First2_Top4']:
    sub = df_ledger[df_ledger['Setup_Mode'] == mode].copy()
    sub_valid = sub[sub['Option_Status'] == 'COMPLETED'].copy()
    sub_nonexp = sub_valid[~sub_valid['Is_Expiry_Week']].copy()

    print(f"\n>>> [{mode}] (Total Trades: {len(sub)} | Completed Option Trades: {len(sub_valid)} | Non-Expiry: {len(sub_nonexp)})")

    for pol, col_pnl in [('ExactSync (Underlying Time)', 'ExactSync_1L_Net_PnL'), ('SmartSync (Option Ratchet)', 'SmartSync_1L_Net_PnL')]:
        net_all = sub_valid[col_pnl].sum() / 1e5
        wr_all = (sub_valid[col_pnl] > 0).mean() * 100.0 if len(sub_valid) else 0.0
        wins = sub_valid[sub_valid[col_pnl] > 0][col_pnl].sum()
        losses = abs(sub_valid[sub_valid[col_pnl] < 0][col_pnl].sum())
        pf = (wins / losses) if losses > 0 else np.nan

        # Daily Drawdown
        daily_pnl = sub_valid.groupby('Date')[col_pnl].sum()
        cum = daily_pnl.cumsum()
        mdd = (cum - cum.cummax()).min() / 1e5

        # Non-Expiry metrics
        net_ne = sub_nonexp[col_pnl].sum() / 1e5
        wr_ne = (sub_nonexp[col_pnl] > 0).mean() * 100.0 if len(sub_nonexp) else 0.0

        # Yearly breakdown
        y_str = []
        for yr in [2024, 2025, 2026]:
            y_df = sub_nonexp[sub_nonexp['Year'] == yr]
            y_net = y_df[col_pnl].sum() / 1e5
            y_wr = (y_df[col_pnl] > 0).mean() * 100.0 if len(y_df) else 0.0
            y_str.append(f"{yr}: +₹{y_net:.2f}L ({y_wr:.1f}% WR, N={len(y_df)})")

        print(f"   • {pol:<28} | Non-Exp Net: +₹{net_ne:6.2f}L | Non-Exp WR: {wr_ne:5.1f}% | PF: {pf:4.2f} | MDD: ₹{mdd:5.2f}L | Total Net: +₹{net_all:6.2f}L")
        print(f"     └─ Non-Expiry Yearly: " + " | ".join(y_str))

print("\n" + "="*140, flush=True)
