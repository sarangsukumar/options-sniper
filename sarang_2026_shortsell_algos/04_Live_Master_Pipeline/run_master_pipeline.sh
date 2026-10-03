#!/bin/bash

# Source environment
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
cd /home/ubuntu/sarang_2026_shortsell_algos/04_Live_Master_Pipeline

LOGFILE="/home/ubuntu/sarang_2026_shortsell_algos/04_Live_Master_Pipeline/master_cron.log"
echo "===================================" >> $LOGFILE
echo "Running Master Pipeline at $(date)" >> $LOGFILE

python3 live_master_execution.py >> $LOGFILE 2>&1

echo "Master Pipeline Finished at $(date)" >> $LOGFILE
