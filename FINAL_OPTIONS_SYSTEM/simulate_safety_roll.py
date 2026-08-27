import pandas as pd
import mysql.connector
import numpy as np
import warnings

warnings.filterwarnings('ignore')

db = mysql.connector.connect(host='localhost', user='root', password='root', database='markets')

# 1. Lot Size
markets_pnl = pd.read_csv('/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/data/markets_pnl0325.csv')
markets_pnl['year'] = pd.to_datetime(markets_pnl['simulationdate'], format='mixed', dayfirst=True).dt.year
lot_map = markets_pnl.groupby(['stockname', 'year'])['quantity'].max().to_dict()

def get_lot(stock, date_str):
    year = float(date_str.split('-')[0])
    qty = lot_map.get((stock, year))
    return int(qty) if pd.notna(qty) else 1000

# 2. Step Sizes
true_steps = pd.read_csv('/home/ubuntu/true_historical_stepsize.csv')
true_steps['expyear'] = true_steps['expyear'].astype(str)
true_steps['stockname'] = true_steps['stockname'].str.strip()
step_dict = {}
for _, row in true_steps.iterrows():
    key = f"{row['stockname']}_{row['expmonth']}_{row['expyear']}"
    step_dict[key] = row['step_size']

def get_true_step(stock, buy_date_obj, price):
    mo_str = buy_date_obj.strftime('%b').upper()
    yr_str = str(buy_date_obj.year)[-2:]
    key = f"{stock}_{mo_str}_{yr_str}"
    if key in step_dict: return step_dict[key]
    if price > 2500: return 50
    if price > 1000: return 20
    if price > 500: return 10
    if price > 100: return 5
    if price > 50: return 2.5
    return 1

# 3. ICICI Map
master = pd.read_csv('/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/config/ICICImaster.csv', header=None)
icici_map = dict(zip(master[6].astype(str).str.strip(), master[2].astype(str).str.strip()))
icici_map.update({
    'AARTIIND': 'AARIND', 'ABCAPITAL': 'ADICAP', 'ADANIENT': 'ADAENT', 'ADANIPORTS': 'ADAPOR',
    'ALKEM': 'ALKLAB', 'AMBUJACEM': 'AMBCE', 'APOLLOHOSP': 'APOHOS', 'ASHOKLEY': 'ASHLEY',
    'ASTRAL': 'ASTPOL', 'AUBANK': 'AUSMA', 'AUROPHARMA': 'AURPHA', 'BAJAJ-AUTO': 'BAAUTO',
    'BAJAJFINSV': 'BAFINS', 'BAJFINANCE': 'BAJFI', 'BALKRISIND': 'BALIND', 'BANDHANBNK': 'BANBAN',
    'BEL': 'BHAELE', 'BHARATFORG': 'BHAFOR', 'BPCL': 'BHAPET', 'BRITANNIA': 'BRIIND',
    'CANBK': 'CANBAN', 'CHAMBLFERT': 'CHAFER', 'CHOLAFIN': 'CHOINV', 'COFORGE': 'NIITEC',
    'CROMPTON': 'CROGR', 'CUMMINSIND': 'CUMIND', 'DABUR': 'DABIND', 'DALBHARAT': 'ODICEM',
    'DIVISLAB': 'DIVLAB', 'DIXON': 'DIXTEC', 'DLF': 'DLFLIM', 'DRREDDY': 'DRREDD',
    'EICHERMOT': 'EICMOT', 'EXIDEIND': 'EXIIND', 'FEDERALBNK': 'FEDBAN', 'GLENMARK': 'GLEPHA',
    'GODREJCP': 'GODCON', 'GODREJPROP': 'GODPRO', 'GRANULES': 'GRANUL', 'HAL': 'HINAER',
    'HCLTECH': 'HCLTEC', 'HEROMOTOCO': 'HERHON', 'HINDALCO': 'HINDAL', 'HINDCOPPER': 'HINCOP',
    'HINDPETRO': 'HINPET', 'ICICIGI': 'ICILOM', 'ICICIPRULI': 'ICIPRU', 'IDEA': 'IDECEL',
    'IDFCFIRSTB': 'IDFBAN', 'IEX': 'INDEN', 'IGL': 'INDGAS', 'INDHOTEL': 'INDHOT',
    'INDIGO': 'INTAVI', 'INDUSINDBK': 'INDBA', 'INDUSTOWER': 'BHAINF', 'IOC': 'INDOIL',
    'IRCTC': 'INDRAI', 'JINDALSTEL': 'JINSP', 'JUBLFOOD': 'JUBFOO', 'KOTAKBANK': 'KOTMAH',
    'LAURUSLABS': 'LAULAB', 'LTF': 'LTFINA', 'M&MFIN': 'MAHFIN', 'MANAPPURAM': 'MANAFI',
    'MARICO': 'MARLIM', 'MFSL': 'MAXFIN', 'MGL': 'MAHGAS', 'MOTHERSON': 'MOTSUM',
    'MPHASIS': 'MPHLIM', 'MUTHOOTFIN': 'MUTFIN', 'NATIONALUM': 'NATALU', 'NAUKRI': 'INFEDG',
    'NESTLEIND': 'NESIND', 'NMDC': 'NATMIN', 'OBEROIRLTY': 'OBEREA', 'OFSS': 'ORAFIN',
    'PERSISTENT': 'PERSYS', 'PETRONET': 'PETLNG', 'PFC': 'POWFIN', 'POLYCAB': 'POLI',
    'POWERGRID': 'POWGRI', 'RBLBANK': 'RBLBAN', 'RECLTD': 'RURELE', 'SBICARD': 'SBICAR',
    'SBILIFE': 'SBILIF', 'SHREECEM': 'SHRCEM', 'SHRIRAMFIN': 'SHRTRA', 'SIEMENS': 'SIEMEN',
    'SYNGENE': 'SYNINT', 'TATACHEM': 'TATCHE', 'TATAMOTORS': 'TATMOT', 'TATAPOWER': 'TATPOW',
    'TATASTEEL': 'TATSTE', 'TECHM': 'TECMAH', 'TVSMOTOR': 'TVSMOT', 'UNITDSPR': 'UNISPI',
    'UPL': 'UNIP', 'VEDL': 'VEDLIM', 'ZYDUSLIFE': 'CADHEA', 'DELTACORP': 'DELCOR',
    'ABBOTINDIA': 'ABBIND', 'ZEEL': 'ZEEENT', 'GMRINFRA': 'GMRINF',
    'COROMANDEL': 'CORINT', 'IPCALAB': 'IPCLAB', 'BALRAMCHIN': 'BALCHI',
    'DEEPAKNTR': 'DEENIT', 'INDIAMART': 'INDMAR', 'NAVINFLUOR': 'NAVFLU', 'ESCORTS': 'ESCORT'
})

# 4. Load targets
files = [
    '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/FINAL_OPTIONS_SYSTEM/options_download_targets_2024_verified.csv',
    '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/FINAL_OPTIONS_SYSTEM/options_download_targets_2025_verified.csv',
    '/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/FINAL_OPTIONS_SYSTEM/options_download_targets_2026_verified.csv'
]
df_list = [pd.read_csv(f) for f in files]
r1r3_targets = pd.concat(df_list, ignore_index=True)
r1r3_targets['buy_date_obj'] = pd.to_datetime(r1r3_targets['buy_date'], errors='coerce')
r1r3_targets = r1r3_targets.dropna(subset=['buy_date_obj']).copy()
r1r3_targets['buy_date_str'] = r1r3_targets['buy_date_obj'].dt.strftime('%Y-%m-%d')
r1r3_targets['sell_date_obj'] = pd.to_datetime(r1r3_targets['sell_date'], errors='coerce')
r1r3_targets['sell_date_str'] = r1r3_targets['sell_date_obj'].dt.strftime('%Y-%m-%d')
r1r3_targets['expiry_date_obj'] = pd.to_datetime(r1r3_targets['expiry_date'], errors='coerce').dt.tz_localize(None).dt.normalize()
r1r3_targets['expiry_date_str'] = r1r3_targets['expiry_date_obj'].dt.strftime('%Y-%m-%d')

date_mappings = {}
for _, row in r1r3_targets.iterrows():
    date_mappings[row['buy_date_str']] = (row['sell_date_str'], row['expiry_date_str'])

# 5. Load inputs
aarang_df = pd.read_csv('/home/ubuntu/aarang/R1_R3_Selections_With_BuyPrices_Full_2024_2026.csv')
aarang_df['buy_date_obj'] = pd.to_datetime(aarang_df['Date'], errors='coerce')
aarang_df = aarang_df.dropna(subset=['buy_date_obj']).copy()
aarang_df['buy_date_str'] = aarang_df['buy_date_obj'].dt.strftime('%Y-%m-%d')

aarang_df = aarang_df[aarang_df['buy_date_obj'].dt.year.isin([2024, 2025, 2026])].copy()
aarang_df['sell_date_str'] = aarang_df['buy_date_str'].map(lambda x: date_mappings[x][0] if x in date_mappings else None)
aarang_df['expiry_date_str'] = aarang_df['buy_date_str'].map(lambda x: date_mappings[x][1] if x in date_mappings else None)
aarang_df = aarang_df.dropna(subset=['sell_date_str', 'expiry_date_str']).copy()
aarang_df['expiry_date_obj'] = pd.to_datetime(aarang_df['expiry_date_str'])

aarang_df['trading_dte'] = aarang_df.apply(lambda row: np.busday_count(row['buy_date_obj'].date(), row['expiry_date_obj'].date()), axis=1)
aarang_df = aarang_df[aarang_df['trading_dte'] > 4].copy()

# Database cache for speed
dates_to_cache = list(set(aarang_df['buy_date_str'].tolist() + aarang_df['sell_date_str'].tolist()))
stocks_to_cache = list(set(aarang_df['Stockname'].str.strip()))
all_stocks_cache = stocks_to_cache + [icici_map.get(s, s) for s in stocks_to_cache]
d_str = "','".join(dates_to_cache)
s_str = "','".join(all_stocks_cache)

q = f"SELECT stock_code, DATE(datetime) as dt, TIME(datetime) as tm, strike_price, close FROM scrapdata_options WHERE stock_code IN ('{s_str}') AND `right`='Put' AND DATE(datetime) IN ('{d_str}')"
df_cache = pd.read_sql(q, db)
df_cache['dt'] = df_cache['dt'].astype(str)
df_cache['tm'] = df_cache['tm'].astype(str).str.replace('0 days ', '')

fast_cache = {}
for row in df_cache.itertuples(index=False):
    fast_cache[(row.stock_code, row.dt, float(row.strike_price), row.tm)] = float(row.close)

def get_tick(stock, dt_str, strike, tm_str):
    icici_stk = icici_map.get(stock, stock)
    val = fast_cache.get((icici_stk, dt_str, strike, tm_str))
    if val is not None: return val
    return fast_cache.get((stock, dt_str, strike, tm_str))

PER_LEG_SLIPPAGE = 0.10
PER_LOT_CHARGES = 300
MIN_PREMIUM = 2.0

# Evaluate OTM-5, OTM-6, and OTM-7 Roll strategies!
for otm_distance, default_premium in [(5, 0.40), (6, 0.25), (7, 0.15)]:
    print(f"\nEvaluating 10:30 AM Decoupled & Roll to OTM-{otm_distance} (Fallback Premium: Rs {default_premium})...")
    
    trades_pnl = []
    wins = 0
    total_trades = 0
    
    for _, row in aarang_df.iterrows():
        stock = row['Stockname'].strip()
        buy_date = row['buy_date_str']
        sell_date = row['sell_date_str']
        price = pd.to_numeric(row['Buy Price'], errors='coerce')
        
        if pd.isna(price) or price < 50: continue
        step = get_true_step(stock, row['buy_date_obj'], price)
        atm = round(price / step) * step
        otm3 = atm - (3 * step)
        
        # Customized sliding window entry scan: First 15:25 to 15:30, then 15:24 down to 15:21
        entry_tm, raw_sell, raw_buy = None, None, None
        search_minutes = list(range(25, 31)) + list(range(24, 20, -1))
        for m in search_minutes:
            tm_str = f"15:{m:02d}:00"
            s = get_tick(stock, buy_date, atm, tm_str)
            b = get_tick(stock, buy_date, otm3, tm_str)
            if s is not None and b is not None:
                raw_sell, raw_buy = s, b
                entry_tm = tm_str
                break
                
        if entry_tm is None: continue
        if raw_sell <= MIN_PREMIUM or raw_buy <= MIN_PREMIUM: continue
        
        lot_size = get_lot(stock, buy_date)
        margin = (atm - otm3) * lot_size
        
        cap_alloc = 400000
        lots = int(cap_alloc / margin) if margin > 0 else 0
        if lots == 0: continue
        
        total_qty = lots * lot_size
        charges = lots * PER_LOT_CHARGES
        
        entry_sell = raw_sell - PER_LEG_SLIPPAGE
        entry_buy = raw_buy + PER_LEG_SLIPPAGE
        
        # Scan exit time of ATM Put Sell
        final_exit_sell = None
        exit_time = None
        exit_status = None
        
        eb_1030 = get_tick(stock, sell_date, otm3, "10:30:00")
        if eb_1030 is None: eb_1030 = get_tick(stock, sell_date, otm3, "09:25:00")
        buy_exit_price = eb_1030 if eb_1030 is not None else entry_buy

        # Determine exact exit minute of the ATM Put Sell
        for h in range(9, 16):
            start_m = 16 if h == 9 else 0
            end_m = 16 if h == 15 else 60
            for m in range(start_m, end_m):
                tm = f"{h:02d}:{m:02d}:00"
                es = get_tick(stock, sell_date, atm, tm)
                
                # Check target profit of combined pair (Put Sell + Put Buy (which squares off at 10:30))
                pnl_curr = ((entry_sell - (es + PER_LEG_SLIPPAGE)) * total_qty) + (((buy_exit_price - PER_LEG_SLIPPAGE) - entry_buy) * total_qty) - charges if es is not None else -999999
                if es is not None and pnl_curr > 0:
                    final_exit_sell = es
                    exit_time = tm
                    exit_status = 'Target Hit'
                    break
            if exit_status: break
            
        if not exit_status:
            exit_time = "15:15:00"
            final_exit_sell = get_tick(stock, sell_date, atm, "15:15:00")
            if final_exit_sell is None:
                final_exit_sell = 0.05 # standard decay fallback
            exit_status = 'End of Day'
            
        # Is this trade held AFTER 10:30 AM?
        exit_h = int(exit_time.split(':')[0])
        exit_m = int(exit_time.split(':')[1])
        total_exit_mins = exit_h * 60 + exit_m
        
        if total_exit_mins <= (10 * 60 + 30):
            # No hold needed! Regular early square-off (both legs closed before 10:30)
            pnl_val = ((entry_sell - (final_exit_sell + PER_LEG_SLIPPAGE)) * total_qty) + (((buy_exit_price - PER_LEG_SLIPPAGE) - entry_buy) * total_qty) - charges
        else:
            # Afternoon Hold is triggered!
            # 1. Close OTM-3 Put Buy at 10:30:00 AM
            otm3_exit_price = buy_exit_price
            
            # 2. Buy new cheap Protection Option (OTM-5, 6, or 7) at 10:30:00 AM
            cheap_strike = atm - (otm_distance * step)
            cheap_entry_price = get_tick(stock, sell_date, cheap_strike, "10:30:00")
            if cheap_entry_price is None:
                cheap_entry_price = default_premium
            cheap_entry_price += PER_LEG_SLIPPAGE
            
            # 3. Square off both the Put Sell and cheap Protection option at the target exit time (or 15:15:00)
            cheap_exit_price = get_tick(stock, sell_date, cheap_strike, exit_time)
            if cheap_exit_price is None:
                # If target was hit, option is near-zero (stock went up). If EOD, option is near-zero.
                cheap_exit_price = 0.05
            cheap_exit_price -= PER_LEG_SLIPPAGE
            if cheap_exit_price < 0.05: cheap_exit_price = 0.05
            
            # PnL Calculation for Hold Trade:
            sell_pnl = (entry_sell - (final_exit_sell + PER_LEG_SLIPPAGE)) * total_qty
            otm3_pnl = (otm3_exit_price - PER_LEG_SLIPPAGE - entry_buy) * total_qty
            cheap_pnl = (cheap_exit_price - cheap_entry_price) * total_qty
            
            # Additional trade charges for rolling to new protective leg
            extra_roll_charges = lots * 150 # buying and selling new leg
            
            pnl_val = sell_pnl + otm3_pnl + cheap_pnl - charges - extra_roll_charges
            
        trades_pnl.append(pnl_val)
        if pnl_val > 0: wins += 1
        total_trades += 1
        
    net_pnl = sum(trades_pnl)
    win_rate = (wins / total_trades) * 100 if total_trades > 0 else 0
    print(f"  Total Trades: {total_trades}")
    print(f"  Win Rate    : {win_rate:.2f}% ({wins} wins)")
    print(f"  Net PnL     : Rs {net_pnl:,.2f}")
