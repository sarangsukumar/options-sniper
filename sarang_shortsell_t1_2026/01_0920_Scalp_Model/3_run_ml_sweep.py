import os
import pandas as pd
import numpy as np
import yfinance as yf
import lightgbm as lgb
import warnings
from dateutil.relativedelta import relativedelta

warnings.filterwarnings('ignore')
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Macro Data ──────────────────────────────────────────────
data = yf.download(['^NSEI','^GSPC','^N225'], start='2018-01-01', end='2026-12-31', progress=False)
df_c = data['Close'].reset_index(); df_o = data['Open'].reset_index()
dates = pd.date_range(start='2018-01-01', end='2026-12-31', freq='B')
mac = pd.DataFrame({'date': dates})
mac['date_str'] = mac['date'].dt.strftime('%Y-%m-%d')
mac = mac.merge(df_c[['Date','^NSEI']].rename(columns={'Date':'date','^NSEI':'nifty_close'}), on='date', how='left')
mac = mac.merge(df_o[['Date','^NSEI']].rename(columns={'Date':'date','^NSEI':'nifty_open'}), on='date', how='left')
mac['nifty_gap'] = (mac['nifty_open'] / mac['nifty_close'].shift(1)) - 1
mac = mac.merge(df_c[['Date','^GSPC']].rename(columns={'Date':'date','^GSPC':'sp500_close'}), on='date', how='left')
mac['sp500_overnight_ret'] = mac['sp500_close'] / mac['sp500_close'].shift(1) - 1
mac = mac.merge(df_c[['Date','^N225']].rename(columns={'Date':'date','^N225':'nikkei_close'}), on='date', how='left')
mac = mac.merge(df_o[['Date','^N225']].rename(columns={'Date':'date','^N225':'nikkei_open'}), on='date', how='left')
mac['nikkei_gap'] = mac['nikkei_open'] / mac['nikkei_close'].shift(1) - 1
mac['nifty_vs_sp500_gap']  = mac['nifty_gap'] - mac['sp500_overnight_ret']
mac['nifty_vs_nikkei_gap'] = mac['nifty_gap'] - mac['nikkei_gap']
mac = mac.fillna(0)

# ── Dataset ──────────────────────────────────────────────────
df = pd.read_csv(os.path.join(BASE_DIR, 'data/scalp_0920_ml_dataset.csv.gz'))
df['date_obj'] = pd.to_datetime(df['short_date'])
df['year'] = df['date_obj'].dt.year
df = df.merge(mac[['date_str','nifty_gap','sp500_overnight_ret','nikkei_gap','nifty_vs_sp500_gap','nifty_vs_nikkei_gap']],
              left_on='short_date', right_on='date_str', how='left')

FEATURES = [
    'morn_range_pct', 'prev_intraday_vwap_gap', 'prev_intraday_roc_last_hour',
    'prev_intraday_return', 'positive_arc_ratio', 'Gap_Pct', 'gap_0907_pct',
    'rejection_wick', 'nifty_gap', 'sp500_overnight_ret', 'nikkei_gap',
    'nifty_vs_sp500_gap', 'nifty_vs_nikkei_gap'
]
df[FEATURES] = df[FEATURES].fillna(0)
df['target'] = (df['pnl_net'] > 0).astype(int)

def run_experiment(name, params, rolling_years=None, use_time_decay=False):
    all_oos = []
    for y in range(2020, 2027):
        test_start = pd.to_datetime(f"{y}-01-01")
        if rolling_years:
            train_start = test_start - relativedelta(years=rolling_years)
            tr = df[(df['date_obj'] >= train_start) & (df['date_obj'] < test_start)].copy()
        else:
            tr = df[df['date_obj'] < test_start].copy()
        te = df[df['year'] == y].copy()
        if len(tr) == 0 or len(te) == 0: continue
        
        weight = None
        if use_time_decay:
            tr['weight'] = np.exp((tr['year'] - y) * 0.5)
            weight = tr['weight']

        dtrain = lgb.Dataset(tr[FEATURES], label=tr['target'], weight=weight)
        mod = lgb.train(params, dtrain, num_boost_round=300)
        te['prob'] = mod.predict(te[FEATURES])
        all_oos.append(te)

    oos = pd.concat(all_oos).sort_values(['short_date','prob'], ascending=[True, False])
    top4 = oos.groupby('short_date').head(4).reset_index(drop=True)
    top4[['short_date','clean_stock','prob']].to_csv(f'sweep_preds_{name}.csv', index=False)
    print(f"\n--- {name} ---")
    for y in sorted(top4['year'].unique()):
        subset = top4[top4['year'] == y]
        wrate = (subset['pnl_net'] > 0).mean() * 100 if 'pnl_net' in subset.columns else 0
        total = subset['pnl_net'].sum() / 100000 if 'pnl_net' in subset.columns else 0
        print(f"  {y}: ₹ {total:.2f} L | {wrate:.1f}% Win Rate | {len(subset)} trades")
    if 'pnl_net' in top4.columns:
        print(f"  TOTAL: ₹ {top4['pnl_net'].sum()/100000:.2f} L")

base_params = {
    'objective': 'binary', 'metric': 'auc', 'learning_rate': 0.05,
    'max_depth': 5, 'num_leaves': 31, 'feature_fraction': 0.8,
    'verbose': -1, 'random_state': 42
}

print("=" * 60)
print("0920 SCALP MODEL — ML ARCHITECTURE SWEEP")
print("=" * 60)

print("\n🔵 Running Exp 1: Current (Binary, Expanding Window, No Decay)...")
run_experiment("1_baseline", base_params, rolling_years=None, use_time_decay=False)

print("\n🟡 Running Exp 2: Binary + Time-Decay (Expanding Window)...")
run_experiment("2_timedecay", base_params, rolling_years=None, use_time_decay=True)

print("\n🟠 Running Exp 3: Binary + 4-Year Rolling Window (No Decay)...")
run_experiment("3_rolling4yr", base_params, rolling_years=4, use_time_decay=False)

print("\n🟢 Running Exp 4: Binary + 4-Year Rolling + Time-Decay...")
run_experiment("4_rolling4yr_decay", base_params, rolling_years=4, use_time_decay=True)

print("\n🔴 Running Exp 5: Binary + 3-Year Rolling + Time-Decay...")
run_experiment("5_rolling3yr_decay", base_params, rolling_years=3, use_time_decay=True)

print("\n\n✅ Sweep complete! Now run 2_db_tick_verification.py on top-performing preds.")
