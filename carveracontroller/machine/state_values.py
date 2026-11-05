"""Checked numeric reads from heterogeneous machine status values."""

import math


def finite_number(value: object) -> float:
    """Accept numeric status values and numeric text; reject missing or invalid data."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError("Invalid numeric machine status")
    try:
        number = float(value)
    except (ValueError, OverflowError) as error:
        raise ValueError("Invalid numeric machine status") from error
    if not math.isfinite(number):
        raise ValueError("Invalid numeric machine status")
    return number
