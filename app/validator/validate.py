"""Final validator: independently replay the schedule to confirm correctness.

The optimizer is treated as untrusted. After it returns, this module
recomputes every total from the hourly plan and re-checks every constraint
the judge harness expects. If anything is off, it raises a typed
:class:`FinalValidationError` so the API can return a controlled failure.

The judge harness re-runs the same checks independently, so the contract
here is: "the totals and constraints in our response match the values the
judge will recompute."
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.directives.apply import NO_GRID_CAP, AppliedDirectives
from app.schemas.request import BatterySpec, OptimizeEnergyRequest
from app.validator.errors import (
    BatteryBoundError,
    BatteryNegative,
    BatteryRateError,
    ChargeActionConflict,
    DirectiveViolation,
    EndOfDayMismatch,
    EnergyBalanceError,
    GridNegative,
    HourRangeError,
    SolarNegative,
    SolarOvershoot,
    TotalMismatch,
)

logger = logging.getLogger("gridwise.validator")


# Absolute tolerance used everywhere. The canonical contract allows up to
# 0.01 kWh / 0.01 BDT unless the official judge package specifies stricter.
ABS_TOL = 0.01


@dataclass(frozen=True)
class ValidatedPlan:
    """A schedule that has passed every final-validation check."""

    scenario_id: str
    hourly_plan: list[dict[str, Any]]
    total_grid_kwh: float
    total_cost_bdt: float
    peak_grid_kwh: float
    plan_summary: str


def _build_plan_summary(req: OptimizeEnergyRequest, applied: AppliedDirectives) -> str:
    """Generate a short human-readable summary of the schedule."""
    parts: list[str] = []
    if applied.no_charge_hours:
        parts.append(
            f"no-charge window during hours {sorted(applied.no_charge_hours)}"
        )
    if applied.no_discharge_hours:
        parts.append(
            f"no-discharge window during hours {sorted(applied.no_discharge_hours)}"
        )
    capped = sorted(h for h in range(24) if applied.max_grid[h] < NO_GRID_CAP)
    if capped:
        parts.append(f"grid import capped at hour(s) {capped}")
    reduced = sorted(
        h
        for h in range(24)
        if applied.effective_solar[h] < req.hours[h].solar_kwh - 1e-9
    )
    if reduced:
        parts.append(f"solar reduced at hour(s) {reduced}")
    reserves = sorted(
        h
        for h in range(24)
        if applied.min_reserve[h] > req.battery.minimum_energy_kwh + 1e-9
    )
    if reserves:
        parts.append(f"elevated battery reserve at hour(s) {reserves}")

    if not parts:
        parts.append("all directives applied; standard schedule")
    return "; ".join(parts) + f" (scenario {req.scenario_id})."


def validate_schedule(
    req: OptimizeEnergyRequest,
    applied: AppliedDirectives,
    hourly_plan: list[dict[str, Any]],
    reported_total_grid_kwh: float,
    reported_total_cost_bdt: float,
    reported_peak_grid_kwh: float,
) -> ValidatedPlan:
    """Independently verify the optimizer's hourly plan.

    Parameters
    ----------
    req
        The original request (for battery spec and tariff data).
    applied
        The applied directives (for re-checking directive constraints).
    hourly_plan
        The optimizer's 24-hour schedule (list of dicts).
    reported_total_grid_kwh
    reported_total_cost_bdt
    reported_peak_grid_kwh
        The optimizer's self-reported totals; we recalculate and compare.

    Returns
    -------
    ValidatedPlan
        A frozen dataclass with the plan + totals + a short summary.

    Raises
    ------
    FinalValidationError (subclass)
        On any inconsistency. The caller MUST treat this as a hard failure
        and return a controlled HTTP error rather than a fake success.
    """
    battery: BatterySpec = req.battery

    # 1. Plan shape: 24 unique hours in ascending order.
    if len(hourly_plan) != 24:
        raise HourRangeError(
            f"hourly_plan must contain exactly 24 entries, got {len(hourly_plan)}"
        )
    hours_seen = [row["hour"] for row in hourly_plan]
    if hours_seen != list(range(24)):
        raise HourRangeError(
            f"hourly_plan must contain hours 0..23 in ascending order, got {hours_seen}"
        )

    # 2. Re-check every hour's GridWise constraints.
    recalc_grid = 0.0
    recalc_cost = 0.0
    recalc_peak = 0.0

    for row in hourly_plan:
        h = row["hour"]
        demand = req.hours[h].demand_kwh
        action = row["battery_action"]
        grid = row["grid_kwh"]
        solar_used = row["solar_used_kwh"]
        battery_kwh = row["battery_kwh"]
        e_after = row["battery_energy_after_kwh"]
        tariff = req.hours[h].tariff_bdt_per_kwh

        # 2a. Non-negativity.
        if grid < 0:
            raise GridNegative(f"hour {h}: grid_kwh={grid} is negative")
        if solar_used < 0:
            raise SolarNegative(f"hour {h}: solar_used_kwh={solar_used} is negative")
        if e_after < 0:
            raise BatteryNegative(f"hour {h}: battery_energy_after_kwh={e_after} is negative")

        # 2b. Action vs magnitude.
        if action == "charge":
            if battery_kwh <= 0:
                raise ChargeActionConflict(
                    f"hour {h}: battery_action='charge' but battery_kwh={battery_kwh}"
                )
            charge = battery_kwh
            discharge = 0.0
        elif action == "discharge":
            if battery_kwh <= 0:
                raise ChargeActionConflict(
                    f"hour {h}: battery_action='discharge' but battery_kwh={battery_kwh}"
                )
            charge = 0.0
            discharge = battery_kwh
        elif action == "idle":
            if battery_kwh != 0:
                raise ChargeActionConflict(
                    f"hour {h}: battery_action='idle' but battery_kwh={battery_kwh}"
                )
            charge = 0.0
            discharge = 0.0
        else:
            raise ChargeActionConflict(
                f"hour {h}: battery_action={action!r} is not one of "
                f"charge/discharge/idle"
            )

        # 2c. Energy balance.
        lhs = grid + solar_used + discharge
        rhs = demand + charge
        if abs(lhs - rhs) > ABS_TOL:
            raise EnergyBalanceError(
                f"hour {h}: grid+solar+discharge={lhs:.4f} != demand+charge={rhs:.4f}"
            )

        # 2d. Solar bound (effective solar from directive).
        eff_solar = applied.effective_solar[h]
        if solar_used > eff_solar + ABS_TOL:
            raise SolarOvershoot(
                f"hour {h}: solar_used_kwh={solar_used} > effective_solar={eff_solar}"
            )

        # 2e. Battery bounds (with per-hour reserve directive override).
        floor = applied.min_reserve[h]
        if e_after < floor - ABS_TOL:
            raise BatteryBoundError(
                f"hour {h}: battery_energy_after_kwh={e_after} < min_reserve={floor}"
            )
        if e_after > battery.capacity_kwh + ABS_TOL:
            raise BatteryBoundError(
                f"hour {h}: battery_energy_after_kwh={e_after} > capacity={battery.capacity_kwh}"
            )

        # 2f. Rate limits.
        if charge > battery.max_charge_kwh_per_hour + ABS_TOL:
            raise BatteryRateError(
                f"hour {h}: charge={charge} > max_charge_kwh_per_hour="
                f"{battery.max_charge_kwh_per_hour}"
            )
        if discharge > battery.max_discharge_kwh_per_hour + ABS_TOL:
            raise BatteryRateError(
                f"hour {h}: discharge={discharge} > max_discharge_kwh_per_hour="
                f"{battery.max_discharge_kwh_per_hour}"
            )

        # 2g. Directive windows.
        if h in applied.no_charge_hours and action == "charge":
            raise DirectiveViolation(
                f"hour {h}: charging in no_charge_window"
            )
        if h in applied.no_discharge_hours and action == "discharge":
            raise DirectiveViolation(
                f"hour {h}: discharging in no_discharge_window"
            )
        cap = applied.max_grid[h]
        if cap < NO_GRID_CAP and grid > cap + ABS_TOL:
            raise DirectiveViolation(
                f"hour {h}: grid_kwh={grid} > max_grid_window cap={cap}"
            )

        # 2h. Tally totals.
        recalc_grid += grid
        recalc_cost += grid * tariff
        if grid > recalc_peak:
            recalc_peak = grid

    # 3. End-of-day neutrality.
    final_e = hourly_plan[-1]["battery_energy_after_kwh"]
    if abs(final_e - battery.initial_energy_kwh) > ABS_TOL:
        raise EndOfDayMismatch(
            f"end-of-day battery {final_e} != initial {battery.initial_energy_kwh}"
        )

    # 4. Reported totals must match recalculation.
    if abs(reported_total_grid_kwh - recalc_grid) > ABS_TOL:
        raise TotalMismatch(
            f"reported total_grid_kwh={reported_total_grid_kwh} "
            f"!= recalculated {recalc_grid:.4f}"
        )
    if abs(reported_total_cost_bdt - recalc_cost) > ABS_TOL:
        raise TotalMismatch(
            f"reported total_cost_bdt={reported_total_cost_bdt} "
            f"!= recalculated {recalc_cost:.4f}"
        )
    if abs(reported_peak_grid_kwh - recalc_peak) > ABS_TOL:
        raise TotalMismatch(
            f"reported peak_grid_kwh={reported_peak_grid_kwh} "
            f"!= recalculated {recalc_peak:.4f}"
        )

    # 5. Round and package the result.
    rounded_grid = round(recalc_grid, 3)
    rounded_cost = round(recalc_cost, 3)
    rounded_peak = round(recalc_peak, 3)
    summary = _build_plan_summary(req, applied)

    logger.info(
        "final validator OK: scenario=%s total_grid=%.3f total_cost=%.3f peak=%.3f",
        req.scenario_id,
        rounded_grid,
        rounded_cost,
        rounded_peak,
    )

    return ValidatedPlan(
        scenario_id=req.scenario_id,
        hourly_plan=hourly_plan,
        total_grid_kwh=rounded_grid,
        total_cost_bdt=rounded_cost,
        peak_grid_kwh=rounded_peak,
        plan_summary=summary,
    )
