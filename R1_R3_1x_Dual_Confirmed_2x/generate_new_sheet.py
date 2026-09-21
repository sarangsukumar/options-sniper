import pandas as pd
import numpy as np
import os
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

OUTPUT_DIR = "/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/historical_models/output"

def load_freq_data(freqs):
    dfs = {}
    for freq in freqs:
        fpath = os.path.join(OUTPUT_DIR, f"trades_dynamic_threshold_{freq}.csv")
        df = pd.read_csv(fpath)
        df['date'] = pd.to_datetime(df['date'])
        dfs[freq] = df
    return dfs

def build_master_feature_table(dfs, freqs):
    # Base is daily
    df_master = dfs['daily'][['date', 'stock', 'pred_pnl', 'actual_pnl']].copy()
    df_master = df_master.rename(columns={'pred_pnl': 'daily'})
    
    for freq in freqs:
        if freq == 'daily': continue
        dft = dfs[freq][['date', 'stock', 'pred_pnl']].rename(columns={'pred_pnl': freq})
        df_master = pd.merge(df_master, dft, on=['date', 'stock'], how='left')
    
    df_master = df_master.dropna().reset_index(drop=True)
    return df_master

freqs = ['daily', 'weekly', 'monthly', 'quarterly', 'yearly']
dfs = load_freq_data(freqs)
df_master = build_master_feature_table(dfs, freqs)
features = [c for c in df_master.columns if c not in ['date', 'stock', 'actual_pnl']]

df_ens_all = pd.read_csv(os.path.join(OUTPUT_DIR, "trades_dynamic_threshold_ensemble.csv"))
df_ens_all['date'] = pd.to_datetime(df_ens_all['date'])

final_trades = []

for test_year in range(2019, 2027):
    train_df = df_master[df_master['date'].dt.year < test_year]
    test_df  = df_master[df_master['date'].dt.year == test_year]

    if len(train_df) < 50 or len(test_df) == 0:
        continue

    X_train = train_df[features].copy()
    X_test  = test_df[features].copy()

    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)

    preds_for_year = {freq: np.zeros(len(test_df)) for freq in freqs}
    for freq in freqs:
        y_train = train_df[freq]
        model = Ridge(alpha=1.0, random_state=42)
        model.fit(X_train_scaled, y_train)
        preds_for_year[freq] = model.predict(X_test_scaled)

    for i, row in enumerate(test_df.itertuples()):
        dt = row.date

        day_static = df_ens_all[df_ens_all['date'] == dt].sort_values(by='pred_pnl', ascending=False)
        if day_static.empty:
            continue

        daily_preds = {freq: preds_for_year[freq][i] for freq in freqs}
        active_freqs = sorted(daily_preds, key=daily_preds.get, reverse=True)[:2]

        ml_stocks = set()
        for freq in active_freqs:
            day_freq_trades = dfs[freq][dfs[freq]['date'] == dt]
            ml_stocks.update(day_freq_trades['stock'].unique())

        static_stocks = day_static['stock'].tolist()
        
        # User Logic: If ANY R1 or R3 comes in dual confirmed, do THAT ONLY 2x
        dual_confirmed_stock = None
        for s in static_stocks[:2]:  # R1 and R3
            if s in ml_stocks:
                dual_confirmed_stock = s
                break
        
        if dual_confirmed_stock:
            # Do ONLY 2x for the dual confirmed stock
            row_data = day_static[day_static['stock'] == dual_confirmed_stock].iloc[0]
            final_trades.append({
                'date': dt.strftime('%Y-%m-%d'),
                'stock1': dual_confirmed_stock,
                'lot1': 2,
                'pnl1': row_data['actual_pnl'] * 2,
                'stock2': None,
                'lot2': 0,
                'pnl2': 0,
                'is_dual_confirmed_day': True,
                'daily_total_pnl': row_data['actual_pnl'] * 2
            })
        else:
            # Neither is dual confirmed. Do R1 and R3 at 1x each.
            s1 = None; s2 = None; p1 = 0; p2 = 0
            if len(static_stocks) > 0:
                s1 = static_stocks[0]
                p1 = day_static.iloc[0]['actual_pnl']
            if len(static_stocks) > 1:
                s2 = static_stocks[1]
                p2 = day_static.iloc[1]['actual_pnl']
                
            final_trades.append({
                'date': dt.strftime('%Y-%m-%d'),
                'stock1': s1,
                'lot1': 1 if s1 else 0,
                'pnl1': p1,
                'stock2': s2,
                'lot2': 1 if s2 else 0,
                'pnl2': p2,
                'is_dual_confirmed_day': False,
                'daily_total_pnl': p1 + p2
            })

res_df = pd.DataFrame(final_trades)
# Deduplicate dates since the itertuples above loops over test_df which might have multiple rows per date!
res_df = res_df.drop_duplicates(subset=['date']).sort_values('date')

out_csv = "/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/R1_R3_1x_Dual_Confirmed_2x/USER_R1_R3_DUAL_SHEET.csv"
res_df.to_csv(out_csv, index=False)
print(f"Generated {len(res_df)} days of trades: {out_csv}")
