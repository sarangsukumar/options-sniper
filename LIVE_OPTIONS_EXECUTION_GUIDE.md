# 🚀 LIVE OPTIONS EXECUTION GUIDE
## Master Playbook for Automated System Integration

This document provides exact, mathematically deterministic instructions for developers setting up the live, fully-automated trade execution engine for the ML-driven options system.

The core underlying ML engine successfully predicts the correct stock and outputs it to the database/terminal. The following logic dictates **exactly how to convert that stock prediction into live options limit orders.**

---

### 🕒 STEP 1: Capture the Anchor Price (F1 Tick)
At exactly **15:25 IST** (just before the 15:26 target entry minute), your system must pull the Live Market Price (LMP) of the **Current Month Futures Contract (F1)** for the predicted stock.
* **Why F1 and not Equity Spot?** The Futures price represents the true cost-of-carry forward price. Options are mathematically priced off the forward curve, making the F1 price the most accurate anchor for strike selection.
* **Example:** `ADANIENT` ML prediction triggers. At 15:25, `ADANIENT` F1 is trading at `₹3,142.60`.

---

### 📏 STEP 2: Calculate the NSE Strike Step (Gap)
The National Stock Exchange (NSE) standardizes strike intervals based on the stock's absolute price. Your system must dynamically calculate the step size using the following logic:

```python
def calculate_strike_step(f1_price):
    if f1_price < 50: return 1
    if f1_price <= 250: return 2.5
    if f1_price <= 1000: return 5
    if f1_price <= 3000: return 10
    if f1_price <= 6000: return 50
    return 100
```
* **Example:** For `₹3,142.60`, the step size is **`₹50`**.

---

### 🎯 STEP 3: Mathematically Calculate the Legs (Optimal -2 OTM Spread)
*Note: Extensive historical backtesting proved that the **-2 OTM** spread outperforms the -3 OTM spread by allowing higher margin leverage and maxing out our lot sizing limits safely.*

Our mathematically proven "Elite" strategy is the **Bull Put Spread (+1 ITM / -2 OTM)** on the R1 & R3 Top Candidates.

**A. Find the At-The-Money (ATM) Anchor:**
Round the F1 price to the nearest valid strike step.
* *Math:* `Round(3142.60 / 50) * 50 = 3150`
* **ATM Strike = `3150`**

**B. Calculate the Target Legs:**
* **SELL LEG (+1 ITM Put):** Move UP one step from ATM.
  * `3150 + (1 * 50)` = **`3200 PE`**
* **BUY LEG (-2 OTM Put):** Move DOWN two steps from ATM.
  * `3150 - (2 * 50)` = **`3050 PE`**

---

### ⚙️ STEP 4: Position Sizing Constraints & NSE Freeze Limits
The total required margin for a credit spread is calculated as the maximum theoretical loss between the strikes. 
* **System Constraint:** Max allocation per trade is **`₹4,00,000`**.
* **NSE Freeze Cap:** To prevent exchange rejection, we place an absolute hard cap of **20 lots** per order.

Calculate the exact number of lots to execute:
```python
margin_per_lot = (sell_strike - buy_strike) * lot_size
calculated_lots = int(400000 // margin_per_lot)

# CRITICAL: Apply safety cap to prevent NSE Quantity Freeze rejection
lots_to_execute = min(calculated_lots, 20) 
```

---

### 🚦 STEP 5: Pre-Trade Liquidity Checks (The "Anti-Fallback" Rule)
**DO NOT use fallback logic!** If the targeted `-2 OTM` strike is missing from the market or completely illiquid, do not fall back to the `-3 OTM` strike. Missing data implies a toxic, illiquid market. If the following liquidity checks fail on the `-2 OTM` leg, **ABORT THE TRADE ENTIRELY.**

1. **Bid-Ask Spread Filter:** If `(Best Ask - Best Bid) / Best Bid` > `0.05` (5%), abort trade.
2. **Market Depth Quantity Check:** Ensure the cumulative quantity at the Top 3 Bids/Asks is greater than `lots_to_execute * lot_size`. Otherwise, abort to prevent slippage.
3. **Volume Check:** Ensure daily volume > 100 contracts.

---

### 🛡️ STEP 6: Order Execution Sequence (CRITICAL)
When placing the limit orders into the live broker system, **the sequence of execution is paramount to prevent margin rejections.**

You are placing a Credit Spread. If you attempt to short the ITM Put first, the broker will require enormous naked-margin (often ₹1L - ₹2L+ per lot) and the order will instantly fail due to insufficient funds.

**The Golden Execution Sequence:**
1. **FIRST ORDER (HEDGE):** Send the `BUY` order for the `-2 OTM Put` (e.g., `3050 PE`).
   * Wait for the broker to return an `EXECUTED` / `FILLED` status.
2. **SECOND ORDER (SHORT):** Send the `SELL` order for the `+1 ITM Put` (e.g., `3200 PE`).
   * Because the Buy order is already filled, the broker recognizes the spread and calculates a drastically reduced margin requirement (usually ~₹10k to ₹20k), allowing the order to pass seamlessly.

---

### 🚪 STEP 7: Next-Day Exit Logic
At **09:25 IST** the next morning (or slightly after opening volatility settles), close the position by executing the inverse orders:
1. **BUY TO COVER:** The `+1 ITM Put`.
2. **SELL TO CLOSE:** The `-2 OTM Put`.
*(Sequence matters less for exit, but closing the short first guarantees margin compliance).*
