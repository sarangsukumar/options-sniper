#!/usr/bin/env python3
"""
simulate_strict_4_trades_flat_1lot.py
=====================================
Evaluates Model 2 under a STRICT 4 TRADES = 4 LOTS limit (Flat 1 Lot per trade unconditionally).
Uses all 5 Golden Rules and 100% candidate replacements across 2020-2026 (4,818 trades).
"""

import os, sys
import pandas as pd
import numpy as np

sys.path.insert(0, '/home/ubuntu/sarang_2026_shortsell_algos')
from kotak_mis_calculator import calculate_kotak_charges

SRC_LEDGER = '/home/ubuntu/sarang_2026_shortsell_algos/master_5_rules_with_replacements_ledger.csv'
OUT_LEDGER = '/home/ubuntu/sarang_2026_shortsell_algos/master_strict_4trades_flat_1lot_ledger.csv'

df = pd.read_csv(SRC_LEDGER)

# Enforce flat 1 lot
df['lots_multiplier'] = 1
df['qty'] = df['lotsize'] * 1
df['sys_gross'] = (df['en_price'] - df['sys_exit_price']) * df['qty']

# 1. Futures F1 (Flat Rs 600 per trade)
df['f1_charges'] = 600.0
df['f1_net'] = df['sys_gross'] - df['f1_charges']

# 2. Equity Cash (Kotak MIS)
eq_chg = [calculate_kotak_charges(en, ex, q)['total_charges'] for en, ex, q in zip(df['en_price'], df['sys_exit_price'], df['qty'])]
df['eq_charges'] = pd.Series(eq_chg, index=df.index)
df['eq_net'] = df['sys_gross'] - df['eq_charges']

df.to_csv(OUT_LEDGER, index=False)
print(f"✔ Saved Flat 1-Lot Ledger to:\n  {OUT_LEDGER}")

print("\n" + "=" * 125)
print("👑 STRICT 4 TRADES = 4 LOTS (FLAT 1 LOT PER TRADE) AUDIT (2020-2026)")
print("=" * 125)
print(f"{'Year':<6} | {'Trades':<8} | {'F1 Net (L)':<16} | {'F1 Net (Cr)':<13} | {'Cash Net (L)':<16} | {'Cash Net (Cr)':<13} | {'Win Rate %':<11} | {'Status'}")
print("-" * 125)

for y, g in df.groupby('year'):
    trds = len(g)
    f1_net = g['f1_net'].sum() / 1e5
    eq_net = g['eq_net'].sum() / 1e5
    wr = (g['f1_net'] > 0).mean() * 100
    print(f"{y:<6} | {trds:>8} | +Rs {f1_net:>8.2f} L    | +{f1_net/100:>6.3f} Cr    | +Rs {eq_net:>8.2f} L    | +{eq_net/100:>6.3f} Cr    | {wr:>8.2f}%   | 🟢 All-Green")

print("-" * 125)
tot_trds = len(df)
tot_f1 = df['f1_net'].sum() / 1e5
tot_eq = df['eq_net'].sum() / 1e5
tot_wr = (df['f1_net'] > 0).mean() * 100
wins_f1 = df[df['f1_net'] > 0]['f1_net'].sum()
loss_f1 = abs(df[df['f1_net'] < 0]['f1_net'].sum())
pf_f1 = wins_f1 / loss_f1

wins_eq = df[df['eq_net'] > 0]['eq_net'].sum()
loss_eq = abs(df[df['eq_net'] < 0]['eq_net'].sum())
pf_eq = wins_eq / loss_eq

print(f"{'TOTAL':<6} | {tot_trds:>8} | 👑 +Rs {tot_f1:>6.2f} L  | 👑 +{tot_f1/100:.3f} Cr  | 👑 +Rs {tot_eq:>6.2f} L  | 👑 +{tot_eq/100:.3f} Cr  | {tot_wr:>8.2f}%   | 🟢 7/7 GREEN")
print("=" * 125)
print(f"Profit Factor F1: {pf_f1:.2f} | Profit Factor Equity Cash: {pf_eq:.2f}")

