#!/bin/bash
echo "Starting Master Verification Suite..."
python3 rebuild_model1_cash.py
python3 rebuild_model2_futures.py
echo "All rebuilds complete! Check the output/ folder for audited ledgers."
