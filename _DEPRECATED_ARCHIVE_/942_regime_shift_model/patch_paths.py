import os

folder = '/home/ubuntu/942_regime_shift_model'
old_folder = '/home/ubuntu/github_repo/sarang_2026_shortsell_algos/02_Best_Longer_Window_0942_1445'

# 0_generate_global_features.py
with open(f'{folder}/0_generate_global_features.py', 'r') as f:
    text = f.read()
text = text.replace(old_folder, folder)
with open(f'{folder}/0_generate_global_features.py', 'w') as f:
    f.write(text)

# 1_run_ml_simulation.py
with open(f'{folder}/1_run_ml_simulation.py', 'r') as f:
    text = f.read()
text = text.replace(old_folder, folder)
with open(f'{folder}/1_run_ml_simulation.py', 'w') as f:
    f.write(text)

# 2_bulletproof_db_audit.py
with open(f'{folder}/2_bulletproof_db_audit.py', 'r') as f:
    text = f.read()
text = text.replace(old_folder, folder)
# Rename the output CSV to be explicitly clear
text = text.replace('bulletproof_model2_pnl.csv', 'final_verified_ledger_86L.csv')
with open(f'{folder}/2_bulletproof_db_audit.py', 'w') as f:
    f.write(text)

