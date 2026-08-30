import os
import time
import pandas as pd
import mysql.connector

t0 = time.time()

# 1. Master Setups
best_model = pd.read_csv('/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/option_simulation_unified/data/sarang_best_model_selections.csv')
best_model['Date'] = pd.to_datetime(best_model['date'], format='%d-%m-%Y').dt.strftime('%Y-%m-%d')
best_model['Stock'] = best_model['stockname'].str.strip()

# 2. NSE Business Dates
b_df = pd.read_csv('/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/option_simulation_unified/data/nse_business_dates.csv')
b_dates = sorted(pd.to_datetime(b_df['date'], format='%d-%m-%Y'))

def get_t1_exit_date(entry_date_str):
    entry_dt = pd.to_datetime(entry_date_str)
    next_days = [d for d in b_dates if d > entry_dt]
    return next_days[0].strftime('%Y-%m-%d') if next_days else entry_date_str

# 3. Master Monthly Expiry Dates
master_exp = pd.read_csv('/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/option_simulation_unified/data/master_expiry_dates.csv')
exp_list = sorted(pd.to_datetime(master_exp['master_expiry_date']).tolist())

def get_nearest_monthly_expiry(entry_dt_str):
    entry_dt = pd.to_datetime(entry_dt_str)
    for exp in exp_list:
        if exp >= entry_dt:
            return exp
    return exp_list[-1]

# 4. Spot Reference Prices
spot_df = pd.read_csv('/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/option_simulation_unified/data/master_reference_spot_prices.csv')
spot_df['Stock'] = spot_df['Stock'].str.strip()
spot_map = dict(zip(zip(spot_df['Stock'], spot_df['Date']), spot_df['Spot_Price']))

# 5. True Stepsizes
step_df = pd.read_csv('/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/option_simulation_unified/data/true_historical_stepsize.csv')
step_df['stockname'] = step_df['stockname'].str.strip()
step_df['expyear'] = step_df['expyear'].astype(str)
step_dict = {f"{r['stockname']}_{r['expmonth']}_{r['expyear']}": r['step_size'] for _, r in step_df.iterrows()}

def get_step_size(stk, dt_str, pr):
    d = pd.to_datetime(dt_str)
    k = f"{stk}_{d.strftime('%b').upper()}_{str(d.year)[-2:]}"
    if k in step_dict and pd.notna(step_dict[k]): return float(step_dict[k])
    if pr > 2500: return 50.0
    if pr > 1000: return 20.0
    if pr > 500: return 10.0
    if pr > 100: return 5.0
    if pr > 50: return 2.5
    return 1.0

# 6. Lot Sizes
lot_df = pd.read_csv('/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/option_simulation_unified/data/historical_lotsizes.csv')
lot_df['stockname'] = lot_df['stockname'].str.strip()
lot_df['expyear'] = lot_df['expyear'].astype(str)
lot_dict = {f"{r['stockname']}_{r['expmonth']}_{r['expyear']}": r['lotsize'] for _, r in lot_df.iterrows()}

def get_lot_size(stk, dt_str):
    d = pd.to_datetime(dt_str)
    k = f"{stk}_{d.strftime('%b').upper()}_{str(d.year)[-2:]}"
    if k in lot_dict: return int(lot_dict[k])
    m_stk = lot_df[lot_df['stockname'] == stk]
    if not m_stk.empty: return int(m_stk.iloc[-1]['lotsize'])
    return 500

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

db = mysql.connector.connect(host='localhost', user='root', password='root', database='markets')
cursor = db.cursor()

def fetch_day_data(stk, icici, date_str, strike):
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

# First pass: identify all candidate setups that qualify on Day T
print("Analyzing and qualifying candidate setups with multi-trade daily margin sharing...", flush=True)

candidate_setups = []

for idx, row in best_model.iterrows():
    stk = row['Stock']
    icici = ICICI_SCRIP_MAP.get(stk, stk)
    b_date = row['Date']
    
    exp_obj = get_nearest_monthly_expiry(b_date)
    sell_date = get_t1_exit_date(b_date)
    
    b_days_to_exp = [d for d in b_dates if pd.to_datetime(b_date) < d <= exp_obj]
    dte = len(b_days_to_exp)
    
    if dte <= 4:
        continue
        
    ref_price = spot_map.get((stk, b_date))
    if ref_price is None or pd.isna(ref_price):
        continue
        
    ref_price = float(ref_price)
    step = get_step_size(stk, b_date, ref_price)
    atm_strike = round(ref_price / step) * step
    otm3_strike = atm_strike - (3 * step)
    
    raw_atm_open, atm_entry_time, _ = fetch_day_data(stk, icici, b_date, atm_strike)
    raw_otm3_open, otm3_entry_time, _ = fetch_day_data(stk, icici, b_date, otm3_strike)
    
    if raw_atm_open is None or raw_otm3_open is None:
        continue
        
    spread_width = atm_strike - otm3_strike
    net_credit = raw_atm_open - raw_otm3_open
    credit_ratio = net_credit / spread_width if spread_width > 0 else 0
    
    # ATM >= 5.0 and Credit Ratio >= 30%
    if credit_ratio < 0.30 or raw_atm_open < 5.0:
        continue
        
    _, _, atm_exit_ticks = fetch_day_data(stk, icici, sell_date, atm_strike)
    _, _, otm3_exit_ticks = fetch_day_data(stk, icici, sell_date, otm3_strike)
    
    common_minutes = sorted(list(set(atm_exit_ticks.keys()).intersection(set(otm3_exit_ticks.keys()))))
    if not common_minutes:
        continue
        
    candidate_setups.append({
        'Stock': stk, 'icici': icici, 'Entry_Date': b_date, 'Exit_Date': sell_date,
        'Expiry': exp_obj.strftime('%Y-%m-%d'), 'DTE': dte, 'Spot_Ref_Price': ref_price,
        'Step_Size': step, 'ATM_Strike': atm_strike, 'OTM3_Strike': otm3_strike,
        'Spread_Width': spread_width, 'Entry_Time': atm_entry_time,
        'ATM_Entry_Price': raw_atm_open, 'OTM3_Entry_Price': raw_otm3_open,
        'Net_Credit_Pt': net_credit, 'Credit_Ratio': credit_ratio,
        'atm_exit_ticks': atm_exit_ticks, 'otm3_exit_ticks': otm3_exit_ticks,
        'common_minutes': common_minutes
    })

# Group candidates by Entry_Date to determine daily trade count N
df_candidates = pd.DataFrame(candidate_setups)
daily_counts = df_candidates.groupby('Entry_Date').size().to_dict()

print(f"Total Qualified Candidate Setups: {len(df_candidates)} across {len(daily_counts)} distinct trading dates.")

executed_trades = []

for c in candidate_setups:
    b_date = c['Entry_Date']
    n_trades_today = daily_counts[b_date]
    
    # Daily margin allocation: ₹4L total budget shared equally among today's trades
    allocated_capital = 400000.0 / n_trades_today
    
    lot_size = get_lot_size(c['Stock'], b_date)
    margin_per_lot = c['Spread_Width'] * lot_size
    
    calc_lots = max(1, round(allocated_capital / margin_per_lot))
    lots = min(calc_lots, 20)  # Max 20 lots limit
    total_qty = lots * lot_size
    total_margin_utilized = margin_per_lot * lots
    
    common_minutes = c['common_minutes']
    atm_exit_ticks = c['atm_exit_ticks']
    otm3_exit_ticks = c['otm3_exit_ticks']
    
    raw_atm_open = c['ATM_Entry_Price']
    raw_otm3_open = c['OTM3_Entry_Price']
    
    exited = False
    exit_info = None
    
    # Phase 1: Live Profit Scanner (09:16 to 15:00)
    scan_minutes = [m for m in common_minutes if '09:16:00' <= m <= '15:00:00']
    
    for m in scan_minutes:
        raw_atm_exit = atm_exit_ticks[m]['close']
        raw_otm3_exit = otm3_exit_ticks[m]['close']
        
        # Raw Gross PnL
        raw_gross_pt = (raw_atm_open - raw_atm_exit) + (raw_otm3_exit - raw_otm3_open)
        raw_gross_pnl = raw_gross_pt * total_qty
        
        # Exact Friction Deductions
        slippage_total = 0.40 * total_qty  # 4 legs * 0.10
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
df_out.to_csv('/home/ubuntu/sarang_bestmodel_detailed_pnl_sheet.csv', index=False)
df_out.to_csv('/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/option_simulation_unified/sarang_bestmodel_detailed_pnl_sheet.csv', index=False)

wins = df_out[df_out['Trade_Result'] == 'WIN']
losses = df_out[df_out['Trade_Result'] == 'LOSS']
win_rate = len(wins) / len(df_out) * 100
tot_gross = df_out['Gross_PnL'].sum()
tot_slippage = df_out['Total_Slippage_Deducted'].sum()
tot_charges = df_out['Charges_Deducted'].sum()
tot_net = df_out['Net_Realized_PnL'].sum()
avg_net = df_out['Net_Realized_PnL'].mean()
profit_factor = wins['Net_Realized_PnL'].sum() / abs(losses['Net_Realized_PnL'].sum())

print("\n" + "="*80)
print("🏆 MASTER DETAILED PNL SHEET GENERATED (100% Shared Margin & Exact Match)")
print("="*80)
print(f"Total Executed Trades:                 {len(df_out)}")
print(f"Single-Trade Days (Allocated ₹4.0L):   {len(df_out[df_out['Trades_On_Day'] == 1])}")
print(f"Two-Trade Days (Allocated ₹2.0L each): {len(df_out[df_out['Trades_On_Day'] == 2])}")
print(f"Three-Trade Days (Allocated ₹1.33L):   {len(df_out[df_out['Trades_On_Day'] >= 3])}")
print(f"Win Rate:                              {win_rate:.1f}% ({len(wins)} Wins / {len(losses)} Losses)")
print(f"Profit Factor:                         {profit_factor:.2f}")
print(f"Total Gross Realized PnL:              Rs. {tot_gross:14,.2f}")
print(f"Total Slippage Deducted (Rs. 0.40/sh): Rs. {tot_slippage:14,.2f}")
print(f"Total Charges Deducted (Rs. 300/lot):  Rs. {tot_charges:14,.2f}")
print(f"TOTAL NET REALIZED PNL:                Rs. {tot_net:14,.2f}")
print(f"Average NET Profit per Trade:          Rs. {avg_net:14,.2f}")
print(f"Saved to: /home/ubuntu/sarang_bestmodel_detailed_pnl_sheet.csv")
print("="*80 + "\n")
