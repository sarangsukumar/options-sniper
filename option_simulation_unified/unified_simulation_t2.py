#!/usr/bin/env python3
"""
========================================================================================
🚀 UNIFIED OPTION SIMULATION ENGINE - T+2 HOLDING STRATEGY
========================================================================================
- Entry on Day T afternoon window (15:20 to 15:30)
- Live Profit Scanner across Day T+1 AND Day T+2 (09:16:00 to 15:00:00)
  * Day T+1: If net spread profit > 0 at any 1-minute tick, exit immediately!
  * If no positive exit on Day T+1, hold overnight into Day T+2.
  * Day T+2: If net spread profit > 0 at any 1-minute tick, exit immediately!
- Day T+2 Hard Square-Off: 15:00 exact (or fallback hierarchy 15:00 -> 15:01-15:30 -> 14:59-10:00)
- Capital & Margin: ₹4,00,000 / ₹2,00,000 daily budget shared across trades, max 20 lots.
- Friction: ₹0.20 slippage/leg (₹0.40/spread) + ₹300/lot round-trip charges.
========================================================================================
"""

import os
import sys
import argparse
import pandas as pd
import numpy as np
import mysql.connector

class UnifiedT2SimulationEngine:
    def __init__(self, data_dir=None, db_config=None, capital_per_day=400000.0,
                 max_lots=20, atm_threshold=5.0, dte_min=5, credit_ratio_thresh=0.0):
        self.data_dir = data_dir or os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
        self.db_config = db_config or {
            'host': 'localhost',
            'user': 'root',
            'password': 'root',
            'database': 'markets'
        }
        self.capital_per_day = capital_per_day
        self.max_lots = max_lots
        self.atm_threshold = atm_threshold
        self.dte_min = dte_min
        self.credit_ratio_thresh = credit_ratio_thresh

        self.slippage_per_leg = 0.20
        self.roundtrip_slippage_per_share = 0.40
        self.taxes_and_charges_per_lot = 300.0

        self.ICICI_SCRIP_MAP = {
            'CANBK': 'CANBAN', 'PFC': 'POWFIN', 'HAL': 'HINAER', 'NATIONALUM': 'NATALU',
            'HEROMOTOCO': 'HERHON', 'IDEA': 'IDECEL', 'IEX': 'INDEN', 'MPHASIS': 'MPHLIM',
            'INDUSTOWER': 'BHAINF', 'ABCAPITAL': 'ADICAP', 'RECLTD': 'RURELE', 'HINDCOPPER': 'HINCOP',
            'IGL': 'INDGAS', 'MGL': 'MAHGAS', 'BALKRISIND': 'BALIND', 'CHAMBLFERT': 'CHAFER',
            'ZEEL': 'ZEEENT', 'GMRINFRA': 'GMRINF', 'DELTACORP': 'DELCOR', 'ABBOTINDIA': 'ABBIND',
            'TATACHEM': 'TATCHE', 'IRCTC': 'INDRAI', 'LALPATHLAB': 'DRLALP', 'LTTS': 'LTTS',
            'OBEROIRLTY': 'OBEROI', 'ESCORTS': 'ESCORT', 'INDIAMART': 'INDMAR', 'SUNTV': 'SUNTV',
            'DEEPAKNTR': 'DEENIT', 'ALKEM': 'ALKLAB', 'NAVINFLUOR': 'NAVINT', 'ZYDUSLIFE': 'CADHEA',
            'OFSS': 'ORAFIN', 'GLENMARK': 'GLEPHA', 'DIXON': 'DIXTEC', 'MCX': 'MCX',
            'AUROPHARMA': 'AURPHA', 'TATAPOWER': 'TATPOW', 'BEL': 'BHAELE', 'TRENT': 'TRENO',
            'CUMMINSIND': 'CUMIND', 'DRREDDY': 'DRREDD', 'JUBLFOOD': 'JUBFOO', 'SIEMENS': 'SIEMEN',
            'MFSL': 'MAXFIN', 'BHEL': 'BHELE', 'ABB': 'ABB', 'CUB': 'CITUNI', 'SYNGENE': 'SYNINT',
            'TATASTEEL': 'TATSTE', 'JKCEMENT': 'JKCEME', 'ASHOKLEY': 'ASHLEY', 'ASTRAL': 'ASTPOL',
            'PERSISTENT': 'PERMIN', 'AUBANK': 'AUDBAN', 'ICICIPRULI': 'ICIPRU', 'MUTHOOTFIN': 'MUTHFI',
            'M&MFIN': 'MMFIN', 'BALRAMCHIN': 'BALCHI', 'AARTIIND': 'AARIND', 'SHREECEM': 'SHRCEM',
            'HINDPETRO': 'HINPET'
        }

        self._load_reference_data()

    def _load_reference_data(self):
        # 1. Master Setups
        best_model_path = os.path.join(self.data_dir, 'sarang_best_model_selections.csv')
        self.df_pred = pd.read_csv(best_model_path)
        self.df_pred['Date'] = pd.to_datetime(self.df_pred['date'], format='%d-%m-%Y').dt.strftime('%Y-%m-%d')
        self.df_pred['Stock'] = self.df_pred['stockname'].str.strip()

        # 2. NSE Business Dates
        b_df_path = os.path.join(self.data_dir, 'nse_business_dates.csv')
        b_df = pd.read_csv(b_df_path)
        self.b_dates = sorted(pd.to_datetime(b_df['date'], format='%d-%m-%Y'))

        # 3. Master Monthly Expiry Dates
        master_exp_path = os.path.join(self.data_dir, 'master_expiry_dates.csv')
        master_exp = pd.read_csv(master_exp_path)
        self.exp_list = sorted(pd.to_datetime(master_exp['master_expiry_date']).tolist())

        # 4. Spot Reference Prices
        spot_df_path = os.path.join(self.data_dir, 'master_reference_spot_prices.csv')
        spot_df = pd.read_csv(spot_df_path)
        spot_df['Stock'] = spot_df['Stock'].str.strip()
        self.spot_map = dict(zip(zip(spot_df['Stock'], spot_df['Date']), spot_df['Spot_Price']))

        # 5. True Stepsizes
        step_df_path = os.path.join(self.data_dir, 'true_historical_stepsize.csv')
        step_df = pd.read_csv(step_df_path)
        step_df['stockname'] = step_df['stockname'].str.strip()
        step_df['expyear'] = step_df['expyear'].astype(str)
        self.step_dict = {f"{r['stockname']}_{r['expmonth']}_{r['expyear']}": r['step_size'] for _, r in step_df.iterrows()}

        # 6. Lot Sizes
        lot_df_path = os.path.join(self.data_dir, 'historical_lotsizes.csv')
        self.lot_df = pd.read_csv(lot_df_path)
        self.lot_df['stockname'] = self.lot_df['stockname'].str.strip()
        self.lot_df['expyear'] = self.lot_df['expyear'].astype(str)
        self.lot_dict = {f"{r['stockname']}_{r['expmonth']}_{r['expyear']}": r['lotsize'] for _, r in self.lot_df.iterrows()}

    def get_t1_exit_date(self, entry_date_str):
        entry_dt = pd.to_datetime(entry_date_str)
        next_days = [d for d in self.b_dates if d > entry_dt]
        return next_days[0].strftime('%Y-%m-%d') if next_days else entry_date_str

    def get_t2_exit_date(self, entry_date_str, expiry_dt):
        entry_dt = pd.to_datetime(entry_date_str)
        next_days = [d for d in self.b_dates if d > entry_dt]
        if len(next_days) >= 2:
            t2_dt = next_days[1]
            if t2_dt > expiry_dt:
                return expiry_dt.strftime('%Y-%m-%d')
            return t2_dt.strftime('%Y-%m-%d')
        elif len(next_days) == 1:
            return next_days[0].strftime('%Y-%m-%d')
        return entry_date_str

    def get_nearest_monthly_expiry(self, entry_dt_str):
        entry_dt = pd.to_datetime(entry_dt_str)
        for exp in self.exp_list:
            if exp >= entry_dt:
                return exp
        return self.exp_list[-1]

    def get_step_size(self, stk, dt_str, pr):
        d = pd.to_datetime(dt_str)
        k = f"{stk}_{d.strftime('%b').upper()}_{str(d.year)[-2:]}"
        if k in self.step_dict and pd.notna(self.step_dict[k]): 
            return float(self.step_dict[k])
        if pr > 2500: return 50.0
        if pr > 1000: return 20.0
        if pr > 500: return 10.0
        if pr > 100: return 5.0
        if pr > 50: return 2.5
        return 1.0

    def get_lot_size(self, stk, dt_str):
        d = pd.to_datetime(dt_str)
        k = f"{stk}_{d.strftime('%b').upper()}_{str(d.year)[-2:]}"
        if k in self.lot_dict: 
            return int(self.lot_dict[k])
        m_stk = self.lot_df[self.lot_df['stockname'] == stk]
        if not m_stk.empty: 
            return int(m_stk.iloc[-1]['lotsize'])
        return 500

    def fetch_day_data(self, cursor, stk, icici, date_str, strike):
        strike_f = float(strike)
        cursor.execute("""
            SELECT datetime, open, high, low, close, volume 
            FROM scrapdata_options 
            WHERE (stock_code=%s OR stock_code=%s) AND strike_price=%s AND scrapdata_options.right IN ('Put', 'P', 'PE')
              AND datetime >= %s AND datetime <= %s
            ORDER BY datetime ASC
        """, (stk, icici, strike_f, f"{date_str} 09:15:00", f"{date_str} 15:30:00"))
        rows = cursor.fetchall()
        
        if not rows:
            return None, None, {}
        
        ticks = {r[0].strftime('%H:%M:00'): {'open': float(r[1]) if r[1] is not None else float(r[4]),
                                             'high': float(r[2]) if r[2] is not None else float(r[4]),
                                             'low': float(r[3]) if r[3] is not None else float(r[4]),
                                             'close': float(r[4])} for r in rows}
        
        entry_price = None
        entry_time = None
        for t_str in sorted(ticks.keys()):
            if '15:20:00' <= t_str <= '15:30:00':
                entry_price = ticks[t_str]['open']
                entry_time = f"{date_str} {t_str}"
                break
        
        if entry_price is None and ticks:
            last_t = sorted(ticks.keys())[-1]
            entry_price = ticks[last_t]['close']
            entry_time = f"{date_str} {last_t}"
            
        return entry_price, entry_time, ticks

    def run_simulation(self):
        print(f"\n" + "=" * 80)
        print(f"🚀 INITIALIZING UNIFIED T+2 SIMULATION ENGINE")
        print(f"   - Capital Budget / Day: ₹{self.capital_per_day:,.2f}")
        print(f"   - Max Lots Cap:         {self.max_lots if self.max_lots else 'Unlimited'}")
        print(f"   - ATM Threshold:        >= {self.atm_threshold}")
        print(f"   - Min DTE:              >= {self.dte_min}")
        print(f"   - Holding Period:       Up to T+2 (Intraday Live Scanner on T+1 & T+2)")
        print(f"=" * 80 + "\n", flush=True)

        db = mysql.connector.connect(**self.db_config)
        cursor = db.cursor()

        print(f"Phase 1: Screening {len(self.df_pred)} predictions against DTE & ATM price filters...", flush=True)
        candidate_setups = []

        for idx, row in self.df_pred.iterrows():
            stk = row['Stock']
            icici = self.ICICI_SCRIP_MAP.get(stk, row.get('ICICI_Code', stk))
            b_date = row['Date']
            
            exp_obj = self.get_nearest_monthly_expiry(b_date)
            dte = (exp_obj - pd.to_datetime(b_date)).days
            if dte < self.dte_min:
                continue
                
            t1_exit_date = self.get_t1_exit_date(b_date)
            t2_exit_date = self.get_t2_exit_date(b_date, exp_obj)

            ref_price = self.spot_map.get((stk, b_date))
            if ref_price is None or pd.isna(ref_price):
                continue
                
            ref_price = float(ref_price)
            step = self.get_step_size(stk, b_date, ref_price)
            atm_strike = round(ref_price / step) * step
            otm3_strike = atm_strike - (3 * step)
            
            # Entry Day T
            raw_atm_open, atm_entry_time, _ = self.fetch_day_data(cursor, stk, icici, b_date, atm_strike)
            raw_otm3_open, otm3_entry_time, _ = self.fetch_day_data(cursor, stk, icici, b_date, otm3_strike)
            
            if raw_atm_open is None or raw_otm3_open is None:
                continue
                
            spread_width = atm_strike - otm3_strike
            net_credit = raw_atm_open - raw_otm3_open
            credit_ratio = net_credit / spread_width if spread_width > 0 else 0
            
            if credit_ratio < self.credit_ratio_thresh or raw_atm_open < self.atm_threshold:
                continue
                
            # Exit Day T+1 ticks
            _, _, atm_t1_ticks = self.fetch_day_data(cursor, stk, icici, t1_exit_date, atm_strike)
            _, _, otm3_t1_ticks = self.fetch_day_data(cursor, stk, icici, t1_exit_date, otm3_strike)
            
            # Exit Day T+2 ticks
            _, _, atm_t2_ticks = self.fetch_day_data(cursor, stk, icici, t2_exit_date, atm_strike) if t2_exit_date != t1_exit_date else (None, None, {})
            _, _, otm3_t2_ticks = self.fetch_day_data(cursor, stk, icici, t2_exit_date, otm3_strike) if t2_exit_date != t1_exit_date else (None, None, {})
            
            candidate_setups.append({
                'Stock': stk, 'ICICI_Code': icici, 'Entry_Date': b_date,
                'T1_Date': t1_exit_date, 'T2_Date': t2_exit_date,
                'Expiry': exp_obj.strftime('%Y-%m-%d'), 'DTE': dte, 'Spot_Ref_Price': ref_price,
                'Step_Size': step, 'ATM_Strike': atm_strike, 'OTM3_Strike': otm3_strike,
                'Spread_Width': spread_width, 'Entry_Time': atm_entry_time,
                'ATM_Entry_Price': raw_atm_open, 'OTM3_Entry_Price': raw_otm3_open,
                'Net_Credit_Pt': net_credit, 'Credit_Ratio': credit_ratio,
                'atm_t1_ticks': atm_t1_ticks, 'otm3_t1_ticks': otm3_t1_ticks,
                'atm_t2_ticks': atm_t2_ticks, 'otm3_t2_ticks': otm3_t2_ticks
            })

        df_candidates = pd.DataFrame(candidate_setups)
        daily_counts = df_candidates.groupby('Entry_Date').size().to_dict()

        print(f"Phase 2: Simulating {len(df_candidates)} candidate trades with multi-trade daily capital sharing under T+2 hold rules...", flush=True)

        executed_trades = []

        for c in candidate_setups:
            b_date = c['Entry_Date']
            n_trades_today = daily_counts[b_date]
            allocated_capital = self.capital_per_day / n_trades_today
            
            lot_size = self.get_lot_size(c['Stock'], b_date)
            margin_per_lot = c['Spread_Width'] * lot_size
            
            calc_lots = max(1, round(allocated_capital / margin_per_lot))
            lots = min(calc_lots, self.max_lots) if self.max_lots is not None else calc_lots
            total_qty = lots * lot_size
            total_margin_utilized = margin_per_lot * lots
            
            raw_atm_open = c['ATM_Entry_Price']
            raw_otm3_open = c['OTM3_Entry_Price']
            
            exited = False
            exit_info = None
            
            # -------------------------------------------------------------
            # STEP A: Scan Day T+1 for net positive profit (09:16:00 to 15:00:00)
            # -------------------------------------------------------------
            atm_t1 = c['atm_t1_ticks']
            otm3_t1 = c['otm3_t1_ticks']
            t1_common = sorted(list(set(atm_t1.keys()).intersection(set(otm3_t1.keys()))))
            t1_scan_mins = [m for m in t1_common if '09:16:00' <= m <= '15:00:00']
            
            for m in t1_scan_mins:
                atm_exit = atm_t1[m]['close']
                otm3_exit = otm3_t1[m]['close']
                gross_pt = (raw_atm_open - atm_exit) + (otm3_exit - raw_otm3_open)
                gross_pnl = gross_pt * total_qty
                slip = total_qty * self.roundtrip_slippage_per_share
                chg = lots * self.taxes_and_charges_per_lot
                net = gross_pnl - slip - chg
                
                if net > 0:
                    exited = True
                    exit_info = {
                        'Exit_Date': c['T1_Date'],
                        'Exit_Time': f"{c['T1_Date']} {m}",
                        'Exit_Reason': 'T+1 Live Positive Profit Exit',
                        'Hold_Days': 'T+1',
                        'ATM_Exit_Price': atm_exit,
                        'OTM3_Exit_Price': otm3_exit,
                        'Gross_Pt': gross_pt
                    }
                    break

            # -------------------------------------------------------------
            # STEP B: If not exited on T+1, hold overnight into Day T+2
            # -------------------------------------------------------------
            if not exited and c['T2_Date'] != c['T1_Date']:
                atm_t2 = c['atm_t2_ticks']
                otm3_t2 = c['otm3_t2_ticks']
                t2_common = sorted(list(set(atm_t2.keys()).intersection(set(otm3_t2.keys()))))
                t2_scan_mins = [m for m in t2_common if '09:16:00' <= m <= '15:00:00']
                
                for m in t2_scan_mins:
                    atm_exit = atm_t2[m]['close']
                    otm3_exit = otm3_t2[m]['close']
                    gross_pt = (raw_atm_open - atm_exit) + (otm3_exit - raw_otm3_open)
                    gross_pnl = gross_pt * total_qty
                    slip = total_qty * self.roundtrip_slippage_per_share
                    chg = lots * self.taxes_and_charges_per_lot
                    net = gross_pnl - slip - chg
                    
                    if net > 0:
                        exited = True
                        exit_info = {
                            'Exit_Date': c['T2_Date'],
                            'Exit_Time': f"{c['T2_Date']} {m}",
                            'Exit_Reason': 'T+2 Live Positive Profit Exit',
                            'Hold_Days': 'T+2',
                            'ATM_Exit_Price': atm_exit,
                            'OTM3_Exit_Price': otm3_exit,
                            'Gross_Pt': gross_pt
                        }
                        break
                        
                # -------------------------------------------------------------
                # STEP C: Day T+2 Hard Square-Off Hierarchy (15:00 exact -> fallback)
                # -------------------------------------------------------------
                if not exited and t2_common:
                    exit_min = None
                    if '15:00:00' in t2_common:
                        exit_min = '15:00:00'
                    else:
                        post_1500 = [m for m in t2_common if m > '15:00:00']
                        if post_1500:
                            exit_min = min(post_1500)
                        else:
                            pre_1500 = [m for m in t2_common if m < '15:00:00']
                            if pre_1500:
                                exit_min = max(pre_1500)
                                
                    if exit_min is not None:
                        atm_exit = atm_t2[exit_min]['close']
                        otm3_exit = otm3_t2[exit_min]['close']
                        gross_pt = (raw_atm_open - atm_exit) + (otm3_exit - raw_otm3_open)
                        exited = True
                        exit_info = {
                            'Exit_Date': c['T2_Date'],
                            'Exit_Time': f"{c['T2_Date']} {exit_min}",
                            'Exit_Reason': 'T+2 Hard Square-Off (15:00)',
                            'Hold_Days': 'T+2',
                            'ATM_Exit_Price': atm_exit,
                            'OTM3_Exit_Price': otm3_exit,
                            'Gross_Pt': gross_pt
                        }

            # -------------------------------------------------------------
            # STEP D: Fallback if T+2 data missing, square off on T+1 Hard Square-Off
            # -------------------------------------------------------------
            if not exited and t1_common:
                exit_min = None
                if '15:00:00' in t1_common:
                    exit_min = '15:00:00'
                else:
                    post_1500 = [m for m in t1_common if m > '15:00:00']
                    if post_1500:
                        exit_min = min(post_1500)
                    else:
                        pre_1500 = [m for m in t1_common if m < '15:00:00']
                        if pre_1500:
                            exit_min = max(pre_1500)
                            
                if exit_min is not None:
                    atm_exit = atm_t1[exit_min]['close']
                    otm3_exit = otm3_t1[exit_min]['close']
                    gross_pt = (raw_atm_open - atm_exit) + (otm3_exit - raw_otm3_open)
                    exited = True
                    exit_info = {
                        'Exit_Date': c['T1_Date'],
                        'Exit_Time': f"{c['T1_Date']} {exit_min}",
                        'Exit_Reason': 'T+1 Fallback Square-Off',
                        'Hold_Days': 'T+1',
                        'ATM_Exit_Price': atm_exit,
                        'OTM3_Exit_Price': otm3_exit,
                        'Gross_Pt': gross_pt
                    }

            if not exited:
                continue

            # Calculate Exact PnL & Friction
            gross_pnl = exit_info['Gross_Pt'] * total_qty
            total_slippage = total_qty * self.roundtrip_slippage_per_share
            total_charges = lots * self.taxes_and_charges_per_lot
            net_pnl = gross_pnl - total_slippage - total_charges
            roi_pct = (net_pnl / total_margin_utilized) * 100 if total_margin_utilized > 0 else 0

            executed_trades.append({
                'Stock': c['Stock'],
                'Entry_Date': b_date,
                'Entry_Time': c['Entry_Time'],
                'Exit_Date': exit_info['Exit_Date'],
                'Exit_Time': exit_info['Exit_Time'],
                'Expiry': c['Expiry'],
                'DTE': c['DTE'],
                'Hold_Days': exit_info['Hold_Days'],
                'Exit_Reason': exit_info['Exit_Reason'],
                'Spot_Ref_Price': c['Spot_Ref_Price'],
                'Step_Size': c['Step_Size'],
                'ATM_Strike': c['ATM_Strike'],
                'OTM3_Strike': c['OTM3_Strike'],
                'Spread_Width': c['Spread_Width'],
                'Lot_Size': lot_size,
                'Lots_Traded': lots,
                'Total_Qty': total_qty,
                'Margin_Per_Lot': margin_per_lot,
                'Total_Margin_Utilized': total_margin_utilized,
                'ATM_Entry_Price': raw_atm_open,
                'OTM3_Entry_Price': raw_otm3_open,
                'Net_Credit_Pt': c['Net_Credit_Pt'],
                'ATM_Exit_Price': exit_info['ATM_Exit_Price'],
                'OTM3_Exit_Price': exit_info['OTM3_Exit_Price'],
                'Spread_Exit_Price': exit_info['ATM_Exit_Price'] - exit_info['OTM3_Exit_Price'],
                'Gross_Pt': exit_info['Gross_Pt'],
                'Gross_PnL': gross_pnl,
                'Slippage_Per_Leg': self.slippage_per_leg,
                'Slippage_Roundtrip': self.roundtrip_slippage_per_share,
                'Total_Slippage': total_slippage,
                'Taxes_Charges_Per_Lot': self.taxes_and_charges_per_lot,
                'Total_Taxes_Charges': total_charges,
                'Net_PnL': net_pnl,
                'ROI_Pct': roi_pct,
                'Result': 'WIN' if net_pnl > 0 else 'LOSS'
            })

        df_trades = pd.DataFrame(executed_trades)
        cursor.close()
        db.close()
        return df_trades

    def print_performance_summary(self, df_trades):
        if df_trades.empty:
            print("No executed trades found.")
            return

        total_trades = len(df_trades)
        wins = df_trades[df_trades['Net_PnL'] > 0]
        losses = df_trades[df_trades['Net_PnL'] <= 0]
        n_wins = len(wins)
        n_losses = len(losses)
        win_rate = (n_wins / total_trades) * 100

        gross_profit = wins['Net_PnL'].sum()
        gross_loss = abs(losses['Net_PnL'].sum())
        pf = gross_profit / gross_loss if gross_loss > 0 else np.nan

        net_pnl = df_trades['Net_PnL'].sum()
        total_slippage = df_trades['Total_Slippage'].sum()
        total_charges = df_trades['Total_Taxes_Charges'].sum()

        t1_exits = len(df_trades[df_trades['Hold_Days'] == 'T+1'])
        t2_exits = len(df_trades[df_trades['Hold_Days'] == 'T+2'])

        print("=" * 80)
        print("🏆 UNIFIED T+2 SIMULATION ENGINE: EXECUTIVE RESULTS")
        print("=" * 80)
        print(f"Total Trades Simulated:    {total_trades}")
        print(f"Holding Distribution:      T+1 Exits: {t1_exits} ({t1_exits/total_trades*100:.1f}%) | T+2 Exits: {t2_exits} ({t2_exits/total_trades*100:.1f}%)")
        print(f"Winning Trades:            {n_wins} ({win_rate:.2f}%)")
        print(f"Losing Trades:             {n_losses} ({100-win_rate:.2f}%)")
        print(f"Profit Factor:             {pf:.2f}")
        print(f"Total Slippage Deducted:   -₹{total_slippage:,.2f}")
        print(f"Total Charges & Brokerage: -₹{total_charges:,.2f}")
        print(f"NET REALIZED P&L:          +₹{net_pnl:,.2f} (+₹{net_pnl/100000:.2f} Lakhs)")
        print("=" * 80 + "\n")

        # Annual breakdown
        df_trades['Year'] = pd.to_datetime(df_trades['Entry_Date']).dt.year
        print("📅 ANNUAL PERFORMANCE BREAKDOWN:")
        print("-" * 80)
        print(f"{'Year':<8} | {'Trades':<8} | {'Wins':<6} | {'Losses':<6} | {'Win Rate':<10} | {'PF':<6} | {'Net Realized PnL':<20}")
        print("-" * 80)
        for y, grp in df_trades.groupby('Year'):
            y_t = len(grp)
            y_w = len(grp[grp['Net_PnL'] > 0])
            y_l = len(grp[grp['Net_PnL'] <= 0])
            y_wr = (y_w / y_t) * 100
            y_gp = grp[grp['Net_PnL'] > 0]['Net_PnL'].sum()
            y_gl = abs(grp[grp['Net_PnL'] <= 0]['Net_PnL'].sum())
            y_pf = y_gp / y_gl if y_gl > 0 else np.nan
            y_net = grp['Net_PnL'].sum()
            print(f"{y:<8} | {y_t:<8} | {y_w:<6} | {y_l:<6} | {y_wr:>6.1f}%    | {y_pf:>5.2f} | +₹{y_net:>14,.2f}")
        print("-" * 80 + "\n")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Run Unified T+2 Holding Option Simulation")
    parser.add_argument('--capital', type=float, default=400000.0, help="Daily portfolio capital limit")
    parser.add_argument('--max-lots', type=int, default=20, help="Max lots cap per trade")
    parser.add_argument('--output-csv', type=str, default='/home/ubuntu/sarang_bestmodel_t2_simulation_pnl.csv', help="Output CSV path")
    args = parser.parse_args()

    engine = UnifiedT2SimulationEngine(capital_per_day=args.capital, max_lots=args.max_lots)
    df_res = engine.run_simulation()
    engine.print_performance_summary(df_res)
    df_res.to_csv(args.output_csv, index=False)
    print(f"📁 Detailed T+2 PnL sheet exported to: {args.output_csv}\n")
