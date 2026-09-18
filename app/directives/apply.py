"""Apply validated directives to produce deterministic constraint inputs.

This module is intentionally pure: it takes already-validated
DirectiveInterpretation objects plus the raw hour/battery data, and
returns a fully-populated :class:`AppliedDirectives` ready to feed into
the OR-Tools optimizer.

No I/O, no LLM, no randomness. Same input -> same output.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.schemas.interpretation import DirectiveInterpretation
from app.schemas.request import BatterySpec, HourData

logger = logging.getLogger("gridwise.directives")


# Sentinel meaning "no cap" in the per-hour grid limits. Large enough to
# never bind against realistic demand but small enough to stay numerically
# friendly inside the solver.
NO_GRID_CAP = 1e9


@dataclass(frozen=True)
class AppliedDirectives:
    """All constraint inputs the optimizer needs, in one structure."""

    # 24-length arrays aligned with hours 0..23.
    effective_solar: tuple[float, ...] = field(default_factory=lambda: (0.0,) * 24)
    min_reserve: tuple[float, ...] = field(default_factory=lambda: (0.0,) * 24)
    max_grid: tuple[float, ...] = field(default_factory=lambda: (NO_GRID_CAP,) * 24)

    # Sets of hours with hard operational rules.
    no_charge_hours: frozenset[int] = field(default_factory=frozenset)
    no_discharge_hours: frozenset[int] = field(default_factory=frozenset)

    def summary(self) -> dict:
        """Plain-dict summary for logging."""
        # We can't recover the raw solar from this dataclass; the caller
        # can compute the diff if they still hold the raw hours. For now
        # we expose only the bound constraints.
        return {
            "no_charge_hours": sorted(self.no_charge_hours),
            "no_discharge_hours": sorted(self.no_discharge_hours),
            "max_grid_capped_hours": [
                h for h in range(24) if self.max_grid[h] < NO_GRID_CAP
            ],
        }


def _base_solar(hours: list[HourData]) -> tuple[float, ...]:
    """The raw solar forecast, one entry per hour, indexed 0..23."""
    arr = [0.0] * 24
    for h in hours:
        arr[h.hour] = float(h.solar_kwh)
    return tuple(arr)


def _base_min_reserve(battery: BatterySpec) -> tuple[float, ...]:
    """The battery's baseline minimum reserve, repeated for every hour."""
    return tuple(float(battery.minimum_energy_kwh) for _ in range(24))


def _base_max_grid() -> tuple[float, ...]:
    """No cap by default; per-hour caps are added by max_grid_window directives."""
    return tuple(NO_GRID_CAP for _ in range(24))


def build_applied_directives(
    interpretations: list[DirectiveInterpretation],
    hours: list[HourData],
    battery: BatterySpec,
) -> AppliedDirectives:
    """Translate validated directive interpretations into solver-ready inputs.

    Parameters
    ----------
    interpretations
        Output of :func:`app.guardrails.validator.validate_directives`.
        Must already be validated and in note_index order. ``no_op``
        entries are ignored here (they carry no constraints).
    hours
        The 24 raw hour rows from the request.
    battery
        The battery spec, used for baseline minimum reserve.

    Returns
    -------
    AppliedDirectives
        Per-hour arrays + hour sets ready to feed into OR-Tools.
    """
    effective_solar_list = list(_base_solar(hours))
    min_reserve_list = list(_base_min_reserve(battery))
    max_grid_list = list(_base_max_grid())
    no_charge: set[int] = set()
    no_discharge: set[int] = set()

    solar_factors_by_hour: dict[int, float] = {}
    reserves_by_hour: dict[int, float] = {}
    caps_by_hour: dict[int, float] = {}

    for interp in interpretations:
        if not interp.applies:
            continue
        adj = interp.structured_adjustment or {}
        hours_list = adj.get("hours", [])

        if interp.directive_type == "solar_reduction":
            factor = float(adj["factor"])
            for h in hours_list:
                # Multiple directives on the same hour -> take the MIN factor
                # (most conservative: least solar usable).
                prev = solar_factors_by_hour.get(h, 1.0)
                solar_factors_by_hour[h] = min(prev, factor)

        elif interp.directive_type == "minimum_battery_reserve":
            reserve = float(adj["minimum_energy_kwh"])
            for h in hours_list:
                # Take the MAX reserve (most conservative: highest floor).
                prev = reserves_by_hour.get(h, float(battery.minimum_energy_kwh))
                reserves_by_hour[h] = max(prev, reserve)

        elif interp.directive_type == "no_charge_window":
            no_charge.update(hours_list)

        elif interp.directive_type == "no_discharge_window":
            no_discharge.update(hours_list)

        elif interp.directive_type == "max_grid_window":
            cap = float(adj["max_grid_kwh"])
            for h in hours_list:
                # Take the MIN cap (most conservative: lowest ceiling).
                prev = caps_by_hour.get(h, NO_GRID_CAP)
                caps_by_hour[h] = min(prev, cap)

        # no_op is intentionally ignored here.

    # Apply effective solar reductions.
    for h, factor in solar_factors_by_hour.items():
        effective_solar_list[h] = effective_solar_list[h] * factor

    # Apply per-hour min reserve overrides (default already in place).
    for h, reserve in reserves_by_hour.items():
        min_reserve_list[h] = reserve

    # Apply per-hour grid caps.
    for h, cap in caps_by_hour.items():
        max_grid_list[h] = cap

    # No-charge and no-discharge must not overlap. The guardrails should
    # catch conflicting directives, but be defensive.
    overlap = no_charge & no_discharge
    if overlap:
        logger.warning(
            "no_charge and no_discharge overlap on hours %s; treating as no-op",
            sorted(overlap),
        )

    applied = AppliedDirectives(
        effective_solar=tuple(effective_solar_list),
        min_reserve=tuple(min_reserve_list),
        max_grid=tuple(max_grid_list),
        no_charge_hours=frozenset(no_charge - overlap),
        no_discharge_hours=frozenset(no_discharge - overlap),
    )

    logger.info(
        "applied %d applicable directive(s); no_charge=%d hours, no_discharge=%d hours, "
        "solar_reduced=%d hours, max_grid_capped=%d hours",
        sum(1 for i in interpretations if i.applies),
        len(applied.no_charge_hours),
        len(applied.no_discharge_hours),
        len(solar_factors_by_hour),
        len(caps_by_hour),
    )
    return applied
