import os
import sys
import warnings
import shutil
import argparse
import pandas as pd
import numpy as np
from datetime import datetime
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings('ignore')

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION & PATHS
# ─────────────────────────────────────────────────────────────────────────────
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR  = os.path.join(_THIS_DIR, 'data')
PNL_CSV   = os.path.join(DATA_DIR, 'markets_pnl0325.csv')
BACKUP_PNL_CSV = os.path.join(DATA_DIR, 'markets_pnl0325_backup.csv')
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

# Dynamic Threshold Constants
DYN_LOSS_DAYS_TRIGGER  = 3
DYN_WIN_DAYS_TRIGGER   = 5
DYN_RAISE_STEP         = 0.30
DYN_LOWER_STEP         = 0.10
DYN_MIN_FACTOR         = 0.60
DYN_MAX_FACTOR         = 2.00
DYN_REVERT_RATE        = 0.08
BASE_THRESHOLD         = 1800.0
MAX_TRADES_PER_DAY     = 4

# SECTOR CONCENTRATION CAPPING
DYN_SECTOR_CAP         = 9999

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
    clean_sym = str(symbol).split('-')[0].strip().upper()
    return sector_mapping.get(clean_sym, sector_mapping.get(str(symbol).strip().upper(), 'Other'))


# Expiry strings (NSE monthly)
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

# Feature Columns
BASE_FEATURE_COLS = [
    'hist_count', 'success_pct', 'avg_pnl', 'std_pnl',
    'rolling_std_30',
    'sharpe_score', 'pf_score', 'conviction_score',
    'recent_wr', 'recent_avg', 'recency_edge',
    'down_wr', 'down_avg',
    'micro_recent_avg', 'micro_recent_wr',
    'short_recent_avg', 'short_recent_wr',
    'volatility_ratio', 'current_streak', 'equity_drawdown_pct',
    'intraday_return', 'intraday_rsi_9', 'intraday_macd',
    'intraday_bb_pct_b', 'first_tick_to_1519_pct', '1450_to_1519_pct', 'Gap_Pct',
    'prev_close_price',
    'daily_open',
    'volume_change_pct',
]

# ─────────────────────────────────────────────────────────────────────────────
# CORE MATHEMATICAL HELPER FUNCTIONS (PARITY WITH MODEL CODES)
# ─────────────────────────────────────────────────────────────────────────────
def log(msg: str):
    print(f"[predict_today] {msg}")

def days_to_next_expiry(dates_series: pd.Series) -> pd.Series:
    expiry_arr = np.array([e.value for e in EXPIRY_DATES], dtype='int64')
    date_vals  = dates_series.values.astype('int64')
    idx = np.searchsorted(expiry_arr, date_vals)
    idx = np.clip(idx, 0, len(EXPIRY_DATES) - 1)
    next_exp = pd.DatetimeIndex([EXPIRY_DATES[i] for i in idx])
    return (next_exp - pd.DatetimeIndex(dates_series.values)).days

def load_pnl() -> pd.DataFrame:
    df = pd.read_csv(PNL_CSV)
    df.columns = df.columns.str.strip().str.lower()
    date_col = next((c for c in df.columns if 'date' in c or 'time' in c), df.columns[0])
    df['dt_parsed'] = pd.to_datetime(df[date_col], dayfirst=True, format='mixed', errors='coerce')
    df = df.dropna(subset=['dt_parsed']).copy()
    df['pnl'] = pd.to_numeric(df['pnl'], errors='coerce')
    df = df.dropna(subset=['pnl']).copy()
    df = df[df['dt_parsed'] >= pd.to_datetime(START_DATE)].copy()
    df = df.sort_values(['stockname', 'dt_parsed']).reset_index(drop=True)
    df['day']       = df['dt_parsed'].dt.day_name()
    df['year']      = df['dt_parsed'].dt.year
    df['month_idx'] = df['dt_parsed'].dt.to_period('M').astype(str)
    df['week_idx']  = df['dt_parsed'].dt.to_period('W').astype(str)
    df['quarter']   = df['dt_parsed'].dt.to_period('Q').astype(str)
    
    # Intraday
    f11_path = os.path.join(DATA_DIR, "f11_intraday_features_all.csv")
    if os.path.exists(f11_path):
        f11 = pd.read_csv(f11_path)
        f11['dt_parsed'] = pd.to_datetime(f11['Date'], format='mixed', dayfirst=True)
        f11 = f11.rename(columns={'Stock': 'stockname'})
        
        # Rename columns dynamically if they end with _pct (for 322 / 1519 / 1522 compatibility)
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

    # Gaps
    gap_path = os.path.join(DATA_DIR, "yahoo_finance_all_stocks_2015_2026_gap_features.csv")
    if os.path.exists(gap_path):
        gap = pd.read_csv(gap_path)
        gap['dt_parsed'] = pd.to_datetime(gap['Date'], format='mixed', dayfirst=True)
        gap = gap.rename(columns={'Stock': 'stockname'})
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
        
    return df

def build_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values(['stockname', 'dt_parsed']).reset_index(drop=True).copy()
    
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

    g_stock = df.groupby('stockname')['pnl']
    
    # Micro-Recency (5 trades)
    df['micro_recent_avg'] = (g_stock.rolling(window=5, min_periods=2).mean()
                               .reset_index(level=0, drop=True)
                               .groupby(df['stockname']).shift(1))
    df['micro_recent_wr']  = (g_stock.rolling(window=5, min_periods=2)
                               .apply(lambda x: (x > 0).mean() * 100, raw=True)
                               .reset_index(level=0, drop=True)
                               .groupby(df['stockname']).shift(1))
                               
    # Short-Recency (10 trades)
    df['short_recent_avg'] = (g_stock.rolling(window=10, min_periods=3).mean()
                               .reset_index(level=0, drop=True)
                               .groupby(df['stockname']).shift(1))
    df['short_recent_wr']  = (g_stock.rolling(window=10, min_periods=3)
                               .apply(lambda x: (x > 0).mean() * 100, raw=True)
                               .reset_index(level=0, drop=True)
                               .groupby(df['stockname']).shift(1))
                               
    # Volatility Ratio
    df['volatility_ratio'] = df['rolling_std_30'] / (df['std_pnl'] + 1.0)
    
    # Streaks
    def get_streak(s):
        s_sign = np.sign(s).replace(0, -1)
        return s_sign.groupby((s_sign != s_sign.shift()).cumsum()).cumsum()
        
    df['current_streak'] = (g_stock.apply(get_streak)
                             .reset_index(level=0, drop=True)
                             .groupby(df['stockname']).shift(1))
                             
    # Equity Drawdown Pct
    cum_pnl = g_stock.cumsum()
    cum_pnl_shifted = cum_pnl.groupby(df['stockname']).shift(1).fillna(0)
    roll_max = cum_pnl_shifted.groupby(df['stockname']).cummax()
    df['equity_drawdown_pct'] = ((roll_max - cum_pnl_shifted) / (roll_max.abs() + 1.0)) * 100.0

    for c in BASE_FEATURE_COLS:
        df[c] = df[c].replace([np.inf, -np.inf], np.nan)

    df = df.dropna(subset=BASE_FEATURE_COLS).reset_index(drop=True)
    return df


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

    top_sets = {
        'Standard Momentum':      sw.head(TOP_N_MOMENTUM)[['Stock', 'Day']].values.tolist(),
        'Rotational Contrarian':  su.head(TOP_N_CONTRARIAN)[['Stock', 'Day']].values.tolist(),
        'Underdog Reversion':     sa.head(TOP_N_UNDERDOG)[['Stock', 'Day']].values.tolist(),
        'Asymmetric Reversion':   sa.head(TOP_N_ASYMMETRIC)[['Stock', 'Day']].values.tolist(),
        'Sharpe Alpha':           ss.head(TOP_N_SHARPE)[['Stock', 'Day']].values.tolist(),
        'EV Leader':              sev.head(TOP_N_EV)[['Stock', 'Day']].values.tolist(),
        'Recency Accelerator':    srec.head(TOP_N_RECENCY)[['Stock', 'Day']].values.tolist(),
        'Profit Factor Champion': spf.head(TOP_N_PF)[['Stock', 'Day']].values.tolist(),
        'Statistical Conviction': sconv.head(TOP_N_CONVICTION)[['Stock', 'Day']].values.tolist(),
        'Momentum Fade':          sfade.head(TOP_N_FADE)[['Stock', 'Day']].values.tolist(),
        'Hot Streak':             shot.head(TOP_N_HOTSTREAK)[['Stock', 'Day']].values.tolist(),
        'Defensive Alpha':        sdef.head(TOP_N_DEFENSIVE)[['Stock', 'Day']].values.tolist(),
    }

    candidate_map = {}
    for strat, pairs in top_sets.items():
        for stock, day in pairs:
            key = (stock, day)
            candidate_map.setdefault(key, set()).add(strat)
    return candidate_map

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

def send_incomplete_telegram_alert(today_dt, missing_reasons):
    """
    Sends a styled Telegram notification when today's run has incomplete feature data
    or no stock candidates, ensuring the user gets today's status explicitly.
    """
    tg_lines = []
    tg_lines.append("🎯 *SNIPER ALGORITHM PREDICTIONS* 🎯")
    tg_lines.append(f"📅 *Date*: {today_dt.strftime('%A, %Y-%m-%d')}")
    tg_lines.append(f"🚪 *Market Status*: INCOMPLETE SESSION")
    tg_lines.append("")
    tg_lines.append("⚠️ *Feature Diagnostics:*")
    for reason in missing_reasons:
        tg_lines.append(f"• {reason}")
    tg_lines.append("")
    tg_lines.append("💡 *Recommendations:*")
    tg_lines.append("• *Static*: [NO TRADES] (Incomplete session / Features missing)")
    tg_lines.append("• *Dynamic*: [NO TRADES] (Incomplete session / Features missing)")
    tg_lines.append("• *Suspensions*: [NO TRADES] (Incomplete session / Features missing)")
    
    tg_msg = "\n".join(tg_lines)
    
    try:
        import subprocess
        bot_path = "/home/ubuntu/telegram_bot/New_OrderInfoBot.js"
        if os.path.exists(bot_path):
            subprocess.run(["node", bot_path, tg_msg], check=True, stdout=subprocess.DEVNULL, timeout=15)
            print("[predict_today] Telegram alert sent for incomplete today's session.")
        else:
            print(f"[predict_today] Warning: OrderInfoBot not found at {bot_path} during incomplete alert")
    except Exception as e:
        print(f"[predict_today] Warning: Failed to send incomplete Telegram alert: {e}")

# ─────────────────────────────────────────────────────────────────────────────
# RETRAINING & PREDICTION HELPER FOR A SPECIFIC FREQUENCY
# ─────────────────────────────────────────────────────────────────────────────
def predict_for_frequency(freq, train, test, today_dt, feats_t1, feats_t2, feats_t3):
    if freq == 'daily':
        train_end = today_dt
    elif freq == 'weekly':
        train_end = today_dt - pd.to_timedelta(today_dt.weekday(), unit='D')
    elif freq == 'monthly':
        train_end = today_dt.to_period('M').start_time
    elif freq == 'quarterly':
        train_end = today_dt.to_period('Q').start_time
    elif freq == 'yearly':
        train_end = today_dt.to_period('Y').start_time
    else:
        train_end = today_dt
        
    three_years_ago = train_end - pd.DateOffset(days=int(3.0 * 365.25))
    train_window = train[(train['dt_parsed'] >= three_years_ago) & (train['dt_parsed'] < train_end)].copy()
    
    # Expiry safety calculations
    expiry_stats = train_window.groupby('days_to_expiry')['pnl'].mean()
    bad_expiry = set(expiry_stats[expiry_stats < FILTER_THRESHOLD].index)
    
    # Apply Static -10% Outlier Filter on training data
    if 'buy_price' in train_window.columns and 'sell_price' in train_window.columns:
        train_window = train_window[
            (train_window['buy_price'] > 0) & 
            (((train_window['sell_price'] - train_window['buy_price']) / train_window['buy_price']) >= -0.10)
        ].copy()
        
    # Target Encode Seasonality
    month_day_stats = train_window.groupby('month_day_key').agg(
        month_hist_avg=('pnl', 'mean'),
        month_hist_wr=('pnl_positive', 'mean')
    )
    train_window = train_window.sort_values('dt_parsed').copy()
    train_window['month_hist_avg'] = (
        train_window.groupby('month_day_key')['pnl']
        .transform(lambda x: x.expanding().mean().shift(1))
        .fillna(0)
    )
    train_window['month_hist_wr'] = (
        train_window.groupby('month_day_key')['pnl_positive']
        .transform(lambda x: x.expanding().mean().shift(1))
        .fillna(0)
    )
    
    # Heuristics mapping
    candidate_map = select_heuristic_candidates(train_window, sc='stockname')
    map_dict = {k: len(v) for k, v in candidate_map.items()}
    train_window['heuristic_count'] = 0
    
    # Train Tower 1
    scaler_t1 = StandardScaler()
    X_train_t1 = scaler_t1.fit_transform(train_window[feats_t1].values)
    model_t1 = Ridge(alpha=3.0, random_state=42).fit(X_train_t1, train_window['pnl'].values)
    res_t1 = train_window['pnl'].values - model_t1.predict(X_train_t1)
    
    # Train Tower 2
    scaler_t2 = StandardScaler()
    X_train_t2 = scaler_t2.fit_transform(train_window[feats_t2].values)
    model_t2 = Ridge(alpha=3.0, random_state=42).fit(X_train_t2, res_t1)
    res_t2 = res_t1 - model_t2.predict(X_train_t2)
    
    # Train Tower 3
    scaler_t3 = StandardScaler()
    X_train_t3 = scaler_t3.fit_transform(train_window[feats_t3].values)
    model_t3 = Ridge(alpha=3.0, random_state=42).fit(X_train_t3, res_t2)
    
    # Predict today
    test_copy = test.copy()
    test_copy['month_hist_avg'] = test_copy['month_day_key'].map(month_day_stats['month_hist_avg']).fillna(0)
    test_copy['month_hist_wr']  = test_copy['month_day_key'].map(month_day_stats['month_hist_wr']).fillna(0)
    test_copy['heuristic_count'] = [map_dict.get((s, d), 0) for s, d in zip(test_copy['stockname'], test_copy['day'])]
    
    X_test_t1 = scaler_t1.transform(test_copy[feats_t1].values)
    pred_test_t1 = model_t1.predict(X_test_t1)
    
    X_test_t2 = scaler_t2.transform(test_copy[feats_t2].values)
    pred_test_t2 = model_t2.predict(X_test_t2)
    
    X_test_t3 = scaler_t3.transform(test_copy[feats_t3].values)
    pred_test_t3 = model_t3.predict(X_test_t3)
    
    pred_pnl = pred_test_t1 + pred_test_t2 + pred_test_t3
    return pred_pnl, pred_test_t1, pred_test_t2, pred_test_t3, bad_expiry

# ─────────────────────────────────────────────────────────────────────────────
# MAIN ORCHESTRATION PIPELINE
# ─────────────────────────────────────────────────────────────────────────────
def main():
    log("=" * 80)
    log("SNIPER ALGORITHM - TODAY'S PREDICTIONS GENERATOR")
    log("=" * 80)
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Predict trading candidates for a target date.")
    parser.add_argument('--date', type=str, help="Target date in DD-MM-YYYY or YYYY-MM-DD format (default: latest in files)")
    parser.add_argument('--retrain-freq', type=str, choices=['daily', 'monthly', 'yearly', 'ensemble'], default='ensemble',
                        help="Walk-forward retraining frequency (default: ensemble)")
    args = parser.parse_args()
    
    # Step 1: Detect target date
    log("Checking latest dates in feature files...")
    f11_path = os.path.join(DATA_DIR, "f11_intraday_features_all.csv")
    gap_path = os.path.join(DATA_DIR, "yahoo_finance_all_stocks_2015_2026_gap_features.csv")
    
    if not os.path.exists(f11_path) or not os.path.exists(gap_path):
        log("ERROR: Intraday or Gap features CSV files do not exist! Update sheets first.")
        sys.exit(1)
        
    df_f11 = pd.read_csv(f11_path)
    
    # Rename columns dynamically if they end with _pct (for 322 / 1519 / 1522 compatibility)
    rename_dict = {}
    for col in df_f11.columns:
        if col.startswith('first_tick_to_15') and col.endswith('_pct'):
            rename_dict[col] = 'first_tick_to_1519_pct'
        if col.startswith('1450_to_15') and col.endswith('_pct'):
            rename_dict[col] = '1450_to_1519_pct'
    if rename_dict:
        df_f11 = df_f11.rename(columns=rename_dict)
        
    df_f11['parsed_date'] = pd.to_datetime(df_f11['Date'], format='mixed', dayfirst=True)
    
    if args.date:
        try:
            today_dt = pd.to_datetime(args.date, format='mixed', dayfirst=True)
            today_str = today_dt.strftime('%d-%m-%Y')
            log(f"Using user-specified target date: {today_dt.strftime('%Y-%m-%d')} ({today_str})")
        except Exception as e:
            log(f"ERROR: Invalid date format: {args.date}. Please use DD-MM-YYYY or YYYY-MM-DD.")
            sys.exit(1)
    else:
        today_dt = pd.to_datetime(datetime.now().date())
        today_str = today_dt.strftime('%d-%m-%Y')
        log(f"No target date specified. Defaulting to today's calendar date: {today_dt.strftime('%Y-%m-%d')} ({today_str})")
        
    # Data-Driven Feature Completeness Check & Self-Cleaning Engine
    now_dt = datetime.now()
    is_today = (today_dt.date() == now_dt.date())
    
    df_f11_today = df_f11[df_f11['parsed_date'] == today_dt]
    
    missing_features = []
    has_incomplete_features = False
    
    if is_today:
        if len(df_f11_today) == 0:
            missing_features = [
                'first_tick_to_1519_pct (No today data found)',
                '1450_to_1519_pct (No today data found)',
                'intraday_volume_ratio (No today data found)',
                'intraday_return (No today data found)',
                'intraday_rsi_9 (No today data found)'
            ]
            has_incomplete_features = True
        else:
            # Specific features we check for NaN or incompleteness
            features_to_check = {
                'first_tick_to_1519_pct': 'first_tick_to_1519_pct (3:19 PM close-to-open gap)',
                '1450_to_1519_pct': '1450_to_1519_pct (2:50 PM to 3:19 PM momentum)',
                'intraday_volume_ratio': 'intraday_volume_ratio (complete session bar ratio)',
                'intraday_return': 'intraday_return (full session intraday returns)',
                'intraday_rsi_9': 'intraday_rsi_9 (full session relative strength index)'
            }
            for col, display in features_to_check.items():
                if col not in df_f11_today.columns or df_f11_today[col].isna().all():
                    missing_features.append(display)
                    has_incomplete_features = True
                    
    if is_today and has_incomplete_features:
        print("\n" + "="*80)
        print("❌ OPERATIONS ERROR: INCOMPLETE FEATURE DATA DETECTED")
        print("="*80)
        print(f"Target Date         : {today_dt.strftime('%A, %Y-%m-%d')} (Today)")
        print(f"Current System Time : {now_dt.strftime('%I:%M %p (%H:%M:%S)')}")
        print("-" * 80)
        print("⚠️ The following features are ABSENT or DEFAULTED (NaN) in your sheets:")
        print("-------------------------------------------------------------------------")
        for f in missing_features:
            print(f"• {f} : ❌ ABSENT / DEFAULTED (NaN)")
        print("-" * 80)
        print("🧹 [CLEANUP] Intermediate run detected. Cleaning database & CSVs to prevent inconsistencies...")
        
        # 1. Clear MySQL 'scrapdata' for today
        try:
            import pymysql
            conn = pymysql.connect(host='localhost', user='root', password='root', database='markets')
            cursor = conn.cursor()
            date_sql = today_dt.strftime('%Y-%m-%d')
            cursor.execute("DELETE FROM scrapdata WHERE DATE(time) = %s", (date_sql,))
            conn.commit()
            print(f"  ✔ MySQL 'scrapdata' table cleaned for {date_sql} ({cursor.rowcount} rows deleted).")
            cursor.close()
            conn.close()
        except Exception as e:
            print(f"  ⚠️ Warning: Failed to clean MySQL table: {e}")
            
        # 2. Clear f11_intraday_features_all.csv for today
        try:
            mask = df_f11['parsed_date'].dt.date == today_dt.date()
            if mask.any():
                df_f11 = df_f11[~mask].copy()
                df_f11.drop(columns=['parsed_date'], inplace=True, errors='ignore')
                df_f11.to_csv(f11_path, index=False)
                print(f"  ✔ 'f11_intraday_features_all.csv' cleared for today's date.")
        except Exception as e:
            print(f"  ⚠️ Warning: Failed to clear F11 CSV: {e}")
            
        # 3. Clear yahoo_finance_all_stocks_2015_2026_gap_features.csv for today
        try:
            df_gap_tmp = pd.read_csv(gap_path)
            df_gap_tmp['parsed_dt'] = pd.to_datetime(df_gap_tmp['Date'], format='mixed', dayfirst=True)
            mask_gap = df_gap_tmp['parsed_dt'].dt.date == today_dt.date()
            if mask_gap.any():
                df_gap_tmp = df_gap_tmp[~mask_gap].copy()
                df_gap_tmp.drop(columns=['parsed_dt'], inplace=True, errors='ignore')
                df_gap_tmp.to_csv(gap_path, index=False)
                print(f"  ✔ 'yahoo_finance_all_stocks_2015_2026_gap_features.csv' cleared for today.")
        except Exception as e:
            print(f"  ⚠️ Warning: Failed to clear Gap CSV: {e}")
            
        print("-" * 80)
        print("👉 Action Required : Please run your downloader and prediction pipeline AFTER 3:15 PM")
        print("                     to obtain full, completed session ticks and features.")
        print("=========================================================================\n")
        
        # Send Telegram alert for incomplete today's session
        send_incomplete_telegram_alert(today_dt, missing_features)
        sys.exit(1)
    
    # Step 2: Back up PnL sheet
    log(f"Creating backup of original {PNL_CSV} to prevent permanent contamination...")
    shutil.copyfile(PNL_CSV, BACKUP_PNL_CSV)
    
    try:
        # Step 3: Temporary append placeholder rows for today
        log("Identifying stocks with today's live features...")
        df_gap_raw = pd.read_csv(gap_path)
        df_gap_raw['parsed_date'] = pd.to_datetime(df_gap_raw['Date'], format='mixed', dayfirst=True)
        
        # Read the raw PnL file to copy its exact schema and append today's dummy rows
        df_pnl_orig = pd.read_csv(PNL_CSV)
        df_pnl_orig.columns = df_pnl_orig.columns.str.strip().str.lower()
        
        # Load unique valid stock names from the PnL sheet (the actual F&O/futures-enabled universe)
        # Load unique valid stock names from the PnL sheet (the actual F&O/futures-enabled universe)
        valid_pnl_stocks = set(df_pnl_orig['stockname'].dropna().unique())
        
        # Load currently active F&O stocks with futures from masterfile to filter out non-futures stocks
        master_path = os.path.join(DATA_DIR, 'masterfile.csv')
        if os.path.exists(master_path):
            df_master = pd.read_csv(master_path)
            if 'stockCodes' in df_master.columns:
                active_fo_stocks = set(df_master['stockCodes'].dropna().unique())
                log(f"Loaded {len(active_fo_stocks)} active F&O stocks from masterfile.csv.")
            else:
                active_fo_stocks = set()
                log("⚠️ [WARNING] 'stockCodes' column not found in masterfile.csv. Active F&O stock filter bypassed.")
        else:
            active_fo_stocks = set()
            log("⚠️ [WARNING] masterfile.csv not found in data/. Active F&O stock filter bypassed.")
        
        # Intersection of stocks that have today's features in both files AND exist in our F&O universe
        f11_today_stocks = set(df_f11[df_f11['parsed_date'] == today_dt]['Stock'].unique())
        gap_today_stocks = set(df_gap_raw[df_gap_raw['parsed_date'] == today_dt]['Stock'].unique())
        
        intersection_set = f11_today_stocks.intersection(gap_today_stocks).intersection(valid_pnl_stocks)
        if active_fo_stocks:
            intersection_set = intersection_set.intersection(active_fo_stocks)
            
        today_stocks = sorted(list(intersection_set))
        
        log(f"Found {len(today_stocks)} unique F&O stocks with complete intraday and gap features for today.")
        if len(today_stocks) == 0:
            log("=========================================================================")
            log("❌ ERROR: No stock data found for today's target date.")
            log("=========================================================================")
            if len(f11_today_stocks) == 0:
                log(f"  ⚠️ [MISSING DATA] F11 Intraday features (f11_intraday_features_all.csv) contain 0 rows for target date: {today_dt.strftime('%Y-%m-%d')}")
            else:
                log(f"  ✔ F11 Intraday features have data for {len(f11_today_stocks)} stocks.")
                
            if len(gap_today_stocks) == 0:
                log(f"  ⚠️ [MISSING DATA] Yahoo/ICICI Gap features (yahoo_finance_all_stocks_2015_2026_gap_features.csv) contain 0 rows for target date: {today_dt.strftime('%Y-%m-%d')}")
            else:
                log(f"  ✔ Gap features have data for {len(gap_today_stocks)} stocks.")
                
            if len(f11_today_stocks) > 0 and len(gap_today_stocks) > 0:
                log("  ⚠️ [ALIGNMENT ERROR] Both files have data, but there is zero stock intersection.")
                log(f"    - F11 stocks: {list(f11_today_stocks)[:5]}... (total {len(f11_today_stocks)})")
                log(f"    - Gap stocks: {list(gap_today_stocks)[:5]}... (total {len(gap_today_stocks)})")
                
            log("\n👉 DIAGNOSTIC: To enable predictions for today, please run the daily downloader pipeline first:")
            log("   ./pipeline/run_todays_prediction_pipeline.sh  (or manually run: node 6.icici_daily_intraday_and_gap.js)")
            log("=========================================================================")
            
            diag_reasons = []
            if len(f11_today_stocks) == 0:
                diag_reasons.append("F11 Intraday features CSV contains 0 rows for today")
            if len(gap_today_stocks) == 0:
                diag_reasons.append("Gap features CSV contains 0 rows for today")
            if len(f11_today_stocks) > 0 and len(gap_today_stocks) > 0:
                diag_reasons.append("Zero stock intersection between features")
            send_incomplete_telegram_alert(today_dt, diag_reasons)
            sys.exit(1)
            
        # Read the raw PnL file to copy its exact schema and append today's dummy rows
        df_pnl_orig = pd.read_csv(PNL_CSV)
        # Remove any existing rows for today in PnL sheet to prevent overlap
        df_pnl_orig.columns = df_pnl_orig.columns.str.strip().str.lower()
        date_col = next((c for c in df_pnl_orig.columns if 'date' in c or 'time' in c), df_pnl_orig.columns[0])
        df_pnl_orig['parsed_date'] = pd.to_datetime(df_pnl_orig[date_col], dayfirst=True, format='mixed', errors='coerce')
        df_pnl_clean = df_pnl_orig[df_pnl_orig['parsed_date'] != today_dt].copy()
        
        # Build dummy rows
        dummy_rows = []
        for stock in today_stocks:
            dummy_row = {col: "" for col in df_pnl_clean.columns if col != 'parsed_date'}
            dummy_row[date_col] = today_str
            dummy_row['stockname'] = stock
            dummy_row['pnl'] = 0.0
            dummy_rows.append(dummy_row)
            
        df_dummy = pd.DataFrame(dummy_rows)
        df_pnl_temp = pd.concat([df_pnl_clean, df_dummy], ignore_index=True)
        df_pnl_temp.drop(columns=['parsed_date'], inplace=True, errors='ignore')
        
        # Save temporary PnL sheet
        df_pnl_temp.to_csv(PNL_CSV, index=False)
        log(f"Successfully appended {len(dummy_rows)} placeholder rows to PnL sheet temporarily.")
        
        # Step 4: Load and run feature engineering over the entire dataset
        log("Loading and building expanding causal features...")
        df_raw = load_pnl()
        df_feats = build_features(df_raw)
        
        # Precomputations for speedup
        df_feats['month'] = df_feats['dt_parsed'].dt.month
        df_feats['month_day_key'] = df_feats['month'].astype(str) + "_" + df_feats['day']
        df_feats['pnl_positive'] = (df_feats['pnl'] > 0).astype(float)
        
        # Isolate today's predictions test set
        test = df_feats[df_feats['dt_parsed'] == today_dt].copy()
        train = df_feats[df_feats['dt_parsed'] < today_dt].copy()
        
        log(f"Total training dataset size: {len(train):,} rows (from {train['dt_parsed'].min().date()} to {train['dt_parsed'].max().date()})")
        log(f"Total prediction candidates size: {len(test):,} rows")
        
        if test.empty:
            log("ERROR: Engineered prediction candidates are empty. Ensure dates align in F11 and Gap CSVs.")
            sys.exit(1)
            
        # Friday Lock check
        day_name = today_dt.day_name()
        if day_name == 'Friday':
            log("WARNING: Today is Friday. Standard Friday Lock is in effect. All trading strategies will skip this day.")
            
        # Step 5: Walk-forward model retraining
        feats_t1 = [f for f in BASE_FEATURE_COLS if f != 'days_to_expiry']
        feats_t2 = ['month_hist_avg', 'month_hist_wr']
        feats_t3 = ['days_to_expiry', 'heuristic_count']

        if args.retrain_freq == 'ensemble':
            log("Retraining Multi-Frequency Ridge ensemble models (Daily, Weekly, Monthly, Quarterly, Yearly)...")
            frequencies = ['daily', 'weekly', 'monthly', 'quarterly', 'yearly']
            freq_preds = {}
            freq_t1 = {}
            freq_t2 = {}
            freq_t3 = {}
            bad_exp_set = set()
            
            for freq in frequencies:
                log(f"  -> Retraining frequency model: {freq}...")
                p_pnl, p_t1, p_t2, p_t3, bad_exp = predict_for_frequency(freq, train, test, today_dt, feats_t1, feats_t2, feats_t3)
                freq_preds[freq] = p_pnl
                freq_t1[freq] = p_t1
                freq_t2[freq] = p_t2
                freq_t3[freq] = p_t3
                bad_exp_set.update(bad_exp)
                
            log("Forming Dual-Metric Hybrid Ensemble score combination...")
            # Retrieve rolling 15-trade actual outcomes from master P&L sheet
            log("Computing trailing performance metrics for Dual-Metric Regime Switcher...")
            df_pnl_hist = pd.read_csv(PNL_CSV)
            df_pnl_hist['parsed_date'] = pd.to_datetime(df_pnl_hist['simulationdate'], format='mixed', dayfirst=True, errors='coerce')
            df_pnl_hist = df_pnl_hist.dropna(subset=['parsed_date']).sort_values('parsed_date')
            
            # Get the actual pnl of the last 15 non-zero trades
            df_non_zero_trades = df_pnl_hist[df_pnl_hist['pnl'] != 0.0]
            recent_trades = df_non_zero_trades['pnl'].tail(15).values.tolist()
            
            if len(recent_trades) >= 10:
                wins = sum(1 for p in recent_trades if p > 0)
                trailing_wr = wins / 10.0
                trailing_avg_pnl = sum(recent_trades) / 10.0
            else:
                # Default Neutral state for warm-ups (no aggressive forcing!)
                trailing_wr = 0.65
                trailing_avg_pnl = 800.0
                
            log(f"Trailing Win Rate (10-trade lookback): {trailing_wr:.1%}, Trailing Avg P&L: Rs {trailing_avg_pnl:,.2f}")
            
            # Determine k_base (Lookahead-Free Optimized 2026 Parameters)
            if trailing_wr >= 0.85 and trailing_avg_pnl >= 2500.0:
                k_base = 0.00
                regime_name = "OPTIMIZED SUPER-TRIMMED MOMENTUM (K=0.00)"
            elif trailing_wr >= 0.70 or trailing_avg_pnl >= 1000.0:
                k_base = 0.10
                regime_name = "OPTIMIZED TRIMMED (K=0.10)"
            elif trailing_wr < 0.60 and trailing_avg_pnl < 500.0:
                k_base = 0.50
                regime_name = "OPTIMIZED DEFENSIVE (K=0.50)"
            else:
                k_base = 0.20
                regime_name = "OPTIMIZED ADAPTIVE STANDARD (K=0.20)"
                
            log(f"Active Regime: {regime_name}")
            
            # Compute disagreement-based normalization baseline
            stacked_df = pd.DataFrame({f: freq_preds[f] for f in frequencies})
            median_std_file = os.path.join(_THIS_DIR, 'output', 'daily_medians_std.csv')
            
            daily_std_devs = stacked_df.std(axis=1).values
            today_median_std = np.median(daily_std_devs) if len(daily_std_devs) > 0 else 1500.0
            
            historical_medians = []
            if os.path.exists(median_std_file):
                try:
                    df_meds = pd.read_csv(median_std_file)
                    df_meds['date'] = pd.to_datetime(df_meds['date'])
                    df_meds_past = df_meds[df_meds['date'] < today_dt].sort_values('date')
                    historical_medians = df_meds_past['median_std'].tail(30).tolist()
                except Exception as e:
                    log(f"Warning: Could not read historical medians file: {e}")
                    
            if len(historical_medians) < 30:
                needed = 30 - len(historical_medians)
                historical_medians = [1500.0] * needed + historical_medians
                
            baseline_std = np.mean(historical_medians) if len(historical_medians) > 0 else 1500.0
            if baseline_std <= 0:
                baseline_std = 1500.0
                
            log(f"Today's Median Disagreement: Rs {today_median_std:.2f}, Normalization Baseline: Rs {baseline_std:.2f}")
            
            # Calculate combined prediction scores for each stock candidate
            combined_preds = []
            combined_t1 = []
            combined_t2 = []
            combined_t3 = []
            
            for idx in range(len(test)):
                preds_row = [freq_preds[f][idx] for f in frequencies]
                std_dev = np.std(preds_row)
                
                K_dyn = k_base * (std_dev / baseline_std)
                K_dyn = max(0.0, min(1.5, K_dyn))
                
                # Trimmed mean
                sorted_preds = sorted(preds_row)
                trimmed = sorted_preds[1:-1] if len(sorted_preds) >= 4 else sorted_preds
                trimmed_mean_val = np.mean(trimmed) if len(trimmed) > 0 else np.median(preds_row)
                
                combined_val = trimmed_mean_val - K_dyn * std_dev
                combined_preds.append(combined_val)
                
                # Trimmed sub-tower predictions for structural visibility
                combined_t1.append(np.mean(sorted([freq_t1[f][idx] for f in frequencies])[1:-1]))
                combined_t2.append(np.mean(sorted([freq_t2[f][idx] for f in frequencies])[1:-1]))
                combined_t3.append(np.mean(sorted([freq_t3[f][idx] for f in frequencies])[1:-1]))
                
            test['pred_pnl'] = combined_preds
            test['pred_t1']  = combined_t1
            test['pred_t2']  = combined_t2
            test['pred_t3']  = combined_t3
            
            bad_expiry = bad_exp_set
            test_scored = score_all_candidates(test, bad_expiry)
            
            # Append today's median std_dev lookahead-free tracking
            os.makedirs(os.path.dirname(median_std_file), exist_ok=True)
            try:
                date_key_str = today_dt.strftime('%Y-%m-%d')
                new_row = pd.DataFrame([{'date': date_key_str, 'median_std': today_median_std}])
                if os.path.exists(median_std_file):
                    try:
                        df_meds_existing = pd.read_csv(median_std_file)
                        df_meds_existing = df_meds_existing[df_meds_existing['date'] != date_key_str].copy()
                        df_meds_combined = pd.concat([df_meds_existing, new_row], ignore_index=True)
                        df_meds_combined.to_csv(median_std_file, index=False)
                    except Exception as parse_med_err:
                        # Fallback to appending if read fails
                        new_row.to_csv(median_std_file, mode='a', header=False, index=False)
                else:
                    new_row.to_csv(median_std_file, index=False)
            except Exception as e:
                log(f"Warning: Could not save today's median standard deviation: {e}")
                
        else:
            log(f"Retraining Ridge ensemble models using {args.retrain_freq} walk-forward (restricted to the last 3 years of historical window)...")
            p_pnl, p_t1, p_t2, p_t3, bad_exp = predict_for_frequency(args.retrain_freq, train, test, today_dt, feats_t1, feats_t2, feats_t3)
            
            test['pred_pnl'] = p_pnl
            test['pred_t1']  = p_t1
            test['pred_t2']  = p_t2
            test['pred_t3']  = p_t3
            
            bad_expiry = bad_exp
            test_scored = score_all_candidates(test, bad_expiry)
        
        # Step 7: Determine today's dynamic threshold and suspension states from existing CSV logs
        log("Calculating today's dynamic threshold and stock suspension states from historical logs...")
        
        # Tracker states
        current_thr = 1800.0
        consec_loss = 0
        consec_win = 0
        stock_consec_losses = {}
        stock_cum_pnl = {}
        stock_suspension_end = {}
        
        trades_dt_path = os.path.join(_THIS_DIR, 'output', 'trades_dynamic_threshold.csv')
        trades_ts_path = os.path.join(_THIS_DIR, 'output', 'trades_ticker_suspension.csv')
        daily_dt_path = os.path.join(_THIS_DIR, 'output', 'daily_dynamic_threshold.csv')
        
        # Track today's DTE
        days_to_expiry = test['days_to_expiry'].iloc[0]
        is_friday_lock = (day_name == 'Friday')
        is_toxic_expiry = (days_to_expiry in bad_expiry)
        
        # Calculate dynamic threshold from history
        if os.path.exists(daily_dt_path):
            try:
                df_daily_dt = pd.read_csv(daily_dt_path)
                df_daily_dt['parsed_date'] = pd.to_datetime(df_daily_dt['date'])
                df_daily_dt_past = df_daily_dt[df_daily_dt['parsed_date'] < today_dt].sort_values('parsed_date')
                
                # Replay threshold logic on the historical sequence to find current_thr today
                current_thr = 1800.0
                consec_loss = 0
                consec_win = 0
                past_traded_pnls = []
                
                for _, row in df_daily_dt_past.iterrows():
                    status = row.get('status', '')
                    pnl = float(row.get('pnl', 0.0))
                    d_name = pd.to_datetime(row['date']).day_name()
                    
                    row_date = pd.to_datetime(row['date'])
                    df_date_feats = df_feats[df_feats['dt_parsed'] == row_date]
                    avg_vol_ratio = df_date_feats['volatility_ratio'].mean() if not df_date_feats.empty else 1.0
                    
                    vol_mult = np.clip(avg_vol_ratio, 0.5, 2.0)
                    raise_step = DYN_RAISE_STEP * vol_mult
                    lower_step = DYN_LOWER_STEP / vol_mult
                    
                    bounds_mult = np.clip(avg_vol_ratio, 0.7, 1.5)
                    dyn_max_factor = DYN_MAX_FACTOR * bounds_mult
                    dyn_min_factor = DYN_MIN_FACTOR * bounds_mult
                    
                    adjusted_revert_rate = DYN_REVERT_RATE / vol_mult
                    
                    if d_name == 'Friday':
                        current_thr = current_thr * (1 - adjusted_revert_rate) + BASE_THRESHOLD * adjusted_revert_rate
                        continue
                        
                    if 'Toxic Expiry' in str(row.get('reason', '')):
                        current_thr = current_thr * (1 - adjusted_revert_rate) + BASE_THRESHOLD * adjusted_revert_rate
                        continue
                        
                    if status == 'TRADED':
                        past_traded_pnls.append(pnl)
                        emergency_limit = -99999999.0
                        if len(past_traded_pnls) >= 20:
                            std_pnl = np.std(past_traded_pnls[-20:])
                            emergency_limit = -2.5 * std_pnl
                            emergency_limit = np.clip(emergency_limit, -25000.0, -10000.0)
                            
                        if pnl <= emergency_limit:
                            current_thr = min(current_thr + BASE_THRESHOLD * 1.20, BASE_THRESHOLD * dyn_max_factor)
                            consec_loss = 0
                        else:
                            if pnl < 0:
                                consec_loss += 1
                                consec_win = 0
                            else:
                                consec_win += 1
                                consec_loss = 0
                                
                            if consec_loss >= DYN_LOSS_DAYS_TRIGGER:
                                current_thr = min(current_thr + BASE_THRESHOLD * raise_step, BASE_THRESHOLD * dyn_max_factor)
                                consec_loss = 0
                            elif consec_win >= DYN_WIN_DAYS_TRIGGER:
                                current_thr = max(current_thr - BASE_THRESHOLD * lower_step, BASE_THRESHOLD * dyn_min_factor)
                                consec_win = 0
                                
                    current_thr = current_thr * (1 - adjusted_revert_rate) + BASE_THRESHOLD * adjusted_revert_rate
                    
                log(f"Calculated Dynamic Threshold for today: Rs {current_thr:,.2f}")
            except Exception as e:
                log(f"Warning: Could not compute dynamic threshold from existing logs: {e}. Falling back to default.")
                current_thr = BASE_THRESHOLD
        else:
            log("No daily dynamic threshold log found. Using baseline threshold: Rs 1800.00")
            current_thr = BASE_THRESHOLD

        # Calculate suspensions from trades history
        if os.path.exists(trades_ts_path):
            try:
                df_trades_ts = pd.read_csv(trades_ts_path)
                df_trades_ts['parsed_date'] = pd.to_datetime(df_trades_ts['date'])
                df_trades_ts_past = df_trades_ts[df_trades_ts['parsed_date'] < today_dt].sort_values('parsed_date')
                
                # Reconstruct stock suspension states
                stock_consec_losses = {}
                stock_cum_pnl = {}
                stock_suspension_end = {}
                
                for _, row in df_trades_ts_past.iterrows():
                    trade_date = pd.to_datetime(row['date'])
                    stock = row['stock']
                    pnl = float(row['actual_pnl'])
                    
                    # Update trackers
                    stock_cum_pnl[stock] = stock_cum_pnl.get(stock, 0.0) + pnl
                    if pnl < 0:
                        stock_consec_losses[stock] = stock_consec_losses.get(stock, 0) + 1
                    else:
                        stock_consec_losses[stock] = 0
                        
                    # Suspend check
                    if stock_consec_losses[stock] >= 2 or stock_cum_pnl[stock] <= -15000.0:
                        stock_suspension_end[stock] = trade_date + pd.Timedelta(days=30)
                        stock_consec_losses[stock] = 0
                        stock_cum_pnl[stock] = 0.0
                        
                # Identify currently suspended stocks today
                suspended_stocks_today = [stock for stock, end_date in stock_suspension_end.items() if today_dt < end_date]
                log(f"Suspended stocks today: {suspended_stocks_today}")
            except Exception as e:
                log(f"Warning: Could not compute ticker suspensions from logs: {e}.")
                suspended_stocks_today = []
        else:
            suspended_stocks_today = []

        # Step 8: Apply signals and extract recommendations for all 3 strategies
        # Filter non-duplicated and sort
        test_candidates = test_scored.drop_duplicates(subset=['stockname']).sort_values('pred_pnl', ascending=False)
        
        # F&O Banlist Filter Integration:
        # Load ban list set for today to filter candidates with zero lookahead bias
        ban_path = '/home/ubuntu/banlist/fo_ban_list_historical.csv'
        banned_today = set()
        if os.path.exists(ban_path):
            try:
                banlist_df = pd.read_csv(ban_path)
                banlist_df['parsed_date'] = pd.to_datetime(banlist_df['date'], dayfirst=True, format='mixed')
                banlist_df['stock_upper'] = banlist_df['stock_name'].str.strip().str.upper()
                
                # Filter banlist for today
                banned_today = set(banlist_df[banlist_df['parsed_date'] == today_dt]['stock_upper'])
                log(f"Loaded F&O Banlist from {ban_path}. Banned stocks today: {banned_today}")
            except Exception as e_ban:
                log(f"⚠️ Warning: Could not load F&O Ban list: {e_ban}")
        else:
            log(f"⚠️ [WARNING] F&O Ban list file not found at {ban_path}")

        # Filter candidates to only non-banned stocks
        if banned_today and not test_candidates.empty:
            before_ban_count = len(test_candidates)
            test_candidates = test_candidates[~test_candidates['stockname'].str.strip().str.upper().isin(banned_today)].copy()
            log(f"Filtered out F&O Banned stocks today: removed {before_ban_count - len(test_candidates)} candidates. Remaining: {len(test_candidates)}")
            
        # ─────────────────────────────────────────────────────────────────────
        # STRATEGY 1: STATIC BASELINE (THRESHOLD = 1800)
        # ─────────────────────────────────────────────────────────────────────
        picks_baseline = []
        if not is_friday_lock and not is_toxic_expiry:
            picks_baseline = test_candidates[test_candidates['pred_pnl'] > BASE_THRESHOLD].head(MAX_TRADES_PER_DAY)
            
        # ─────────────────────────────────────────────────────────────────────
        # STRATEGY 2: DYNAMIC THRESHOLD (THRESHOLD = current_thr)
        # ─────────────────────────────────────────────────────────────────────
        picks_dynamic = []
        if not is_friday_lock and not is_toxic_expiry:
            picks_dynamic = test_candidates[test_candidates['pred_pnl'] > current_thr].head(MAX_TRADES_PER_DAY)
            
        # ─────────────────────────────────────────────────────────────────────
        # STRATEGY 3: TICKER SUSPENSION (THRESHOLD = 1800 + SUSPENSIONS)
        # ─────────────────────────────────────────────────────────────────────
        picks_suspension = []
        if not is_friday_lock and not is_toxic_expiry:
            non_suspended_candidates = test_candidates[~test_candidates['stockname'].isin(suspended_stocks_today)]
            picks_suspension = non_suspended_candidates[non_suspended_candidates['pred_pnl'] > BASE_THRESHOLD].head(MAX_TRADES_PER_DAY)
            
        # ─────────────────────────────────────────────────────────────────────
        # STRATEGY 4: GOLDEN WEEKDAY COMBO (BYPASS THRESHOLD + 2.0X SIZING)
        # ─────────────────────────────────────────────────────────────────────
        picks_golden_combo = []
        if not is_friday_lock and not is_toxic_expiry:
            allocated_units = 0.0
            max_units = 4.0
            sector_counts = {}
            for _, r in test_candidates.iterrows():
                ticker = r['stockname']
                sector = get_stock_sector(ticker)
                
                # Enforce sector concentration limit (maximum 1 trade per sector)
                current_sec_count = sector_counts.get(sector, 0)
                if current_sec_count >= DYN_SECTOR_CAP:
                    continue
                    
                # Check if it passes standard threshold OR is golden bypass setup (Fully Volatility-Adjusted)
                is_gold_setup = (r['success_pct'] >= 75.0) & (r['avg_pnl'] >= r['std_pnl'] * 0.40) & (r['hist_count'] >= 15)
                is_golden_bypass = is_gold_setup & (r['pred_pnl'] >= r['std_pnl'] * 0.32)
                
                if (r['pred_pnl'] > current_thr) or is_golden_bypass:
                    qty = 2.0 if is_gold_setup else 1.0
                    if allocated_units + qty <= max_units:
                        picks_golden_combo.append((r, qty))
                        allocated_units += qty
                        sector_counts[sector] = current_sec_count + 1
                    elif allocated_units + 1.0 <= max_units:
                        picks_golden_combo.append((r, 1.0))
                        allocated_units += 1.0
                        sector_counts[sector] = current_sec_count + 1
                    if allocated_units >= max_units:
                        break

            
        # Print Beautiful Summary Report
        print("\n" + "="*90)
        print(f"                        SNIPER ALGORITHM PRODUCTION TRADING CANDIDATES")
        print(f"                       TARGET DATE: {today_dt.strftime('%A, %Y-%m-%d')} ({today_str})")
        print("="*90)
        print(f"Market Status      : {'FRIDAY LOCK (NO TRADES)' if is_friday_lock else 'ACTIVE'}")
        print(f"Expiry Safety Lock : {'TOXIC EXPIRY (NO TRADES - DTE: ' + str(days_to_expiry) + ')' if is_toxic_expiry else 'PASSED (DTE: ' + str(days_to_expiry) + ')'}")
        print(f"Dynamic Threshold  : Rs {current_thr:,.2f}  (Base: Rs {BASE_THRESHOLD:,.2f})")
        print(f"Suspended Stocks   : {len(suspended_stocks_today)} stocks suspended ({', '.join(suspended_stocks_today) if suspended_stocks_today else 'None'})")
        print("-" * 90)
        print(f"{'Stock Name':<12} | {'Score':<5} | {'Band':<8} | {'Pred PnL':<10} | {'Gap %':<8} | {'RSI (9)':<8} | {'Intraday Ret %':<14}")
        print("-" * 90)
        
        for _, row in test_candidates.head(15).iterrows():
            stock = row['stockname']
            score = row['score']
            band = row['band']
            pred_pnl = row['pred_pnl']
            gap_pct = row['Gap_Pct']
            rsi = row['intraday_rsi_9']
            int_ret = row['intraday_return']
            
            # Format display
            print(f"{stock:<12} | {score:>5.1f} | {band:<8} | Rs {pred_pnl:>7.0f} | {gap_pct:>7.2f}% | {rsi:>7.1f} | {int_ret:>13.2f}%")
        print("-" * 90)
        
        # Print suggestions for each model
        print("\n" + "="*40 + " FINAL STRATEGY RECOMMENDATIONS " + "="*40)
        
        # 1. Static Baseline Picks
        print(f"\n1. STATIC BASELINE PICKS (Threshold: Rs {BASE_THRESHOLD:,.0f}):")
        if picks_baseline.empty if hasattr(picks_baseline, 'empty') else len(picks_baseline) == 0:
            if is_friday_lock:
                print("  -> [NO TRADES] Friday Lock is ACTIVE (no trades are generated on Fridays to avoid weekend gap risk).")
            elif is_toxic_expiry:
                print(f"  -> [NO TRADES] Toxic Expiry Safety Lock is ACTIVE (Days to Expiry: {days_to_expiry} is flagged as high-risk).")
            elif test_candidates.empty:
                print("  -> [NO TRADES] No stock candidates were available for scoring.")
            else:
                top_stock = test_candidates.iloc[0]['stockname']
                top_pnl = test_candidates.iloc[0]['pred_pnl']
                print(f"  -> [NO TRADES] All candidates fell below the Rs {BASE_THRESHOLD:,.0f} threshold. (Highest candidate: {top_stock} predicted Rs {top_pnl:,.0f}).")
        else:
            for idx, (_, r) in enumerate(picks_baseline.iterrows(), 1):
                print(f"  [{idx}] {r['stockname']:<12} | Score: {r['score']:>5.1f} ({r['band']}) | Predicted PnL: Rs {r['pred_pnl']:,.0f}")
                
        # 2. Dynamic Threshold Picks
        print(f"\n2. DYNAMIC THRESHOLD PICKS (Threshold: Rs {current_thr:,.0f}):")
        if picks_dynamic.empty if hasattr(picks_dynamic, 'empty') else len(picks_dynamic) == 0:
            if is_friday_lock:
                print("  -> [NO TRADES] Friday Lock is ACTIVE (no trades are generated on Fridays to avoid weekend gap risk).")
            elif is_toxic_expiry:
                print(f"  -> [NO TRADES] Toxic Expiry Safety Lock is ACTIVE (Days to Expiry: {days_to_expiry} is flagged as high-risk).")
            elif test_candidates.empty:
                print("  -> [NO TRADES] No stock candidates were available for scoring.")
            else:
                top_stock = test_candidates.iloc[0]['stockname']
                top_pnl = test_candidates.iloc[0]['pred_pnl']
                print(f"  -> [NO TRADES] All candidates fell below the dynamic Rs {current_thr:,.0f} threshold. (Highest candidate: {top_stock} predicted Rs {top_pnl:,.0f}).")
        else:
            for idx, (_, r) in enumerate(picks_dynamic.iterrows(), 1):
                print(f"  [{idx}] {r['stockname']:<12} | Score: {r['score']:>5.1f} ({r['band']}) | Predicted PnL: Rs {r['pred_pnl']:,.0f}")
                
        # 3. Ticker Suspension Picks
        print(f"\n3. TICKER SUSPENSION PICKS (Threshold: Rs {BASE_THRESHOLD:,.0f} + Suspensions):")
        if picks_suspension.empty if hasattr(picks_suspension, 'empty') else len(picks_suspension) == 0:
            if is_friday_lock:
                print("  -> [NO TRADES] Friday Lock is ACTIVE (no trades are generated on Fridays to avoid weekend gap risk).")
            elif is_toxic_expiry:
                print(f"  -> [NO TRADES] Toxic Expiry Safety Lock is ACTIVE (Days to Expiry: {days_to_expiry} is flagged as high-risk).")
            elif test_candidates.empty:
                print("  -> [NO TRADES] No stock candidates were available for scoring.")
            elif len(suspended_stocks_today) > 0 and all(s in suspended_stocks_today for s in test_candidates.head(4)['stockname']):
                print(f"  -> [NO TRADES] Top high-scoring candidates were filtered out due to active ticker suspensions: {suspended_stocks_today}.")
            else:
                non_suspended_candidates = test_candidates[~test_candidates['stockname'].isin(suspended_stocks_today)]
                if non_suspended_candidates.empty:
                     print("  -> [NO TRADES] All scored candidates are currently suspended.")
                else:
                     top_stock = non_suspended_candidates.iloc[0]['stockname']
                     top_pnl = non_suspended_candidates.iloc[0]['pred_pnl']
                     print(f"  -> [NO TRADES] All non-suspended candidates fell below the Rs {BASE_THRESHOLD:,.0f} threshold. (Highest non-suspended: {top_stock} predicted Rs {top_pnl:,.0f}).")
        else:
            for idx, (_, r) in enumerate(picks_suspension.iterrows(), 1):
                print(f"  [{idx}] {r['stockname']:<12} | Score: {r['score']:>5.1f} ({r['band']}) | Predicted PnL: Rs {r['pred_pnl']:,.0f}")
                
        # 4. Golden Weekday Combo Picks
        print(f"\n4. GOLDEN WEEKDAY COMBO PICKS (Bypass Threshold + 2.0x Double Lot Allocation):")
        if len(picks_golden_combo) == 0:
            if is_friday_lock:
                print("  -> [NO TRADES] Friday Lock is ACTIVE.")
            elif is_toxic_expiry:
                print(f"  -> [NO TRADES] Toxic Expiry Safety Lock is ACTIVE (DTE: {days_to_expiry}).")
            else:
                print("  -> [NO TRADES] No candidates qualified.")
        else:
            for idx, (r, qty) in enumerate(picks_golden_combo, 1):
                size_label = "2.0x (DOUBLE LOT)" if qty == 2.0 else "1.0x (STANDARD)"
                print(f"  [{idx}] {r['stockname']:<12} | Allocation Size: {size_label} | Pred PnL: Rs {r['pred_pnl']:,.0f} | Success WR: {r['success_pct']:.1f}%")
        print("="*90 + "\n")
        
        # Step 8.5: Write predictions to predictedstocksfortoday.csv
        try:
            import csv
            predicted_stocks_path = os.path.join(_THIS_DIR, 'output', 'predictedstocksfortoday.csv')
            os.makedirs(os.path.dirname(predicted_stocks_path), exist_ok=True)
            date_str = today_dt.strftime("%Y%m%d")
            
            # Read existing records to prevent duplication upon re-runs
            existing_records = []
            if os.path.exists(predicted_stocks_path):
                with open(predicted_stocks_path, 'r', newline='') as f_read:
                    reader = csv.reader(f_read)
                    for row in reader:
                        if row and row[0] != date_str:
                            existing_records.append(row)
            
            records_to_append = []
            if picks_golden_combo:
                for r, qty in picks_golden_combo:
                    records_to_append.append([date_str, r['stockname']])
            
            # Rewrite clean historical records and append new ones
            with open(predicted_stocks_path, 'w', newline='') as f_write:
                writer = csv.writer(f_write)
                if existing_records:
                    writer.writerows(existing_records)
                if records_to_append:
                    writer.writerows(records_to_append)
                    
            if records_to_append:
                print(f"✔ Successfully updated {predicted_stocks_path}: wrote {len(records_to_append)} Golden Weekday Combo predictions for {date_str} cleanly (de-duplicated).")
            else:
                print(f"ℹ No predictions to write to predictedstocksfortoday.csv for {date_str} (Golden Weekday Combo picks are empty).")
        except Exception as csv_err:
            print(f"⚠️ Warning: Failed to write/append predictions to predictedstocksfortoday.csv: {csv_err}")
            
        # Send Telegram Message
        import subprocess
        
        # Build Telegram Message String
        tg_lines = []
        tg_lines.append("🎯 <b>DYNAMIC THRESHOLD SYSTEM</b> 🎯")
        tg_lines.append(f"📅 <b>Date</b>: {today_dt.strftime('%A, %Y-%m-%d')}")
        tg_lines.append(f"🚪 <b>Market Status</b>: {'FRIDAY LOCK' if is_friday_lock else 'ACTIVE'}")
        tg_lines.append(f"🔒 <b>Expiry Lock</b>: {'TOXIC EXPIRY (DTE: ' + str(days_to_expiry) + ')' if is_toxic_expiry else 'PASSED (DTE: ' + str(days_to_expiry) + ')'}")
        tg_lines.append(f"📈 <b>Dynamic Threshold</b>: Rs {current_thr:,.2f}")
        tg_lines.append(f"🚫 <b>Suspensions</b>: {', '.join(suspended_stocks_today) if suspended_stocks_today else 'None'}")
        tg_lines.append("")
        tg_lines.append("🏆 <b>RECOMMENDATIONS</b>")
        
        # 1. Golden Weekday Combo Recommendations (Catch-eye First)
        if len(picks_golden_combo) == 0:
            reason_golden = " (Friday Lock is Active)" if is_friday_lock else \
                             f" (Toxic Expiry Lock, DTE: {days_to_expiry})" if is_toxic_expiry else \
                             " (No candidates qualified)"
            tg_lines.append(f"• [NO TRADES]{reason_golden}")
        else:
            for idx, (r, qty) in enumerate(picks_golden_combo, 1):
                size_label = "2.0x (DOUBLE LOT)" if qty == 2.0 else "1.0x (STANDARD)"
                tg_lines.append(f"{idx}. 🔥 <b>{r['stockname']}</b> - {size_label} (Rs {r['pred_pnl']:,.0f})")
                
        tg_lines.append("")
        tg_lines.append("💡 <b>Top Candidates:</b>")
        if not test_candidates.empty:
            for idx, (_, row) in enumerate(test_candidates.head(5).iterrows(), 1):
                tg_lines.append(f"{idx}. {row['stockname']} (Rs {row['pred_pnl']:,.0f})")
        else:
            tg_lines.append("No candidates available.")
            
        tg_msg = "\n".join(tg_lines)
        
        try:
            bot_path = "/home/ubuntu/telegram_bot/New_OrderInfoBot.js"
            if os.path.exists(bot_path):
                subprocess.run(["node", bot_path, tg_msg], check=True, timeout=15)
                print("[predict_today] Telegram alert sent successfully via OrderInfoBot.")
            else:
                print(f"[predict_today] Warning: OrderInfoBot not found at {bot_path}")
        except Exception as tg_err:
            print(f"[predict_today] Warning: Failed to send Telegram alert: {tg_err}")

        
    finally:
        # Step 9: Cleanup and restore the original PnL sheet
        if os.path.exists(BACKUP_PNL_CSV):
            log("Restoring original PnL sheet to keep files clean and uncontaminated...")
            os.replace(BACKUP_PNL_CSV, PNL_CSV)
            log("Original PnL CSV restored successfully.")
            
if __name__ == '__main__':
    main()
