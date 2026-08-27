#!/bin/bash
DATES=("2026-03-04" "2026-03-12" "2026-04-21" "2026-04-22" "2026-04-28" "2026-05-29" "2026-06-01" "2026-06-02" "2026-06-03" "2026-06-04")

for d in "${DATES[@]}"; do
    echo "======================================"
    echo "[MySQL] Deleting stale rows for $d..."
    mysql -u root -proot markets -e "DELETE FROM scrapdata_F1 WHERE date='$d';"
    
    echo "[Node] Starting backfill for $d..."
    node pipeline/fill_missing_f1_data.js $d $d
done
echo "======================================"
echo "All done! Verifying new counts..."
mysql -u root -proot markets -e "SELECT date, COUNT(*) FROM scrapdata_F1 WHERE date IN ('2026-03-04','2026-03-12','2026-04-21','2026-04-22','2026-04-28','2026-05-29','2026-06-01','2026-06-02','2026-06-03','2026-06-04') GROUP BY date;"
