# 🚀 LIVE EXECUTION PLAYBOOK: DUAL HYBRID OPTIONS

This document outlines the strict production rules required to translate the historical backtest performance (+₹42L to +₹85L) into a live brokerage environment. Failure to enforce these mathematical constraints exposes the account to extreme slippage and black-swan margin traps.

---

## 🛠️ THE 3 MANDATORY SAFETY FILTERS

These three filters **must** be verified in your execution code *before* a payload is sent to the broker API (Zerodha, Upstox, etc.). Reference the provided `live_execution_bot_template.py` for the exact code implementation.

### 1. The Maximum Capital Cap (Volume Dial)
* **Rule:** Never deploy more than **₹2,00,000** (or your designated cap) per stock.
* **Mechanic:** The bot calculates the exact number of lots you can afford based on the margin block of the spread.
* **Formula:** `lots_to_execute = min(int(MAX_CAPITAL_PER_TRADE // margin_for_1_lot), 20)`
* **Why:** This prevents compounding risk. If you double your account size, you do not double your trade size. You maintain a flat allocation to survive outlier losing streaks.

### 2. The Penny Stock Margin Trap Filter (>₹2L Reject)
* **Rule:** If the theoretical max physical loss for a single lot exceeds **₹2,00,000**, skip the trade immediately.
* **Mechanic:** Calculate the spread width (e.g., ATM+1 minus ATM-3) and multiply by the lot size. 
* **Formula:** `if (put_spread_width * lot_size) > 200000: return REJECT`
* **Why:** This surgically targets and bans toxic penny options with massive lot sizes (like *Vodafone Idea* requiring ₹3.2L per lot, or *Canara Bank* requiring ₹2.7L per lot) without randomly banning perfectly fine low-priced stocks. It prevents tying up 100% of your account on a single lot.

### 3. The ₹0.50 Premium Liquidity Floor
* **Rule:** If *any* of the 4 required options legs (Buy or Sell, Entry or Exit) has a live premium strictly below **₹0.50**, cancel the trade.
* **Mechanic:** Ping the broker API for real-time CMP quotes of all strikes 1 second before order placement.
* **Why:** The deepest out-of-the-money legs (like the ATM-3 Put) frequently decay to zero (₹0.05 or ₹0.10) on low volatility days. Crossing the bid-ask spread on these penny options guarantees 100% slippage on exit. Banning them forces the system to sit out the lowest-probability, choppiest days, actively *increasing* overall PnL.

---

## ⏱️ TIME & EXECUTION CONSTRAINTS

### Entry: 15:26 IST (Strict)
* **Why:** Avoids intraday gamma spikes, Theta decay, and stop-loss hunting. Entering 4 minutes before market close capitalizes purely on the overnight gap probabilities predicted by the ML model.

### Exit: 09:25 IST (Strict)
* **Why:** The first 10 minutes (09:15 to 09:25) allows the volatile bid-ask spreads to settle. Exiting exactly at 09:25 captures the gap momentum before 10:00 AM intraday reversals systematically erase the profit.

---

## 📁 REFERENCE FILES IN REPOSITORY
* `live_execution_bot_template.py` - The Python logic framework enforcing these rules.
* `DUAL_HYBRID_FINDINGS.md` - The master architectural breakdown of the strategy.
* `Perfected_Quant_Tearsheet.md` - The mathematical breakdown of CAGR, Sharpe, and Win Rates for the system.

### 4. The Gamma/Expiry Rollover Rule (DTE <= 2)
* **Rule:** If the ML signal is generated 2 days or less before the current month's expiry date (e.g., on Wednesday or Thursday of expiry week), the bot MUST execute the option spread on the **Next Month's (Far Month)** contract instead of the Current Month.
* **Why:** The backtest revealed that signals generated near expiry occasionally hold overnight past the actual expiry date (if gap_days > 1 due to holidays). Executing on a dying contract makes this physically impossible and exposes the portfolio to extreme Gamma risk. Rolling to the next month guarantees 30+ days of safety and prevents expiration assignment crossovers.
