import os, sys, warnings
import pandas as pd
import numpy as np
from sklearn.linear_model import Ridge, RidgeCV
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings('ignore')

# Resolve directory
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))

# ─────────────────────────────────────────────────────────────────────────────
# PATHS & CONFIG
# ─────────────────────────────────────────────────────────────────────────────
if os.path.exists(os.path.join(_THIS_DIR, 'data')):
    DATA_DIR   = os.path.join(_THIS_DIR, 'data')
else:
    DATA_DIR   = os.path.abspath(os.path.join(_THIS_DIR, '..', 'data'))
PNL_CSV    = os.path.join(DATA_DIR, 'markets_pnl0325.csv')
START_DATE = '2015-01-01'
FILTER_THRESHOLD = -500

# Heuristic Strategy Counts
TOP_N_MOMENTUM    = 10
TOP_N_CONTRARIAN  = 25
TOP_N_UNDERDOG    = 10
TOP_N_ASYMMETRIC  = 10
TOP_N_SHARPE      = 10
TOP_N_EV          = 10
TOP_N_RECENCY     = 10
TOP_N_PF          = 10
TOP_N_CONVICTION  = 10
TOP_N_FADE        = 10
TOP_N_HOTSTREAK   = 10
TOP_N_DEFENSIVE   = 15

# ─────────────────────────────────────────────────────────────────────────────
# DYNAMIC THRESHOLD CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────
DYN_LOSS_DAYS_TRIGGER  = 3
DYN_WIN_DAYS_TRIGGER   = 5
DYN_RAISE_STEP         = 0.30
DYN_LOWER_STEP         = 0.10
DYN_MIN_FACTOR         = 0.60
DYN_MAX_FACTOR         = 2.00
DYN_REVERT_RATE        = 0.08

# ─────────────────────────────────────────────────────────────────────────────
# SECTOR CONCENTRATION CAPPING CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────
DYN_SECTOR_CAP         = int(os.getenv('DYN_SECTOR_CAP', '9999'))  # Maximum trades per sector per day

# ─────────────────────────────────────────────────────────────────────────────
# ADVANCED QUANT UPGRADES CONFIGURATIONS (OPTIONS 1, 2 & 3)
# ─────────────────────────────────────────────────────────────────────────────
ENABLE_OPTION_1        = os.getenv('ENABLE_OPTION_1', 'False').lower() == 'true'
EMERGENCY_LOSS_LIMIT   = float(os.getenv('EMERGENCY_LOSS_LIMIT', '-10000.0'))
EMERGENCY_RAISE_STEP   = float(os.getenv('EMERGENCY_RAISE_STEP', '0.50'))

ENABLE_OPTION_2        = os.getenv('ENABLE_OPTION_2', 'True').lower() == 'true'
ENABLE_OPTION_3        = os.getenv('ENABLE_OPTION_3', 'False').lower() == 'true'



def get_stock_sector(symbol):
    """
    Returns the economic sector for a given Indian stock symbol.
    Defaults to 'Other' if not in the comprehensive mapping.
    """
    sector_mapping = {
        'AXISBANK': 'Banking', 'AUBANK': 'Banking', 'BANDHANBNK': 'Banking', 'BANKBARODA': 'Banking', 
        'CANBK': 'Banking', 'CUB': 'Banking', 'FEDERALBNK': 'Banking', 'HDFCBANK': 'Banking', 
        'ICICIBANK': 'Banking', 'IDFCFIRSTB': 'Banking', 'KOTAKBANK': 'Banking', 'PNB': 'Banking', 
        'RBLBANK': 'Banking', 'SBIN': 'Banking', 'INDUSINDBK': 'Banking',
        
        'ABCAPITAL': 'Financial Services', 'BAJAJFINSV': 'Financial Services', 'BAJFINANCE': 'Financial Services', 
        'CHOLAFIN': 'Financial Services', 'HDFCAMC': 'Financial Services', 'HDFCLIFE': 'Financial Services', 
        'ICICIGI': 'Financial Services', 'ICICIPRULI': 'Financial Services', 'IDFC': 'Financial Services', 
        'LICHSGFIN': 'Financial Services', 'LTF': 'Financial Services', 'M&MFIN': 'Financial Services', 
        'MANAPPURAM': 'Financial Services', 'MUTHOOTFIN': 'Financial Services', 'PEL': 'Financial Services', 
        'PFC': 'Financial Services', 'RECLTD': 'Financial Services', 'SBICARD': 'Financial Services', 
        'SBILIFE': 'Financial Services', 'SHRIRAMFIN': 'Financial Services', 'MCX': 'Financial Services', 
        'CANFINHOME': 'Financial Services', 'IEX': 'Financial Services',
        
        'BSOFT': 'IT', 'COFORGE': 'IT', 'HCLTECH': 'IT', 'INFY': 'IT', 'LTIM': 'IT', 'LTTS': 'IT', 
        'MPHASIS': 'IT', 'OFSS': 'IT', 'PERSISTENT': 'IT', 'TCS': 'IT', 'TECHM': 'IT', 'WIPRO': 'IT', 
        'INDIAMART': 'IT', 'NAUKRI': 'IT',
        
        'APOLLOTYRE': 'Auto Ancillaries', 'BALKRISIND': 'Auto Ancillaries', 'BOSCHLTD': 'Auto Ancillaries', 
        'EXIDEIND': 'Auto Ancillaries', 'MOTHERSON': 'Auto Ancillaries', 'MRF': 'Auto Ancillaries', 
        'BHARATFORG': 'Auto Ancillaries',
        
        'ASHOKLEY': 'Automobile', 'EICHERMOT': 'Automobile', 'ESCORTS': 'Automobile', 'HEROMOTOCO': 'Automobile', 
        'M&M': 'Automobile', 'MARUTI': 'Automobile', 'TATAMOTORS': 'Automobile', 'TVSMOTOR': 'Automobile',
        
        'ABBOTINDIA': 'Pharma & Healthcare', 'ALKEM': 'Pharma & Healthcare', 'APOLLOHOSP': 'Pharma & Healthcare', 
        'AUROPHARMA': 'Pharma & Healthcare', 'BIOCON': 'Pharma & Healthcare', 'CIPLA': 'Pharma & Healthcare', 
        'DIVISLAB': 'Pharma & Healthcare', 'DRREDDY': 'Pharma & Healthcare', 'GLENMARK': 'Pharma & Healthcare', 
        'GRANULES': 'Pharma & Healthcare', 'IPCALAB': 'Pharma & Healthcare', 'LALPATHLAB': 'Pharma & Healthcare', 
        'LAURUSLABS': 'Pharma & Healthcare', 'LUPIN': 'Pharma & Healthcare', 'METROPOLIS': 'Pharma & Healthcare', 
        'SUNPHARMA': 'Pharma & Healthcare', 'SYNGENE': 'Pharma & Healthcare', 'TORNTPHARM': 'Pharma & Healthcare', 
        'ZYDUSLIFE': 'Pharma & Healthcare',
        
        'BPCL': 'Oil & Gas', 'GAIL': 'Oil & Gas', 'HINDPETRO': 'Oil & Gas', 'IOC': 'Oil & Gas', 
        'MGL': 'Oil & Gas', 'IGL': 'Oil & Gas', 'ONGC': 'Oil & Gas', 'PETRONET': 'Oil & Gas', 'RELIANCE': 'Oil & Gas',
        
        'COALINDIA': 'Power & Utilities', 'NTPC': 'Power & Utilities', 'POWERGRID': 'Power & Utilities', 
        'TATAPOWER': 'Power & Utilities', 'GUJGASLTD': 'Power & Utilities',
        
        'HINDALCO': 'Metals & Mining', 'HINDCOPPER': 'Metals & Mining', 'JINDALSTEL': 'Metals & Mining', 
        'NATIONALUM': 'Metals & Mining', 'NMDC': 'Metals & Mining', 'SAIL': 'Metals & Mining', 
        'TATASTEEL': 'Metals & Mining', 'VEDL': 'Metals & Mining',
        
        'ASIANPAINT': 'FMCG & Consumer Goods', 'BERGEPAINT': 'FMCG & Consumer Goods', 'BRITANNIA': 'FMCG & Consumer Goods', 
        'COLPAL': 'FMCG & Consumer Goods', 'DABUR': 'FMCG & Consumer Goods', 'GODREJCP': 'FMCG & Consumer Goods', 
        'HINDUNILVR': 'FMCG & Consumer Goods', 'ITC': 'FMCG & Consumer Goods', 'MARICO': 'FMCG & Consumer Goods', 
        'NESTLEIND': 'FMCG & Consumer Goods', 'TATACONSUM': 'FMCG & Consumer Goods', 'UNITDSPR': 'FMCG & Consumer Goods', 
        'UBL': 'FMCG & Consumer Goods', 'TITAN': 'FMCG & Consumer Goods',
        
        'ACC': 'Cement & Construction', 'AMBUJACEM': 'Cement & Construction', 'DALBHARAT': 'Cement & Construction', 
        'JKCEMENT': 'Cement & Construction', 'RAMCOMCEM': 'Cement & Construction', 'SHREECEM': 'Cement & Construction', 
        'ULTRACEMCO': 'Cement & Construction', 'INDIACEM': 'Cement & Construction', 'RAMCOCEM': 'Cement & Construction',
        
        'ABB': 'Capital Goods & Infrastructure', 'BEL': 'Capital Goods & Infrastructure', 'BHEL': 'Capital Goods & Infrastructure', 
        'CONCOR': 'Capital Goods & Infrastructure', 'CUMMINSIND': 'Capital Goods & Infrastructure', 'GMRINFRA': 'Capital Goods & Infrastructure', 
        'HAL': 'Capital Goods & Infrastructure', 'HAVELLS': 'Capital Goods & Infrastructure', 'LT': 'Capital Goods & Infrastructure', 
        'POLYCAB': 'Capital Goods & Infrastructure', 'SIEMENS': 'Capital Goods & Infrastructure', 'VOLTAS': 'Capital Goods & Infrastructure', 
        'ASTRAL': 'Capital Goods & Infrastructure', 'CROMPTON': 'Capital Goods & Infrastructure', 'ADANIPORTS': 'Capital Goods & Infrastructure',
        
        'AARTIIND': 'Chemicals & Fertilizers', 'ATUL': 'Chemicals & Fertilizers', 'BALRAMCHIN': 'Chemicals & Fertilizers', 
        'CHAMBLFERT': 'Chemicals & Fertilizers', 'COROMANDEL': 'Chemicals & Fertilizers', 'DEEPAKNTR': 'Chemicals & Fertilizers', 
        'GNFC': 'Chemicals & Fertilizers', 'NAVINFLUOR': 'Chemicals & Fertilizers', 'PIDILITIND': 'Chemicals & Fertilizers', 
        'PIIND': 'Chemicals & Fertilizers', 'SRF': 'Chemicals & Fertilizers', 'TATACHEM': 'Chemicals & Fertilizers', 
        'UPL': 'Chemicals & Fertilizers',
        
        'DLF': 'Real Estate', 'GODREJPROP': 'Real Estate', 'OBEROIRLTY': 'Real Estate',
        
        'BHARTIARTL': 'Telecom', 'IDEA': 'Telecom', 'INDUSTOWER': 'Telecom', 'TATACOMM': 'Telecom',
        
        'ABFRL': 'Retail & Services', 'BATAINDIA': 'Retail & Services', 'DELTACORP': 'Retail & Services', 
        'INDHOTEL': 'Retail & Services', 'INDIGO': 'Retail & Services', 'IRCTC': 'Retail & Services', 
        'JUBLFOOD': 'Retail & Services', 'PAGEIND': 'Retail & Services', 'PVRINOX': 'Retail & Services', 
        'SUNTV': 'Retail & Services', 'TRENT': 'Retail & Services', 'ZEEL': 'Retail & Services',
        
        'ADANIENT': 'Conglomerate', 'GRASIM': 'Conglomerate'
    }
    # Clean up standard ticker suffixes if any
    clean_sym = str(symbol).split('-')[0].strip().upper()
    return sector_mapping.get(clean_sym, sector_mapping.get(str(symbol).strip().upper(), 'Other'))

# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# NSE MONTHLY EXPIRY DATES
# ─────────────────────────────────────────────────────────────────────────────
_EXPIRY_STRINGS = [
    "27 Jan 2011","24 Feb 2011","31 Mar 2011","28 Apr 2011","26 May 2011","30 Jun 2011",
    "28 Jul 2011","25 Aug 2011","29 Sep 2011","25 Oct 2011","24 Nov 2011","29 Dec 2011",
    "25 Jan 2012","23 Feb 2012","29 Mar 2012","26 Apr 2012","31 May 2012","28 Jun 2012",
    "26 Jul 2012","30 Aug 2012","27 Sep 2012","25 Oct 2012","29 Nov 2012","27 Dec 2012",
    "31 Jan 2013","28 Feb 2013","28 Mar 2013","25 Apr 2013","30 May 2013","27 Jun 2013",
    "25 jul 2013","29 Aug 2013","26 Sep 2013","31 Oct 2013","28 Nov 2013","26 Dec 2013",
    "30 Jan 2014","26 Feb 2014","27 Mar 2014","24 Apr 2014","29 May 2014","26 Jun 2014",
    "31 Jul 2014","28 Aug 2014","25 Sep 2014","30 Oct 2014","27 Nov 2014","24 Dec 2014",
    "29 Jan 2015","26 Feb 2015","26 Mar 2015","30 Apr 2015","28 May 2015","25 Jun 2015",
    "30 Jul 2015","27 Aug 2015","24 Sep 2015","29 Oct 2015","26 Nov 2015","31 Dec 2015",
    "28 Jan 2016","25 Feb 2016","31 Mar 2016","28 Apr 2016","26 May 2016","30 Jun 2016",
    "28 Jul 2016","25 Aug 2016","29 Sep 2016","27 Oct 2016","24 Nov 2016","29 Dec 2016",
    "25 Jan 2017","23 Feb 2017","30 Mar 2017","27 Apr 2017","25 May 2017","29 Jun 2017",
    "27 Jul 2017","31 Aug 2017","28 Sep 2017","26 Oct 2017","30 Nov 2017","28 Dec 2017",
    "25 Jan 2018","22 Feb 2018","28 Mar 2018","26 Apr 2018","31 May 2018","28 Jun 2018",
    "26 Jul 2018","30 Aug 2018","27 Sep 2018","25 Oct 2018","29 Nov 2018","27 Dec 2018",
    "31 Jan 2019","28 Feb 2019","28 Mar 2019","25 Apr 2019","30 May 2019","27 Jun 2019",
    "25 Jul 2019","29 Aug 2019","26 Sep 2019","24 Oct 2019","28 Nov 2019","26 Dec 2019",
    "30 Jan 2020","27 Feb 2020","26 Mar 2020","30 Apr 2020","28 May 2020","25 Jun 2020",
    "30 Jul 2020","27 Aug 2020","24 Sep 2020","29 Oct 2020","26 Nov 2020","31 Dec 2020",
    "28 Jan 2021","25 Feb 2021","25 Mar 2021","29 Apr 2021","27 May 2021","24 Jun 2021",
    "29 Jul 2021","26 Aug 2021","30 Sep 2021","28 Oct 2021","25 Nov 2021","30 Dec 2021",
    "27 Jan 2022","24 Feb 2022","31 Mar 2022","28 Apr 2022","26 May 2022","30 Jun 2022",
    "28 Jul 2022","25 Aug 2022","29 Sep 2022","27 Oct 2022","24 Nov 2022","29 Dec 2022",
    "25 Jan 2023","23 Feb 2023","29 Mar 2023","20 Apr 2023","25 May 2023","22 Jun 2023",
    "27 Jul 2023","31 Aug 2023","28 Sep 2023","26 Oct 2023","30 Nov 2023","28 Dec 2023",
    "25 Jan 2024","29 Feb 2024","28 Mar 2024","25 Apr 2024","30 May 2024","27 Jun 2024",
    "25 Jul 2024","29 Aug 2024","26 Sep 2024","31 Oct 2024","28 Nov 2024","26 Dec 2024",
    "30 Jan 2025","27 Feb 2025","27 Mar 2025","24 Apr 2025","29 May 2025","26 Jun 2025",
    "31 Jul 2025","28 Aug 2025","25 Sep 2025","30 Oct 2025","27 Nov 2025","31 Dec 2025",
    "27 Jan 2026","24 Feb 2026","25 Mar 2026","28 Apr 2026","26 May 2026","30 Jun 2026",
    "28 Jul 2026","25 Aug 2026","29 Sep 2026","26 Oct 2026","24 Nov 2026","29 Dec 2026",
]
EXPIRY_DATES = sorted(pd.to_datetime(_EXPIRY_STRINGS, format='mixed'))

# Base feature columns for Ridge Regression
BASE_FEATURE_COLS = [
    'hist_count', 'success_pct', 'avg_pnl', 'std_pnl',
    'rolling_std_30',
    'sharpe_score', 'pf_score', 'conviction_score',
    'recent_wr', 'recent_avg', 'recency_edge',
    'down_wr', 'down_avg',
    'micro_recent_avg', 'micro_recent_wr',
    'short_recent_avg', 'short_recent_wr',
    'volatility_ratio', 'current_streak', 'equity_drawdown_pct',
    # External Live Intraday Features (No Look Ahead)
    'intraday_return', 'intraday_rsi_9', 'intraday_macd',
    'intraday_bb_pct_b', 'first_tick_to_1519_pct', '1450_to_1519_pct', 'Gap_Pct',
    # Gap CSV features — all known before 3:20 PM trade (clean, no look-ahead)
    'prev_close_price',    # yesterday's close — absolute price level context
    'daily_open',          # today's market open — known at 9:15 AM
    'volume_change_pct',   # today vs prev day volume — participation/conviction signal
]

# ─────────────────────────────────────────────────────────────────────────────
# UTILITIES
# ─────────────────────────────────────────────────────────────────────────────
def log(msg: str):
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode('ascii', errors='replace').decode('ascii'))

def days_to_next_expiry(dates_series: pd.Series) -> pd.Series:
    expiry_arr = np.array([e.value for e in EXPIRY_DATES], dtype='int64')
    date_vals  = dates_series.values.astype('int64')
    idx = np.searchsorted(expiry_arr, date_vals)
    idx = np.clip(idx, 0, len(EXPIRY_DATES) - 1)
    next_exp = pd.DatetimeIndex([EXPIRY_DATES[i] for i in idx])
    return (next_exp - pd.DatetimeIndex(dates_series.values)).days

# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — LOAD DATA
# ─────────────────────────────────────────────────────────────────────────────
def load_pnl() -> pd.DataFrame:
    log("=" * 70)
    log("STEP 1: Loading PnL data …")
    df = pd.read_csv(PNL_CSV)
    df.columns = df.columns.str.strip().str.lower()
    date_col = next((c for c in df.columns if 'date' in c or 'time' in c), df.columns[0])
    df['dt_parsed'] = pd.to_datetime(df[date_col], dayfirst=True, format='mixed', errors='coerce')
    df = df.dropna(subset=['dt_parsed']).copy()
    df['pnl'] = pd.to_numeric(df['pnl'], errors='coerce')
    df = df.dropna(subset=['pnl']).copy()
    df = df[df['dt_parsed'] >= pd.to_datetime(START_DATE)].copy()
    df = df.sort_values(['stockname', 'dt_parsed']).reset_index(drop=True)
    df = df.drop_duplicates(subset=['dt_parsed', 'stockname'], keep='last').copy()

    df['day']       = df['dt_parsed'].dt.day_name()
    df['year']      = df['dt_parsed'].dt.year
    df['month_idx'] = df['dt_parsed'].dt.to_period('M').astype(str)
    df['week_idx']  = df['dt_parsed'].dt.to_period('W').astype(str)
    df['quarter']   = df['dt_parsed'].dt.to_period('Q').astype(str)
    
    f11_path = os.path.join(DATA_DIR, "f11_intraday_features_all.csv.gz")
    if not os.path.exists(f11_path):
        f11_path = os.path.join(DATA_DIR, "f11_intraday_features_all.csv")
    if os.path.exists(f11_path):
        log(f"  Loading F11 intraday features from {f11_path}...")
        f11 = pd.read_csv(f11_path)
        f11['dt_parsed'] = pd.to_datetime(f11['Date'], format='mixed', dayfirst=True)
        f11 = f11.rename(columns={'Stock': 'stockname'})
        f11 = f11.drop_duplicates(subset=['dt_parsed', 'stockname'], keep='last')

        
        # Rename columns dynamically if they end with _pct
        rename_dict = {}
        for col in f11.columns:
            if col.startswith('first_tick_to_15') and col.endswith('_pct'):
                rename_dict[col] = 'first_tick_to_1519_pct'
            if col.startswith('1450_to_15') and col.endswith('_pct'):
                rename_dict[col] = '1450_to_1519_pct'
        if rename_dict:
            f11 = f11.rename(columns=rename_dict)
            
        f11_cols = ['dt_parsed', 'stockname', 'intraday_return', 'intraday_rsi_9', 'intraday_macd', 'intraday_bb_pct_b', 'first_tick_to_1519_pct', '1450_to_1519_pct']
        for c in f11_cols[2:]:
            f11[c] = pd.to_numeric(f11[c], errors='coerce')
        df = df.merge(f11[f11_cols], on=['dt_parsed', 'stockname'], how='left')

    # Load Gap Features (ICICI-sourced CSV)
    gap_file = os.getenv('GAP_FEATURES_PATH', 'yahoo_finance_all_stocks_2015_2026_gap_features.csv')
    if os.path.isabs(gap_file):
        gap_path = gap_file
    else:
        gap_path = os.path.join(DATA_DIR, gap_file)
    if os.path.exists(gap_path):
        log(f"  Loading Gap features from {gap_path}...")
        gap = pd.read_csv(gap_path)
        gap['dt_parsed'] = pd.to_datetime(gap['Date'], format='mixed', dayfirst=True)
        gap = gap.rename(columns={'Stock': 'stockname'})
        gap = gap.drop_duplicates(subset=['dt_parsed', 'stockname'], keep='last')

        for c in ['Gap_Pct', 'Open', 'Prev_Close', 'Volume_Change_Pct']:
            if c in gap.columns:
                gap[c] = pd.to_numeric(gap[c], errors='coerce')
        gap = gap.rename(columns={
            'Open':               'daily_open',
            'Prev_Close':         'prev_close_price',
            'Volume_Change_Pct':  'volume_change_pct',
        })
        available_gap_cols = ['dt_parsed', 'stockname', 'Gap_Pct']
        for c in ['daily_open', 'prev_close_price', 'volume_change_pct']:
            if c in gap.columns:
                available_gap_cols.append(c)
        df = df.merge(gap[available_gap_cols], on=['dt_parsed', 'stockname'], how='left')
        
    log(f"  Loaded {len(df):,} rows | {df['dt_parsed'].min().date()} → {df['dt_parsed'].max().date()}")
    return df

# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — BUILD FEATURES (expanding, no look-ahead)
# ─────────────────────────────────────────────────────────────────────────────
def build_features(df: pd.DataFrame) -> pd.DataFrame:
    log("\nSTEP 2: Building expanding historical features (look-ahead free) …")
    df = df.sort_values(['stockname', 'dt_parsed']).reset_index(drop=True).copy()
    
    # Fill NaNs for all external features
    ext_cols = [
        'intraday_return', 'intraday_rsi_9', 'intraday_macd',
        'intraday_bb_pct_b', 'first_tick_to_1519_pct', '1450_to_1519_pct',
        'Gap_Pct', 'daily_open', 'prev_close_price', 'volume_change_pct',
    ]
    for c in ext_cols:
        if c in df.columns:
            fill_val = 50.0 if 'rsi' in c else 0.0
            df[c] = df[c].fillna(fill_val)
            
    grp_keys = [df['stockname'], df['day']]

    def safe_expand(series, metric='mean'):
        is_null = series.isna()
        if is_null.any():
            non_null_val = series.fillna(0.0)
            non_null_indicator = (~is_null).astype(float)
            g_val = non_null_val.groupby(grp_keys)
            g_ind = non_null_indicator.groupby(grp_keys)
            cum_count = g_ind.cumsum()
            
            if metric == 'count':
                return cum_count.groupby(grp_keys).shift(1)
            elif metric == 'sum':
                cum_sum = g_val.cumsum()
                return cum_sum.groupby(grp_keys).shift(1)
            elif metric == 'mean':
                cum_sum = g_val.cumsum()
                running_mean = np.where(cum_count == 0, np.nan, cum_sum / cum_count)
                running_mean = pd.Series(running_mean, index=series.index)
                return running_mean.groupby(grp_keys).shift(1)
            elif metric == 'std':
                cum_sum = g_val.cumsum()
                cum_sum_sq = (non_null_val ** 2).groupby(grp_keys).cumsum()
                var_val = (cum_sum_sq - (cum_sum ** 2) / cum_count) / (cum_count - 1)
                var_val = pd.Series(np.where(cum_count <= 1, np.nan, var_val), index=series.index)
                std_val = np.sqrt(var_val.clip(lower=0))
                return std_val.groupby(grp_keys).shift(1)
        else:
            g = series.groupby(grp_keys)
            cum_count = g.cumcount() + 1
            if metric == 'count':
                return cum_count.groupby(grp_keys).shift(1)
            elif metric == 'sum':
                cum_sum = g.cumsum()
                return cum_sum.groupby(grp_keys).shift(1)
            elif metric == 'mean':
                cum_sum = g.cumsum()
                return (cum_sum / cum_count).groupby(grp_keys).shift(1)
            elif metric == 'std':
                cum_sum = g.cumsum()
                cum_sum_sq = (series ** 2).groupby(grp_keys).cumsum()
                var_val = (cum_sum_sq - (cum_sum ** 2) / cum_count) / (cum_count - 1)
                var_val = pd.Series(np.where(cum_count <= 1, np.nan, var_val), index=series.index)
                std_val = np.sqrt(var_val.clip(lower=0))
                return std_val.groupby(grp_keys).shift(1)

    is_win  = (df['pnl'] > 0).astype(float)
    pnl_win = df['pnl'].clip(lower=0)
    pnl_los = df['pnl'].clip(upper=0).abs()

    df['hist_count']   = safe_expand(df['pnl'], 'count').astype(float)
    df['avg_pnl']      = safe_expand(df['pnl'], 'mean')
    df['std_pnl']      = safe_expand(df['pnl'], 'std')
    df['success_pct']  = safe_expand(is_win, 'mean') * 100
    win_sum            = safe_expand(pnl_win, 'sum')
    loss_sum           = safe_expand(pnl_los, 'sum')

    df['sharpe_score']    = df['avg_pnl'] / (df['std_pnl'] + 1.0)
    df['pf_score']        = win_sum / (loss_sum + 1.0)
    df['conviction_score']= df['success_pct'] * np.log1p(df['hist_count'])

    roll_std = (df.groupby('stockname')['pnl']
                  .rolling(window=30, min_periods=5).std()
                  .reset_index(level=0, drop=True)
                  .groupby(df['stockname']).shift(1))
    df['rolling_std_30'] = roll_std.fillna(df['std_pnl'])

    g_roll = df['pnl'].groupby(grp_keys)
    df['recent_avg'] = (g_roll.rolling(window=20, min_periods=3).mean()
                               .reset_index(level=[0, 1], drop=True)
                               .reindex(df.index)
                               .groupby(grp_keys).shift(1))
    df['recent_wr']  = (g_roll.rolling(window=20, min_periods=3)
                               .apply(lambda x: (x > 0).mean() * 100, raw=True)
                               .reset_index(level=[0, 1], drop=True)
                               .reindex(df.index)
                               .groupby(grp_keys).shift(1))
    df['recency_edge'] = df['recent_wr'] - df['success_pct']

    daily_mkt = df.groupby('dt_parsed', as_index=False)['pnl'].mean()
    daily_mkt = daily_mkt.sort_values('dt_parsed').reset_index(drop=True)
    daily_mkt['mkt_rolling'] = daily_mkt['pnl'].rolling(window=30, min_periods=5).mean()
    daily_mkt['is_down']     = (daily_mkt['mkt_rolling'] < 0).astype(float).shift(1)
    df = df.merge(daily_mkt[['dt_parsed', 'is_down']], on='dt_parsed', how='left')

    down_pnl = df['pnl'].where(df['is_down'] == 1, np.nan)
    down_win = is_win.where(df['is_down'] == 1, np.nan)
    df['down_avg'] = safe_expand(down_pnl, 'mean').fillna(0)
    df['down_wr']  = (safe_expand(down_win, 'mean') * 100).fillna(50)
    df.drop(columns=['is_down'], inplace=True)

    df['days_to_expiry'] = days_to_next_expiry(df['dt_parsed'])

    # === NEW FEATURES (ALL DAYS, FAST REACTING) ===
    g_stock = df.groupby('stockname')['pnl']
    
    # 1. Micro-Recency (5 trades)
    df['micro_recent_avg'] = (g_stock.rolling(window=5, min_periods=2).mean()
                               .reset_index(level=0, drop=True)
                               .groupby(df['stockname']).shift(1))
    df['micro_recent_wr']  = (g_stock.rolling(window=5, min_periods=2)
                               .apply(lambda x: (x > 0).mean() * 100, raw=True)
                               .reset_index(level=0, drop=True)
                               .groupby(df['stockname']).shift(1))
                               
    # 2. Short-Recency (10 trades)
    df['short_recent_avg'] = (g_stock.rolling(window=10, min_periods=3).mean()
                               .reset_index(level=0, drop=True)
                               .groupby(df['stockname']).shift(1))
    df['short_recent_wr']  = (g_stock.rolling(window=10, min_periods=3)
                               .apply(lambda x: (x > 0).mean() * 100, raw=True)
                               .reset_index(level=0, drop=True)
                               .groupby(df['stockname']).shift(1))
                               
    # 3. Volatility Ratio
    df['volatility_ratio'] = df['rolling_std_30'] / (df['std_pnl'] + 1.0)
    
    # 4. Streaks
    def get_streak(s):
        s_sign = np.sign(s).replace(0, -1)
        return s_sign.groupby((s_sign != s_sign.shift()).cumsum()).cumsum()
        
    df['current_streak'] = (g_stock.apply(get_streak)
                             .reset_index(level=0, drop=True)
                             .groupby(df['stockname']).shift(1))
                             
    # 5. Equity Drawdown Pct
    cum_pnl = g_stock.cumsum()
    cum_pnl_shifted = cum_pnl.groupby(df['stockname']).shift(1).fillna(0)
    roll_max = cum_pnl_shifted.groupby(df['stockname']).cummax()
    df['equity_drawdown_pct'] = ((roll_max - cum_pnl_shifted) / (roll_max.abs() + 1.0)) * 100.0

    for c in BASE_FEATURE_COLS:
        df[c] = df[c].replace([np.inf, -np.inf], np.nan)

    # df = df.dropna(subset=BASE_FEATURE_COLS).reset_index(drop=True) # MOVED TO WALK-FORWARD TO PREVENT LOOK-AHEAD
    log(f"  Feature matrix size (incl NaNs): {len(df):,} rows")
    return df

# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — HEURISTIC CANDIDATE SELECTION
# ─────────────────────────────────────────────────────────────────────────────
def _build_stats_table(train_df: pd.DataFrame, sc: str, min_count: int = 5) -> pd.DataFrame:
    grp = train_df.groupby([sc, 'day'])['pnl']
    cnt = grp.count()
    valid = cnt[cnt >= min_count].index
    if len(valid) == 0:
        return pd.DataFrame()

    sub = train_df.set_index([sc, 'day'])
    sub = sub[sub.index.isin(valid)].reset_index()

    st = sub.groupby([sc, 'day'])['pnl'].agg(
        S=lambda x: (x > 0).mean() * 100,
        A='mean',
        V='std',
        W=lambda x: x[x > 0].sum(),
        L=lambda x: x[x < 0].sum(),
        N='count',
    ).reset_index()
    st.columns = ['Stock', 'Day', 'Success_%', 'Avg_PnL', 'Std_PnL',
                  'Win_Sum', 'Loss_Sum', 'Trade_Count']
    st['Std_PnL'] = st['Std_PnL'].fillna(1.0)
    st['Sharpe_Score']    = st['Avg_PnL'] / (st['Std_PnL'] + 1)
    st['PF_Score']        = st['Win_Sum'] / (st['Loss_Sum'].abs() + 1)
    st['Conviction_Score']= st['Success_%'] * np.log1p(st['Trade_Count'])
    return st

def _add_recency(st: pd.DataFrame, train_df: pd.DataFrame, sc: str, rec_periods: int = 3) -> pd.DataFrame:
    all_months  = sorted(train_df['month_idx'].unique())
    recent_months = set(all_months[-rec_periods:]) if len(all_months) >= rec_periods else set(all_months)
    rec = train_df[train_df['month_idx'].isin(recent_months)]
    rec_st = (rec.groupby([sc, 'day'])['pnl']
                 .apply(lambda x: (x > 0).mean() * 100)
                 .reset_index())
    rec_st.columns = ['Stock', 'Day', 'Recent_WR']
    st = st.merge(rec_st, on=['Stock', 'Day'], how='left')
    st['Recent_WR']   = st['Recent_WR'].fillna(st['Success_%'])
    st['Recency_Edge'] = st['Recent_WR'] - st['Success_%']
    return st

def _add_down_market(st: pd.DataFrame, train_df: pd.DataFrame, sc: str) -> pd.DataFrame:
    mkt_mo   = train_df.groupby('month_idx')['pnl'].mean()
    down_mo  = set(mkt_mo[mkt_mo < 0].index)
    if down_mo:
        dn = train_df[train_df['month_idx'].isin(down_mo)]
        dg = (dn.groupby([sc, 'day'])['pnl']
                .agg(DWR=lambda x: (x > 0).mean() * 100, DAVG='mean')
                .reset_index())
        dg.columns = ['Stock', 'Day', 'Down_WR', 'Down_Avg']
        st = st.merge(dg, on=['Stock', 'Day'], how='left')
    else:
        st['Down_WR']  = 50.0
        st['Down_Avg'] = 0.0
    st['Down_WR']  = st['Down_WR'].fillna(50.0)
    st['Down_Avg'] = st['Down_Avg'].fillna(0.0)
    return st

def select_heuristic_candidates(train_df: pd.DataFrame, sc: str = 'stockname') -> dict:
    rr = None
    for floor in [20, 10, 5, 2]:
        rr = _build_stats_table(train_df, sc, min_count=floor)
        if not rr.empty:
            break
    if rr is None or rr.empty:
        return {}

    rr = _add_recency(rr, train_df, sc)
    rr = _add_down_market(rr, train_df, sc)

    sw    = rr.sort_values(['Success_%', 'Avg_PnL'],  ascending=[False, False])
    su    = rr.sort_values(['Success_%', 'Avg_PnL'],  ascending=[True,  True])
    sa    = rr.sort_values(['Success_%', 'Avg_PnL'],  ascending=[False, True])
    ss    = rr[rr['Avg_PnL'] > 0].sort_values('Sharpe_Score',    ascending=False)
    sev   = rr[rr['Avg_PnL'] > 0].sort_values('Avg_PnL',         ascending=False)
    srec  = rr.sort_values('Recent_WR',               ascending=False)
    spf   = rr[rr['Avg_PnL'] > 0].sort_values('PF_Score',        ascending=False)
    sconv = rr.sort_values('Conviction_Score',         ascending=False)
    sfade = rr.sort_values('Recency_Edge',             ascending=True)
    shot  = rr[rr['Recent_WR'] > 70].sort_values('Recent_WR',    ascending=False)
    sdef  = rr.sort_values('Down_WR',                 ascending=False)

    total_assets = len(rr)
    if os.getenv('ENABLE_DYNAMIC_CANDIDATE_SIZES', 'False') == 'True':
        n_momentum   = max(5, int(0.05 * total_assets))
        n_contrarian = max(10, int(0.12 * total_assets))
        n_underdog   = max(5, int(0.05 * total_assets))
        n_asymmetric = max(5, int(0.05 * total_assets))
        n_sharpe     = max(5, int(0.05 * total_assets))
        n_ev         = max(5, int(0.05 * total_assets))
        n_recency    = max(5, int(0.05 * total_assets))
        n_pf         = max(5, int(0.05 * total_assets))
        n_conviction = max(5, int(0.05 * total_assets))
        n_fade       = max(5, int(0.05 * total_assets))
        n_hotstreak  = max(5, int(0.05 * total_assets))
        n_defensive  = max(8, int(0.07 * total_assets))
    else:
        n_momentum   = TOP_N_MOMENTUM
        n_contrarian = TOP_N_CONTRARIAN
        n_underdog   = TOP_N_UNDERDOG
        n_asymmetric = TOP_N_ASYMMETRIC
        n_sharpe     = TOP_N_SHARPE
        n_ev         = TOP_N_EV
        n_recency    = TOP_N_RECENCY
        n_pf         = TOP_N_PF
        n_conviction = TOP_N_CONVICTION
        n_fade       = TOP_N_FADE
        n_hotstreak  = TOP_N_HOTSTREAK
        n_defensive  = TOP_N_DEFENSIVE

    top_sets = {
        'Standard Momentum':      sw.head(n_momentum)[['Stock', 'Day']].values.tolist(),
        'Rotational Contrarian':  su.head(n_contrarian)[['Stock', 'Day']].values.tolist(),
        'Underdog Reversion':     sa.head(n_underdog)[['Stock', 'Day']].values.tolist(),
        'Asymmetric Reversion':   sa.head(n_asymmetric)[['Stock', 'Day']].values.tolist(),
        'Sharpe Alpha':           ss.head(n_sharpe)[['Stock', 'Day']].values.tolist(),
        'EV Leader':              sev.head(n_ev)[['Stock', 'Day']].values.tolist(),
        'Recency Accelerator':    srec.head(n_recency)[['Stock', 'Day']].values.tolist(),
        'Profit Factor Champion': spf.head(n_pf)[['Stock', 'Day']].values.tolist(),
        'Statistical Conviction': sconv.head(n_conviction)[['Stock', 'Day']].values.tolist(),
        'Momentum Fade':          sfade.head(n_fade)[['Stock', 'Day']].values.tolist(),
        'Hot Streak':             shot.head(n_hotstreak)[['Stock', 'Day']].values.tolist(),
        'Defensive Alpha':        sdef.head(n_defensive)[['Stock', 'Day']].values.tolist(),
    }

    candidate_map = {}
    for strat, pairs in top_sets.items():
        for stock, day in pairs:
            key = (stock, day)
            candidate_map.setdefault(key, set()).add(strat)
    return candidate_map

# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 — SCORE ENGINE
# ─────────────────────────────────────────────────────────────────────────────
def score_band(score: float):
    if score >= 80:    return "ELITE",    "Full capital"
    elif score >= 65:  return "STRONG",   "Normal size"
    elif score >= 50:  return "MODERATE", "Reduced size"
    elif score >= 35:  return "WEAK",     "Caution"
    else:              return "SKIP",     "Do not trade"

def compute_score(pred_t1, pred_t2, pred_t3, row, all_candidates, bad_expiry):
    pred_total = pred_t1 + pred_t2 + pred_t3

    # Consensus (35 pts)
    preds      = [pred_t1, pred_t2, pred_t3]
    n_positive = sum(1 for p in preds if p > 0)
    if n_positive == 3:
        base_consensus = 20.0
        pos_preds = [abs(p) for p in preds]
        harmony   = (min(pos_preds) / max(pos_preds)) * 15.0 if max(pos_preds) > 0 else 0.0
        score_consensus = base_consensus + harmony
    elif n_positive == 2:
        score_consensus = 10.0
    elif n_positive == 1:
        score_consensus = 4.0
    else:
        score_consensus = 0.0
    score_consensus = min(score_consensus, 35.0)

    # Magnitude (25 pts)
    if len(all_candidates) > 1 and 'pred_pnl' in all_candidates.columns:
        pct_rank = (all_candidates['pred_pnl'] < pred_total).mean()
    else:
        pct_rank = 0.5
    score_magnitude = pct_rank * 25.0

    # Seasonal Strength (15 pts)
    month_hist_wr  = float(row.get('month_hist_wr', 0.0))
    month_hist_avg = float(row.get('month_hist_avg', 0.0))
    wr_score = month_hist_wr * 10.0
    if len(all_candidates) > 1 and 'month_hist_avg' in all_candidates.columns:
        avg_pct = (all_candidates['month_hist_avg'] < month_hist_avg).mean()
    else:
        avg_pct = 0.5
    avg_score      = avg_pct * 5.0
    score_seasonal = min(wr_score + avg_score, 15.0)

    # Heuristic Confidence (15 pts)
    heuristic_count = float(row.get('heuristic_count', 0.0))
    score_heuristic = min(heuristic_count / 5.0, 1.0) * 15.0

    # Expiry Safety (10 pts)
    dte = row.get('days_to_expiry', None)
    if dte is None or dte in bad_expiry:
        score_expiry = 0.0
    else:
        score_expiry = 5.0
        sweet_spot   = 7.0
        proximity    = max(0.0, 1.0 - abs(dte - sweet_spot) / 10.0)
        score_expiry += proximity * 5.0
    score_expiry = min(score_expiry, 10.0)

    total = score_consensus + score_magnitude + score_seasonal + score_heuristic + score_expiry
    total = round(min(max(total, 0.0), 100.0), 1)

    breakdown = {
        "tower_consensus":      round(score_consensus, 1),
        "pnl_magnitude":        round(score_magnitude, 1),
        "seasonal_strength":    round(score_seasonal, 1),
        "heuristic_confidence": round(score_heuristic, 1),
        "expiry_safety":        round(score_expiry, 1),
        "total":                total,
        "n_towers_positive":    n_positive,
    }
    return total, breakdown

def score_all_candidates(test_df, bad_expiry):
    required = {'pred_t1', 'pred_t2', 'pred_t3', 'pred_pnl'}
    missing  = required - set(test_df.columns)
    if missing:
        raise ValueError(f"score_all_candidates: missing columns {missing}")

    scores     = []
    breakdowns = []
    for _, row in test_df.iterrows():
        score, bd = compute_score(
            pred_t1        = row['pred_t1'],
            pred_t2        = row['pred_t2'],
            pred_t3        = row['pred_t3'],
            row            = row,
            all_candidates = test_df,
            bad_expiry     = bad_expiry,
        )
        scores.append(score)
        breakdowns.append(bd)

    df_out = test_df.copy()
    df_out['score']           = scores
    df_out['score_consensus'] = [b['tower_consensus']      for b in breakdowns]
    df_out['score_magnitude'] = [b['pnl_magnitude']        for b in breakdowns]
    df_out['score_seasonal']  = [b['seasonal_strength']    for b in breakdowns]
    df_out['score_heuristic'] = [b['heuristic_confidence'] for b in breakdowns]
    df_out['score_expiry']    = [b['expiry_safety']        for b in breakdowns]
    df_out['n_towers_pos']    = [b['n_towers_positive']    for b in breakdowns]

    band_labels    = [score_band(s) for s in scores]
    df_out['band']   = [b[0] for b in band_labels]
    df_out['action'] = [b[1] for b in band_labels]
    return df_out

# ─────────────────────────────────────────────────────────────────────────────
# WALK-FORWARD SIMULATION RUNNER WITH DYNAMIC THRESHOLD
# ─────────────────────────────────────────────────────────────────────────────
def run_dynamic_threshold(start_year=2019, end_year=2025, pt=1800, mt=4, ra=5.0, retrain_freq='daily'):
    env_mt = os.getenv('DYN_MAX_TRADES')
    if env_mt is not None:
        mt = int(env_mt)
        
    print("\n" + "="*80)
    print(f"  DYNAMIC THRESHOLD (BEST ABSOLUTE AVG) — WALK-FORWARD SIMULATION")
    print(f"  Years: {start_year} to {end_year}  |  Base Threshold: Rs {pt:,}  |  Max Trades/Day: {mt}  |  Retrain: {retrain_freq.upper()}")
    print("="*80)
    
    print("\n[1/4] Loading master datasets and building expanding features...")
    df = load_pnl()
    df_feats = build_features(df)
    
    # Precomputations for speedup
    df_feats['month'] = df_feats['dt_parsed'].dt.month
    df_feats['month_day_key'] = df_feats['month'].astype(str) + "_" + df_feats['day']
    df_feats['pnl_positive'] = (df_feats['pnl'] > 0).astype(float)
    df_feats['sector'] = df_feats['stockname'].apply(get_stock_sector)
    
    all_dates = sorted(df_feats[(df_feats['dt_parsed'].dt.year >= start_year) & (df_feats['dt_parsed'].dt.year <= end_year)]['dt_parsed'].unique())
    print(f"Found {len(all_dates)} unique trading dates.")
    
    sc = 'stockname'
    
    # Pre-compute yearly dynamic structural overlays (fully walk-forward & look-ahead free)
    yearly_overlays = {}
    print("[*] Pre-computing yearly dynamic structural overlays...")
    for yr in range(start_year, end_year + 1):
        prior_train = df_feats[df_feats['dt_parsed'].dt.year < yr]
        if not prior_train.empty:
            st = _build_stats_table(prior_train, sc, min_count=15)
            if not st.empty:
                # Find elite combinations: Win Rate >= 72.0% and Average PnL >= Rs 400
                elite = st[(st['Success_%'] >= 72.0) & (st['Avg_PnL'] >= 400.0)]
                yearly_overlays[yr] = set(zip(elite['Stock'].str.upper(), elite['Day'].str.upper()))
                print(f"  Year {yr}: Identified {len(yearly_overlays[yr])} dynamic elite structural overlays.")
            else:
                yearly_overlays[yr] = set()
        else:
            yearly_overlays[yr] = set()
            
    feats_t1 = [f for f in BASE_FEATURE_COLS if f != 'days_to_expiry']
    feats_t2 = ['month_hist_avg', 'month_hist_wr']
    feats_t3 = ['days_to_expiry', 'heuristic_count']
    
    trade_log = []
    daily_log = []
    
    # Dynamic threshold state
    current_thr = float(pt)
    consec_loss = 0
    consec_win = 0
    dyn_loss_days_trigger = DYN_LOSS_DAYS_TRIGGER
    dyn_win_days_trigger = DYN_WIN_DAYS_TRIGGER
    
    import pickle
    da_val = os.getenv('DYN_ALPHA', 'standard')
    dl_val = os.getenv('DYN_LOOKBACK_YEARS', '3.0')
    is_nf = os.getenv('REMOVE_EXTREME_TRAINING_LOSSES', 'False').lower() == 'true'
    method = os.getenv('NOISE_CLEANING_METHOD', 'static_10').lower()
    nf_suffix = ""
    if is_nf:
        nf_suffix = f"_nf_{method}" if method != 'static_10' else "_nf"
    cache_file = os.path.join(_THIS_DIR, 'output', f'wf_predictions_cache_{retrain_freq}_da_{da_val}_dl_{dl_val}{nf_suffix}.pkl')
    scored_cache = {}


    use_cache = False
    
    if os.path.exists(cache_file):
        try:
            with open(cache_file, 'rb') as f:
                scored_cache = pickle.load(f)
            use_cache = True
            print(f"[+] CACHE HIT: Loaded {len(scored_cache)} days of model predictions. Retraining is bypassed!")
        except Exception as e:
            print(f"[-] CACHE LOAD ERROR: {e}. Re-running model fitting...")

    # Trackers for the active trained models and period statistics
    current_period_key = None
    model_t1, model_t2, model_t3 = None, None, None
    scaler_t1, scaler_t2, scaler_t3 = None, None, None
    bad_expiry = None
    month_day_stats = None
    candidate_map = None
    map_dict = None
    weak_sectors = set()
    
    print(f"\n[2/4] Running walk-forward {retrain_freq}-by-{retrain_freq}...")
    for idx, today_np in enumerate(all_dates, 1):
        today = pd.to_datetime(today_np)
        day_name = today.day_name()
        
        # 1. Determine period key based on selected frequency
        if retrain_freq == 'daily':
            if os.getenv('REMOVE_EXTREME_TRAINING_LOSSES', 'False').lower() == 'true':
                period_key = today.strftime('%Y-W%U')  # Group into weekly blocks to speed up 5x
            else:
                period_key = today.strftime('%Y-%m-%d')
        elif retrain_freq == 'weekly':
            period_key = today.strftime('%Y-W%U')
        elif retrain_freq == 'monthly':
            period_key = today.strftime('%Y-%m')
        elif retrain_freq == 'quarterly':
            period_key = f"{today.year}-Q{(today.month - 1) // 3 + 1}"
        elif retrain_freq == 'ensemble':
            period_key = today.strftime('%Y-%m-%d')
        elif retrain_freq == 'yearly':
            period_key = today.strftime('%Y')
        else:
            raise ValueError(f"Unknown retrain_freq: {retrain_freq}")
            
        test  = df_feats[df_feats['dt_parsed'] == today].copy()
        if test.empty:
            continue
            
        if os.getenv('ENABLE_DYNAMIC_FEEDBACK_TRIGGERS', 'False') == 'True':
            recent_trades = [t for t in trade_log][-30:]
            if len(recent_trades) >= 10:
                recent_wins = sum(1 for t in recent_trades if t['actual_pnl'] > 0)
                recent_wr = recent_wins / len(recent_trades)
            else:
                recent_wr = 0.74
            
            dyn_loss_days_trigger = max(2, int(round(5 * (1 - recent_wr))))
            dyn_win_days_trigger = max(3, int(round(8 * recent_wr)))
            
        days_to_expiry = test['days_to_expiry'].iloc[0]
        
        # Friday lock
        if day_name == 'Friday':
            daily_log.append({'date': today.strftime('%Y-%m-%d'), 'status': 'SKIPPED', 'reason': 'Friday Safety Lock', 'trades': 0, 'pnl': 0.0, 'threshold': current_thr})
            current_thr = current_thr * (1 - DYN_REVERT_RATE) + pt * DYN_REVERT_RATE
            continue
            
        # Check cache first to bypass training and scoring
        if use_cache and today_np in scored_cache:
            cache_entry = scored_cache[today_np]
            if isinstance(cache_entry, dict) and cache_entry.get('status') == 'SKIPPED':
                daily_log.append({'date': today.strftime('%Y-%m-%d'), 'status': 'SKIPPED', 'reason': cache_entry['reason'], 'trades': 0, 'pnl': 0.0, 'threshold': current_thr})
                current_thr = current_thr * (1 - DYN_REVERT_RATE) + pt * DYN_REVERT_RATE
                continue
            test_scored = cache_entry.copy()
            # Restore weekday historical features from test
            for col in ['success_pct', 'avg_pnl', 'hist_count', 'std_pnl', 'sector']:
                if col in test.columns:
                    test_scored[col] = test_scored['stockname'].map(test.drop_duplicates(subset=['stockname']).set_index('stockname')[col])
            test = test_scored # keep for option 2 volatility check
        else:
            # 2. Check if we need to retrain (new period started or first day of backtest)
            if period_key != current_period_key:
                # Determine training boundary (data ending at previous month/year/day)
                if retrain_freq == 'daily':
                    train_end = today
                elif retrain_freq == 'weekly':
                    train_end = today - pd.to_timedelta(today.weekday(), unit='D')
                elif retrain_freq == 'monthly':
                    train_end = today.to_period('M').start_time
                elif retrain_freq == 'quarterly':
                    train_end = today.to_period('Q').start_time
                elif retrain_freq == 'ensemble':
                    train_end = today
                elif retrain_freq == 'yearly':
                    train_end = today.to_period('Y').start_time
                lookback_years = float(os.getenv('DYN_LOOKBACK_YEARS', '3.0'))
                three_years_ago = train_end - pd.DateOffset(days=int(lookback_years * 365.25))
                train = df_feats[(df_feats['dt_parsed'] >= three_years_ago) & (df_feats['dt_parsed'] < train_end)].copy()
                
                # Extreme losses filter (Noise Removal from training set itself)
                if os.getenv('REMOVE_EXTREME_TRAINING_LOSSES', 'False').lower() == 'true':
                    method = os.getenv('NOISE_CLEANING_METHOD', 'static_10').lower()
                    if method == 'static_10':
                        # Exclude trade return < -10%
                        train = train[(train['buy_price'] > 0) & (((train['sell_price'] - train['buy_price']) / train['buy_price']) >= -0.10)].copy()
                    elif method == 'iqr':
                        if len(train) > 10:
                            rets = (train['sell_price'] - train['buy_price']) / train['buy_price']
                            q1 = rets.quantile(0.25)
                            q3 = rets.quantile(0.75)
                            iqr = q3 - q1
                            cutoff = q1 - 2.0 * iqr
                            train = train[(train['buy_price'] > 0) & (((train['sell_price'] - train['buy_price']) / train['buy_price']) >= cutoff)].copy()
                    elif method == 'winsor':
                        if len(train) > 10:
                            rets = (train['sell_price'] - train['buy_price']) / train['buy_price']
                            p1 = rets.quantile(0.01)
                            mask = (train['buy_price'] > 0) & (rets < p1)
                            train.loc[mask, 'sell_price'] = train.loc[mask, 'buy_price'] * (1.0 + p1)
                            train.loc[mask, 'pnl'] = train.loc[mask, 'sell_price'] - train.loc[mask, 'buy_price']
                    elif method == 'z_score':
                        if len(train) > 10:
                            rets = (train['sell_price'] - train['buy_price']) / train['buy_price']
                            mean_ret = rets.mean()
                            std_ret = rets.std()
                            cutoff = mean_ret - 2.5 * std_ret
                            train = train[(train['buy_price'] > 0) & (((train['sell_price'] - train['buy_price']) / train['buy_price']) >= cutoff)].copy()
                    elif method == 'static_15k':
                        # Exclude training trades with raw loss > 15,000 Rupees
                        train = train[train['pnl'] >= -15000.0].copy()
                    elif method == 'quantile_15':
                        # Exclude worst 15% of training trades sorted by PnL lookahead-free
                        if len(train) > 10:
                            thresh = train['pnl'].quantile(0.15)
                            train = train[train['pnl'] > thresh].copy()



                
                if train.empty:
                    continue  # Skip if there's no historical training data for this window yet
                
                weak_sectors = set()
                if os.getenv('ENABLE_SECTOR_STRENGTH_FILTER', 'False') == 'True':
                    sector_pnl = train.groupby('sector')['pnl'].mean()
                    bottom_count = max(1, int(len(sector_pnl) * 0.20))
                    weak_sectors = set(sector_pnl.nsmallest(bottom_count).index)

                if os.getenv('ENABLE_DYNAMIC_BASE_THRESHOLD', 'False') == 'True':
                    train_positive = train[train['pnl'] > 0]
                    if not train_positive.empty:
                        regime_factor = 0.55
                        if os.getenv('ENABLE_REGIME_ADAPTIVE_THRESHOLD', 'False') == 'True':
                            recent_traded = [entry for entry in daily_log if entry.get('status') == 'TRADED']
                            if len(recent_traded) >= 15:
                                recent_wins = sum(1 for entry in recent_traded[-15:] if entry['pnl'] > 0)
                                recent_wr = recent_wins / 15.0
                                if recent_wr >= 0.70:
                                    regime_factor = 0.45
                                elif recent_wr < 0.55:
                                    regime_factor = 0.65
                        pt = train_positive['pnl'].mean() * regime_factor
                    

                # Bad Expiry Filter for this period
                expiry_stats = train.groupby('days_to_expiry')['pnl'].mean()
                if os.getenv('ENABLE_DYNAMIC_EXPIRY_FILTER', 'False') == 'True':
                    dynamic_filter_threshold = -0.15 * train['pnl'].std()
                    bad_expiry = set(expiry_stats[expiry_stats < dynamic_filter_threshold].index)
                else:
                    bad_expiry = set(expiry_stats[expiry_stats < FILTER_THRESHOLD].index)
                
                # Target Encode Monthly + Weekday Seasonality
                # BUG FIX (Lookahead): Use expanding leave-one-out encoding with shift(1)
                # instead of mapping the full-window aggregate back onto training rows.
                # The old approach let each row "see" its own pnl baked into the mean
                # (within-sample target leakage into Tower 2 features).
                # month_day_stats is still built from full train window — used ONLY for test-day lookup.
                month_day_stats = train.groupby('month_day_key').agg(
                    month_hist_avg=('pnl', 'mean'),
                    month_hist_wr=('pnl_positive', 'mean')
                )
                train = train.sort_values('dt_parsed').copy()
                train['month_hist_avg'] = (
                    train.groupby('month_day_key')['pnl']
                    .transform(lambda x: x.expanding().mean().shift(1))
                    .fillna(0)
                )
                train['month_hist_wr'] = (
                    train.groupby('month_day_key')['pnl_positive']
                    .transform(lambda x: x.expanding().mean().shift(1))
                    .fillna(0)
                )
                
                # Heuristics mapping
                candidate_map = select_heuristic_candidates(train, sc=sc)
                map_dict = {k: len(v) for k, v in candidate_map.items()}
                # BUG FIX (Lookahead): heuristic_count is derived from the full training window
                # aggregate. Mapping it back onto train rows retroactively stamps "future knowledge"
                # of heuristic qualification onto early historical rows (e.g. a stock that only
                # became a momentum candidate in year 3 would get heuristic_count=1 on year 1 rows).
                # Fix: set heuristic_count=0 on all train rows (conservative prior).
                # The correct live value is still applied to the test day below (line 944).
                train['heuristic_count'] = 0
                
                # Train Tower 1
                train = train.dropna(subset=feats_t1 + ['pnl'])
                if train.empty:
                    continue
                scaler_t1 = StandardScaler()
                X_train_t1 = scaler_t1.fit_transform(train[feats_t1].values)
                if os.getenv('DYN_ALPHA', 'False').lower() == 'auto':
                    model_t1 = RidgeCV(alphas=[0.1, 1.0, 5.0, 10.0, 20.0, 50.0, 100.0]).fit(X_train_t1, train['pnl'].values)
                else:
                    model_t1 = Ridge(alpha=ra, random_state=42).fit(X_train_t1, train['pnl'].values)
                res_t1 = train['pnl'].values - model_t1.predict(X_train_t1)
                
                # Train Tower 2
                scaler_t2 = StandardScaler()
                X_train_t2 = scaler_t2.fit_transform(train[feats_t2].values)
                if os.getenv('DYN_ALPHA', 'False').lower() == 'auto':
                    model_t2 = RidgeCV(alphas=[0.1, 1.0, 5.0, 10.0, 20.0, 50.0, 100.0]).fit(X_train_t2, res_t1)
                else:
                    model_t2 = Ridge(alpha=ra, random_state=42).fit(X_train_t2, res_t1)
                res_t2 = res_t1 - model_t2.predict(X_train_t2)
                
                # Train Tower 3
                scaler_t3 = StandardScaler()
                X_train_t3 = scaler_t3.fit_transform(train[feats_t3].values)
                if os.getenv('DYN_ALPHA', 'False').lower() == 'auto':
                    model_t3 = RidgeCV(alphas=[0.1, 1.0, 5.0, 10.0, 20.0, 50.0, 100.0]).fit(X_train_t3, res_t2)
                else:
                    model_t3 = Ridge(alpha=ra, random_state=42).fit(X_train_t3, res_t2)
                
                current_period_key = period_key
                
            # 3. Apply cached bad expiry lock
            if days_to_expiry in bad_expiry:
                daily_log.append({'date': today.strftime('%Y-%m-%d'), 'status': 'SKIPPED', 'reason': f'Toxic Expiry (DTE: {days_to_expiry})', 'trades': 0, 'pnl': 0.0, 'threshold': current_thr})
                current_thr = current_thr * (1 - DYN_REVERT_RATE) + pt * DYN_REVERT_RATE
                scored_cache[today_np] = {'status': 'SKIPPED', 'reason': f'Toxic Expiry (DTE: {days_to_expiry})'}
                continue
                
            # 4. Predict using currently cached models
            test['month_hist_avg'] = test['month_day_key'].map(month_day_stats['month_hist_avg']).fillna(0)
            test['month_hist_wr']  = test['month_day_key'].map(month_day_stats['month_hist_wr']).fillna(0)
            test['heuristic_count'] = [map_dict.get((s, d), 0) for s, d in zip(test[sc], test['day'])]
            
            test = test.dropna(subset=feats_t1).copy()
            if test.empty:
                continue
            
            X_test_t1 = scaler_t1.transform(test[feats_t1].values)
            pred_test_t1 = model_t1.predict(X_test_t1)
            
            X_test_t2 = scaler_t2.transform(test[feats_t2].values)
            pred_test_t2 = model_t2.predict(X_test_t2)
            
            X_test_t3 = scaler_t3.transform(test[feats_t3].values)
            pred_test_t3 = model_t3.predict(X_test_t3)
            
            test['pred_pnl'] = pred_test_t1 + pred_test_t2 + pred_test_t3
            test['pred_t1']  = pred_test_t1
            test['pred_t2']  = pred_test_t2
            test['pred_t3']  = pred_test_t3
            
            test_scored = score_all_candidates(test, bad_expiry)
            # Save relevant columns to scored_cache (including score)
            scored_cache[today_np] = test_scored[['dt_parsed', 'stockname', 'pred_pnl', 'pnl', 'volatility_ratio', 'days_to_expiry', 'score']].copy()
        
        # 5. Sector-Capping Filtered Trade Selection
        dyn_sort_by = os.getenv('DYN_SORT_BY', 'pnl')
        dyn_min_score = float(os.getenv('DYN_MIN_SCORE', '0'))
        
        enable_golden_fasttrack = os.getenv('ENABLE_GOLDEN_FASTTRACK', 'False') == 'True'
        enable_golden_hybrid = os.getenv('ENABLE_GOLDEN_HYBRID', 'False') == 'True'
        enable_adaptive_golden = os.getenv('ENABLE_ADAPTIVE_GOLDEN', 'False') == 'True'
        
        if enable_adaptive_golden:
            # 1. Dynamic Win Rate hurdle (the 80th percentile of success_pct on today's candidates, capped between 70% and 80%)
            success_hurdle = np.clip(test_scored['success_pct'].quantile(0.8), 70.0, 80.0) if len(test_scored) > 0 else 75.0
            
            # 2. Volatility-Adjusted Average PnL hurdle (30% of each stock's rolling standard deviation of PnL)
            avg_pnl_hurdle = test_scored['std_pnl'] * 0.3
            
            # 3. Volatility-Adjusted prediction bypass hurdle (25% of the stock's standard deviation of PnL)
            pred_pnl_golden_hurdle = test_scored['std_pnl'] * 0.25
            
            # 4. Volatility-Adjusted structural overlay bypass hurdle (10% of the stock's standard deviation of PnL)
            pred_pnl_structural_hurdle = test_scored['std_pnl'] * 0.1
            
            is_golden = (
                (test_scored['success_pct'] >= success_hurdle) & 
                (test_scored['avg_pnl'] >= avg_pnl_hurdle) & 
                (test_scored['hist_count'] >= 15) & 
                (test_scored['pred_pnl'] >= pred_pnl_golden_hurdle)
            )
            test_scored['is_gold_candidate'] = is_golden
            
            # Structural Overlays (dynamically pre-computed for each year)
            stock_upper = test_scored['stockname'].str.upper()
            day_upper_val = today.day_name().upper()
            
            active_overlays = yearly_overlays.get(today.year, set())
            is_structural_overlay = pd.Series([
                (s, day_upper_val) in active_overlays for s in stock_upper
            ], index=test_scored.index) & (test_scored['pred_pnl'] >= pred_pnl_structural_hurdle)
            
            candidates = test_scored[(test_scored['pred_pnl'] > current_thr) | is_golden | is_structural_overlay].drop_duplicates(subset=[sc])
            
        elif enable_golden_hybrid:
            # 1. Standard Golden Fast-Track (Win Rate >= 75%, avg PnL >= 1000, hist_count >= 15, pred_pnl >= 800)
            is_golden = (test_scored['success_pct'] >= 75.0) & (test_scored['avg_pnl'] >= 1000.0) & (test_scored['hist_count'] >= 15) & (test_scored['pred_pnl'] >= 800.0)
            test_scored['is_gold_candidate'] = (test_scored['success_pct'] >= 75.0) & (test_scored['avg_pnl'] >= 1000.0) & (test_scored['hist_count'] >= 15)
            
            # 2. Structural Weekday Overlays (lowered prediction hurdle of Rs 300)
            stock_upper = test_scored['stockname'].str.upper()
            day_upper_val = today.day_name().upper()
            
            is_structural_overlay = (
                ((stock_upper == 'LUPIN') & (day_upper_val == 'TUESDAY')) |
                ((stock_upper == 'LUPIN') & (day_upper_val == 'MONDAY')) |
                ((stock_upper == 'DELTACORP') & (day_upper_val == 'MONDAY')) |
                ((stock_upper == 'CHAMBLFERT') & (day_upper_val == 'MONDAY')) |
                ((stock_upper == 'DEEPAKNTR') & (day_upper_val == 'MONDAY'))
            ) & (test_scored['pred_pnl'] >= 300.0)
            
            candidates = test_scored[(test_scored['pred_pnl'] > current_thr) | is_golden | is_structural_overlay].drop_duplicates(subset=[sc])
            
        elif enable_golden_fasttrack:
            # Fully Dynamic Volatility-Adjusted (price-agnostic and split-resilient)
            is_gold_setup = (test_scored['success_pct'] >= 75.0) & (test_scored['avg_pnl'] >= test_scored['std_pnl'] * 0.40) & (test_scored['hist_count'] >= 15)
            is_golden = is_gold_setup & (test_scored['pred_pnl'] >= test_scored['std_pnl'] * 0.32)
            test_scored['is_gold_candidate'] = is_gold_setup
            candidates = test_scored[(test_scored['pred_pnl'] > current_thr) | is_golden].drop_duplicates(subset=[sc])
        else:
            test_scored['is_gold_candidate'] = (test_scored['success_pct'] >= 75.0) & (test_scored['avg_pnl'] >= 1000.0) & (test_scored['hist_count'] >= 15)
            candidates = test_scored[test_scored['pred_pnl'] > current_thr].drop_duplicates(subset=[sc])
            
        if os.getenv('ENABLE_SECTOR_STRENGTH_FILTER', 'False') == 'True' and not candidates.empty:
            candidates = candidates[~candidates['sector'].isin(weak_sectors)]

        # F&O Banlist Filter Integration:
        # Load ban list set for today to filter candidates with zero lookahead bias
        banlist_df = getattr(run_dynamic_threshold, '_banlist_df_cache', None)
        if banlist_df is None:
            ban_path = '/home/ubuntu/banlist/fo_ban_list_historical.csv'
            if os.path.exists(ban_path):
                print("[*] LOADING HISTORICAL F&O BAN LIST CSV DATABASE...")
                banlist_df = pd.read_csv(ban_path)
                banlist_df['parsed_date'] = pd.to_datetime(banlist_df['date'], dayfirst=True, format='mixed')
                banlist_df['stock_upper'] = banlist_df['stock_name'].str.strip().str.upper()
                run_dynamic_threshold._banlist_df_cache = banlist_df
            else:
                banlist_df = pd.DataFrame(columns=['parsed_date', 'stock_upper'])
                run_dynamic_threshold._banlist_df_cache = banlist_df

        # Filter banlist for today
        banned_today = set(banlist_df[banlist_df['parsed_date'] == today]['stock_upper'])
        
        # Track counts of skipped banned stocks
        skipped_banned_today_count = 0
        original_candidates_count = len(candidates)
        
        # Filter candidates to only non-banned stocks
        if not candidates.empty:
            is_banned_mask = candidates['stockname'].str.strip().str.upper().isin(banned_today)
            skipped_banned_today_count = is_banned_mask.sum()
            if skipped_banned_today_count > 0:
                # Keep a running list of how many we skipped per year
                yr_skips = getattr(run_dynamic_threshold, '_skipped_by_year', {})
                yr_skips[today.year] = yr_skips.get(today.year, 0) + skipped_banned_today_count
                run_dynamic_threshold._skipped_by_year = yr_skips
            
            # Select replacement: simply filter out banned ones. The ranking sort has already happened,
            # so slicing to 'mt' or selecting picks will automatically slide down to the next non-banned candidates as replacements!
            candidates = candidates[~is_banned_mask]

        if dyn_min_score > 0:
            candidates = candidates[candidates['score'] >= dyn_min_score]
        
        if dyn_sort_by == 'score':
            candidates = candidates.sort_values('score', ascending=False)
        elif dyn_sort_by == 'pnl_score':
            candidates = candidates.sort_values(['pred_pnl', 'score'], ascending=[False, False])
        elif dyn_sort_by == 'score_pnl':
            candidates = candidates.sort_values(['score', 'pred_pnl'], ascending=[False, False])
        else:
            candidates = candidates.sort_values('pred_pnl', ascending=False)
        
        strategy = os.getenv('DYN_ALLOCATION_STRATEGY', 'r1_r3').lower()
        
        selected_rows = []
        sector_counts = {}
        allocated_units = 0.0
        if 'golden_booster' in strategy or 'golden_combo' in strategy or 'golden_hybrid' in strategy or 'adaptive_golden' in strategy:
            max_trades_allowed = mt
            max_units = 2.0 if mt == 1 else 4.0
            for _, row in candidates.iterrows():
                if len(selected_rows) >= max_trades_allowed:
                    break
                ticker = row[sc]
                sector = get_stock_sector(ticker)
                current_sec_count = sector_counts.get(sector, 0)
                if current_sec_count < DYN_SECTOR_CAP:
                    is_gold = row.get('is_gold_candidate', False)
                    qty = 2.0 if is_gold else 1.0
                    if allocated_units + qty <= max_units:
                        selected_rows.append((row, qty))
                        allocated_units += qty
                        sector_counts[sector] = current_sec_count + 1
                    elif allocated_units + 1.0 <= max_units:
                        selected_rows.append((row, 1.0))
                        allocated_units += 1.0
                        sector_counts[sector] = current_sec_count + 1
                    if allocated_units >= max_units:
                        break
                        
        elif strategy == 'baseline':
            for _, row in candidates.iterrows():
                if len(selected_rows) >= mt:
                    break
                ticker = row[sc]
                sector = get_stock_sector(ticker)
                current_sec_count = sector_counts.get(sector, 0)
                if current_sec_count < DYN_SECTOR_CAP:
                    selected_rows.append((row, 1.0))
                    sector_counts[sector] = current_sec_count + 1
                    
        elif strategy == 'dynamic_double_vol':
            max_trades_allowed = mt
            max_units = 6.0
            for _, row in candidates.iterrows():
                if len(selected_rows) >= max_trades_allowed:
                    break
                ticker = row[sc]
                sector = get_stock_sector(ticker)
                current_sec_count = sector_counts.get(sector, 0)
                if current_sec_count < DYN_SECTOR_CAP:
                    is_exceptionally_good = row['pred_pnl'] >= (current_thr + row['std_pnl'] * 0.50)
                    qty = 2.0 if is_exceptionally_good else 1.0
                    
                    if allocated_units + qty <= max_units:
                        selected_rows.append((row, qty))
                        allocated_units += qty
                        sector_counts[sector] = current_sec_count + 1
                    elif allocated_units + 1.0 <= max_units:
                        selected_rows.append((row, 1.0))
                        allocated_units += 1.0
                        sector_counts[sector] = current_sec_count + 1
                    if allocated_units >= max_units:
                        break
                    
        elif strategy == 'top_heavy_trio':
            # Select up to 3 trades. Rank 1 gets 2.0x, Rank 2 & 3 get 1.0x.
            filtered_candidates = []
            for _, row in candidates.iterrows():
                ticker = row[sc]
                sector = get_stock_sector(ticker)
                current_sec_count = sector_counts.get(sector, 0)
                if current_sec_count < DYN_SECTOR_CAP:
                    filtered_candidates.append(row)
                    sector_counts[sector] = current_sec_count + 1
                    if len(filtered_candidates) >= 3:
                        break
            for idx, row in enumerate(filtered_candidates):
                qty = 2.0 if idx == 0 else 1.0
                selected_rows.append((row, qty))
                
        elif strategy == 'elite_duo':
            # Select up to 2 trades. Both get 2.0x.
            filtered_candidates = []
            for _, row in candidates.iterrows():
                ticker = row[sc]
                sector = get_stock_sector(ticker)
                current_sec_count = sector_counts.get(sector, 0)
                if current_sec_count < DYN_SECTOR_CAP:
                    filtered_candidates.append(row)
                    sector_counts[sector] = current_sec_count + 1
                    if len(filtered_candidates) >= 2:
                        break
            for row in filtered_candidates:
                selected_rows.append((row, 2.0))
                
        elif strategy == 'lone_champion':
            # Select up to 1 trade. Gets 4.0x.
            for _, row in candidates.iterrows():
                ticker = row[sc]
                sector = get_stock_sector(ticker)
                current_sec_count = sector_counts.get(sector, 0)
                if current_sec_count < DYN_SECTOR_CAP:
                    selected_rows.append((row, 4.0))
                    break

        elif strategy == 'r1_r3':
            # ─── SNIPER v3.0: R1 + R3 (1x Size) No-Noise Architecture ───────
            # Normal Days (3+ sector-eligible candidates): Rank 1 and Rank 3 at 1x each.
            # Scarce Days (1 or 2 candidates): Rank 1 Only at 1x to protect capital.
            # Completely bypasses all noise filters and ML dual-confirmation.
            eligible = []
            for _, row in candidates.iterrows():
                ticker = row[sc]
                sector = get_stock_sector(ticker)
                current_sec_count = sector_counts.get(sector, 0)
                if current_sec_count < DYN_SECTOR_CAP:
                    eligible.append(row)
                    sector_counts[sector] = current_sec_count + 1
            if len(eligible) >= 3:
                # Normal day: pick Rank 1 (index 0) and Rank 3 (index 2) at 1x each
                selected_rows.append((eligible[0], 1.0))
                selected_rows.append((eligible[2], 1.0))
            elif len(eligible) >= 1:
                # Scarce day: Rank 1 Only at 1x
                selected_rows.append((eligible[0], 1.0))
                    
        elif strategy == 'progressive':
            # Select up to 4 trades. Rank 1 gets 2.0, Rank 2 gets 1.0, Rank 3 gets 0.67, Rank 4 gets 0.33. Total units = 4.0.
            filtered_candidates = []
            for _, row in candidates.iterrows():
                ticker = row[sc]
                sector = get_stock_sector(ticker)
                current_sec_count = sector_counts.get(sector, 0)
                if current_sec_count < DYN_SECTOR_CAP:
                    filtered_candidates.append(row)
                    sector_counts[sector] = current_sec_count + 1
                    if len(filtered_candidates) >= 4:
                        break
            weights = [2.0, 1.0, 0.67, 0.33]
            for idx, row in enumerate(filtered_candidates):
                selected_rows.append((row, weights[idx]))
                
        elif 'threshold_double_' in strategy:
            thr_val = float(strategy.split('_')[-1])
            for _, row in candidates.iterrows():
                qty = 2.0 if row['pred_pnl'] >= thr_val else 1.0
                ticker = row[sc]
                sector = get_stock_sector(ticker)
                current_sec_count = sector_counts.get(sector, 0)
                if current_sec_count < DYN_SECTOR_CAP:
                    if allocated_units + qty <= max_units:
                        selected_rows.append((row, qty))
                        allocated_units += qty
                    elif allocated_units + 1.0 <= max_units:
                        selected_rows.append((row, 1.0))
                        allocated_units += 1.0
                    if allocated_units >= max_units:
                        break
                        
        elif 'threshold_triple_' in strategy:
            thr_val = float(strategy.split('_')[-1])
            for _, row in candidates.iterrows():
                qty = 3.0 if row['pred_pnl'] >= thr_val else 1.0
                ticker = row[sc]
                sector = get_stock_sector(ticker)
                current_sec_count = sector_counts.get(sector, 0)
                if current_sec_count < DYN_SECTOR_CAP:
                    if allocated_units + qty <= max_units:
                        selected_rows.append((row, qty))
                        allocated_units += qty
                    elif allocated_units + 1.0 <= max_units:
                        selected_rows.append((row, 1.0))
                        allocated_units += 1.0
                    if allocated_units >= max_units:
                        break
                        
        elif 'score_double_' in strategy:
            score_val = float(strategy.split('_')[-1])
            for _, row in candidates.iterrows():
                qty = 2.0 if row['score'] >= score_val else 1.0
                ticker = row[sc]
                sector = get_stock_sector(ticker)
                current_sec_count = sector_counts.get(sector, 0)
                if current_sec_count < DYN_SECTOR_CAP:
                    if allocated_units + qty <= max_units:
                        selected_rows.append((row, qty))
                        allocated_units += qty
                    elif allocated_units + 1.0 <= max_units:
                        selected_rows.append((row, 1.0))
                        allocated_units += 1.0
                    if allocated_units >= max_units:
                        break
                        
        elif 'score_triple_' in strategy:
            score_val = float(strategy.split('_')[-1])
            for _, row in candidates.iterrows():
                qty = 3.0 if row['score'] >= score_val else 1.0
                ticker = row[sc]
                sector = get_stock_sector(ticker)
                current_sec_count = sector_counts.get(sector, 0)
                if current_sec_count < DYN_SECTOR_CAP:
                    if allocated_units + qty <= max_units:
                        selected_rows.append((row, qty))
                        allocated_units += qty
                    elif allocated_units + 1.0 <= max_units:
                        selected_rows.append((row, 1.0))
                        allocated_units += 1.0
                    if allocated_units >= max_units:
                        break
                        
        elif 'combined_double_' in strategy:
            parts = strategy.split('_')
            thr_val = float(parts[2])
            score_val = float(parts[3])
            for _, row in candidates.iterrows():
                qty = 2.0 if (row['pred_pnl'] >= thr_val and row['score'] >= score_val) else 1.0
                ticker = row[sc]
                sector = get_stock_sector(ticker)
                current_sec_count = sector_counts.get(sector, 0)
                if current_sec_count < DYN_SECTOR_CAP:
                    if allocated_units + qty <= max_units:
                        selected_rows.append((row, qty))
                        allocated_units += qty
                    elif allocated_units + 1.0 <= max_units:
                        selected_rows.append((row, 1.0))
                        allocated_units += 1.0
                    if allocated_units >= max_units:
                        break
                        
        elif 'combined_triple_' in strategy:
            parts = strategy.split('_')
            thr_val = float(parts[2])
            score_val = float(parts[3])
            for _, row in candidates.iterrows():
                qty = 3.0 if (row['pred_pnl'] >= thr_val and row['score'] >= score_val) else 1.0
                ticker = row[sc]
                sector = get_stock_sector(ticker)
                current_sec_count = sector_counts.get(sector, 0)
                if current_sec_count < DYN_SECTOR_CAP:
                    if allocated_units + qty <= max_units:
                        selected_rows.append((row, qty))
                        allocated_units += qty
                    elif allocated_units + 1.0 <= max_units:
                        selected_rows.append((row, 1.0))
                        allocated_units += 1.0
                    if allocated_units >= max_units:
                        break
                        
        elif 'hybrid_' in strategy or 'dynamic_risk_sizer_' in strategy:
            filtered_candidates = candidates
            if 'score50' in strategy:
                filtered_candidates = filtered_candidates[filtered_candidates['score'] >= 50]
            elif 'score55' in strategy:
                filtered_candidates = filtered_candidates[filtered_candidates['score'] >= 55]
            elif 'score60' in strategy:
                filtered_candidates = filtered_candidates[filtered_candidates['score'] >= 60]
            elif 'score65' in strategy:
                filtered_candidates = filtered_candidates[filtered_candidates['score'] >= 65]
                
            if 'pnl2500' in strategy:
                filtered_candidates = filtered_candidates[filtered_candidates['pred_pnl'] >= 2500]
            elif 'pnl3000' in strategy:
                filtered_candidates = filtered_candidates[filtered_candidates['pred_pnl'] >= 3000]
                
            if 'consensus_trio' in strategy:
                filtered_candidates = filtered_candidates[(filtered_candidates['score'] >= 50) & (filtered_candidates['pred_pnl'] >= 2500)]
            elif 'consensus_duo' in strategy:
                filtered_candidates = filtered_candidates[(filtered_candidates['score'] >= 65) & (filtered_candidates['pred_pnl'] >= 3000)]
                
            if 'trio' in strategy:
                sub_candidates = []
                for _, row in filtered_candidates.iterrows():
                    ticker = row[sc]
                    sector = get_stock_sector(ticker)
                    current_sec_count = sector_counts.get(sector, 0)
                    if current_sec_count < DYN_SECTOR_CAP:
                        sub_candidates.append(row)
                        sector_counts[sector] = current_sec_count + 1
                        if len(sub_candidates) >= 3:
                            break
                for idx, row in enumerate(sub_candidates):
                    qty = 2.0 if idx == 0 else 1.0
                    selected_rows.append((row, qty))
                    
            elif 'duo' in strategy:
                sub_candidates = []
                for _, row in filtered_candidates.iterrows():
                    ticker = row[sc]
                    sector = get_stock_sector(ticker)
                    current_sec_count = sector_counts.get(sector, 0)
                    if current_sec_count < DYN_SECTOR_CAP:
                        sub_candidates.append(row)
                        sector_counts[sector] = current_sec_count + 1
                        if len(sub_candidates) >= 2:
                            break
                for row in sub_candidates:
                    selected_rows.append((row, 2.0))
                    
            elif strategy == 'dynamic_risk_sizer_score':
                sizer_high_score = float(os.getenv('SIZER_HIGH_SCORE_LIMIT', '65.0'))
                sizer_mid_score = float(os.getenv('SIZER_MID_SCORE_LIMIT', '45.0'))
                if os.getenv('ENABLE_DYNAMIC_SIZER_THRESHOLDS', 'False') == 'True' and not test.empty:
                    vol_mult = np.clip(test['volatility_ratio'].mean(), 0.5, 2.0)
                    sizer_high_score = sizer_high_score * vol_mult
                    sizer_mid_score = sizer_mid_score * vol_mult
                for _, row in candidates.iterrows():
                    ticker = row[sc]
                    sector = get_stock_sector(ticker)
                    current_sec_count = sector_counts.get(sector, 0)
                    if current_sec_count < DYN_SECTOR_CAP:
                        qty = 2.0 if row['score'] >= sizer_high_score else (1.0 if row['score'] >= sizer_mid_score else 0.5)
                        if allocated_units + qty <= max_units:
                            selected_rows.append((row, qty))
                            allocated_units += qty
                        elif allocated_units + 0.5 <= max_units:
                            selected_rows.append((row, 0.5))
                            allocated_units += 0.5
                        if allocated_units >= max_units:
                            break
                            
            elif strategy == 'dynamic_risk_sizer_pnl':
                sizer_high_pnl = float(os.getenv('SIZER_HIGH_PNL_LIMIT', '3500.0'))
                sizer_mid_pnl = float(os.getenv('SIZER_MID_PNL_LIMIT', '2000.0'))
                if os.getenv('ENABLE_DYNAMIC_SIZER_THRESHOLDS', 'False') == 'True' and not test.empty:
                    vol_mult = np.clip(test['volatility_ratio'].mean(), 0.5, 2.0)
                    sizer_high_pnl = sizer_high_pnl * vol_mult
                    sizer_mid_pnl = sizer_mid_pnl * vol_mult
                for _, row in candidates.iterrows():
                    ticker = row[sc]
                    sector = get_stock_sector(ticker)
                    current_sec_count = sector_counts.get(sector, 0)
                    if current_sec_count < DYN_SECTOR_CAP:
                        qty = 2.0 if row['pred_pnl'] >= sizer_high_pnl else (1.0 if row['pred_pnl'] >= sizer_mid_pnl else 0.5)
                        if allocated_units + qty <= max_units:
                            selected_rows.append((row, qty))
                            allocated_units += qty
                        elif allocated_units + 0.5 <= max_units:
                            selected_rows.append((row, 0.5))
                            allocated_units += 0.5
                            if allocated_units >= max_units:
                                break
                                
            elif 'golden_booster' in strategy or 'golden_combo' in strategy:
                gold_success_pct = float(os.getenv('GOLD_SUCCESS_PCT_LIMIT', '75.0'))
                gold_avg_pnl = float(os.getenv('GOLD_AVG_PNL_LIMIT', '1000.0'))
                gold_hist_count = int(os.getenv('GOLD_HIST_COUNT_LIMIT', '15'))
                if os.getenv('ENABLE_DYNAMIC_SIZER_THRESHOLDS', 'False') == 'True' and not test.empty:
                    vol_mult = np.clip(test['volatility_ratio'].mean(), 0.5, 2.0)
                    gold_success_pct = np.clip(gold_success_pct * vol_mult, 60.0, 85.0)
                    gold_avg_pnl = gold_avg_pnl * vol_mult
                for _, row in candidates.iterrows():
                    ticker = row[sc]
                    sector = get_stock_sector(ticker)
                    current_sec_count = sector_counts.get(sector, 0)
                    if current_sec_count < DYN_SECTOR_CAP:
                        is_gold = (row['success_pct'] >= gold_success_pct) & (row['avg_pnl'] >= gold_avg_pnl) & (row['hist_count'] >= gold_hist_count)
                        qty = 2.0 if is_gold else 1.0
                        if allocated_units + qty <= max_units:
                            selected_rows.append((row, qty))
                            allocated_units += qty
                        elif allocated_units + 1.0 <= max_units:
                            selected_rows.append((row, 1.0))
                            allocated_units += 1.0
                        if allocated_units >= max_units:
                            break
                            
        if selected_rows:
            pick_rows = []
            for r, qty in selected_rows:
                r_dict = r.to_dict()
                r_dict['qty'] = int(round(qty))
                pick_rows.append(r_dict)
            picks = pd.DataFrame(pick_rows)
        else:
            picks = pd.DataFrame()
            
        if picks.empty:
            daily_log.append({'date': today.strftime('%Y-%m-%d'), 'status': 'NO_TRADES', 'reason': f'Below Rs {current_thr:,.0f} threshold', 'trades': 0, 'pnl': 0.0, 'threshold': current_thr})
        else:
            # Option 3: Performance-Based Capital Scaling (Rolling Win Rate scaling)
            allocation_multiplier = 1.0
            if ENABLE_OPTION_3 and len(daily_log) >= 10:
                # Look at the last 15 days to find traded days
                recent_traded = [entry for entry in daily_log[-15:] if entry['status'] == 'TRADED']
                if recent_traded:
                    recent_wins = sum(1 for entry in recent_traded if entry['pnl'] > 0)
                    recent_win_rate = recent_wins / len(recent_traded)
                    if recent_win_rate >= 0.75:
                        allocation_multiplier = 1.2
                    elif recent_win_rate < 0.55:
                        allocation_multiplier = 0.5
            
            day_pnl = 0.0
            picks_made = []
            for _, row in picks.iterrows():
                qty = int(row['qty'])
                picks_made.append(f"{row[sc]} ({qty}x)")
                trade_pnl = row['pnl'] * qty * allocation_multiplier
                day_pnl += trade_pnl
                trade_log.append({
                    'date': today.strftime('%Y-%m-%d'), 'day': day_name, 'stock': row[sc],
                    'pred_pnl': row['pred_pnl'], 'actual_pnl': trade_pnl, 'threshold_used': current_thr,
                    'multiplier_used': allocation_multiplier, 'qty': qty
                })
            daily_log.append({
                'date': today.strftime('%Y-%m-%d'), 'status': 'TRADED', 'reason': f'Executed {len(picks)} trades',
                'trades': len(picks), 'picks': ", ".join(picks_made), 'pnl': day_pnl, 'threshold': current_thr
            })
            
            # Update threshold logic
            if day_pnl < 0:
                consec_loss += 1
                consec_win = 0
            else:
                consec_win += 1
                consec_loss = 0
                
            # Option 1: Asymmetric Emergency Loss Spike
            emergency_limit = EMERGENCY_LOSS_LIMIT
            if os.getenv('ENABLE_PERCENTAGE_EMERGENCY_LIMIT', 'False') == 'True':
                past_pnls = [entry['pnl'] for entry in daily_log if entry.get('status') == 'TRADED']
                if len(past_pnls) >= 20:
                    std_pnl = np.std(past_pnls[-20:])
                    emergency_limit = -2.5 * std_pnl
                    emergency_limit = np.clip(emergency_limit, -12.5 * pt, -5.0 * pt)
                else:
                    emergency_limit = -5.0 * pt
            elif os.getenv('ENABLE_DYNAMIC_EMERGENCY_LIMIT', 'False') == 'True':
                past_pnls = [entry['pnl'] for entry in daily_log if entry.get('status') == 'TRADED']
                if len(past_pnls) >= 20:
                    std_pnl = np.std(past_pnls[-20:])
                    emergency_limit = -2.5 * std_pnl
                    emergency_limit = np.clip(emergency_limit, -25000.0, -10000.0)
            
            # Step adjustment scaling based on volatility ratio
            raise_step = DYN_RAISE_STEP
            lower_step = DYN_LOWER_STEP
            dyn_max_factor = DYN_MAX_FACTOR
            dyn_min_factor = DYN_MIN_FACTOR
            if not test.empty:
                avg_vol_ratio = test['volatility_ratio'].mean()
                if os.getenv('ENABLE_DYNAMIC_STEPS', 'True') == 'True':
                    vol_mult = np.clip(avg_vol_ratio, 0.5, 2.0)
                    raise_step = DYN_RAISE_STEP * vol_mult
                    lower_step = DYN_LOWER_STEP / vol_mult
                if os.getenv('ENABLE_DYNAMIC_BOUNDS', 'True') == 'True':
                    bounds_mult = np.clip(avg_vol_ratio, 0.7, 1.5)
                    dyn_max_factor = DYN_MAX_FACTOR * bounds_mult
                    dyn_min_factor = DYN_MIN_FACTOR * bounds_mult

            if ENABLE_OPTION_1 and day_pnl <= emergency_limit:
                current_thr = min(current_thr + pt * EMERGENCY_RAISE_STEP, pt * dyn_max_factor)
                consec_loss = 0  # reset consecutive loss since we took emergency action
            else:
                if consec_loss >= dyn_loss_days_trigger:
                    current_thr = min(current_thr + pt * raise_step, pt * dyn_max_factor)
                    consec_loss = 0
                elif consec_win >= dyn_win_days_trigger:
                    current_thr = max(current_thr - pt * lower_step, pt * dyn_min_factor)
                    consec_win = 0
                
        # Option 2: Volatility-Adaptive Threshold Decay
        if ENABLE_OPTION_2 and not test.empty:
            avg_vol_ratio = test['volatility_ratio'].mean()
            multiplier = np.clip(avg_vol_ratio, 0.5, 2.0)
            adjusted_revert_rate = DYN_REVERT_RATE / multiplier
            current_thr = current_thr * (1 - adjusted_revert_rate) + pt * adjusted_revert_rate
        else:
            current_thr = current_thr * (1 - DYN_REVERT_RATE) + pt * DYN_REVERT_RATE
        
        if idx % 100 == 0 or idx == len(all_dates):
            print(f"  Progress: {idx}/{len(all_dates)} days completed...")
            
    # Save the cache if we didn't load it
    if scored_cache:
        os.makedirs(os.path.join(_THIS_DIR, 'output'), exist_ok=True)
        try:
            with open(cache_file, 'wb') as f:
                pickle.dump(scored_cache, f)
            print(f"[+] CACHE SAVED: Saved {len(scored_cache)} days of predictions to {cache_file}!")
        except Exception as e:
            print(f"[-] CACHE SAVE ERROR: {e}")
            
    print("\n[3/4] Compiling metrics...")
    trades_df = pd.DataFrame(trade_log)
    daily_df = pd.DataFrame(daily_log)
    
    os.makedirs(os.path.join(_THIS_DIR, 'output'), exist_ok=True)
    trades_df.to_csv(os.path.join(_THIS_DIR, 'output', 'trades_dynamic_threshold.csv'), index=False)
    daily_df.to_csv(os.path.join(_THIS_DIR, 'output', 'daily_dynamic_threshold.csv'), index=False)
    trades_df.to_csv(os.path.join(_THIS_DIR, 'output', f'trades_dynamic_threshold_{retrain_freq}.csv'), index=False)
    daily_df.to_csv(os.path.join(_THIS_DIR, 'output', f'daily_dynamic_threshold_{retrain_freq}.csv'), index=False)
    
    # Write two-column tick predictions format for user
    if not trades_df.empty:
        formatted_predictions = []
        for _, row in trades_df.iterrows():
            dt_obj = pd.to_datetime(row['date'])
            date_str = dt_obj.strftime('%Y%m%d')
            stock_str = str(row['stock']).strip()
            formatted_predictions.append(f"{date_str}    {stock_str}")
        
        pred_txt_path = os.path.join(_THIS_DIR, 'output', 'tick_predictions.csv')
        with open(pred_txt_path, 'w') as f:
            f.write("\n".join(formatted_predictions) + "\n")
        print(f"[+] Formatted tick predictions written to: {pred_txt_path}")
    
    # Calculate overall CAGR, Max Drawdown, and Sharpe/Sortino ratios
    INITIAL_CAPITAL = float(os.getenv('DYN_INITIAL_CAPITAL', '600000.0'))
    
    daily_df_sorted = daily_df.sort_values('date').copy()
    daily_df_sorted['cumulative_pnl'] = daily_df_sorted['pnl'].cumsum()
    daily_df_sorted['equity'] = INITIAL_CAPITAL + daily_df_sorted['cumulative_pnl']
    daily_df_sorted['peak'] = daily_df_sorted['equity'].cummax()
    daily_df_sorted['drawdown_pct'] = (daily_df_sorted['equity'] - daily_df_sorted['peak']) / daily_df_sorted['peak'] * 100.0
    
    max_dd_pct = daily_df_sorted['drawdown_pct'].min()
    
    # Calculate CAGR
    if not daily_df_sorted.empty:
        start_date = pd.to_datetime(daily_df_sorted['date'].min())
        end_date = pd.to_datetime(daily_df_sorted['date'].max())
        total_days = (end_date - start_date).days
        years = total_days / 365.25
        ending_equity = daily_df_sorted['equity'].iloc[-1]
        if years > 0 and ending_equity > 0:
            cagr = ((ending_equity / INITIAL_CAPITAL) ** (1.0 / years) - 1.0) * 100.0
        else:
            cagr = 0.0
    else:
        cagr = 0.0
        max_dd_pct = 0.0
        years = 0.0
        
    # Calculate Sharpe and Sortino Ratios (Annualized)
    daily_df_sorted['daily_return'] = daily_df_sorted['pnl'] / INITIAL_CAPITAL
    daily_std = daily_df_sorted['daily_return'].std()
    daily_mean = daily_df_sorted['daily_return'].mean()
    
    if daily_std > 0:
        sharpe = (daily_mean / daily_std) * np.sqrt(252)
    else:
        sharpe = 0.0
        
    downside_returns = daily_df_sorted['daily_return'][daily_df_sorted['daily_return'] < 0]
    downside_std = downside_returns.std() if len(downside_returns) > 1 else 0.0
    if downside_std > 0:
        sortino = (daily_mean / downside_std) * np.sqrt(252)
    else:
        sortino = 0.0
        
    print("\n[4/4] DYNAMIC THRESHOLD REPORT SUMMARY")
    print("="*80)
    print(f"Total Trading Days : {len(daily_df)}")
    print(f"Total Trades       : {len(trades_df)}")
    print(f"Overall Win Rate   : {(len(trades_df[trades_df['actual_pnl'] > 0]) / len(trades_df) * 100.0):.1f}%" if not trades_df.empty else "0.0%")
    print(f"Average PnL/Trade  : Rs {trades_df['actual_pnl'].mean():,.2f}" if not trades_df.empty else "Rs 0.00")
    print(f"Total Realized PnL : Rs {trades_df['actual_pnl'].sum():,.2f}" if not trades_df.empty else "Rs 0.00")
    print("-" * 80)
    print(f"Assumed Capital    : Rs {INITIAL_CAPITAL:,.2f}")
    print(f"Overall CAGR       : {cagr:.2f}%")
    print(f"Max Drawdown       : {max_dd_pct:.2f}%")
    print(f"Sharpe Ratio (Ann) : {sharpe:.2f}")
    print(f"Sortino Ratio (Ann): {sortino:.2f}")
    print("="*80)
    
    # Year-by-year Breakdown
    print("\nYEAR-BY-YEAR PERFORMANCE BREAKDOWN")
    print("-" * 80)
    print(f"{'Year':<6} | {'Trade Count':<12} | {'Win Rate':<10} | {'Avg PnL/Trade':<15} | {'Total PnL':<15}")
    print("-" * 80)
    
    if not trades_df.empty:
        trades_df_temp = trades_df.copy()
        trades_df_temp['datetime'] = pd.to_datetime(trades_df_temp['date'])
        trades_df_temp['year'] = trades_df_temp['datetime'].dt.year
        
        years_list = sorted(trades_df_temp['year'].unique())
        for y in years_list:
            y_trades = trades_df_temp[trades_df_temp['year'] == y]
            count = len(y_trades)
            yr_skips = getattr(run_dynamic_threshold, '_skipped_by_year', {}).get(y, 0)
            if count > 0:
                wins = len(y_trades[y_trades['actual_pnl'] > 0])
                win_rate = (wins / count) * 100.0
                avg_pnl = y_trades['actual_pnl'].mean()
                total_pnl = y_trades['actual_pnl'].sum()
                print(f"{y:<6} | {count:<12} | {win_rate:>8.1f}% | Rs {avg_pnl:>11,.2f} | Rs {total_pnl:>11,.2f} | Banned Skips: {yr_skips}")
            else:
                print(f"{y:<6} | {'0':<12} | {'0.0%':>8} | Rs {'0.00':>11} | Rs {'0.00':>11} | Banned Skips: {yr_skips}")
    else:
        print("No trades executed.")
    print("-" * 80 + "\n")

if __name__ == '__main__':
    retrain_freq_arg = 'daily'
    if len(sys.argv) > 1:
        retrain_freq_arg = sys.argv[1].lower()
    start_year_env = int(os.getenv('START_YEAR', '2019'))
    end_year_env = int(os.getenv('END_YEAR', '2025'))
    run_dynamic_threshold(start_year=start_year_env, end_year=end_year_env, retrain_freq=retrain_freq_arg)

    if os.getenv('DISABLE_PDF', 'False').lower() != 'true':
        # Automatically regenerate the PDF comparison report
        print("\nRegenerating PDF Comparison Report...")
        try:
            pdf_script = os.path.join(os.path.dirname(_THIS_DIR), 'scratch', 'generate_pdf.py')
            import subprocess
            subprocess.run(["python3", pdf_script], check=True)
        except Exception as e:
            print(f"Failed to regenerate PDF report: {e}")
