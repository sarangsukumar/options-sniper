import subprocess
import re

def verify_flat():
    try:
        # Run the existing robust script in dry-run/query mode to fetch positions safely
        res = subprocess.run(['python3', '/home/ubuntu/KotakCodes1/CreateOptionSquareofflimitorders.py', 'ZCK30', 'CUSTOM'], capture_output=True, text=True)
        
        anomalies = []
        # Find any non-zero positions logged by the script
        for line in res.stdout.split('\n') + res.stderr.split('\n'):
            if "Considering position for CUSTOM order" in line and "NetQty=" in line:
                match = re.search(r'Symbol=([^,]+).*?NetQty=([-\d\.]+)', line)
                if match:
                    sym = match.group(1)
                    qty = float(match.group(2))
                    if qty != 0:
                        anomalies.append(f"• {sym} -> Net Qty: {qty}")
                        
        # Deduplicate
        anomalies = list(set(anomalies))
        
        if anomalies:
            msg = "⚠️ <b>URGENT: UNCLOSED POSITIONS DETECTED!</b>\n"
            msg += "The bot has finished the morning square-off, but Kotak's backend reports the following positions are STILL OPEN in your account:\n\n"
            msg += "\n".join(anomalies)
            msg += "\n\n<i>Please log into the Kotak app immediately to verify and close them manually!</i>"
            
            print("Sending warning to Telegram...")
            subprocess.run(['node', '/home/ubuntu/KotakCodes1/status_Info_bot.js', msg], timeout=15)
        else:
            print("All F&O positions are completely flat. No anomalies detected.")
            
    except Exception as e:
        print(f"Error in verification: {e}")

if __name__ == "__main__":
    verify_flat()
