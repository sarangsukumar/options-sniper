#!/usr/bin/env python3
"""
reconcile_0920_options_helper.py
--------------------------------
Helper module called by reconcile_0920_scalp_pnl.py to automatically fetch (if missing)
and simulate both:
  1. ExactSync_0920 (Put Option exits at the exact timestamp the underlying 09:20 Cash MIS trade exits)
  2. SmartSync_0920 (Cadence Profit Sync + Ratchet Trail + Strict 09:40 Hard Exit)
with strict NSE ₹0.05 tick rounding, Smart Strike Step-Up (`1_OTM_PE` -> `ATM_PE` / `1_ITM_PE` when
premium < ₹5.00 or 1-lot cost < ₹8,000), and Soft 15-Lot Cap on ₹1,00,000 capital per stock.
"""

import os
import re
import math
import subprocess
from datetime import datetime
import numpy as np
import pandas as pd

NSE_TICK = 0.05
MAX_LOTS_STEPUP = 15
MIN_PREM_RS = 5.0
MIN_LOT_COST_RS = 8000.0
EXPIRY_FILE = '/home/ubuntu/KotakCodes1/expiry_dates.txt'
ICICI_OPT_MASTER = '/home/ubuntu/ICICImaster_options.csv'

_OPT_META_CACHE = None

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

def _load_opt_meta():
    global _OPT_META_CACHE
    if _OPT_META_CACHE is not None:
        return _OPT_META_CACHE
    scrip_by_stk = {}
    lot_by_stk = {}
    step_by_stk = {}
    if os.path.exists(ICICI_OPT_MASTER):
        df_m = pd.read_csv(ICICI_OPT_MASTER)
        df_pe = df_m[(df_m['instrumentname'] == 'OPTSTK') & (df_m['OptionType'] == 'PE')].copy()
        df_pe['stockcodes'] = df_pe['stockcodes'].astype(str).str.strip().str.upper()
        df_pe['scripcode'] = df_pe['scripcode'].astype(str).str.strip().str.upper()
        df_pe['StrikePrice'] = pd.to_numeric(df_pe['StrikePrice'], errors='coerce')
        df_pe['lotsize'] = pd.to_numeric(df_pe['lotsize'], errors='coerce')
        for stk, grp in df_pe.groupby('stockcodes'):
            scrip_by_stk[stk] = str(grp['scripcode'].iloc[0])
            lot_by_stk[stk] = int(grp['lotsize'].dropna().iloc[0]) if grp['lotsize'].notna().any() else 1
            stks = np.sort(grp['StrikePrice'].dropna().unique())
            if len(stks) >= 3:
                diffs = np.round(np.diff(stks), 4)
                vals, cnts = np.unique(diffs, return_counts=True)
                dom = float(vals[np.argmax(cnts)])
                step_by_stk[stk] = float(np.min(vals)) if (dom == 10.0 and 5.0 in vals and np.mean(stks) < 800) else dom
    _OPT_META_CACHE = (scrip_by_stk, lot_by_stk, step_by_stk)
    return _OPT_META_CACHE

def get_upcoming_expiry_info(d_str: str):
    exp_dates = []
    if os.path.exists(EXPIRY_FILE):
        with open(EXPIRY_FILE, 'r', encoding='utf-8') as f:
            txt = f.read()
        m = re.search(r'"([^"]+)"', txt)
        if m:
            exp_dates = sorted([x.strip() for x in m.group(1).split(',') if x.strip()])
    fut = [e for e in exp_dates if e >= d_str]
    exp_iso = fut[0] if fut else d_str
    cal_days = (pd.to_datetime(exp_iso) - pd.to_datetime(d_str)).days
    return exp_iso, int(cal_days)

def calc_default_step(spot: float) -> float:
    if spot < 50: return 1.0
    if spot <= 250: return 2.5
    if spot <= 1000: return 5.0
    if spot <= 3000: return 10.0
    if spot <= 6000: return 50.0
    return 100.0

def fetch_day_option_bars_from_breeze_if_needed(cursor, conn, stock: str, icici_code: str, d_str: str, exp_iso: str, strikes: list):
    """Downloads 1-minute Put Option bars from Breeze if not already present in scrapdata_options."""
    missing_strikes = []
    for st in strikes:
        cursor.execute(
            """
            SELECT COUNT(*) as cnt FROM scrapdata_options
            WHERE (stock_code=%s OR stock_code=%s)
              AND DATE(datetime)=%s
              AND ABS(strike_price - %s) < 0.01
              AND `right` IN ('Put','PE','P')
            """,
            (stock, icici_code, d_str, float(st))
        )
        row = cursor.fetchone()
        cnt = int(row['cnt'] if isinstance(row, dict) else row[0])
        if cnt < 10:
            missing_strikes.append(st)

    if not missing_strikes:
        return

    js_code = f"""
const BreezeConnect = require('breezeconnect').BreezeConnect;
const fs = require('fs');
const mysql = require('mysql2/promise');
const appKey = "S945YmT9K3Z4425450K+C205BMZ9$085";
const sessionFile = "/home/ubuntu/KotakCodes1/ICICI/icici_session_token/icicisession_bineesh.txt";
const breeze = new BreezeConnect({{ appKey }});
async function run() {{
    const token = fs.readFileSync(sessionFile, 'utf8').trim();
    await breeze.generateSession("6P9^377d3*412585q(527i3ZgJ437040", token);
    const db = await mysql.createConnection({{ host: 'localhost', user: 'root', password: 'root', database: 'markets' }});
    const strikes = {missing_strikes};
    for (const st of strikes) {{
        let res = await breeze.getHistoricalDatav2({{
            interval: "1minute",
            fromDate: "{d_str}T09:15:00.000Z",
            toDate: "{d_str}T15:30:00.000Z",
            stockCode: "{icici_code}",
            exchangeCode: "NFO",
            productType: "options",
            expiryDate: "{exp_iso}T06:00:00.000Z",
            right: "Put",
            strikePrice: st.toString()
        }});
        if (res && res.Success && res.Success.length > 0) {{
            let vals = res.Success.map(r => [
                r.datetime, "{stock}", parseFloat(st), 'Put',
                parseFloat(r.open || 0), parseFloat(r.high || 0),
                parseFloat(r.low || 0), parseFloat(r.close || 0),
                parseInt(r.volume || 0), parseInt(r.open_interest || 0), 'F1'
            ]);
            await db.query("INSERT IGNORE INTO scrapdata_options (datetime,stock_code,strike_price,`right`,open,high,low,close,volume,open_interest,month_type) VALUES ?", [vals]);
        }}
    }}
    await db.end();
}}
run().catch(() => process.exit(0));
"""
    env = os.environ.copy()
    env['NODE_PATH'] = '/home/ubuntu/KotakCodes1/node_modules:/home/ubuntu/node_modules'
    try:
        subprocess.run(['node', '-e', js_code], env=env, timeout=25, capture_output=True)
        conn.commit()
    except Exception:
        pass

def get_opt_bars_from_db(cursor, stock: str, icici_code: str, d_str: str, strike: float) -> list:
    cursor.execute(
        """
        SELECT TIME_FORMAT(datetime, '%%H:%%i:%%s') as tm, open, high, low, close, volume
        FROM scrapdata_options
        WHERE (stock_code=%s OR stock_code=%s)
          AND DATE(datetime)=%s
          AND ABS(strike_price - %s) < 0.01
          AND `right` IN ('Put','PE','P')
        ORDER BY datetime ASC
        """,
        (stock, icici_code, d_str, float(strike))
    )
    rows = cursor.fetchall()
    bars = []
    seen = set()
    for r in rows:
        tm = str(r['tm'] if isinstance(r, dict) else r[0]).split()[-1]
        if tm in seen or tm < '09:15:00' or tm > '15:15:00':
            continue
        seen.add(tm)
        o = float((r['open'] if isinstance(r, dict) else r[1]) or 0)
        h = float((r['high'] if isinstance(r, dict) else r[2]) or 0)
        l = float((r['low'] if isinstance(r, dict) else r[3]) or 0)
        c = float((r['close'] if isinstance(r, dict) else r[4]) or 0)
        v = int((r['volume'] if isinstance(r, dict) else r[5]) or 0)
        p = c if c > 0 else o
        if p <= 0:
            continue
        bars.append((tm, o if o > 0 else p, h if h > 0 else p, l if l > 0 else p, p, v))
    return bars

def simulate_0920_option_for_trade(cursor, conn, stock: str, d_str: str, u_entry_price: float, u_entry_time: str, u_exit_time: str, u_exit_reason: str):
    """
    Runs both ExactSync_0920 and SmartSync_0920 for a single 09:20 trade on ₹1,00,000 capital.
    """
    scrip_by_stk, lot_by_stk, step_by_stk = _load_opt_meta()
    stk = stock.strip().upper()
    icici_code = scrip_by_stk.get(stk, stk)
    opt_lot_size = lot_by_stk.get(stk, max(1, int(round(550000.0 / max(1.0, u_entry_price)))))
    step = step_by_stk.get(stk, calc_default_step(u_entry_price))

    exp_iso, cal_days = get_upcoming_expiry_info(d_str)
    if cal_days <= 4:
        return {'opt_status': f'SKIPPED_EXPIRY_{cal_days}D'}

    atm_strike = round(round(u_entry_price / step) * step, 2)
    otm_strike = round(atm_strike - step, 2)
    itm_strike = round(atm_strike + step, 2)
    candidate_strikes = [
        ('1_OTM_PE', otm_strike),
        ('ATM_PE_STEPUP', atm_strike),
        ('1_ITM_PE_STEPUP', itm_strike),
    ]

    fetch_day_option_bars_from_breeze_if_needed(
        cursor, conn, stk, icici_code, d_str, exp_iso, [s for _, s in candidate_strikes]
    )

    chosen = None
    fallback = None
    sell_tm = str(u_entry_time).split()[-1] if u_entry_time else '09:25:00'

    for role, st in candidate_strikes:
        bars = get_opt_bars_from_db(cursor, stk, icici_code, d_str, st)
        if not bars:
            continue
        rem = [b for b in bars if b[0] >= sell_tm and b[0] <= '09:41:00']
        if len(rem) < 2:
            continue
        # If the first bar in rem is at 09:26:00 and there is a valid 09:24:00 bar right before 09:25:00,
        # use the 09:24:00 close as the 09:25:00 entry price if 09:25:00 had no print, or use rem[0]
        pre_bars = [b for b in bars if '09:23:00' <= b[0] < sell_tm]
        if rem[0][0] > '09:25:00' and pre_bars:
            ep_raw = pre_bars[-1][4]
            rem = [('09:25:00', ep_raw, ep_raw, ep_raw, ep_raw, 0)] + rem
        else:
            ep_raw = rem[0][4]
        if ep_raw <= 0.05:
            continue
        ep = round_to_nse_tick(ep_raw, direction='ceil')
        if fallback is None:
            fallback = (role, st, ep, rem)
        # Prefer strike that actually printed at 09:25:00 OR passes the step-up filter
        has_exact_0925 = any(b[0] == '09:25:00' and b[5] > 0 for b in rem)
        if ep >= MIN_PREM_RS and (ep * opt_lot_size) >= MIN_LOT_COST_RS and has_exact_0925:
            chosen = (role, st, ep, rem)
            break
        elif ep >= MIN_PREM_RS and (ep * opt_lot_size) >= MIN_LOT_COST_RS and chosen is None:
            chosen = (role, st, ep, rem)

    if chosen is None:
        chosen = fallback
    if chosen is None:
        return {'opt_status': 'MISSING_OPT_BARS'}

    role, strike, ep, rem = chosen
    u_ex_tm = str(u_exit_time).split()[-1] if u_exit_time else '09:40:00'

    # 1. ExactSync_0920 (Exit at exact underlying exit timestamp; if exact minute has no print, use most recent print <= u_ex_tm)
    exact_raw, exact_tm = rem[-1][4], rem[-1][0]
    le_bars = [b for b in rem[1:] if b[0] <= u_ex_tm]
    ge_bars = [b for b in rem[1:] if b[0] >= u_ex_tm]
    if ge_bars and ge_bars[0][0] == u_ex_tm:
        exact_raw, exact_tm = ge_bars[0][4], ge_bars[0][0]
    elif le_bars:
        exact_raw, exact_tm = le_bars[-1][4], le_bars[-1][0]
    elif ge_bars:
        exact_raw, exact_tm = ge_bars[0][4], ge_bars[0][0]
    exact_px = round_to_nse_tick(exact_raw, direction='floor')

    # 2. SmartSync_0920 (Cadence Profit Sync + Ratchet Trail + Strict 09:40 Hard Exit)
    smart_raw, smart_tm, smart_rsn = rem[-1][4], rem[-1][0], 'HARD_EXIT_0940'
    best_c = ep
    u_prof_trig = False
    for idx, (tm, o, h, l, c, v) in enumerate(rem):
        if idx == 0:
            best_c = max(best_c, c)
            continue
        if tm >= u_ex_tm:
            if 'HARD_EXIT' in str(u_exit_reason) or 'TIME_EXIT' in str(u_exit_reason) or 'SL' in str(u_exit_reason):
                smart_raw, smart_tm, smart_rsn = c, tm, str(u_exit_reason)
                break
            else:
                u_prof_trig = True
        if u_prof_trig and ((c - ep) / ep * 100.0) >= 0.60:
            smart_raw, smart_tm, smart_rsn = c, tm, f"SYNC_{u_exit_reason}"
            break
        best_ret = ((best_c - ep) / ep) * 100.0
        if best_ret >= 4.5:
            stop_p = round_to_nse_tick(best_c * (1.0 - 0.012), direction='floor')
            if l <= stop_p:
                smart_raw, smart_tm, smart_rsn = min(o, stop_p), tm, 'OPT_TRAIL_LOCK'
                break
        elif best_ret >= 1.8:
            stop_p = round_to_nse_tick(ep * 1.008, direction='floor')
            if l <= stop_p:
                smart_raw, smart_tm, smart_rsn = min(o, stop_p), tm, 'OPT_FLOOR_LOCK'
                break
        best_c = max(best_c, c)
        if '09:36:00' <= tm < '09:40:00' and ((c - ep) / ep * 100.0) >= 0.60:
            smart_raw, smart_tm, smart_rsn = c, tm, 'OPT_CADENCE_0936'
            break
        if tm >= '09:40:00':
            smart_raw, smart_tm, smart_rsn = c, tm, 'HARD_EXIT_0940'
            break
    smart_px = round_to_nse_tick(smart_raw, direction='floor')

    raw_lots = max(1, int(round(100000.0 / (opt_lot_size * ep))))
    lots = min(raw_lots, MAX_LOTS_STEPUP)
    qty = lots * opt_lot_size
    cap_used = round(qty * ep, 2)

    g_ex = round((exact_px - ep) * qty, 2)
    c_ex = get_opt_taxes(qty, ep, exact_px)
    n_ex = round(g_ex - c_ex, 2)
    ret_ex = round((exact_px - ep) / ep * 100.0, 2)

    g_sm = round((smart_px - ep) * qty, 2)
    c_sm = get_opt_taxes(qty, ep, smart_px)
    n_sm = round(g_sm - c_sm, 2)
    ret_sm = round((smart_px - ep) / ep * 100.0, 2)

    return {
        'opt_status': 'COMPLETED',
        'opt_expiry': exp_iso,
        'opt_cal_days': cal_days,
        'opt_role': role,
        'opt_strike': strike,
        'opt_lot_size': opt_lot_size,
        'opt_lots': lots,
        'opt_qty': qty,
        'opt_capital_used': cap_used,
        'opt_entry_time': rem[0][0],
        'opt_entry_price': ep,
        'opt_exactsync_exit_time': exact_tm,
        'opt_exactsync_exit_price': exact_px,
        'opt_exactsync_gross_pnl': g_ex,
        'opt_exactsync_charges': c_ex,
        'opt_exactsync_net_pnl': n_ex,
        'opt_exactsync_ret_pct': ret_ex,
        'opt_smartsync_exit_time': smart_tm,
        'opt_smartsync_exit_price': smart_px,
        'opt_smartsync_exit_reason': smart_rsn,
        'opt_smartsync_gross_pnl': g_sm,
        'opt_smartsync_charges': c_sm,
        'opt_smartsync_net_pnl': n_sm,
        'opt_smartsync_ret_pct': ret_sm,
    }
