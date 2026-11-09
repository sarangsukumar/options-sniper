#!/usr/bin/env python3
"""
qa_execution_guardrails.py
=============================================================================
Institutional QA Execution Guardrails & Financial Compliance Utilities.

Addresses key vulnerabilities identified in PR #7 Forensic Audit:
1. Strict NSE Tick Size Rounding (₹0.05 rule enforcement).
2. Liquidity-Aware Position Sizing (Max Lot Caps for Single-Stock Options).
3. Realistic Bid-Ask Spread Modeling (2-Tick Friction).
4. Dynamic SEBI Cleared Capital Validation (Session 1 to Session 2 Recycling).
5. Segregated Option Order Staging (Prevents silent Cash MIS DB collisions).
=============================================================================
"""

import os
import json
import numpy as np
import pandas as pd
from datetime import datetime

NSE_TICK_SIZE = 0.05
DEFAULT_MAX_OPTION_LOTS = 5  # Realistic order book depth limit for single-stock options
SMART_STEPUP_MAX_OPTION_LOTS = 15  # Soft liquidity cap when Smart Strike Step-Up (min_prem>=5, min_lot_cost>=8000) is active
MIN_OPTION_PREMIUM_RS = 5.0
MIN_OPTION_LOT_COST_RS = 8000.0


def should_step_up_option_strike(
    premium_cmp: float,
    lot_size: int,
    min_premium: float = MIN_OPTION_PREMIUM_RS,
    min_lot_cost: float = MIN_OPTION_LOT_COST_RS
) -> bool:
    """
    Returns True if a 1_OTM_PE contract is a cheap penny/low-notional option
    that would cause excessive lot counts (e.g. >15-229 lots for ₹1L capital),
    signaling the execution daemon to step up 1 strike to ATM_PE or 1_ITM_PE.
    """
    if premium_cmp is None or premium_cmp <= 0 or lot_size <= 0:
        return True
    return (premium_cmp < min_premium) or ((premium_cmp * lot_size) < min_lot_cost)


def round_to_nse_tick(price: float, direction: str = 'floor', tick: float = NSE_TICK_SIZE) -> float:
    """
    Rounds a price strictly to the nearest valid NSE tick size (₹0.05).

    Parameters:
    -----------
    price : float
        Raw calculated price (e.g., from percentage ratchets).
    direction : str
        'floor' for exits/limit sells (conservative lower price).
        'ceil' for entries/limit buys (conservative higher price).
        'nearest' for standard midpoint rounding.
    tick : float
        Tick size (default 0.05 for NSE equities and stock options).

    Returns:
    --------
    float: Tick-compliant price rounded to 2 decimal places.
    """
    if price is None or np.isnan(price) or price <= 0:
        return 0.05

    if direction == 'floor':
        rounded = np.floor(round(price, 6) / tick) * tick
    elif direction == 'ceil':
        rounded = np.ceil(round(price, 6) / tick) * tick
    else:
        rounded = np.round(round(price, 6) / tick) * tick

    # Guard against zero or negative options pricing
    return max(0.05, round(rounded, 2))


def calculate_option_lots(
    allocated_capital: float,
    premium_cmp: float,
    lot_size: int,
    max_lots: int = DEFAULT_MAX_OPTION_LOTS
) -> int:
    """
    Computes integer option lots constrained by capital and exchange order-book liquidity.

    Parameters:
    -----------
    allocated_capital : float
        Capital allocated for this stock (e.g. ₹1,00,000).
    premium_cmp : float
        Option premium per share (₹).
    lot_size : int
        Exchange contract lot size (e.g. 250 for RELIANCE, 1500 for TATASTEEL).
    max_lots : int
        Maximum permitted lots per single-stock option order (default: 5 lots).

    Returns:
    --------
    int: Discrete lots to trade (1 <= lots <= max_lots).
    """
    if premium_cmp <= 0 or lot_size <= 0 or allocated_capital <= 0:
        return 1

    contract_cost = premium_cmp * lot_size
    theoretical_lots = int(allocated_capital / contract_cost)

    # Floor at 1 lot minimum (if budget permits at least 50% of 1 contract)
    if theoretical_lots < 1:
        if allocated_capital >= 0.5 * contract_cost:
            theoretical_lots = 1
        else:
            theoretical_lots = 0

    # Institutional Guardrail: Cap at max_lots to prevent severe market impact / illiquidity traps
    bounded_lots = min(theoretical_lots, max_lots)
    return max(1, bounded_lots) if theoretical_lots >= 1 else 0


def apply_bid_ask_spread_friction(
    entry_price: float,
    exit_price: float,
    tick_spread: int = 1,
    tick: float = NSE_TICK_SIZE
) -> tuple[float, float]:
    """
    Applies realistic exchange bid-ask spread friction.
    Buys execute at the Ask (entry + spread ticks).
    Sells execute at the Bid (exit - spread ticks).
    """
    friction = tick_spread * tick
    effective_entry = round_to_nse_tick(entry_price + friction, direction='ceil', tick=tick)
    effective_exit = round_to_nse_tick(exit_price - friction, direction='floor', tick=tick)
    return effective_entry, effective_exit


def verify_cleared_recycling_margin(
    session1_realized_loss: float = 0.0,
    base_capital: float = 200000.0,
    max_utilization_ratio: float = 1.0
) -> float:
    """
    Enforces SEBI margin compliance for capital recycling from Session 1 to Session 2.
    If Session 1 suffered a drawdown, the available capital for Session 2 is reduced.

    Parameters:
    -----------
    session1_realized_loss : float
        Realized loss from Session 1 (positive number for losses, e.g. 8000.0 for -₹8,000 PnL).
    base_capital : float
        Base starting margin allocated for the strategy (default ₹2,00,000).
    max_utilization_ratio : float
        Safety factor (default 1.0 = 100% of remaining cleared cash).

    Returns:
    --------
    float: Available cleared capital for Session 2 (09:40).
    """
    cleared_capital = base_capital - max(0.0, session1_realized_loss)
    usable_capital = max(0.0, cleared_capital * max_utilization_ratio)
    return usable_capital


def stage_option_orders_safely(
    df_plan: pd.DataFrame,
    model_name: str,
    trade_date: str,
    output_dir: str
) -> str:
    """
    Safely stages Put Option orders into a dedicated options execution feed.
    Prevents silent insertion into Cash MIS Equity table in MySQL.

    Parameters:
    -----------
    df_plan : pd.DataFrame
        DataFrame of candidate stocks with option metadata.
    model_name : str
        Name of calling pipeline (e.g. '0920_SCALP_PE', '0940_SNIPER_PE').
    trade_date : str
        Trading date YYYY-MM-DD.
    output_dir : str
        Directory to write staging JSON / CSV feeds.

    Returns:
    --------
    str: Path to staged file.
    """
    os.makedirs(output_dir, exist_ok=True)
    staging_file = os.path.join(output_dir, f"options_orders_staging_{model_name}_{trade_date}.json")

    records = []
    for idx, row in df_plan.iterrows():
        records.append({
            'trade_date': trade_date,
            'model': model_name,
            'rank': idx + 1,
            'stockname': row.get('stockname', row.get('clean_stock', '')),
            'underlying_cmp': float(row.get('close_0919', row.get('entry_price_0940', 0.0))),
            'strike_role': row.get('put_option_strike_role', '1_OTM_PE_OR_ATM_PE'),
            'exit_policy': row.get('put_option_exit_policy', 'FastLock_WR_Boost'),
            'max_capital': float(row.get('put_option_capital_per_stock', 100000.0)),
            'max_lots': int(row.get('put_option_max_lots', DEFAULT_MAX_OPTION_LOTS)),
            'staged_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S IST'),
            'status': 'STAGED_FOR_OPTIONS_DAEMON'
        })

    with open(staging_file, 'w', encoding='utf-8') as f:
        json.dump(records, f, indent=2)

    return staging_file
