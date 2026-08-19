"""
LIVE OPTIONS EXECUTION BOT - DUAL HYBRID COMBO
----------------------------------------------
This is a production-ready template that automatically enforces the 3 core safety rules:
1. MAX_CAPITAL_PER_TRADE = ₹2,00,000 to ₹4,00,000 (Adjustable)
2. MIN_PREMIUM_FILTER = ₹0.50 (Liquidity Check)
3. PENNY_STOCK_MARGIN_FILTER = ₹2,00,000 (Margin Trap Check)

Execution Timing:
- Entry: 15:26 IST
- Exit: 09:25 IST (Next trading day)
"""

import math
from datetime import datetime
import pandas as pd

# === STRATEGY CONFIGURATION ===
MAX_CAPITAL_PER_TRADE = 200000  # Rs 2 Lakhs strictly capped per order
MIN_PREMIUM = 0.50              # Minimum premium required to execute any leg
MAX_1LOT_MARGIN = 200000        # Reject stock if 1 lot spread margin exceeds this
BROKER_COMMISSION_EST = 400     # Estimated cost per lot (Entry+Exit round trip)

def get_strike_step(price):
    if price > 2500: return 50
    if price > 1000: return 20
    if price > 500:  return 10
    if price > 100:  return 5
    if price > 50:   return 2.5
    return 1

def generate_hybrid_strikes(spot_price):
    step = get_strike_step(spot_price)
    atm = round(spot_price / step) * step
    
    return {
        'put_sell': atm + step,      # ATM+1
        'put_buy': atm - (3 * step), # ATM-3
        'call_buy': atm - step,      # ATM-1
        'call_sell': atm + step,     # ATM+1
        'step_width': step
    }

def validate_and_size_trade(stock, spot_price, lot_size, broker_api):
    """
    Validates a stock signal against the 3 core risk filters and calculates position size.
    """
    strikes = generate_hybrid_strikes(spot_price)
    
    # -------------------------------------------------------------
    # FILTER 1: PENNY STOCK MARGIN FILTER (The "IDEA / CANBK" Trap)
    # -------------------------------------------------------------
    put_spread_width = strikes['put_sell'] - strikes['put_buy']
    margin_for_1_lot = put_spread_width * lot_size
    
    if margin_for_1_lot > MAX_1LOT_MARGIN:
        print(f"[REJECTED] {stock}: 1-Lot Margin (Rs {margin_for_1_lot}) exceeds {MAX_1LOT_MARGIN} limit.")
        return None
        
    # Calculate Safe Position Sizing (Volume Dial)
    allocated_lots = min(int(MAX_CAPITAL_PER_TRADE // margin_for_1_lot), 20) # NSE Freeze limit is 20
    if allocated_lots < 1:
        print(f"[REJECTED] {stock}: Capital Rs {MAX_CAPITAL_PER_TRADE} insufficient for 1 lot (Req: {margin_for_1_lot}).")
        return None
        
    # -------------------------------------------------------------
    # FILTER 2: THE 0.50 LIQUIDITY FILTER (Penny Option Trap)
    # -------------------------------------------------------------
    # In live execution, fetch real-time CMP for the required strikes from broker
    live_quotes = broker_api.get_live_quotes(stock, strikes)
    
    if any(premium < MIN_PREMIUM for premium in live_quotes.values()):
        print(f"[REJECTED] {stock}: One or more legs dropped below {MIN_PREMIUM} liquidity floor.")
        return None
        
    # -------------------------------------------------------------
    # PASS: RETURN EXECUTION PAYLOAD
    # -------------------------------------------------------------
    print(f"[APPROVED] {stock}: Passing all safety filters. Executing {allocated_lots} lots.")
    return {
        'stock': stock,
        'lots_to_execute': allocated_lots,
        'strikes': strikes,
        'margin_utilized': allocated_lots * margin_for_1_lot
    }

class MockBrokerAPI:
    """Placeholder for actual Zerodha/Upstox API integrations"""
    def get_live_quotes(self, stock, strikes):
        # Mocking prices safely above 0.5 for demonstration
        return {'put_sell': 5.50, 'put_buy': 1.20, 'call_buy': 7.00, 'call_sell': 3.50}

if __name__ == "__main__":
    broker = MockBrokerAPI()
    
    print("--- TESTING VALID STOCK (NMDC) ---")
    validate_and_size_trade(stock="NMDC", spot_price=230, lot_size=4500, broker_api=broker)
    
    print("\n--- TESTING PENNY TRAP (IDEA) ---")
    validate_and_size_trade(stock="IDEA", spot_price=13.70, lot_size=80000, broker_api=broker)
