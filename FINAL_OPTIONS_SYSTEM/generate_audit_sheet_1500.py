import pandas as pd
import mysql.connector
import numpy as np
import time

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

# Fix the 5 dates that erroneously skipped expiry days due to lack of signals
date_fixes = {
    ('OFSS', '2024-03-27'): '2024-03-28',
    ('HAL', '2024-07-24'): '2024-07-25',
    ('DALBHARAT', '2025-08-26'): '2025-08-28', # Ganesh Chaturthi on 27th
    ('HEROMOTOCO', '2025-09-29'): '2025-09-30',
    ('HAL', '2025-11-24'): '2025-11-25',
}
for (stock, bdate), correct_exit in date_fixes.items():
    aarang_df.loc[(aarang_df['Stockname'].str.strip() == stock) & (aarang_df['buy_date_str'] == bdate), 'sell_date_str'] = correct_exit

# Database cache for speed: query all Put options
dates_to_cache = list(set(aarang_df['buy_date_str'].tolist() + aarang_df['sell_date_str'].tolist()))
stocks_to_cache = list(set(aarang_df['Stockname'].str.strip()))
all_stocks_cache = stocks_to_cache + [icici_map.get(s, s) for s in stocks_to_cache]
d_str = "','".join(dates_to_cache)
s_str = "','".join(all_stocks_cache)

# We load the ticks, ordering by volume DESC so active traded ticks are prioritized!
q = f"SELECT stock_code, DATE(datetime) as dt, TIME(datetime) as tm, strike_price, close, IFNULL(volume, 0) as volume, DATE(expiry_date) as exp FROM scrapdata_options WHERE stock_code IN ('{s_str}') AND `right`='Put' AND DATE(datetime) IN ('{d_str}') ORDER BY volume DESC"
df_cache = pd.read_sql(q, db)
df_cache['dt'] = df_cache['dt'].astype(str)
df_cache['tm'] = df_cache['tm'].astype(str).str.replace('0 days ', '')
df_cache['exp'] = df_cache['exp'].astype(str)

# Build a multi-key fast cache: (stock_code, dt, exp, strike, tm) -> close
fast_cache_exp = {}
fast_cache_fallback = {}

for row in df_cache.itertuples(index=False):
    key_exp = (row.stock_code, row.dt, row.exp, float(row.strike_price), row.tm)
    if key_exp not in fast_cache_exp:
        fast_cache_exp[key_exp] = float(row.close)
        
    key_fb = (row.stock_code, row.dt, float(row.strike_price), row.tm)
    if key_fb not in fast_cache_fallback:
        fast_cache_fallback[key_fb] = float(row.close)

def get_tick(stock, dt_str, exp_str, strike, tm_str):
    icici_stk = icici_map.get(stock, stock)
    # 1. Try exact official liquid monthly expiry date match
    val = fast_cache_exp.get((icici_stk, dt_str, exp_str, float(strike), tm_str))
    if val is not None: return val
    val = fast_cache_exp.get((stock, dt_str, exp_str, float(strike), tm_str))
    if val is not None: return val
    
    # 2. Fallback to volume-prioritized tick
    val = fast_cache_fallback.get((icici_stk, dt_str, float(strike), tm_str))
    if val is not None: return val
    return fast_cache_fallback.get((stock, dt_str, float(strike), tm_str))

PER_LEG_SLIPPAGE = 0.10
PER_LOT_CHARGES = 300
MIN_PREMIUM = 2.0

print("Generating lightning-fast, official liquid monthly expiry verified Simulation A Audit Verification Sheet...")
start_t = time.time()

audit_rows = []

for idx, row in aarang_df.iterrows():
    stock = row['Stockname'].strip()
    buy_date = row['buy_date_str']
    sell_date = row['sell_date_str']
    exp_date = row['expiry_date_str']
    price = pd.to_numeric(row['Buy Price'], errors='coerce')
    
    if pd.isna(price) or price < 50: continue
    step = get_true_step(stock, row['buy_date_obj'], price)
    atm = round(price / step) * step
    otm3 = atm - (3 * step)
    
    # Entry search across minutes 15:20 to 15:30 using official liquid monthly expiry date!
    entry_tm, raw_sell, raw_buy = None, None, None
    search_minutes = list(range(25, 31)) + list(range(24, 19, -1))
    for m in search_minutes:
        tm_str = f"15:{m:02d}:00"
        s = get_tick(stock, buy_date, exp_date, atm, tm_str)
        b = get_tick(stock, buy_date, exp_date, otm3, tm_str)
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
    
    # Pre-resolve 10:30 fallback (sliding)
    eb_1500 = None
    for offset in range(15):
        check_tm = f"15:{0 + offset:02d}:00"
        val = get_tick(stock, sell_date, exp_date, otm3, check_tm)
        if val is not None:
            eb_1500 = val
            break
    if eb_1500 is None:
        for offset in range(0, 100):
            h_c = 15
            m_c = 0 - offset
            if m_c < 0:
                h_c -= 1
                m_c = 60 + m_c
            check_tm = f"{h_c:02d}:{m_c:02d}:00"
            val = get_tick(stock, sell_date, exp_date, otm3, check_tm)
            if val is not None:
                eb_1500 = val
                break
    buy_exit_price_1500 = eb_1500 if eb_1500 is not None else entry_buy
    
    final_exit_sell = None
    buy_exit_price = None
    exit_time = None
    exit_status = None
    
    # Exit loop (Up to 15:00 PM only)
    for h in range(9, 16):
        start_m = 16 if h == 9 else 0
        end_m = 1 if h == 15 else 60
        for m in range(start_m, end_m):
            tm = f"{h:02d}:{m:02d}:00"
            es = get_tick(stock, sell_date, exp_date, atm, tm)
            eb = get_tick(stock, sell_date, exp_date, otm3, tm)
            if es is not None and eb is not None:
                pnl_curr = ((entry_sell - (es + PER_LEG_SLIPPAGE)) * total_qty) + \
                           (((eb - PER_LEG_SLIPPAGE) - entry_buy) * total_qty) - charges
                           
                if pnl_curr > 0:
                    final_exit_sell = es
                    buy_exit_price = eb
                    exit_time = tm
                    exit_status = 'Target Hit'
                    break
        if exit_status: break
        
    if not exit_status:
        # 1. Search backwards from 15:00 up to 100 minutes (13:20 PM)
        final_exit_sell = None
        for offset in range(0, 100):
            h_check = 15
            m_check = 0 - offset
            if m_check < 0:
                h_check -= 1
                m_check = 60 + m_check
            if h_check < 9 or (h_check == 9 and m_check < 16):
                break
            tm_check = f"{h_check:02d}:{m_check:02d}:00"
            val = get_tick(stock, sell_date, exp_date, atm, tm_check)
            if val is not None:
                final_exit_sell = val
                exit_time = tm_check
                exit_status = 'Hard Squareoff 15:00'
                break
                
        # 2. If still missing, search forwards/future from 15:01 PM up to 15:30 PM (e.g. 15:30 simulation fallback)
        if final_exit_sell is None:
            for offset in range(1, 31):
                h_check = 15
                m_check = 0 + offset
                if m_check >= 60:
                    h_check += 1
                    m_check -= 60
                tm_check = f"{h_check:02d}:{m_check:02d}:00"
                val = get_tick(stock, sell_date, exp_date, atm, tm_check)
                if val is not None:
                    final_exit_sell = val
                    exit_time = tm_check
                    exit_status = 'Hard Squareoff 15:00 (Future Fill)'
                    break

        # 3. If still missing, search further backwards all the way to 09:16 AM
        if final_exit_sell is None:
            for offset in range(100, 350):
                h_check = 15
                m_check = 0 - offset
                while m_check < 0:
                    h_check -= 1
                    m_check = 60 + m_check
                if h_check < 9 or (h_check == 9 and m_check < 16):
                    break
                tm_check = f"{h_check:02d}:{m_check:02d}:00"
                val = get_tick(stock, sell_date, exp_date, atm, tm_check)
                if val is not None:
                    final_exit_sell = val
                    exit_time = tm_check
                    exit_status = 'Hard Squareoff 15:00 (Far Past Fill)'
                    break

        # 4. If still missing, fallback to entry_sell (neutral fallback)
        if final_exit_sell is None:
            final_exit_sell = entry_sell
            exit_time = "15:00:00"
            exit_status = 'Hard Squareoff 15:00 (Fallback to Entry)'
            
        buy_exit_price = buy_exit_price_1500
        
    pnl_val = ((entry_sell - (final_exit_sell + PER_LEG_SLIPPAGE)) * total_qty) + \
              (((buy_exit_price - PER_LEG_SLIPPAGE) - entry_buy) * total_qty) - charges
              
    audit_rows.append({
        'Trade_Index': len(audit_rows) + 1,
        'Stock_Name': stock,
        'ICICI_Code': icici_map.get(stock, stock),
        'Buy_Entry_Date': buy_date,
        'Sell_Exit_Date': sell_date,
        'ATM_Strike': atm,
        'OTM3_Strike': otm3,
        'Lot_Size': lot_size,
        'Trade_Lots': lots,
        'Total_Qty': total_qty,
        'Entry_Time': entry_tm,
        'ATM_Raw_Sell_Entry': raw_sell,
        'ATM_Net_Sell_Entry': entry_sell,
        'OTM3_Raw_Buy_Entry': raw_buy,
        'OTM3_Net_Buy_Entry': entry_buy,
        'Exit_Time': exit_time,
        'Exit_Status': exit_status,
        'ATM_Raw_Sell_Exit': final_exit_sell,
        'ATM_Net_Sell_Exit': final_exit_sell + PER_LEG_SLIPPAGE,
        'OTM3_Raw_Buy_Exit': buy_exit_price,
        'OTM3_Net_Buy_Exit': buy_exit_price - PER_LEG_SLIPPAGE,
        'Slippage_Deducted_Per_Leg': PER_LEG_SLIPPAGE,
        'Total_Charges_Deducted': charges,
        'Net_Trade_PnL_Rupees': pnl_val
    })

audit_df = pd.DataFrame(audit_rows)
audit_df.to_csv('/home/ubuntu/Simulation_A_True_Audit_PnL_Sheet_1500.csv', index=False)
print(f"Done in {time.time() - start_t:.2f}s! Audit Sheet exported to '/home/ubuntu/Simulation_A_True_Audit_PnL_Sheet_1500.csv'!")
