import pandas as pd

df = pd.read_csv('/home/ubuntu/sarang_2026_shortsell_algos/05_Clean_Strict_Rebuild/model1_0920_pnl_sheet.csv')
sample = df.iloc[0]  # Just take the very first trade

buy_p = sample['Buy_Price']
sq_p = sample['SquareOff_Price']
qty = sample['Quantity']
net_csv = sample['Net_Rs_PnL']

print(f"--- RANDOM TRADE VERIFICATION ---")
print(f"Date: {sample['Date']} | Stock: {sample['Stock']}")
print(f"Buy Price (Short): Rs {buy_p}")
print(f"Square Off Price: Rs {sq_p}")
print(f"Quantity: {qty}")

gross = (buy_p - sq_p) * qty
print(f"\n1. Gross Profit: ({buy_p} - {sq_p}) * {qty} = Rs {gross:.2f}")

sell_value = qty * buy_p
buy_value = qty * sq_p
turnover = sell_value + buy_value

stt = round(sell_value * 0.00025)
txn = turnover * 0.0000322
sebi = turnover * 0.000001
stamp = round(buy_value * 0.00003)
gst = (txn + sebi) * 0.18
taxes = round(stt + txn + sebi + stamp + gst, 2)

print(f"2. Taxes (Kotak MIS):")
print(f"   STT: Rs {stt}")
print(f"   Txn: Rs {txn:.2f}")
print(f"   SEBI: Rs {sebi:.2f}")
print(f"   Stamp: Rs {stamp}")
print(f"   GST: Rs {gst:.2f}")
print(f"   Total Taxes: Rs {taxes:.2f}")

net = round(gross - taxes, 2)
print(f"\n3. Final Net Profit: {gross:.2f} - {taxes:.2f} = Rs {net:.2f}")
print(f"4. CSV Sheet Value: Rs {net_csv}")

if net == net_csv:
    print("\n✅ MATCH CONFIRMED! THE MATH TALLIES PERFECTLY.")
else:
    print("\n❌ MISMATCH DETECTED!")
