import pandas as pd
import numpy as np

df = pd.read_csv('/home/ubuntu/sarang_2026_shortsell_algos/rebuild_model2_strict_db_ledger.csv')

F1_FLAT_CHARGE = 600.0

cash_gross_all = []
cash_chg_all = []
cash_net_all = []

f1_gross_all = []
f1_chg_all = []
f1_net_all = []

for _, r in df.iterrows():
    lot = r['lotsize']
    # If the user trades 1x across the board, qty is exactly the lotsize.
    en_c = r['cash_entry']
    ex_c = r['cash_exit']
    
    # CASH Recalc
    c_gross = (en_c - ex_c) * lot
    sell_val = en_c * lot
    buy_val = ex_c * lot
    
    stt = sell_val * 0.00025
    ex_tx = (sell_val + buy_val) * 0.0000325
    sebi = (sell_val + buy_val) * 0.000001
    stamp = sell_val * 0.00003
    gst = (ex_tx + sebi) * 0.18
    c_chg = stt + ex_tx + sebi + stamp + gst + 50.0
    c_net = c_gross - c_chg
    
    cash_gross_all.append(c_gross)
    cash_chg_all.append(c_chg)
    cash_net_all.append(c_net)
    
    # F1 Recalc
    en_f = r['f1_entry']
    ex_f = r['f1_exit']
    f_gross = (en_f - ex_f) * lot
    f_chg = F1_FLAT_CHARGE
    f_net = f_gross - f_chg
    
    f1_gross_all.append(f_gross)
    f1_chg_all.append(f_chg)
    f1_net_all.append(f_net)

df['1x_cash_gross'] = cash_gross_all
df['1x_cash_chg'] = cash_chg_all
df['1x_cash_net'] = cash_net_all

df['1x_f1_gross'] = f1_gross_all
df['1x_f1_chg'] = f1_chg_all
df['1x_f1_net'] = f1_net_all

def print_yoy(df, is_f1=False):
    prefix = '1x_f1' if is_f1 else '1x_cash'
    
    print(f"Year   | Trades | Gross (L) | Charges (L) | Net (L) | Net (Cr)")
    print("-" * 75)
    
    tot_gross = 0
    tot_chg = 0
    tot_net = 0
    
    years = sorted(df['year'].unique())
    for y in years:
        ydf = df[df['year'] == y]
        trd = len(ydf)
        g = ydf[f'{prefix}_gross'].sum() / 100000
        c = ydf[f'{prefix}_chg'].sum() / 100000
        n = ydf[f'{prefix}_net'].sum() / 100000
        
        tot_gross += g
        tot_chg += c
        tot_net += n
        
        print(f"{y:<6} | {trd:<6} | +Rs {g:>5.2f} L | -Rs {c:>5.2f} L | Rs {n:>5.2f} L | {n/100:.3f} Cr")
        
    print("-" * 75)
    print(f"TOTAL  | {len(df):<6} | +Rs {tot_gross:>5.2f} L | -Rs {tot_chg:>5.2f} L | Rs {tot_net:>5.2f} L | {tot_net/100:.3f} Cr")
    print("=" * 75)
    return tot_net

print("\n===========================================================================")
print(" EQUITY CASH — FLAT 1x SIZING (NO MULTIPLIERS)")
print("===========================================================================")
cash_total = print_yoy(df, is_f1=False)

print("\n===========================================================================")
print(" FUTURES F1 — FLAT 1x SIZING (NO MULTIPLIERS)")
print("===========================================================================")
f1_total = print_yoy(df, is_f1=True)

print("\n--- DIFFERENCE ANALYSIS ---")
print(f"Cash PnL @ 2x Dual Confirmed: +Rs 162.76 L")
print(f"Cash PnL @ 1x Flat Sizing:    +Rs {cash_total:.2f} L")
print(f"Extra Profit from 2x Rule:    +Rs {162.76 - cash_total:.2f} L")

