#!/usr/bin/env python3
"""
kotak_mis_calculator.py
=======================
Exact Kotak Securities / Kotak Neo MIS Margin & Brokerage Calculator.

Formulas match official Kotak Neo Trade Free Plan & SEBI Regulatory Mandates:
1. Margin Requirement:
   - Product: MIS (Margin Intraday Square-off) on Equity Cash
   - Leverage: 5.0x (20% margin requirement based on SEBI VaR + ELM rules for Category 1 F&O stocks)
   - Margin Required = (Entry Price * Quantity) / 5.0

2. Transaction & Regulatory Charges (Round-Trip Intraday):
   - Brokerage: Flat Rs 20 per executed order (Rs 40 round-trip for entry + exit)
   - STT (Securities Transaction Tax): 0.025% on Sell side turnover
   - Exchange Transaction Charges (NSE): 0.00297% on Total turnover (Buy + Sell)
   - SEBI Turnover Fees: Rs 10 per crore (0.0001% of Total turnover)
   - Stamp Duty: 0.003% on Buy side turnover (Rs 300 per crore)
   - GST: 18% on (Brokerage + Exchange Txn Charges + SEBI Fees)
"""

def calculate_kotak_margin(entry_price: float, quantity: int, leverage: float = 5.0) -> dict:
    """
    Calculates exact MIS margin requirement for an intraday stock trade.
    """
    trade_value = round(entry_price * quantity, 2)
    margin_required = round(trade_value / leverage, 2)
    return {
        'trade_value': trade_value,
        'leverage': leverage,
        'margin_pct': round((1.0 / leverage) * 100, 2),
        'margin_required': margin_required
    }

def calculate_kotak_charges(entry_price: float, exit_price: float, quantity: int, is_short: bool = True) -> dict:
    """
    Calculates line-by-line Kotak Neo statutory charges & brokerage for round-trip trade.
    For short-sell: Sell first (Entry), Buy later (Exit).
    """
    if is_short:
        sell_turnover = round(entry_price * quantity, 2)
        buy_turnover  = round(exit_price * quantity, 2)
    else:
        buy_turnover  = round(entry_price * quantity, 2)
        sell_turnover = round(exit_price * quantity, 2)

    total_turnover = round(sell_turnover + buy_turnover, 2)

    # 1. Kotak Neo Trade Free Brokerage (Rs 20 per order, 2 orders = Rs 40)
    brokerage = 40.00

    # 2. STT: 0.025% on Sell side only
    stt = round(sell_turnover * 0.00025, 2)

    # 3. Exchange Transaction Charges (NSE): 0.00297% on total turnover
    exchange_charges = round(total_turnover * 0.0000297, 2)

    # 4. SEBI Turnover Charges: Rs 10 / Crore = 0.0001% of total turnover
    sebi_fees = round(total_turnover * 0.000001, 2)

    # 5. Stamp Duty: 0.003% on Buy side
    stamp_duty = round(buy_turnover * 0.00003, 2)

    # 6. GST: 18% on (Brokerage + Exchange Charges + SEBI Fees)
    gst = round((brokerage + exchange_charges + sebi_fees) * 0.18, 2)

    # 7. Safety Buffer: Rs 50.00 extra per trade to account for slippage/miscellaneous charges
    safety_buffer = 50.00

    # Total Charges (including Rs 50 safety buffer)
    total_charges = round(brokerage + stt + exchange_charges + sebi_fees + stamp_duty + gst + safety_buffer, 2)

    return {
        'sell_turnover': sell_turnover,
        'buy_turnover': buy_turnover,
        'total_turnover': total_turnover,
        'brokerage': brokerage,
        'stt': stt,
        'exchange_charges': exchange_charges,
        'sebi_fees': sebi_fees,
        'stamp_duty': stamp_duty,
        'gst': gst,
        'safety_buffer': safety_buffer,
        'total_charges': total_charges
    }

if __name__ == '__main__':
    # Demonstration on a sample trade
    ep = 500.0
    xp = 490.0
    qty = 1000
    m = calculate_kotak_margin(ep, qty)
    c = calculate_kotak_charges(ep, xp, qty)
    print("=" * 60)
    print("KOTAK NEO MIS MARGIN & CHARGES DEMONSTRATION")
    print("=" * 60)
    print(f"Stock Trade        : Qty {qty} @ Entry Rs {ep} -> Exit Rs {xp}")
    print(f"Trade Value        : Rs {m['trade_value']:,.2f}")
    print(f"Leverage Available : {m['leverage']}x ({m['margin_pct']}%)")
    print(f"Margin Required    : Rs {m['margin_required']:,.2f}")
    print("-" * 60)
    print(f"Brokerage (Kotak)  : Rs {c['brokerage']:.2f}")
    print(f"STT (0.025% Sell)  : Rs {c['stt']:.2f}")
    print(f"Exchange Txn Fee   : Rs {c['exchange_charges']:.2f}")
    print(f"SEBI Turnover Fee  : Rs {c['sebi_fees']:.2f}")
    print(f"Stamp Duty (Buy)   : Rs {c['stamp_duty']:.2f}")
    print(f"GST (18%)          : Rs {c['gst']:.2f}")
    print(f"Total Charges      : Rs {c['total_charges']:.2f}")
    print("=" * 60)
