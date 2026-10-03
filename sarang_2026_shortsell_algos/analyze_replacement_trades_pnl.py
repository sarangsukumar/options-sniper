import os, sys, warnings
import pandas as pd
import numpy as np

# Load df_with_rep and df_no_rep from test_candidate_replacements
# Let's inspect known_map (sl3_points_master.csv) and compute the PnL of replacements vs discarded trades!

SCRIPT_DIR = '/home/ubuntu/sarang_2026_shortsell_algos/02_Best_Longer_Window_0942_1445'
sl_master = pd.read_csv(os.path.join(SCRIPT_DIR, 'sl3_points_master.csv'))
known_map = dict(zip(sl_master['date'] + '_' + sl_master['stockname'], sl_master['points']))

# We can import or inspect the results from test_candidate_replacements
from test_candidate_replacements import df_no_rep, df_with_rep

# Identify the 225 discarded trades and the 225 replacement trades
set_orig_passed = set(df_no_rep[df_no_rep['passed_prefilter']]['date_str'] + '_' + df_no_rep[df_no_rep['clean_stock']])
set_orig_failed = set(df_no_rep[~df_no_rep['passed_prefilter']]['date_str'] + '_' + df_no_rep[~df_no_rep['clean_stock']])
set_with_rep    = set(df_with_rep['date_str'] + '_' + df_with_rep['clean_stock'])

replacements = df_with_rep[~df_with_rep.apply(lambda r: (r['date_str'] + '_' + r['clean_stock']) in set_orig_passed, axis=1)].copy()
discarded    = df_no_rep[~df_no_rep['passed_prefilter']].copy()

print("=" * 80)
print(f"📊 REPLACEMENT TRADES ANALYSIS ({len(replacements)} trades)")
print("=" * 80)

# Compute PnL for discarded
discarded['key'] = discarded['date_str'] + '_' + discarded['clean_stock']
discarded['points'] = [known_map.get(k, 0.0) for k in discarded['key']]
discarded['traded_qty'] = discarded['lotsize'] * discarded['lots_multiplier']
discarded['gross_pnl'] = discarded['points'] * discarded['traded_qty']
discarded['f1_charges'] = 600.0 * discarded['lots_multiplier']
discarded['net_pnl'] = discarded['gross_pnl'] - discarded['f1_charges']

# Compute PnL for replacements
replacements['key'] = replacements['date_str'] + '_' + replacements['clean_stock']
replacements['points'] = [known_map.get(k, 0.0) for k in replacements['key']]
replacements['traded_qty'] = replacements['lotsize'] * replacements['lots_multiplier']
replacements['gross_pnl'] = replacements['points'] * replacements['traded_qty']
replacements['f1_charges'] = 600.0 * replacements['lots_multiplier']
replacements['net_pnl'] = replacements['gross_pnl'] - replacements['f1_charges']

print(f"1. DISCARDED TRADES (Failing Pre-Filter): {len(discarded)} trades")
print(f"   • Gross PnL: Rs {discarded['gross_pnl'].sum()/1e5:+.2f} Lakhs")
print(f"   • Net PnL:   Rs {discarded['net_pnl'].sum()/1e5:+.2f} Lakhs")
print(f"   • Win Rate:  {(discarded['net_pnl'] > 0).mean()*100:.2f}%")

print(f"\n2. NEW REPLACEMENT TRADES (Next-in-line candidates): {len(replacements)} trades")
print(f"   • Gross PnL: Rs {replacements['gross_pnl'].sum()/1e5:+.2f} Lakhs")
print(f"   • Net PnL:   Rs {replacements['net_pnl'].sum()/1e5:+.2f} Lakhs")
print(f"   • Win Rate:  {(replacements['net_pnl'] > 0).mean()*100:.2f}%")

net_diff = (replacements['net_pnl'].sum() - discarded['net_pnl'].sum()) / 1e5
print(f"\n3. NET PORTFOLIO IMPACT:")
print(f"   • Net Profit Difference: Rs {net_diff:+.2f} Lakhs (Rs {net_diff*1e5:+,.0f})")
print("=" * 80)

# Overall portfolio performance with replacements:
df_with_rep['key'] = df_with_rep['date_str'] + '_' + df_with_rep['clean_stock']
df_with_rep['points'] = [known_map.get(k, 0.0) for k in df_with_rep['key']]
df_with_rep['traded_qty'] = df_with_rep['lotsize'] * df_with_rep['lots_multiplier']
df_with_rep['gross_pnl'] = df_with_rep['points'] * df_with_rep['traded_qty']
df_with_rep['f1_charges'] = 600.0 * df_with_rep['lots_multiplier']
df_with_rep['net_pnl'] = df_with_rep['gross_pnl'] - df_with_rep['f1_charges']

print(f"\n🏆 FULL PORTFOLIO WITH PRE-FILTER REPLACEMENTS (4,818 Trades):")
print(f"   • Gross PnL:   Rs {df_with_rep['gross_pnl'].sum()/1e5:+.2f} Lakhs")
print(f"   • Net PnL:     Rs {df_with_rep['net_pnl'].sum()/1e5:+.2f} Lakhs (+{df_with_rep['net_pnl'].sum()/1e7:.3f} Cr)")
print(f"   • Win Rate:    {(df_with_rep['net_pnl'] > 0).mean()*100:.2f}%")
print(f"   • Year-by-Year Net PnL:")
for y, g in df_with_rep.groupby('year'):
    print(f"     - {y}: Rs {g['net_pnl'].sum()/1e5:+.2f} L (WR: {(g['net_pnl'] > 0).mean()*100:.2f}%)")

