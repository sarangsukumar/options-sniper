while pgrep -f "build_0923_dataset_fast.py" > /dev/null; do
    sleep 30
done
python3 /home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_shortsell_t1_2026/03_0925_Extended_Model/train_and_eval.py > /home/ubuntu/daily_prediction_sytem_Dynamic_threshold/sarang_shortsell_t1_2026/03_0925_Extended_Model/final_eval.log 2>&1
