# Notice: 01_model1_0920 (Archival / Reference)

> ⚠️ **CANONICAL PRODUCTION MODEL LOCATION:**  
> The certified, production-ready 09:20 Scalp Model and all reproduction scripts have been centralized into:  
> 👉 `/home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_shortsell_t1_2026/01_0920_Scalp_Model/`

### Reproduction Commands:
```bash
cd /home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_shortsell_t1_2026/01_0920_Scalp_Model

# Step 1: Extract features from MySQL scrapdata
python3 0_extract_0920_dataset.py

# Step 2: Retrain Walk-Forward LightGBM Model
python3 1_build_features_and_train.py

# Step 3: Run full tick-by-tick MySQL verification audit
python3 2_db_tick_verification.py
```

Refer to `sarang_shortsell_t1_2026/01_0920_Scalp_Model/HOW_TO_REPRODUCE_FROM_SCRATCH.md` for complete mathematical and architecture documentation.
