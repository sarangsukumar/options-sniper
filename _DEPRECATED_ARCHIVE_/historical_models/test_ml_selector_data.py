import os
import sys
import pandas as pd

# Add parent dir to path so we can import predict_today
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PARENT_DIR = os.path.dirname(_THIS_DIR)
sys.path.append(_PARENT_DIR)

from predict_today import load_pnl

def main():
    print("⏳ Loading master PnL and computing all standard features...")
    df_features = load_pnl()
    print(f"Features loaded! Shape: {df_features.shape}")
    
    # Identify features actually present in the loaded dataframe
    present_features = [
        'intraday_return', 'intraday_rsi_9', 'intraday_macd', 'intraday_bb_pct_b', 
        'first_tick_to_1519_pct', '1450_to_1519_pct', 'Gap_Pct', 'prev_close_price', 
        'daily_open', 'volume_change_pct'
    ]
    available_features = [c for c in present_features if c in df_features.columns]
    print("Feature columns available:", available_features)
    
    # Load the combined multi-exit CSV
    combined_csv_path = "/home/ubuntu/daily_prediction_system_Dynamic_threshold_Backtest_Dev/data/combined_multi_exit_pnl.csv"
    print(f"\n⏳ Loading combined multi-exit PnL sheet from {combined_csv_path}...")
    df_multi = pd.read_csv(combined_csv_path)
    print(f"Combined sheet loaded! Shape: {df_multi.shape}")
    
    # Align dates and merge
    df_features['simulationdate'] = df_features['dt_parsed'].dt.strftime('%Y-%m-%d')
    
    print("\n⏳ Merging features with multi-exit targets...")
    merged_df = pd.merge(
        df_multi,
        df_features[['simulationdate', 'stockname'] + available_features],
        on=['simulationdate', 'stockname'],
        how='inner'
    )
    print(f"Merged successfully! Shape: {merged_df.shape}")
    print("Matched rows for training:", len(merged_df))
    
    # Drop rows with NaN in features
    train_data = merged_df.dropna(subset=available_features)
    print(f"Rows ready after dropping NaNs in features: {len(train_data)}")
    
if __name__ == '__main__':
    main()
