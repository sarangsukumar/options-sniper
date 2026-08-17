#!/usr/bin/env python3
"""
Master Orchestrator
===================
1. Waits for daily cache rebuild to complete
2. Runs ensemble rebuild
3. Runs full_yoy_analysis.py (max_order=2,3,4 + dual-confirmed + PDF + Telegram)

Crash-resistant: checks completion via CSV dates, retries each step up to 3 times.
"""

import os, sys, time, subprocess, json, urllib.request, urllib.parse

_THIS_DIR  = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(_THIS_DIR, "output")

BOT_TOKEN = "8701163032:AAGE-TiX4-zippXmqtWc2oc4dgROoLokS6k"
CHAT_ID   = "-698073972"

def send_tg(text):
    url  = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({'chat_id': CHAT_ID, 'text': text}).encode()
    try: urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=15)
    except: pass

def get_csv_last_date(freq):
    path = os.path.join(OUTPUT_DIR, f"trades_dynamic_threshold_{freq}.csv")
    if not os.path.exists(path): return None
    try:
        result = subprocess.run(['tail', '-1', path], capture_output=True, text=True)
        return result.stdout.strip().split(',')[0] if result.stdout else None
    except: return None

def run_step(cmd, label, max_retries=3):
    for attempt in range(1, max_retries+1):
        print(f"\n[{label}] Attempt {attempt}/{max_retries}...")
        try:
            result = subprocess.run(
                cmd, cwd=_THIS_DIR, capture_output=True, text=True, timeout=1800
            )
            if result.returncode == 0:
                print(f"[{label}] ✅ Done")
                return True
            else:
                print(f"[{label}] ❌ Failed (exit {result.returncode})")
                print(result.stderr[-500:] if result.stderr else "no stderr")
                if attempt < max_retries:
                    print(f"[{label}] Retrying in 10s...")
                    time.sleep(10)
        except subprocess.TimeoutExpired:
            print(f"[{label}] ⏱ Timed out after 30 min")
            if attempt < max_retries:
                time.sleep(10)
        except Exception as e:
            print(f"[{label}] Exception: {e}")
            if attempt < max_retries:
                time.sleep(10)
    send_tg(f"⚠️ [{label}] failed after {max_retries} attempts. Check server logs.")
    return False

def wait_for_daily(timeout_min=30):
    """Wait for any running daily rebuild process to finish."""
    print("\n[WAIT] Checking if daily rebuild is already running...")
    deadline = time.time() + timeout_min * 60
    while time.time() < deadline:
        result = subprocess.run(
            ['pgrep', '-f', 'dynamic_threshold.py daily'],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            print("[WAIT] No daily process running — proceeding.")
            return True
        print(f"[WAIT] Daily rebuild still running... (checking again in 60s)")
        time.sleep(60)
    print("[WAIT] Timeout waiting for daily. Will rebuild it ourselves.")
    return False

def main():
    print("=" * 60)
    print("  MASTER ORCHESTRATOR — Champion Strategy Rebuild + Analysis")
    print("=" * 60)

    send_tg("🔧 Orchestrator started: rebuilding caches and running analysis.")

    # ── Step 1: Wait for or run daily rebuild ──────────────────────────────
    daily_date = get_csv_last_date('daily')
    print(f"\n[CHECK] Current daily CSV date: {daily_date}")

    # Wait for any existing daily process
    wait_for_daily(timeout_min=25)

    # Check if daily needs rebuild (target: should be >= 2026-08-04 ideally Aug 11)
    daily_date = get_csv_last_date('daily')
    print(f"[CHECK] Daily CSV date after wait: {daily_date}")

    if not daily_date or daily_date < '2026-08-04':
        print("[STEP 1] Running daily rebuild...")
        send_tg("⚙️ Step 1/3: Rebuilding daily frequency cache...")
        ok = run_step(['python3', 'dynamic_threshold.py', 'daily'], 'DAILY')
        if not ok:
            send_tg("❌ Daily rebuild failed. Attempting analysis with existing data.")
    else:
        print(f"[STEP 1] Daily already up-to-date ({daily_date}). Skipping.")

    # ── Step 2: Run ensemble ───────────────────────────────────────────────
    print("\n[STEP 2] Running ensemble rebuild...")
    send_tg("⚙️ Step 2/3: Rebuilding ensemble (combining all 5 frequencies)...")
    run_step(['python3', 'test_trimmed_adaptive_hybrid_pnl_noise_removed.py'], 'ENSEMBLE')

    # ── Step 3: Full YoY analysis + PDF + Telegram ─────────────────────────
    print("\n[STEP 3] Running full YoY analysis (Max Orders 2, 3, 4)...")
    send_tg("⚙️ Step 3/3: Running YoY analysis for Max Orders 2, 3, 4...")
    ok = run_step(['python3', 'full_yoy_analysis.py'], 'ANALYSIS')

    if ok:
        print("\n✅ ALL STEPS COMPLETE — PDF sent via Telegram!")
    else:
        send_tg("⚠️ Analysis step failed. Check /home/ubuntu logs.")
        sys.exit(1)

if __name__ == "__main__":
    main()
