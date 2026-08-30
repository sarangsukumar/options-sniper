#!/usr/bin/env python3
"""
========================================================================================
🏆 UNIFIED OPTION SIMULATION ENGINE (Bull Put Credit Spreads)
========================================================================================
Author: Google Deepmind Antigravity Pair-Programming Agent & Sarang Sukumar
Strategy: Bull Put Spread (Sell ATM Put + Buy OTM-3 Put)
Execution Timing:
  - Entry Window: Day T Afternoon (15:20:00 to 15:30:00)
  - Exit Window 1: Day T+1 Live Positive Profit Scanner (09:16:00 to 15:00:00)
  - Exit Window 2: Day T+1 Hard Square-Off Hierarchy (15:00:00 exact -> 15:01-15:30 -> 14:59-10:00)
Quality & Risk Rules:
  - DTE > 4 business days (Avoid high-gamma expiry week decay)
  - Net Credit Ratio >= 30% of Spread Width
  - ATM Premium >= Rs. 5.0 (Customizable via CLI)
Friction & Statutory Charges:
  - Slippage: Rs. 0.10 per share per leg (Rs. 0.40 round-trip spread)
  - Statutory Charges: Rs. 300.00 flat per lot (STT, Exchange Turnover, GST, Stamp Duty)
========================================================================================
"""

import os
import sys
import time
import argparse
import pandas as pd
import mysql.connector

# ICICI Breeze Symbol Mapping Quirks
ICICI_SCRIP_MAP = {
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

class UnifiedSimulationEngine:
    def __init__(self, data_dir=None, atm_threshold=5.0, credit_ratio=0.30, dte_min=5, capital_per_trade=400000.0,
                 db_host='localhost', db_user='root', db_password='root', db_name='markets'):
        self.data_dir = data_dir or os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
        self.atm_threshold = float(atm_threshold)
        self.credit_ratio_thresh = float(credit_ratio)
        self.dte_min = int(dte_min)
        self.capital_per_trade = float(capital_per_trade)
        
        self.db_host = db_host
        self.db_user = db_user
        self.db_password = db_password
        self.db_name = db_name
        
        self._load_reference_data()

    def _load_reference_data(self):
        print(f"Loading reference datasets from: {self.data_dir}...")
        
        # 1. Candidate Setups
        selections_path = os.path.join(self.data_dir, 'sarang_best_model_selections.csv')
        df_sel = pd.read_csv(selections_path)
        df_sel['Date'] = pd.to_datetime(df_sel['date'], format='%d-%m-%Y').dt.strftime('%Y-%m-%d')
        df_sel['Stock'] = df_sel['stockname'].str.strip()
        self.setups = df_sel

        # 2. NSE Business Dates
        b_path = os.path.join(self.data_dir, 'nse_business_dates.csv')
        b_df = pd.read_csv(b_path)
        self.b_dates = sorted(pd.to_datetime(b_df['date'], format='%d-%m-%Y'))

        # 3. Master Expiry Dates
        exp_path = os.path.join(self.data_dir, 'master_expiry_dates.csv')
        exp_df = pd.read_csv(exp_path)
        self.exp_list = sorted(pd.to_datetime(exp_df['master_expiry_date']).tolist())

        # 4. Reference Spot Prices
        spot_path = os.path.join(self.data_dir, 'master_reference_spot_prices.csv')
        spot_df = pd.read_csv(spot_path)
        spot_df['Stock'] = spot_df['Stock'].str.strip()
        self.spot_map = dict(zip(zip(spot_df['Stock'], spot_df['Date']), spot_df['Spot_Price']))

        # 5. True Stepsizes
        step_path = os.path.join(self.data_dir, 'true_historical_stepsize.csv')
        step_df = pd.read_csv(step_path)
        step_df['stockname'] = step_df['stockname'].str.strip()
        step_df['expyear'] = step_df['expyear'].astype(str)
        self.step_dict = {f"{r['stockname']}_{r['expmonth']}_{r['expyear']}": r['step_size'] for _, r in step_df.iterrows()}

        # 6. Lot Sizes
        lot_path = os.path.join(self.data_dir, 'historical_lotsizes.csv')
        lot_df = pd.read_csv(lot_path)
        lot_df['stockname'] = lot_df['stockname'].str.strip()
        lot_df['expyear'] = lot_df['expyear'].astype(str)
        self.lot_dict = {f"{r['stockname']}_{r['expmonth']}_{r['expyear']}": r['lotsize'] for _, r in lot_df.iterrows()}
        self.master_lots = lot_df

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
        m_stk = self.master_lots[self.master_lots['stockname'] == stk]
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
            return None, {}
        
        ticks = {r[0].strftime('%H:%M:00'): {'open': float(r[1]) if r[1] is not None else float(r[4]),
                                             'high': float(r[2]) if r[2] is not None else float(r[4]),
                                             'low': float(r[3]) if r[3] is not None else float(r[4]),
                                             'close': float(r[4]),
                                             'volume': r[5]} for r in rows if r[4] is not None}
        
        raw_1520 = None
        for t_str in ['15:20:00', '15:21:00', '15:22:00', '15:23:00', '15:24:00', '15:25:00', '15:26:00', '15:27:00', '15:28:00', '15:29:00', '15:30:00']:
            if t_str in ticks:
                raw_1520 = float(ticks[t_str]['open'])
                break
                
        if raw_1520 is None:
            raw_1520 = float(rows[-1][1]) if rows[-1][1] is not None else float(rows[-1][4])
            
        return float(raw_1520), ticks

    def run(self, output_csv='sarang_bestmodel_unified_trades.csv'):
        t0 = time.time()
        print("\n" + "="*80)
        print("🚀 RUNNING UNIFIED OPTION SIMULATION ENGINE")
        print(f"   ATM Threshold: >= Rs. {self.atm_threshold}")
        print(f"   Net Credit Ratio: >= {self.credit_ratio_thresh*100:.0f}%")
        print(f"   Min DTE: >= {self.dte_min} business days")
        print(f"   Allocated Capital: Rs. {self.capital_per_trade:,.2f} per trade")
        print("="*80 + "\n")

        db = mysql.connector.connect(host=self.db_host, user=self.db_user, password=self.db_password, database=self.db_name)
        cursor = db.cursor()

        executed_trades = []
        filtered_dte = 0
        filtered_credit = 0
        skipped_incomplete = 0

        total_setups = len(self.setups)

        for idx, row in self.setups.iterrows():
            stk = row['Stock']
            icici = ICICI_SCRIP_MAP.get(stk, stk)
            b_date = row['Date']
            
            exp_obj = self.get_nearest_monthly_expiry(b_date)
            sell_date = self.get_t1_exit_date(b_date)
            
            b_days_to_exp = [d for d in self.b_dates if pd.to_datetime(b_date) < d <= exp_obj]
            dte = len(b_days_to_exp)
            
            # Rule 1: DTE Expiry Risk Filter
            if dte < self.dte_min:
                filtered_dte += 1
                continue
                
            # Rule 2: Spot Reference Price
            ref_price = self.spot_map.get((stk, b_date))
            if ref_price is None or pd.isna(ref_price):
                skipped_incomplete += 1
                continue
                
            ref_price = float(ref_price)
            step = self.get_step_size(stk, b_date, ref_price)
            atm_strike = round(ref_price / step) * step
            otm3_strike = atm_strike - (3 * step)
            
            # Rule 3: Entry Option Data Fetch
            raw_atm_open, _ = self.fetch_day_data(cursor, stk, icici, b_date, atm_strike)
            raw_otm3_open, _ = self.fetch_day_data(cursor, stk, icici, b_date, otm3_strike)
            
            if raw_atm_open is None or raw_otm3_open is None:
                skipped_incomplete += 1
                continue
                
            spread_width = atm_strike - otm3_strike
            net_credit = raw_atm_open - raw_otm3_open
            credit_ratio = net_credit / spread_width if spread_width > 0 else 0
            
            # Rule 4: Quality & Premium Filters
            if credit_ratio < self.credit_ratio_thresh or raw_atm_open < self.atm_threshold:
                filtered_credit += 1
                continue
                
            # Position Sizing
            lot_size = self.get_lot_size(stk, b_date)
            lots = max(1, round(self.capital_per_trade / (spread_width * lot_size)))
            total_qty = lots * lot_size
            
            # Entry Pricing with ₹0.10 Slippage per Leg
            entry_atm_sell = raw_atm_open - 0.10
            entry_otm3_buy = raw_otm3_open + 0.10
            
            # Exit Day T+1 Ticks Fetch
            _, atm_exit_ticks = self.fetch_day_data(cursor, stk, icici, sell_date, atm_strike)
            _, otm3_exit_ticks = self.fetch_day_data(cursor, stk, icici, sell_date, otm3_strike)
            
            common_minutes = sorted(list(set(atm_exit_ticks.keys()).intersection(set(otm3_exit_ticks.keys()))))
            
            if not common_minutes:
                skipped_incomplete += 1
                continue
                
            exited = False
            exit_info = None
            
            # Phase 1: Live Profit Scanner (09:16 to 15:00)
            scan_minutes = [m for m in common_minutes if '09:16:00' <= m <= '15:00:00']
            
            for m in scan_minutes:
                atm_buy_close = atm_exit_ticks[m]['close'] + 0.10
                otm3_sell_close = otm3_exit_ticks[m]['close'] - 0.10
                
                gross_pnl_pt = (entry_atm_sell - atm_buy_close) + (otm3_sell_close - entry_otm3_buy)
                gross_pnl = gross_pnl_pt * total_qty
                
                slippage_total = 0.40 * total_qty
                charges_total = lots * 300.0
                net_pnl = gross_pnl - charges_total
                
                if net_pnl > 0:
                    exited = True
                    exit_info = {
                        'time': m,
                        'type': 'Live Scanner Profit Exit',
                        'gross_pnl': gross_pnl,
                        'net_pnl': net_pnl,
                        'slippage': slippage_total,
                        'charges': charges_total
                    }
                    break
                    
            # Phase 2: Hard Square-Off Hierarchy
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
                            
                atm_buy_close = atm_exit_ticks[chosen_min]['close'] + 0.10
                otm3_sell_close = otm3_exit_ticks[chosen_min]['close'] - 0.10
                
                gross_pnl_pt = (entry_atm_sell - atm_buy_close) + (otm3_sell_close - entry_otm3_buy)
                gross_pnl = gross_pnl_pt * total_qty
                
                slippage_total = 0.40 * total_qty
                charges_total = lots * 300.0
                net_pnl = gross_pnl - charges_total
                
                exit_info = {
                    'time': chosen_min,
                    'type': 'Hard Square-Off Exit',
                    'gross_pnl': gross_pnl,
                    'net_pnl': net_pnl,
                    'slippage': slippage_total,
                    'charges': charges_total
                }
                
            executed_trades.append({
                'Stock': stk,
                'Entry_Date': b_date,
                'Exit_Date': sell_date,
                'DTE': dte,
                'Spot_Ref_Price': ref_price,
                'Step_Size': step,
                'ATM_Strike': atm_strike,
                'OTM3_Strike': otm3_strike,
                'Spread_Width': spread_width,
                'ATM_Entry_Price': raw_atm_open,
                'OTM3_Entry_Price': raw_otm3_open,
                'Net_Credit_Pt': net_credit,
                'Credit_Ratio': credit_ratio,
                'Lot_Size': lot_size,
                'Lots': lots,
                'Total_Qty': total_qty,
                'Exit_Time': exit_info['time'],
                'Exit_Type': exit_info['type'],
                'Gross_PnL': exit_info['gross_pnl'],
                'Slippage_Deducted': exit_info['slippage'],
                'Charges_Deducted': exit_info['charges'],
                'Net_Realized_PnL': exit_info['net_pnl']
            })

        cursor.close()
        db.close()

        df_res = pd.DataFrame(executed_trades)
        if output_csv:
            df_res.to_csv(output_csv, index=False)
            print(f"Saved complete trade log to: {output_csv}")

        # Metrics calculation
        wins = df_res[df_res['Net_Realized_PnL'] > 0]
        losses = df_res[df_res['Net_Realized_PnL'] <= 0]
        win_rate = (len(wins) / len(df_res) * 100) if len(df_res) > 0 else 0
        tot_gross = df_res['Gross_PnL'].sum()
        tot_slippage = df_res['Slippage_Deducted'].sum()
        tot_charges = df_res['Charges_Deducted'].sum()
        tot_net = df_res['Net_Realized_PnL'].sum()
        avg_net = df_res['Net_Realized_PnL'].mean()
        profit_factor = (wins['Net_Realized_PnL'].sum() / abs(losses['Net_Realized_PnL'].sum())) if len(losses) > 0 and abs(losses['Net_Realized_PnL'].sum()) > 0 else 999.0

        print("\n" + "="*80)
        print("🏆 UNIFIED SIMULATION EXECUTIVE SUMMARY")
        print("="*80)
        print(f"Total Trade Setups Analyzed:           {total_setups}")
        print(f"Filtered (DTE <= {self.dte_min-1}):                   {filtered_dte}")
        print(f"Filtered (Credit < {self.credit_ratio_thresh*100:.0f}% or ATM < Rs. {self.atm_threshold}): {filtered_credit}")
        print(f"Skipped / Incomplete Option Data:      {skipped_incomplete}")
        print(f"100% Fully Verified Executed Trades:   {len(df_res)}")
        print(f"Live Scanner Profit Exits (09:16-15:00):{len(df_res[df_res['Exit_Type'] == 'Live Scanner Profit Exit'])} / {len(df_res)} ({len(df_res[df_res['Exit_Type'] == 'Live Scanner Profit Exit'])/len(df_res)*100:.1f}%)")
        print(f"End-of-Day Hard Square-Offs:           {len(df_res[df_res['Exit_Type'] == 'Hard Square-Off Exit'])} / {len(df_res)}")
        print(f"Win Rate:                              {win_rate:.1f}% ({len(wins)} Wins / {len(losses)} Losses)")
        print(f"Profit Factor:                         {profit_factor:.2f}")
        print(f"Total Gross Realized PnL:              Rs. {tot_gross:14,.2f}")
        print(f"Total Slippage Deducted (Rs. 0.10/leg):Rs. {tot_slippage:14,.2f}")
        print(f"Total Statutory Charges (Rs. 300/lot): Rs. {tot_charges:14,.2f}")
        print(f"TOTAL NET REALIZED PNL:                Rs. {tot_net:14,.2f}")
        print(f"Average NET Profit per Trade:          Rs. {avg_net:14,.2f}")
        print(f"Total Execution Time:                  {time.time() - t0:.2f} seconds")
        print("="*80 + "\n")

        return df_res

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Unified Bull Put Credit Spread Simulation Engine')
    parser.add_argument('--atm-threshold', type=float, default=5.0, help='Minimum ATM Put entry premium (default: 5.0)')
    parser.add_argument('--credit-ratio', type=float, default=0.30, help='Minimum Net Credit Ratio (default: 0.30)')
    parser.add_argument('--dte-min', type=int, default=5, help='Minimum business days to expiry (default: 5)')
    parser.add_argument('--capital', type=float, default=400000.0, help='Capital allocated per trade (default: 400000.0)')
    parser.add_argument('--output-csv', type=str, default='unified_trades.csv', help='Output CSV trade log path')
    parser.add_argument('--data-dir', type=str, default=None, help='Path to reference data directory')
    args = parser.parse_args()

    engine = UnifiedSimulationEngine(
        data_dir=args.data_dir,
        atm_threshold=args.atm_threshold,
        credit_ratio=args.credit_ratio,
        dte_min=args.dte_min,
        capital_per_trade=args.capital
    )
    engine.run(output_csv=args.output_csv)
