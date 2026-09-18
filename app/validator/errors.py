"""Typed exceptions raised by the final validator."""
from __future__ import annotations


class FinalValidationError(Exception):
    """Base class for every final-schedule validation failure."""


class TotalMismatch(FinalValidationError):
    """A reported total does not match the value recalculated from hourly_plan."""


class HourRangeError(FinalValidationError):
    """An hour entry is missing, duplicate, or out of the 0..23 range."""


class EnergyBalanceError(FinalValidationError):
    """Per-hour energy balance equation is violated."""


class SolarOvershoot(FinalValidationError):
    """solar_used_kwh exceeds the effective solar bound for that hour."""


class BatteryBoundError(FinalValidationError):
    """Battery energy went outside [min_reserve, capacity]."""


class BatteryRateError(FinalValidationError):
    """Battery charge or discharge rate exceeds the per-hour limit."""


class ChargeActionConflict(FinalValidationError):
    """battery_action is 'charge' but battery_kwh is 0 or vice versa."""


class DirectiveViolation(FinalValidationError):
    """An applicable directive constraint is not reflected in the schedule."""


class EndOfDayMismatch(FinalValidationError):
    """Battery energy at end of hour 23 does not equal the initial energy."""


class BatteryNegative(FinalValidationError):
    """battery_energy_after_kwh is negative."""


class GridNegative(FinalValidationError):
    """grid_kwh is negative."""


class SolarNegative(FinalValidationError):
    """solar_used_kwh is negative."""
