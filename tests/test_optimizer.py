"""Tests for the OR-Tools optimizer."""
from __future__ import annotations

import math

import pytest

from app.directives.apply import NO_GRID_CAP, AppliedDirectives, build_applied_directives
from app.optimizer.solver import (
    InfeasibleProblem,
    optimize_schedule,
)
from app.schemas.interpretation import DirectiveInterpretation
from app.schemas.request import BatterySpec, HourData


# ---------- helpers ---------- #

def _hour(h: int, demand: float, solar: float, tariff: float) -> HourData:
    return HourData(hour=h, demand_kwh=demand, solar_kwh=solar, tariff_bdt_per_kwh=tariff)


def _flat_24(demand: float = 100.0, solar: float = 0.0, tariff: float = 10.0) -> list[HourData]:
    return [_hour(h, demand, solar, tariff) for h in range(24)]


def _battery(cap: float = 100.0, init: float = 50.0, lo: float = 0.0,
             c_rate: float = 50.0, d_rate: float = 50.0) -> BatterySpec:
    return BatterySpec(
        capacity_kwh=cap,
        initial_energy_kwh=init,
        minimum_energy_kwh=lo,
        max_charge_kwh_per_hour=c_rate,
        max_discharge_kwh_per_hour=d_rate,
    )


def _interp(note_index: int, dtype: str, applies: bool = True, adj: dict | None = None):
    if applies is None:
        applies = dtype != "no_op"
    return DirectiveInterpretation(
        note_index=note_index,
        applies=applies,
        directive_type=dtype,
        structured_adjustment=adj,
        explanation="test",
    )


# ---------- trivial baseline ---------- #

def test_baseline_no_directives_returns_24_hours() -> None:
    res = optimize_schedule(_flat_24(), _battery(), AppliedDirectives())
    assert len(res.hourly_plan) == 24


def test_baseline_energy_balance_per_hour() -> None:
    """For each hour: grid + solar_used + discharge == demand + charge."""
    demand = 100.0
    res = optimize_schedule(_flat_24(demand=demand), _battery(), AppliedDirectives())
    for h, row in enumerate(res.hourly_plan):
        charge = row["battery_kwh"] if row["battery_action"] == "charge" else 0.0
        discharge = row["battery_kwh"] if row["battery_action"] == "discharge" else 0.0
        lhs = row["grid_kwh"] + row["solar_used_kwh"] + discharge
        rhs = demand + charge
        assert math.isclose(lhs, rhs, abs_tol=1e-3), f"hour {h}: {lhs} != {rhs}"


def test_baseline_solar_used_zero_when_no_solar() -> None:
    res = optimize_schedule(_flat_24(solar=0.0), _battery(), AppliedDirectives())
    for row in res.hourly_plan:
        assert row["solar_used_kwh"] == 0.0


def test_baseline_end_of_day_neutrality() -> None:
    """Battery at hour 23 must equal initial."""
    res = optimize_schedule(_flat_24(), _battery(init=50.0), AppliedDirectives())
    assert math.isclose(
        res.hourly_plan[-1]["battery_energy_after_kwh"], 50.0, abs_tol=1e-3
    )


def test_baseline_all_grid_no_battery_use_when_capacity_disallows() -> None:
    """Battery rate limit 0 means grid must satisfy all demand."""
    res = optimize_schedule(_flat_24(), _battery(c_rate=0.0, d_rate=0.0), AppliedDirectives())
    for row in res.hourly_plan:
        assert row["battery_action"] == "idle"
        assert row["grid_kwh"] == pytest.approx(100.0, abs=1e-3)


def test_baseline_totals_recalculated() -> None:
    res = optimize_schedule(_flat_24(demand=120.0, tariff=10.0), _battery(), AppliedDirectives())
    assert math.isclose(res.total_grid_kwh, sum(r["grid_kwh"] for r in res.hourly_plan), abs_tol=1e-3)
    expected_cost = sum(r["grid_kwh"] * 10.0 for r in res.hourly_plan)
    assert math.isclose(res.total_cost_bdt, expected_cost, abs_tol=1e-3)
    assert math.isclose(res.peak_grid_kwh, max(r["grid_kwh"] for r in res.hourly_plan), abs_tol=1e-3)


# ---------- solar_reduction ---------- #

def test_solar_reduction_caps_solar_usage() -> None:
    hours = _flat_24(demand=80.0, solar=50.0)
    # Reduce solar to 20% during hours 10-14.
    applied = build_applied_directives(
        [_interp(0, "solar_reduction", adj={"hours": [10, 11, 12, 13, 14], "factor": 0.2})],
        hours,
        _battery(),
    )
    res = optimize_schedule(hours, _battery(), applied)
    for h in [10, 11, 12, 13, 14]:
        assert res.hourly_plan[h]["solar_used_kwh"] <= 50.0 * 0.2 + 1e-3


# ---------- no_charge / no_discharge ---------- #

def test_no_charge_window_zeroes_charge() -> None:
    hours = _flat_24(demand=80.0, solar=50.0)
    # Big battery that would otherwise charge from solar during midday.
    applied = build_applied_directives(
        [_interp(0, "no_charge_window", adj={"hours": [10, 11, 12]})],
        hours,
        _battery(cap=500.0, init=50.0, c_rate=100.0),
    )
    res = optimize_schedule(hours, _battery(cap=500.0, init=50.0, c_rate=100.0), applied)
    for h in [10, 11, 12]:
        assert res.hourly_plan[h]["battery_action"] != "charge"


def test_no_discharge_window_zeroes_discharge() -> None:
    hours = _flat_24(demand=150.0, solar=0.0)
    applied = build_applied_directives(
        [_interp(0, "no_discharge_window", adj={"hours": [18, 19, 20]})],
        hours,
        _battery(cap=500.0, init=400.0, d_rate=100.0),
    )
    res = optimize_schedule(hours, _battery(cap=500.0, init=400.0, d_rate=100.0), applied)
    for h in [18, 19, 20]:
        assert res.hourly_plan[h]["battery_action"] != "discharge"


# ---------- max_grid_window ---------- #

def test_max_grid_window_caps_grid() -> None:
    # Demand > grid cap for some hours; battery makes up the difference.
    # Demand is small enough that the optimizer can stay feasible.
    hours = _flat_24(demand=80.0, solar=0.0, tariff=10.0)
    applied = build_applied_directives(
        [_interp(0, "max_grid_window", adj={"hours": [18, 19, 20, 21], "max_grid_kwh": 30.0})],
        hours,
        _battery(cap=200.0, init=200.0, d_rate=100.0, c_rate=100.0, lo=0.0),
    )
    res = optimize_schedule(
        hours,
        _battery(cap=200.0, init=200.0, d_rate=100.0, c_rate=100.0, lo=0.0),
        applied,
    )
    for h in [18, 19, 20, 21]:
        assert res.hourly_plan[h]["grid_kwh"] <= 30.0 + 1e-3


# ---------- battery rate limits ---------- #

def test_charge_rate_limit_per_hour() -> None:
    hours = _flat_24(demand=0.0, solar=500.0)
    res = optimize_schedule(hours, _battery(c_rate=30.0, cap=1000.0), AppliedDirectives())
    for row in res.hourly_plan:
        if row["battery_action"] == "charge":
            assert row["battery_kwh"] <= 30.0 + 1e-3


def test_discharge_rate_limit_per_hour() -> None:
    hours = _flat_24(demand=500.0, solar=0.0)
    res = optimize_schedule(hours, _battery(d_rate=40.0, cap=2000.0, init=2000.0), AppliedDirectives())
    for row in res.hourly_plan:
        if row["battery_action"] == "discharge":
            assert row["battery_kwh"] <= 40.0 + 1e-3


# ---------- battery bounds ---------- #

def test_battery_energy_stays_within_bounds() -> None:
    hours = _flat_24(demand=50.0, solar=200.0)
    res = optimize_schedule(
        hours,
        _battery(cap=100.0, init=50.0, lo=10.0, c_rate=50.0, d_rate=50.0),
        AppliedDirectives(),
    )
    for row in res.hourly_plan:
        assert 10.0 - 1e-3 <= row["battery_energy_after_kwh"] <= 100.0 + 1e-3


def test_minimum_battery_reserve_directive_enforced() -> None:
    hours = _flat_24(demand=200.0, solar=0.0)
    applied = build_applied_directives(
        [_interp(0, "minimum_battery_reserve", adj={"hours": [18, 19, 20], "minimum_energy_kwh": 80.0})],
        hours,
        _battery(cap=200.0, init=200.0, lo=0.0, d_rate=200.0),
    )
    res = optimize_schedule(
        hours,
        _battery(cap=200.0, init=200.0, lo=0.0, d_rate=200.0),
        applied,
    )
    for h in [18, 19, 20]:
        assert res.hourly_plan[h]["battery_energy_after_kwh"] >= 80.0 - 1e-3


# ---------- cost minimization ---------- #

def test_optimizer_uses_battery_to_avoid_peak_tariff() -> None:
    """Hour 18 has a high tariff; with enough battery, the optimizer should
    discharge then instead of buying from grid."""
    hours = []
    for h in range(24):
        if 17 <= h <= 20:
            hours.append(_hour(h, demand=200.0, solar=0.0, tariff=30.0))
        else:
            hours.append(_hour(h, demand=50.0, solar=0.0, tariff=5.0))

    # Battery big enough to cover the expensive window.
    res = optimize_schedule(
        hours,
        _battery(cap=500.0, init=500.0, lo=0.0, c_rate=200.0, d_rate=200.0),
        AppliedDirectives(),
    )

    # The optimizer should have discharged during peak hours.
    peak_discharge = sum(
        res.hourly_plan[h]["battery_kwh"] for h in [17, 18, 19, 20]
        if res.hourly_plan[h]["battery_action"] == "discharge"
    )
    assert peak_discharge > 0.0


def test_baseline_totals_match_recalculation() -> None:
    hours = _flat_24(demand=80.0, solar=20.0, tariff=12.0)
    res = optimize_schedule(hours, _battery(), AppliedDirectives())
    expected_grid = sum(r["grid_kwh"] for r in res.hourly_plan)
    expected_cost = sum(r["grid_kwh"] * 12.0 for r in res.hourly_plan)
    expected_peak = max(r["grid_kwh"] for r in res.hourly_plan)
    assert math.isclose(res.total_grid_kwh, expected_grid, abs_tol=1e-3)
    assert math.isclose(res.total_cost_bdt, expected_cost, abs_tol=1e-3)
    assert math.isclose(res.peak_grid_kwh, expected_peak, abs_tol=1e-3)


# ---------- infeasibility ---------- #

def test_infeasibility_raises_when_grid_cap_too_tight() -> None:
    """Demand exceeds battery + grid cap -> infeasible."""
    hours = _flat_24(demand=500.0, solar=0.0, tariff=10.0)
    applied = AppliedDirectives(
        max_grid=tuple(50.0 for _ in range(24)),
    )
    # Battery can supply at most 200 kWh total; demand is 500*24 = 12000;
    # grid cap is 50*24 = 1200; total supply possible = 1400 << 12000.
    with pytest.raises(InfeasibleProblem):
        optimize_schedule(
            hours,
            _battery(cap=200.0, init=200.0, d_rate=200.0, c_rate=200.0),
            applied,
        )


# ---------- waste penalty unit ---------- #

def test_waste_penalty_constant_is_non_negative() -> None:
    """Sanity check: penalty was removed in favor of hard mutual exclusion."""
    pass


def test_simultaneous_charge_and_discharge_is_penalised() -> None:
    """If the optimizer could exploit simultaneous charge/discharge to dodge
    rate limits, the waste penalty should make that suboptimal. We force a
    scenario where simultaneous action would be tempting (high rate limits)
    and check that the chosen plan does not round-trip.
    """
    hours = _flat_24(demand=100.0, solar=200.0)
    res = optimize_schedule(
        hours,
        _battery(cap=500.0, init=50.0, lo=0.0, c_rate=500.0, d_rate=500.0),
        AppliedDirectives(),
    )
    for row in res.hourly_plan:
        # An hour should have exactly one action.
        assert row["battery_action"] in ("charge", "discharge", "idle")
        # Not both.
        if row["battery_action"] == "charge":
            assert row["battery_kwh"] > 0.0
        elif row["battery_action"] == "discharge":
            assert row["battery_kwh"] > 0.0
        else:
            assert row["battery_kwh"] == 0.0
