"""Shared constants for the GridWise schema."""
from __future__ import annotations

from typing import Final

# Hours in the planning horizon.
HOURS: Final[tuple[int, ...]] = tuple(range(24))
HOURS_LEN: Final[int] = 24

# Maximum number of operator notes the LLM must interpret.
MAX_OPERATOR_NOTES: Final[int] = 3
MIN_OPERATOR_NOTES: Final[int] = 1

# Allowed directive types (from the Problem Statement).
ALLOWED_DIRECTIVE_TYPES: Final[frozenset[str]] = frozenset(
    {
        "solar_reduction",
        "minimum_battery_reserve",
        "no_charge_window",
        "no_discharge_window",
        "max_grid_window",
        "no_op",
    }
)

# Allowed battery actions in the hourly plan.
ALLOWED_BATTERY_ACTIONS: Final[frozenset[str]] = frozenset(
    {"charge", "discharge", "idle"}
)

# Numeric tolerance used by the validator.
NUMERIC_TOLERANCE: Final[float] = 0.01
