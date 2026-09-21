"""
STEP 2: Train Meta-Decision Model (Walk-Forward) + Evaluate Combined PnL
=========================================================================
For each 09:20 scalp trade at 09:40:
  - Predict: HOLD till 14:45 OR EXIT now
  - Compute combined PnL vs baseline (always scalp at 09:40)
"""

import os
import pandas as pd
import lightgbm as lgb
import warnings
warnings.filterwarnings('ignore')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

print("1. Loading meta dataset...")
df = pd.read_csv(os.path.join(BASE_DIR, 'meta_dataset.csv'))
df['year'] = pd.to_datetime(df['date']).dt.year
print(f"   Total rows: {len(df)}, Years: {sorted(df['year'].unique())}")

FEATURES = [
    'move_pct',           # How much price moved since entry (+ = good for short)
    'unrealized_pnl',     # Current unrealised PnL at 09:40
    'sl_distance_pct',    # Distance from current price to SL
    'pred_942',           # 09:42 model confidence for this stock
    'has_942_signal',     # Did 09:42 model flag this stock today?
    'original_prob',      # 09:20 model's original confidence score
]

params = {
    'objective': 'binary',
    'metric': 'auc',
    'boosting_type': 'gbdt',
    'learning_rate': 0.05,
    'max_depth': 4,
    'num_leaves': 15,
    'feature_fraction': 0.8,
    'verbose': -1,
    'random_state': 42
}

print("\n2. Walk-Forward Training (Hold vs Exit Decision)...")
all_oos = []
for y in range(2021, 2027):
    tr = df[df['year'] < y].copy()
    te = df[df['year'] == y].copy()
    if len(tr) == 0 or len(te) == 0:
        continue
    model = lgb.train(params, lgb.Dataset(tr[FEATURES], label=tr['target']), num_boost_round=200)
    te['meta_prob'] = model.predict(te[FEATURES])
    te['meta_decision'] = (te['meta_prob'] >= 0.55).astype(int)  # 1=Hold, 0=Exit at 09:40
    all_oos.append(te)
    print(f"   {y}: Trained on {len(tr)} rows, testing on {len(te)} rows")

oos = pd.concat(all_oos).reset_index(drop=True)

# ---- Compute final PnL for each decision ----
def final_pnl(row):
    if row['meta_decision'] == 1:
        return row['exit_pnl_1445']   # Hold till 14:45
    else:
        return row['exit_pnl_0940']   # Exit at 09:40

oos['final_pnl'] = oos.apply(final_pnl, axis=1)

# Save decisions
out_file = os.path.join(BASE_DIR, 'meta_decisions.csv')
oos.to_csv(out_file, index=False)

print("\n" + "="*65)
print("  META-DECISION MODEL — FINAL CERTIFIED RESULTS")
print("="*65)

# Year-by-year breakdown
print("\n📊 YEAR-BY-YEAR COMPARISON\n")
print(f"{'Year':<6} {'Always Exit 09:40':>20} {'Always Hold 14:45':>20} {'Meta-Model Decision':>22}")
print("-"*70)
total_meta, total_exit, total_hold = 0, 0, 0
for y, g in oos.groupby('year'):
    meta = g['final_pnl'].sum()
    exit_only = g['exit_pnl_0940'].sum()
    hold_only = g['exit_pnl_1445'].sum()
    total_meta += meta
    total_exit += exit_only
    total_hold += hold_only
    print(f"{y:<6} Rs {exit_only/1e5:>12.2f}L    Rs {hold_only/1e5:>12.2f}L    Rs {meta/1e5:>12.2f}L")

print("-"*70)
print(f"{'TOTAL':<6} Rs {total_exit/1e7:>10.2f}Cr    Rs {total_hold/1e7:>10.2f}Cr    Rs {total_meta/1e7:>10.2f}Cr")

print("\n📊 META-MODEL DECISION STATS")
hold_decisions = (oos['meta_decision'] == 1).sum()
exit_decisions = (oos['meta_decision'] == 0).sum()
print(f"   Hold till 14:45 decisions : {hold_decisions} ({hold_decisions/len(oos)*100:.1f}%)")
print(f"   Exit at 09:40 decisions   : {exit_decisions} ({exit_decisions/len(oos)*100:.1f}%)")

print("\n📊 WIN RATES (Meta-Model)")
for y, g in oos.groupby('year'):
    wins = (g['final_pnl'] > 0).sum()
    print(f"   {y}: {wins/len(g)*100:.2f}% Win Rate ({wins}/{len(g)})")

overall_wins = (oos['final_pnl'] > 0).sum()
print(f"   OVERALL: {overall_wins/len(oos)*100:.2f}% Win Rate ({overall_wins}/{len(oos)})")

print(f"\n🏆 IMPROVEMENT OVER ALWAYS-SCALP (09:40 exit)")
improvement = total_meta - total_exit
print(f"   Extra PnL from Meta-Model : Rs {improvement/1e5:.2f} Lakhs")
print(f"   That is {improvement/total_exit*100:.1f}% better than always exiting at 09:40")
print(f"\n✅ Meta decisions saved to {out_file}")
