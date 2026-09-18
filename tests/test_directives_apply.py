"""Tests for directive application (turning interpretations into solver inputs)."""
from __future__ import annotations

import pytest

from app.directives.apply import NO_GRID_CAP, build_applied_directives
from app.schemas.interpretation import DirectiveInterpretation
from app.schemas.request import BatterySpec, HourData


# ---------- helpers ---------- #

def _hour(h: int, solar: float = 0.0) -> HourData:
    return HourData(
        hour=h,
        demand_kwh=100.0,
        solar_kwh=solar,
        tariff_bdt_per_kwh=10.0,
    )


def _battery(min_reserve: float = 10.0, capacity: float = 100.0) -> BatterySpec:
    return BatterySpec(
        capacity_kwh=capacity,
        initial_energy_kwh=50.0,
        minimum_energy_kwh=min_reserve,
        max_charge_kwh_per_hour=30.0,
        max_discharge_kwh_per_hour=30.0,
    )


def _interp(
    note_index: int,
    directive_type: str,
    applies: bool | None = None,
    adj: dict | None = None,
) -> DirectiveInterpretation:
    # For no_op, applies must be False; for any other directive, True.
    if applies is None:
        applies = directive_type != "no_op"
    return DirectiveInterpretation(
        note_index=note_index,
        applies=applies,
        directive_type=directive_type,
        structured_adjustment=adj,
        explanation="test",
    )


def _hours_24(solar_per_hour: dict[int, float] | None = None) -> list[HourData]:
    solar_per_hour = solar_per_hour or {}
    return [
        _hour(h, solar=solar_per_hour.get(h, 50.0))
        for h in range(24)
    ]


# ---------- baseline (no directives) ---------- #

def test_no_directives_passes_through_unchanged() -> None:
    hours = _hours_24()
    battery = _battery()
    applied = build_applied_directives(
        [_interp(0, "no_op")],
        hours,
        battery,
    )
    assert all(s == 50.0 for s in applied.effective_solar)
    assert all(r == 10.0 for r in applied.min_reserve)
    assert all(g == NO_GRID_CAP for g in applied.max_grid)
    assert applied.no_charge_hours == frozenset()
    assert applied.no_discharge_hours == frozenset()


# ---------- solar_reduction ---------- #

def test_solar_reduction_scales_effective_solar() -> None:
    hours = _hours_24({12: 100.0, 13: 100.0, 14: 100.0})
    applied = build_applied_directives(
        [_interp(0, "solar_reduction", adj={"hours": [12, 13], "factor": 0.25})],
        hours,
        _battery(),
    )
    assert applied.effective_solar[12] == 25.0
    assert applied.effective_solar[13] == 25.0
    assert applied.effective_solar[14] == 100.0  # untouched


def test_solar_reduction_factor_zero_zeros_out_solar() -> None:
    hours = _hours_24({12: 80.0})
    applied = build_applied_directives(
        [_interp(0, "solar_reduction", adj={"hours": [12], "factor": 0.0})],
        hours,
        _battery(),
    )
    assert applied.effective_solar[12] == 0.0


def test_multiple_solar_reductions_take_min_factor() -> None:
    hours = _hours_24({12: 100.0})
    applied = build_applied_directives(
        [
            _interp(0, "solar_reduction", adj={"hours": [12], "factor": 0.5}),
            _interp(1, "solar_reduction", adj={"hours": [12], "factor": 0.3}),
        ],
        hours,
        _battery(),
    )
    # min(0.5, 0.3) = 0.3 -> 30.0
    assert applied.effective_solar[12] == pytest.approx(30.0)


# ---------- minimum_battery_reserve ---------- #

def test_minimum_battery_reserve_raises_floor() -> None:
    hours = _hours_24()
    applied = build_applied_directives(
        [_interp(0, "minimum_battery_reserve", adj={"hours": [18, 19, 20], "minimum_energy_kwh": 60.0})],
        hours,
        _battery(min_reserve=10.0),
    )
    assert applied.min_reserve[18] == 60.0
    assert applied.min_reserve[19] == 60.0
    assert applied.min_reserve[20] == 60.0
    # Unrelated hours retain the battery baseline.
    assert applied.min_reserve[0] == 10.0


def test_multiple_reserves_take_max_floor() -> None:
    hours = _hours_24()
    applied = build_applied_directives(
        [
            _interp(0, "minimum_battery_reserve", adj={"hours": [18], "minimum_energy_kwh": 40.0}),
            _interp(1, "minimum_battery_reserve", adj={"hours": [18], "minimum_energy_kwh": 60.0}),
        ],
        hours,
        _battery(min_reserve=10.0),
    )
    assert applied.min_reserve[18] == 60.0


# ---------- no_charge / no_discharge ---------- #

def test_no_charge_window_marks_hours() -> None:
    applied = build_applied_directives(
        [_interp(0, "no_charge_window", adj={"hours": [12, 13, 14]})],
        _hours_24(),
        _battery(),
    )
    assert applied.no_charge_hours == frozenset({12, 13, 14})
    assert applied.no_discharge_hours == frozenset()


def test_no_discharge_window_marks_hours() -> None:
    applied = build_applied_directives(
        [_interp(0, "no_discharge_window", adj={"hours": [18, 19]})],
        _hours_24(),
        _battery(),
    )
    assert applied.no_discharge_hours == frozenset({18, 19})
    assert applied.no_charge_hours == frozenset()


def test_overlap_between_no_charge_and_no_discharge_is_resolved() -> None:
    applied = build_applied_directives(
        [
            _interp(0, "no_charge_window", adj={"hours": [18, 19]}),
            _interp(1, "no_discharge_window", adj={"hours": [19, 20]}),
        ],
        _hours_24(),
        _battery(),
    )
    # Hour 19 is in both -> removed from both.
    assert 19 not in applied.no_charge_hours
    assert 19 not in applied.no_discharge_hours
    assert applied.no_charge_hours == frozenset({18})
    assert applied.no_discharge_hours == frozenset({20})


# ---------- max_grid_window ---------- #

def test_max_grid_window_caps_hours() -> None:
    applied = build_applied_directives(
        [_interp(0, "max_grid_window", adj={"hours": [18, 19, 20], "max_grid_kwh": 50.0})],
        _hours_24(),
        _battery(),
    )
    assert applied.max_grid[18] == 50.0
    assert applied.max_grid[19] == 50.0
    assert applied.max_grid[20] == 50.0
    assert applied.max_grid[0] == NO_GRID_CAP


def test_multiple_caps_take_min_value() -> None:
    applied = build_applied_directives(
        [
            _interp(0, "max_grid_window", adj={"hours": [18], "max_grid_kwh": 80.0}),
            _interp(1, "max_grid_window", adj={"hours": [18], "max_grid_kwh": 50.0}),
        ],
        _hours_24(),
        _battery(),
    )
    assert applied.max_grid[18] == 50.0


# ---------- combined scenarios ---------- #

def test_all_directives_compose_correctly() -> None:
    hours = _hours_24({12: 100.0, 13: 100.0, 18: 100.0})
    applied = build_applied_directives(
        [
            _interp(0, "solar_reduction", adj={"hours": [12, 13], "factor": 0.5}),
            _interp(1, "no_discharge_window", adj={"hours": [18, 19]}),
            _interp(2, "max_grid_window", adj={"hours": [20], "max_grid_kwh": 80.0}),
        ],
        hours,
        _battery(min_reserve=10.0, capacity=200.0),
    )
    assert applied.effective_solar[12] == 50.0
    assert applied.effective_solar[13] == 50.0
    assert applied.effective_solar[18] == 100.0  # untouched
    assert applied.no_discharge_hours == frozenset({18, 19})
    assert applied.max_grid[20] == 80.0
    assert applied.max_grid[0] == NO_GRID_CAP


def test_no_op_entries_are_ignored() -> None:
    hours = _hours_24({12: 100.0})
    applied = build_applied_directives(
        [
            _interp(0, "solar_reduction", adj={"hours": [12], "factor": 0.5}),
            _interp(1, "no_op", applies=False),  # irrelevant
        ],
        hours,
        _battery(),
    )
    assert applied.effective_solar[12] == 50.0


# ---------- edge cases ---------- #

def test_three_interpretations_in_note_index_order() -> None:
    """Guardrails guarantee order; the applicator respects it."""
    hours = _hours_24()
    applied = build_applied_directives(
        [
            _interp(0, "solar_reduction", adj={"hours": [0], "factor": 0.5}),
            _interp(1, "no_charge_window", adj={"hours": [1]}),
            _interp(2, "max_grid_window", adj={"hours": [2], "max_grid_kwh": 10.0}),
        ],
        hours,
        _battery(),
    )
    assert applied.effective_solar[0] == 25.0
    assert applied.no_charge_hours == frozenset({1})
    assert applied.max_grid[2] == 10.0


def test_effective_solar_never_exceeds_raw_solar() -> None:
    """factor in [0,1] guarantees this; defensive assertion in code."""
    hours = _hours_24({h: 100.0 for h in range(24)})
    applied = build_applied_directives(
        [_interp(0, "solar_reduction", adj={"hours": list(range(24)), "factor": 0.5})],
        hours,
        _battery(),
    )
    for h in range(24):
        assert applied.effective_solar[h] <= 100.0


def test_summary_is_a_plain_dict() -> None:
    applied = build_applied_directives(
        [_interp(0, "no_charge_window", adj={"hours": [12]})],
        _hours_24(),
        _battery(),
    )
    s = applied.summary()
    assert isinstance(s, dict)
    assert s["no_charge_hours"] == [12]
    assert s["no_discharge_hours"] == []
    assert s["max_grid_capped_hours"] == []
