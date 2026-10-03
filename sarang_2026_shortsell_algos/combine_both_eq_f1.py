import pandas as pd

# Load Model 1
m1_eq = pd.read_csv('/home/ubuntu/sarang_2026_shortsell_algos/01_Best_Shorter_Window_0920_0940/rebuilt_model1_strict_pnl.csv')
m1_eq = m1_eq[~m1_eq['exit_reason'].str.startswith('SKIPPED')]

m1_f1 = pd.read_csv('/home/ubuntu/sarang_2026_shortsell_algos/01_Best_Shorter_Window_0920_0940/rebuilt_model1_strict_f1_pnl.csv')
m1_f1 = m1_f1[~m1_f1['exit_reason'].str.startswith('SKIPPED')]

# Load Model 2
m2_eq = pd.read_csv('/home/ubuntu/sarang_2026_shortsell_algos/02_Best_Longer_Window_0942_1445/rebuilt_model2_strict_pnl.csv')
m2_eq = m2_eq[~m2_eq['exit_reason'].str.startswith('SKIPPED')]

m2_f1 = pd.read_csv('/home/ubuntu/sarang_2026_shortsell_algos/02_Best_Longer_Window_0942_1445/rebuilt_model2_f1_pnl.csv')
m2_f1 = m2_f1[~m2_f1['exit_reason'].str.startswith('SKIPPED')]

def calc_stats(df1, df2, name):
    combined = pd.concat([df1, df2])
    trades = len(combined)
    wins = len(combined[combined['net_pnl'] > 0])
    win_rate = (wins / trades) * 100 if trades > 0 else 0
    net_pnl = combined['net_pnl'].sum()
    print(f"--- {name} ---")
    print(f"Net PnL: ₹ {net_pnl/100000:.2f} Lakhs")
    print(f"Win Rate: {win_rate:.2f}%")
    print(f"Trades: {trades}")
    print(f"M1 Contribution: ₹ {df1['net_pnl'].sum()/100000:.2f}L | M2 Contribution: ₹ {df2['net_pnl'].sum()/100000:.2f}L\n")

calc_stats(m1_eq, m2_eq, "BOTH STRICTLY CASH (EQ)")
calc_stats(m1_f1, m2_f1, "BOTH STRICTLY FUTURES (F1)")

