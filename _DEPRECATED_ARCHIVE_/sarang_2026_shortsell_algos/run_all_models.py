#!/usr/bin/env python3
"""
Master runner redirecting to verify_all_results.py for instant verification
"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
script = os.path.join(BASE_DIR, 'verify_all_results.py')
os.system(f"python3 {script}")
