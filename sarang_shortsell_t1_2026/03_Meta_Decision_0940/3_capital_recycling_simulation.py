"""
STEP 3: Capital Recycling Simulation
======================================
Strategy:
  - 09:20 model takes up to MAX_SLOTS positions (10L each)
  - At 09:40, Meta-Model decides: HOLD or EXIT for each position
  - Capital freed from EXITs is recycled into top 09:42 signals (ranked by confidence)
  - 09:42 trades run till 14:45
  - Compare combined PnL vs baseline (always scalp at 09:40, no 09:42)
"""

import pandas as pd
import numpy as np

CAPITAL_PER_SLOT = 1_000_000   # 10 Lakhs per slot
MAX_SLOTS = 4                   # Max 4 concurrent positions = 40L total deployed

BASE = '/home/ubuntu/sarang_shortsell_t1_2026'
META = f'{BASE}/03_Meta_Decision_0940/meta_decisions.csv'
PRED_942 = f'{BASE}/02_0942_Hybrid_Model/0942_predictions.csv'
PNL_942  = f'{BASE}/02_0942_Hybrid_Model/0942_verified_pnl_sheet.csv'

# ── Load data ──────────────────────────────────────────────────────────────
print("Loading data...")
meta = pd.read_csv(META, parse_dates=['date'])
pred = pd.read_csv(PRED_942)
pred['date'] = pd.to_datetime(pred['date_str'])
pred = pred.rename(columns={'clean_stock': 'stock'})

pnl942 = pd.read_csv(PNL_942, parse_dates=['Date'])
pnl942 = pnl942.rename(columns={'Date': 'date', 'Stock': 'stock', 'Net_PnL': 'pnl_942'})
pnl942_lookup = pnl942.set_index(['date', 'stock'])['pnl_942'].to_dict()

meta['year'] = meta['date'].dt.year
print(f"  meta_decisions : {len(meta)} rows | years: {sorted(meta['year'].unique())}")
print(f"  0942 predictions: {len(pred)} rows")
print(f"  0942 verified PnL: {len(pnl942)} rows")

# ── Day-by-day simulation ──────────────────────────────────────────────────
print("\nRunning capital recycling simulation day by day...")

results = []

for date, day_meta in meta.groupby('date'):

    # — 09:20 positions for this day (capped at MAX_SLOTS, ranked by confidence) —
    day_meta = day_meta.sort_values('original_prob', ascending=False).head(MAX_SLOTS)
    n_positions = len(day_meta)

    # — Meta-decision at 09:40 —
    hold_trades = day_meta[day_meta['meta_decision'] == 1]
    exit_trades = day_meta[day_meta['meta_decision'] == 0]

    # — PnL from 09:20 positions —
    pnl_from_0920 = hold_trades['exit_pnl_1445'].sum() + exit_trades['exit_pnl_0940'].sum()

    # — Freed slots from exited 09:20 trades —
    freed_slots = len(exit_trades)

    # — 09:42 signals for this day (ranked by confidence, exclude stocks already held) —
    held_stocks = set(hold_trades['stock'].values)
    day_pred = pred[pred['date'] == date].copy()
    day_pred = day_pred[~day_pred['stock'].isin(held_stocks)]  # Don't double-enter held stocks
    day_pred = day_pred.sort_values('pred', ascending=False)   # Best signals first

    # — Take top N 09:42 signals where N = freed slots —
    selected_942 = day_pred.head(freed_slots)

    # — PnL from recycled 09:42 trades —
    pnl_from_0942 = 0
    executed_942 = 0
    for _, row in selected_942.iterrows():
        key = (date, row['stock'])
        if key in pnl942_lookup:
            pnl_from_0942 += pnl942_lookup[key]
            executed_942 += 1

    # — Baseline: always exit all 09:20 at 09:40, no 09:42 —
    baseline_pnl = day_meta['exit_pnl_0940'].sum()

    results.append({
        'date': date,
        'year': date.year,
        'n_0920_positions': n_positions,
        'n_held': len(hold_trades),
        'n_exited': len(exit_trades),
        'n_0942_executed': executed_942,
        'pnl_0920': pnl_from_0920,
        'pnl_0942_recycled': pnl_from_0942,
        'combined_pnl': pnl_from_0920 + pnl_from_0942,
        'baseline_pnl': baseline_pnl,
    })

df = pd.DataFrame(results)

# ── Print Results ──────────────────────────────────────────────────────────
print("\n" + "="*75)
print("  CAPITAL RECYCLING STRATEGY — CERTIFIED YEAR-BY-YEAR RESULTS")
print("="*75)

print(f"\n{'Year':<6} {'Baseline (Always Exit 09:40)':>28} {'Combined (Recycle into 09:42)':>30} {'Extra Profit':>14}")
print("-"*80)

total_combined = 0
total_baseline = 0

for year, g in df.groupby('year'):
    combined = g['combined_pnl'].sum()
    baseline = g['baseline_pnl'].sum()
    extra    = combined - baseline
    total_combined += combined
    total_baseline += baseline
    arrow = "⬆️ " if extra > 0 else "⬇️ "
    print(f"{year:<6}  Rs {baseline/1e5:>10.2f} L              Rs {combined/1e5:>10.2f} L          {arrow}Rs {extra/1e5:>7.2f} L")

print("-"*80)
total_extra = total_combined - total_baseline
print(f"{'TOTAL':<6}  Rs {total_baseline/1e7:>10.2f} Cr             Rs {total_combined/1e7:>10.2f} Cr          ⬆️  Rs {total_extra/1e5:>7.2f} L")

print("\n" + "="*75)
print("  TRADE EXECUTION SUMMARY")
print("="*75)
print(f"  Total 09:20 positions taken    : {df['n_0920_positions'].sum():,}")
print(f"  Total held till 14:45 (09:20)  : {df['n_held'].sum():,}")
print(f"  Total exited at 09:40 (09:20)  : {df['n_exited'].sum():,}")
print(f"  Total 09:42 trades executed    : {df['n_0942_executed'].sum():,}")
print(f"  Total trades overall           : {df['n_0920_positions'].sum() + df['n_0942_executed'].sum():,}")

print("\n" + "="*75)
print("  WIN RATES")
print("="*75)
combined_wins = (df['combined_pnl'] > 0).sum()
baseline_wins = (df['baseline_pnl'] > 0).sum()
total_days = len(df)
print(f"  Profitable days (Baseline)     : {baseline_wins}/{total_days} = {baseline_wins/total_days*100:.1f}%")
print(f"  Profitable days (Combined)     : {combined_wins}/{total_days} = {combined_wins/total_days*100:.1f}%")

print("\n" + "="*75)
print("  IMPROVEMENT SUMMARY")
print("="*75)
print(f"  Baseline (always exit 09:40)   : Rs {total_baseline/1e7:.2f} Cr")
print(f"  Combined (recycled capital)    : Rs {total_combined/1e7:.2f} Cr")
print(f"  Extra profit from recycling    : Rs {total_extra/1e5:.2f} Lakhs")
print(f"  Improvement %                  : {total_extra/total_baseline*100:.1f}%")
print()

# Save result
df.to_csv(f'{BASE}/03_Meta_Decision_0940/capital_recycling_results.csv', index=False)
print(f"✅ Full daily results saved to capital_recycling_results.csv")
