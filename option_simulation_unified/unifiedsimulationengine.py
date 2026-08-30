#!/usr/bin/env python3
"""
================================================================================
UNIFIED OPTION SIMULATION ENGINE
================================================================================
Production Standalone Option Spread Simulation Engine.
Features:
- Dynamic Multi-Trade Daily Margin Sharing (e.g. ₹4L on 1-trade days, ₹2L each on 2-trade days)
- Live Intraday Profit Scanner (09:16 - 15:00) + 15:00 Hard Square-Off Hierarchy
- OTM-3 Defined Risk Bull Put Credit Spreads
- True NSE Stepsizes, Lot Sizes, Expiry Calendars, and Spot References
- Exact Cost Deductions: ₹0.10/leg slippage (₹0.40/share roundtrip) + ₹300/lot statutory charges
- 34-Column Comprehensive Trade-by-Trade Audit Export
================================================================================
"""

import os
import sys
import time
import argparse
import pandas as pd
import mysql.connector

class UnifiedSimulationEngine:
    def __init__(self, data_dir=None, atm_threshold=5.0, credit_ratio=0.30, dte_min=5, 
                 capital_per_day=400000.0, max_lots=20, db_host='localhost', db_user='root', 
                 db_password='root', db_name='markets'):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.data_dir = data_dir or os.path.join(base_dir, 'data')
        self.atm_threshold = float(atm_threshold)
        self.credit_ratio_thresh = float(credit_ratio)
        self.dte_min = int(dte_min)
        self.capital_per_day = float(capital_per_day)
        self.max_lots = int(max_lots) if max_lots is not None else None
        
        self.db_host = db_host
        self.db_user = db_user
        self.db_password = db_password
        self.db_name = db_name
        
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
        
        self.load_reference_data()

    def load_reference_data(self):
        print(f"Loading reference datasets from: {self.data_dir}...")
        
        # 1. Master Setups
        best_model_path = os.path.join(self.data_dir, 'sarang_best_model_selections.csv')
        self.best_model = pd.read_csv(best_model_path)
        self.best_model['Date'] = pd.to_datetime(self.best_model['date'], format='%d-%m-%Y').dt.strftime('%Y-%m-%d')
        self.best_model['Stock'] = self.best_model['stockname'].str.strip()

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
                                             'close': float(r[4]),
                                             'volume': r[5]} for r in rows if r[4] is not None}
        
        raw_entry = None
        entry_time = None
        for t_str in ['15:25:00', '15:24:00', '15:26:00', '15:23:00', '15:27:00', '15:22:00', '15:28:00', '15:21:00', '15:29:00', '15:20:00', '15:30:00']:
            if t_str in ticks:
                raw_entry = float(ticks[t_str]['open'])
                entry_time = t_str
                break
                
        if raw_entry is None:
            raw_entry = float(rows[-1][1]) if rows[-1][1] is not None else float(rows[-1][4])
            entry_time = rows[-1][0].strftime('%H:%M:00')
            
        return float(raw_entry), entry_time, ticks

    def run(self, output_csv='sarang_bestmodel_detailed_pnl_sheet.csv'):
        t0 = time.time()
        print("\n" + "="*80)
        print("🚀 RUNNING PRODUCTION UNIFIED OPTION SIMULATION ENGINE")
        print(f"   Daily Portfolio Capital: Rs. {self.capital_per_day:,.2f} per day")
        print(f"   Max Lots Limit:          {self.max_lots if self.max_lots is not None else 'No Limit'} lots")
        print(f"   ATM Entry Premium:       >= Rs. {self.atm_threshold}")
        print(f"   Net Credit Ratio:        >= {self.credit_ratio_thresh*100:.0f}%")
        print(f"   Min DTE to Expiry:       >= {self.dte_min} business days")
        print("="*80 + "\n")

        db = mysql.connector.connect(host=self.db_host, user=self.db_user, password=self.db_password, database=self.db_name)
        cursor = db.cursor()

        print("Phase 1: Analyzing setups and finding qualifying candidate trades...", flush=True)
        candidate_setups = []

        for idx, row in self.best_model.iterrows():
            stk = row['Stock']
            icici = self.ICICI_SCRIP_MAP.get(stk, stk)
            b_date = row['Date']
            
            exp_obj = self.get_nearest_monthly_expiry(b_date)
            sell_date = self.get_t1_exit_date(b_date)
            
            b_days_to_exp = [d for d in self.b_dates if pd.to_datetime(b_date) < d <= exp_obj]
            dte = len(b_days_to_exp)
            
            if dte < self.dte_min:
                continue
                
            ref_price = self.spot_map.get((stk, b_date))
            if ref_price is None or pd.isna(ref_price):
                continue
                
            ref_price = float(ref_price)
            step = self.get_step_size(stk, b_date, ref_price)
            atm_strike = round(ref_price / step) * step
            otm3_strike = atm_strike - (3 * step)
            
            raw_atm_open, atm_entry_time, _ = self.fetch_day_data(cursor, stk, icici, b_date, atm_strike)
            raw_otm3_open, otm3_entry_time, _ = self.fetch_day_data(cursor, stk, icici, b_date, otm3_strike)
            
            if raw_atm_open is None or raw_otm3_open is None:
                continue
                
            spread_width = atm_strike - otm3_strike
            net_credit = raw_atm_open - raw_otm3_open
            credit_ratio = net_credit / spread_width if spread_width > 0 else 0
            
            if credit_ratio < self.credit_ratio_thresh or raw_atm_open < self.atm_threshold:
                continue
                
            _, _, atm_exit_ticks = self.fetch_day_data(cursor, stk, icici, sell_date, atm_strike)
            _, _, otm3_exit_ticks = self.fetch_day_data(cursor, stk, icici, sell_date, otm3_strike)
            
            common_minutes = sorted(list(set(atm_exit_ticks.keys()).intersection(set(otm3_exit_ticks.keys()))))
            if not common_minutes:
                continue
                
            candidate_setups.append({
                'Stock': stk, 'Entry_Date': b_date, 'Exit_Date': sell_date,
                'Expiry': exp_obj.strftime('%Y-%m-%d'), 'DTE': dte, 'Spot_Ref_Price': ref_price,
                'Step_Size': step, 'ATM_Strike': atm_strike, 'OTM3_Strike': otm3_strike,
                'Spread_Width': spread_width, 'Entry_Time': atm_entry_time,
                'ATM_Entry_Price': raw_atm_open, 'OTM3_Entry_Price': raw_otm3_open,
                'Net_Credit_Pt': net_credit, 'Credit_Ratio': credit_ratio,
                'atm_exit_ticks': atm_exit_ticks, 'otm3_exit_ticks': otm3_exit_ticks,
                'common_minutes': common_minutes
            })

        df_candidates = pd.DataFrame(candidate_setups)
        daily_counts = df_candidates.groupby('Entry_Date').size().to_dict()

        print(f"Phase 2: Simulating {len(df_candidates)} candidate trades with multi-trade daily capital sharing...", flush=True)

        executed_trades = []

        for c in candidate_setups:
            b_date = c['Entry_Date']
            n_trades_today = daily_counts[b_date]
            
            # Shared daily capital budget
            allocated_capital = self.capital_per_day / n_trades_today
            
            lot_size = self.get_lot_size(c['Stock'], b_date)
            margin_per_lot = c['Spread_Width'] * lot_size
            
            calc_lots = max(1, round(allocated_capital / margin_per_lot))
            lots = min(calc_lots, self.max_lots) if self.max_lots is not None else calc_lots
            total_qty = lots * lot_size
            total_margin_utilized = margin_per_lot * lots
            
            common_minutes = c['common_minutes']
            atm_exit_ticks = c['atm_exit_ticks']
            otm3_exit_ticks = c['otm3_exit_ticks']
            
            raw_atm_open = c['ATM_Entry_Price']
            raw_otm3_open = c['OTM3_Entry_Price']
            
            exited = False
            exit_info = None
            
            # Live Profit Scanner (09:16 to 15:00)
            scan_minutes = [m for m in common_minutes if '09:16:00' <= m <= '15:00:00']
            
            for m in scan_minutes:
                raw_atm_exit = atm_exit_ticks[m]['close']
                raw_otm3_exit = otm3_exit_ticks[m]['close']
                
                raw_gross_pt = (raw_atm_open - raw_atm_exit) + (raw_otm3_exit - raw_otm3_open)
                raw_gross_pnl = raw_gross_pt * total_qty
                
                slippage_total = 0.40 * total_qty  # 4 legs * Rs. 0.10
                charges_total = lots * 300.0       # Rs. 300 flat per lot
                net_pnl = raw_gross_pnl - slippage_total - charges_total
                
                if net_pnl > 0:
                    exited = True
                    exit_info = {
                        'time': m,
                        'type': 'Live Scanner Profit Exit',
                        'atm_exit_price': raw_atm_exit,
                        'otm3_exit_price': raw_otm3_exit,
                        'raw_gross_pnl': raw_gross_pnl,
                        'slippage': slippage_total,
                        'charges': charges_total,
                        'net_pnl': net_pnl
                    }
                    break
                    
            # Hard Square-Off Hierarchy (15:00)
            if not exited:
                chosen_min = None
                if '15:00:00' in common_minutes:
                    chosen_min = '15:00:00'
                else:
                    fwd = [m for m in common_minutes if '15:01:00' <= m <= '15:30:00']
                    if fwd:
                        chosen_min = fwd[0]
                    else:
                        rev = [m for m in common_minutes if '10:00:00' <= m < '15:00:00']
                        if rev:
                            chosen_min = rev[-1]
                        else:
                            chosen_min = common_minutes[-1]
                            
                raw_atm_exit = atm_exit_ticks[chosen_min]['close']
                raw_otm3_exit = otm3_exit_ticks[chosen_min]['close']
                
                raw_gross_pt = (raw_atm_open - raw_atm_exit) + (raw_otm3_exit - raw_otm3_open)
                raw_gross_pnl = raw_gross_pt * total_qty
                
                slippage_total = 0.40 * total_qty
                charges_total = lots * 300.0
                net_pnl = raw_gross_pnl - slippage_total - charges_total
                
                exit_info = {
                    'time': chosen_min,
                    'type': 'Hard Square-Off Exit',
                    'atm_exit_price': raw_atm_exit,
                    'otm3_exit_price': raw_otm3_exit,
                    'raw_gross_pnl': raw_gross_pnl,
                    'slippage': slippage_total,
                    'charges': charges_total,
                    'net_pnl': net_pnl
                }
                
            executed_trades.append({
                'Entry_Date': c['Entry_Date'],
                'Entry_Time': c['Entry_Time'],
                'Stock_Name': c['Stock'],
                'Expiry': c['Expiry'],
                'DTE': c['DTE'],
                'Spot_Ref_Price': c['Spot_Ref_Price'],
                'Step_Size': c['Step_Size'],
                'ATM_Strike_Price': c['ATM_Strike'],
                'OTM3_Strike_Price': c['OTM3_Strike'],
                'Spread_Width': c['Spread_Width'],
                'ATM_Entry_Price': c['ATM_Entry_Price'],
                'OTM3_Entry_Price': c['OTM3_Entry_Price'],
                'Net_Credit_Pt': round(c['Net_Credit_Pt'], 2),
                'Credit_Ratio_Pct': round(c['Credit_Ratio'] * 100, 1),
                'Exit_Date': c['Exit_Date'],
                'Exit_Time': exit_info['time'],
                'Exit_Type': exit_info['type'],
                'ATM_Exit_Price': exit_info['atm_exit_price'],
                'OTM3_Exit_Price': exit_info['otm3_exit_price'],
                'Lot_Size': lot_size,
                'Trades_On_Day': n_trades_today,
                'Allocated_Capital': allocated_capital,
                'Margin_Per_Lot': margin_per_lot,
                'Calculated_Lots': calc_lots,
                'No_Of_Lots_Traded': lots,
                'Total_Qty': total_qty,
                'Total_Margin_Utilized': total_margin_utilized,
                'Slippage_Per_Leg': 0.10,
                'Slippage_Roundtrip_Per_Share': 0.40,
                'Total_Slippage_Deducted': round(exit_info['slippage'], 2),
                'Charges_Deducted': round(exit_info['charges'], 2),
                'Gross_PnL': round(exit_info['raw_gross_pnl'], 2),
                'Net_Realized_PnL': round(exit_info['net_pnl'], 2),
                'Trade_Result': 'WIN' if exit_info['net_pnl'] > 0 else 'LOSS'
            })

        cursor.close()
        db.close()

        df_out = pd.DataFrame(executed_trades)
        df_out.to_csv(output_csv, index=False)

        wins = df_out[df_out['Trade_Result'] == 'WIN']
        losses = df_out[df_out['Trade_Result'] == 'LOSS']
        win_rate = len(wins) / len(df_out) * 100
        tot_gross = df_out['Gross_PnL'].sum()
        tot_slippage = df_out['Total_Slippage_Deducted'].sum()
        tot_charges = df_out['Charges_Deducted'].sum()
        tot_net = df_out['Net_Realized_PnL'].sum()
        avg_net = df_out['Net_Realized_PnL'].mean()
        profit_factor = wins['Net_Realized_PnL'].sum() / abs(losses['Net_Realized_PnL'].sum()) if len(losses) > 0 and abs(losses['Net_Realized_PnL'].sum()) > 0 else 999.0

        print("\n" + "="*80)
        print("🏆 UNIFIED SIMULATION EXECUTIVE SUMMARY")
        print("="*80)
        print(f"Total Executed Trades:                 {len(df_out)}")
        print(f"Single-Trade Days:                     {len(df_out[df_out['Trades_On_Day'] == 1])}")
        print(f"Two-Trade Days:                        {len(df_out[df_out['Trades_On_Day'] == 2])}")
        print(f"Win Rate:                              {win_rate:.1f}% ({len(wins)} Wins / {len(losses)} Losses)")
        print(f"Profit Factor:                         {profit_factor:.2f}")
        print(f"Total Gross Realized PnL:              Rs. {tot_gross:14,.2f}")
        print(f"Total Slippage Deducted (Rs. 0.40/sh): Rs. {tot_slippage:14,.2f}")
        print(f"Total Charges Deducted (Rs. 300/lot):  Rs. {tot_charges:14,.2f}")
        print(f"TOTAL NET REALIZED PNL:                Rs. {tot_net:14,.2f}")
        print(f"Average NET Profit per Trade:          Rs. {avg_net:14,.2f}")
        print(f"Saved complete 34-column trade log to: {output_csv}")
        print(f"Total Execution Time:                  {time.time() - t0:.2f} seconds")
        print("="*80 + "\n")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Production Standalone Unified Option Simulation Engine")
    parser.add_argument('--atm-threshold', type=float, default=5.0, help='Minimum ATM Put entry premium (default: 5.0)')
    parser.add_argument('--credit-ratio', type=float, default=0.30, help='Minimum Net Credit Ratio (default: 0.30)')
    parser.add_argument('--dte-min', type=int, default=5, help='Minimum business days to expiry (default: 5)')
    parser.add_argument('--capital', type=float, default=400000.0, help='Total daily capital budget (default: 400000.0)')
    parser.add_argument('--max-lots', type=int, default=20, help='Maximum lot limit per trade (default: 20)')
    parser.add_argument('--output-csv', type=str, default='sarang_bestmodel_detailed_pnl_sheet.csv', help='Output CSV path')
    parser.add_argument('--data-dir', type=str, default=None, help='Path to reference data directory')
    args = parser.parse_args()

    engine = UnifiedSimulationEngine(
        data_dir=args.data_dir,
        atm_threshold=args.atm_threshold,
        credit_ratio=args.credit_ratio,
        dte_min=args.dte_min,
        capital_per_day=args.capital,
        max_lots=args.max_lots
    )
    engine.run(output_csv=args.output_csv)
