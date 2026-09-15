import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# Set aesthetic styling
plt.style.use('seaborn-v0_8-whitegrid' if 'seaborn-v0_8-whitegrid' in plt.style.available else 'default')
plt.rcParams['font.family'] = 'sans-serif'
plt.rcParams['font.sans-serif'] = ['DejaVu Sans', 'Arial', 'Helvetica']

BASE_DIR = '/home/ubuntu/sarang_2026_shortsell_algos'
M1_FILE = os.path.join(BASE_DIR, '01_Best_Shorter_Window_0920_0940', 'audited_0920_0940_realistic_7p5L_kotak.csv')
M2_FILE = os.path.join(BASE_DIR, '02_Best_Longer_Window_0942_1445', 'audited_0940_hybrid_realistic_7p5L_kotak.csv')
PLOTS_DIR = os.path.join(BASE_DIR, 'plots')
os.makedirs(PLOTS_DIR, exist_ok=True)

df1 = pd.read_csv(M1_FILE)
df2 = pd.read_csv(M2_FILE)

# Filter executed
ex1 = df1[df1['allocated_qty'] > 0].copy()
ex2 = df2[df2['allocated_qty'] > 0].copy()

ex1['date'] = pd.to_datetime(ex1['date'])
ex2['date'] = pd.to_datetime(ex2['date'])

# Daily PnL
d1 = ex1.groupby('date')['net_pnl'].sum().reset_index().rename(columns={'net_pnl': 'm1_pnl'})
d2 = ex2.groupby('date')['net_pnl'].sum().reset_index().rename(columns={'net_pnl': 'm2_pnl'})

comb = pd.merge(d1, d2, on='date', how='outer').sort_values('date').fillna(0)
comb['combined_pnl'] = comb['m1_pnl'] + comb['m2_pnl']
comb['m1_cum'] = comb['m1_pnl'].cumsum() / 1e5
comb['m2_cum'] = comb['m2_pnl'].cumsum() / 1e5
comb['combined_cum'] = comb['combined_pnl'].cumsum() / 1e5

# 1. Equity Curve Plot
fig, ax = plt.subplots(figsize=(10, 5), dpi=300)
ax.plot(comb['date'], comb['combined_cum'], label='👑 Combined Dual Portfolio (+₹272.85 L)', color='#10B981', linewidth=2.5)
ax.plot(comb['date'], comb['m2_cum'], label='Model 2: 09:42 Hybrid (+₹215.11 L)', color='#3B82F6', linewidth=1.8, linestyle='--')
ax.plot(comb['date'], comb['m1_cum'], label='Model 1: 09:20 Scalp (+₹57.74 L)', color='#F59E0B', linewidth=1.8, linestyle=':')

ax.set_title('Cumulative Realistic Net Equity Curve (2020 – 2026)\n[₹7.5L Daily Capital Base | Exact Kotak MIS Margin & Brokerage + ₹50 Buffer]', fontsize=12, fontweight='bold', pad=12)
ax.set_ylabel('Net Profit (₹ Lakhs)', fontsize=11, fontweight='bold')
ax.set_xlabel('Date', fontsize=11, fontweight='bold')
ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
ax.xaxis.set_major_locator(mdates.YearLocator())
ax.legend(loc='upper left', frameon=True, facecolor='white', framealpha=0.9, fontsize=10)
ax.grid(True, linestyle='--', alpha=0.5)
plt.tight_layout()
plt.savefig(os.path.join(PLOTS_DIR, 'equity_curve.png'))
plt.close()

# 2. Drawdown Plot
comb['peak'] = comb['combined_cum'].cummax()
comb['drawdown'] = comb['combined_cum'] - comb['peak']

fig, ax = plt.subplots(figsize=(10, 3.5), dpi=300)
ax.fill_between(comb['date'], comb['drawdown'], 0, color='#EF4444', alpha=0.35, label='Drawdown Depth')
ax.plot(comb['date'], comb['drawdown'], color='#DC2626', linewidth=1.2)
ax.axhline(0, color='black', linewidth=0.8, linestyle='-')
ax.set_title('Portfolio Drawdown Profile (Max DD: -₹3.58 Lakhs)', fontsize=12, fontweight='bold', pad=10)
ax.set_ylabel('Drawdown (₹ Lakhs)', fontsize=10, fontweight='bold')
ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
ax.xaxis.set_major_locator(mdates.YearLocator())
ax.grid(True, linestyle='--', alpha=0.5)
plt.tight_layout()
plt.savefig(os.path.join(PLOTS_DIR, 'drawdown_curve.png'))
plt.close()

# 3. Year-over-Year Bar Chart
y1 = ex1.groupby('year')['net_pnl'].sum() / 1e5
y2 = ex2.groupby('year')['net_pnl'].sum() / 1e5
all_years = sorted(list(set(y1.index).union(set(y2.index))))

y1_vals = [y1.get(y, 0) for y in all_years]
y2_vals = [y2.get(y, 0) for y in all_years]
tot_vals = [y1_vals[i] + y2_vals[i] for i in range(len(all_years))]

x = np.arange(len(all_years))
width = 0.35

fig, ax = plt.subplots(figsize=(10, 4.5), dpi=300)
rects1 = ax.bar(x - width/2, y1_vals, width, label='Model 1 (09:20 Scalp)', color='#F59E0B', alpha=0.9)
rects2 = ax.bar(x + width/2, y2_vals, width, label='Model 2 (09:42 Hybrid)', color='#3B82F6', alpha=0.9)

for i, tot in enumerate(tot_vals):
    ax.annotate(f'Total: ₹{tot:.1f}L',
                xy=(x[i], max(y1_vals[i], y2_vals[i]) + 2.5),
                ha='center', va='bottom', fontsize=9, fontweight='bold', color='#1E293B')

ax.set_title('Year-over-Year Net Take-Home Profit (₹ Lakhs)', fontsize=12, fontweight='bold', pad=12)
ax.set_ylabel('Net Profit (₹ Lakhs)', fontsize=10, fontweight='bold')
ax.set_xticks(x)
ax.set_xticklabels([str(int(y)) for y in all_years], fontweight='bold')
ax.set_ylim(0, max(tot_vals) + 12)
ax.legend(loc='upper right', frameon=True, facecolor='white', framealpha=0.9, fontsize=10)
ax.grid(True, axis='y', linestyle='--', alpha=0.5)
plt.tight_layout()
plt.savefig(os.path.join(PLOTS_DIR, 'yearly_pnl.png'))
plt.close()

# 4. Win Rate / Cost Breakdown Pie Chart
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4.2), dpi=300)

# Trade Outcome Pie
ex_comb = pd.concat([ex1, ex2])
wins = (ex_comb['net_pnl'] > 0).sum()
losses = (ex_comb['net_pnl'] <= 0).sum()
ax1.pie([wins, losses], labels=[f'Winning Trades\n({wins:,} | {wins/len(ex_comb)*100:.1f}%)', f'Losing Trades\n({losses:,} | {losses/len(ex_comb)*100:.1f}%)'],
        colors=['#10B981', '#F43F5E'], autopct='%1.1f%%', startangle=140, textprops={'fontweight':'bold', 'fontsize':9}, explode=(0.04, 0))
ax1.set_title('Overall Trade Win/Loss Distribution\n(9,182 Executed Trades)', fontsize=11, fontweight='bold')

# Revenue vs Costs Pie
gross = ex_comb['gross_pnl'].sum() / 1e5
charges = ex_comb['total_kotak_charges'].sum() / 1e5
net = ex_comb['net_pnl'].sum() / 1e5
ax2.pie([net, charges], labels=[f'Net Take-Home\n(₹{net:.2f}L | {net/gross*100:.1f}%)', f'Kotak Taxes & Fees\n(₹{charges:.2f}L | {charges/gross*100:.1f}%)'],
        colors=['#0EA5E9', '#F97316'], autopct='%1.1f%%', startangle=140, textprops={'fontweight':'bold', 'fontsize':9}, explode=(0.05, 0))
ax2.set_title('Gross Profit Allocation\n(Net Cash vs. Statutory Charges)', fontsize=11, fontweight='bold')

plt.tight_layout()
plt.savefig(os.path.join(PLOTS_DIR, 'breakdown_pies.png'))
plt.close()

print("✔ All 4 high-resolution plots generated successfully in:", PLOTS_DIR)
