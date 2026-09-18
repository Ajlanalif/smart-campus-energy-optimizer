"""Phase 2 smoke tests: validate Pydantic schemas accept good input and reject bad input."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.interpretation import (
    DirectiveInterpretation,
    HoursOnlyAdjustment,
    MaxGridWindowAdjustment,
    MinimumBatteryReserveAdjustment,
    SolarReductionAdjustment,
)
from app.schemas.request import BatterySpec, HourData, OptimizeEnergyRequest
from app.schemas.response import HourlyPlanEntry


# ---------- helpers ---------- #

def _hour(h: int) -> dict:
    return {"hour": h, "demand_kwh": 100.0, "solar_kwh": 50.0, "tariff_bdt_per_kwh": 10.0}


def _battery() -> dict:
    return {
        "capacity_kwh": 100.0,
        "initial_energy_kwh": 50.0,
        "minimum_energy_kwh": 10.0,
        "max_charge_kwh_per_hour": 30.0,
        "max_discharge_kwh_per_hour": 30.0,
    }


def _valid_request() -> dict:
    return {
        "scenario_id": "TEST-01",
        "operator_notes": ["Wash panels 1-3 PM, treat solar as 25%."],
        "hours": [_hour(h) for h in range(24)],
        "battery": _battery(),
    }


# ---------- request: happy path ---------- #

def test_valid_request_parses() -> None:
    req = OptimizeEnergyRequest(**_valid_request())
    assert req.scenario_id == "TEST-01"
    assert len(req.operator_notes) == 1
    assert len(req.hours) == 24
    assert req.battery.capacity_kwh == 100.0


def test_three_notes_is_allowed() -> None:
    payload = _valid_request()
    payload["operator_notes"] = ["note a", "note b", "note c"]
    req = OptimizeEnergyRequest(**payload)
    assert len(req.operator_notes) == 3


# ---------- request: rejection cases ---------- #

def test_zero_notes_rejected() -> None:
    payload = _valid_request()
    payload["operator_notes"] = []
    with pytest.raises(ValidationError):
        OptimizeEnergyRequest(**payload)


def test_four_notes_rejected() -> None:
    payload = _valid_request()
    payload["operator_notes"] = ["a", "b", "c", "d"]
    with pytest.raises(ValidationError):
        OptimizeEnergyRequest(**payload)


def test_empty_note_rejected() -> None:
    payload = _valid_request()
    payload["operator_notes"] = ["   "]
    with pytest.raises(ValidationError):
        OptimizeEnergyRequest(**payload)


def test_wrong_hours_count_rejected() -> None:
    payload = _valid_request()
    payload["hours"] = [_hour(h) for h in range(23)]  # 23 instead of 24
    with pytest.raises(ValidationError):
        OptimizeEnergyRequest(**payload)


def test_duplicate_hours_rejected() -> None:
    payload = _valid_request()
    payload["hours"] = [_hour(0)] + [_hour(1)] * 23  # duplicate hour 1
    with pytest.raises(ValidationError):
        OptimizeEnergyRequest(**payload)


def test_unsorted_hours_rejected() -> None:
    payload = _valid_request()
    hours = [_hour(h) for h in range(24)]
    hours[0], hours[1] = hours[1], hours[0]
    payload["hours"] = hours
    with pytest.raises(ValidationError):
        OptimizeEnergyRequest(**payload)


def test_negative_demand_rejected() -> None:
    payload = _valid_request()
    payload["hours"][5]["demand_kwh"] = -10.0
    with pytest.raises(ValidationError):
        OptimizeEnergyRequest(**payload)


def test_battery_min_above_capacity_rejected() -> None:
    payload = _valid_request()
    payload["battery"]["minimum_energy_kwh"] = 200.0
    with pytest.raises(ValidationError):
        OptimizeEnergyRequest(**payload)


def test_battery_initial_below_min_rejected() -> None:
    payload = _valid_request()
    payload["battery"]["initial_energy_kwh"] = 5.0
    with pytest.raises(ValidationError):
        OptimizeEnergyRequest(**payload)


def test_extra_field_rejected() -> None:
    payload = _valid_request()
    payload["rogue_field"] = "nope"
    with pytest.raises(ValidationError):
        OptimizeEnergyRequest(**payload)


# ---------- interpretation ---------- #

def test_no_op_requires_applies_false_and_null_adjustment() -> None:
    interp = DirectiveInterpretation(
        note_index=0,
        applies=False,
        directive_type="no_op",
        structured_adjustment=None,
        explanation="Irrelevant note.",
    )
    assert interp.applies is False
    assert interp.structured_adjustment is None


def test_no_op_with_applies_true_rejected() -> None:
    with pytest.raises(ValidationError):
        DirectiveInterpretation(
            note_index=0,
            applies=True,  # wrong
            directive_type="no_op",
            structured_adjustment=None,
            explanation="x",
        )


def test_real_directive_requires_applies_true() -> None:
    interp = DirectiveInterpretation(
        note_index=1,
        applies=True,
        directive_type="solar_reduction",
        structured_adjustment={"hours": [13, 14], "factor": 0.25},
        explanation="Cleaning",
    )
    assert interp.directive_type == "solar_reduction"


def test_solar_reduction_factor_above_one_rejected() -> None:
    with pytest.raises(ValidationError):
        SolarReductionAdjustment(hours=[13, 14], factor=1.5)


def test_solar_reduction_factor_negative_rejected() -> None:
    with pytest.raises(ValidationError):
        SolarReductionAdjustment(hours=[13, 14], factor=-0.1)


def test_minimum_battery_reserve_negative_rejected() -> None:
    with pytest.raises(ValidationError):
        MinimumBatteryReserveAdjustment(hours=[18, 19], minimum_energy_kwh=-5)


def test_max_grid_negative_rejected() -> None:
    with pytest.raises(ValidationError):
        MaxGridWindowAdjustment(hours=[18, 19], max_grid_kwh=-10)


def test_hours_only_adjustment_requires_at_least_one_hour() -> None:
    with pytest.raises(ValidationError):
        HoursOnlyAdjustment(hours=[])


# ---------- response ---------- #

def test_hourly_plan_entry_valid() -> None:
    entry = HourlyPlanEntry(
        hour=5,
        grid_kwh=80.0,
        solar_used_kwh=20.0,
        battery_action="charge",
        battery_kwh=5.0,
        battery_energy_after_kwh=55.0,
    )
    assert entry.battery_action == "charge"


def test_hourly_plan_entry_negative_kwh_rejected() -> None:
    with pytest.raises(ValidationError):
        HourlyPlanEntry(
            hour=0,
            grid_kwh=-1.0,
            solar_used_kwh=0.0,
            battery_action="idle",
            battery_kwh=0.0,
            battery_energy_after_kwh=50.0,
        )
