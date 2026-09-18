"""Tests for the final validator."""
from __future__ import annotations

import copy

import pytest

from app.directives.apply import AppliedDirectives, build_applied_directives
from app.optimizer.solver import optimize_schedule
from app.schemas.interpretation import DirectiveInterpretation
from app.schemas.request import (
    BatterySpec,
    HourData,
    OptimizeEnergyRequest,
)
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
from app.validator.validate import validate_schedule


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


def _make_request(case_id: str = "TEST", with_notes: list | None = None) -> OptimizeEnergyRequest:
    return OptimizeEnergyRequest(
        scenario_id=case_id,
        operator_notes=with_notes or ["test note"],
        hours=_flat_24(),
        battery=_battery(),
    )


def _run_and_validate(
    hours: list[HourData] | None = None,
    battery: BatterySpec | None = None,
    interpretations: list | None = None,
    scenario_id: str = "TEST",
    operator_notes: list | None = None,
) -> object:
    """Run optimizer + validator end-to-end. Returns ValidatedPlan."""
    req = OptimizeEnergyRequest(
        scenario_id=scenario_id,
        operator_notes=operator_notes or ["test note"],
        hours=hours or _flat_24(),
        battery=battery or _battery(),
    )
    applied = build_applied_directives(interpretations or [], req.hours, req.battery)
    result = optimize_schedule(req.hours, req.battery, applied)
    return validate_schedule(
        req,
        applied,
        result.hourly_plan,
        result.total_grid_kwh,
        result.total_cost_bdt,
        result.peak_grid_kwh,
    )


# ---------- happy paths ---------- #

def test_baseline_validates() -> None:
    v = _run_and_validate()
    assert v.scenario_id == "TEST"
    assert len(v.hourly_plan) == 24
    assert v.total_grid_kwh > 0
    assert v.total_cost_bdt > 0
    assert v.peak_grid_kwh > 0


def test_with_solar_reduction_validates() -> None:
    interps = [
        _interp(0, "solar_reduction", adj={"hours": [12, 13], "factor": 0.25}),
    ]
    hours = _flat_24(solar=50.0)
    v = _run_and_validate(hours=hours, interpretations=interps)
    assert v is not None


def test_with_all_directives_validates() -> None:
    interps = [
        _interp(0, "solar_reduction", adj={"hours": [12, 13], "factor": 0.5}),
        _interp(1, "no_charge_window", adj={"hours": [14, 15]}),
        _interp(2, "minimum_battery_reserve", adj={"hours": [18, 19], "minimum_energy_kwh": 60.0}),
        _interp(3, "max_grid_window", adj={"hours": [20], "max_grid_kwh": 50.0}),
        _interp(4, "no_discharge_window", adj={"hours": [22, 23]}),
    ]
    # 5 notes exceeds the 1-3 limit; use only 3 instead.
    interps = interps[:3]
    v = _run_and_validate(interpretations=interps, battery=_battery(cap=200.0))
    assert v is not None


def test_no_op_with_other_directives_validates() -> None:
    interps = [
        _interp(0, "no_op", applies=False),
        _interp(1, "no_charge_window", adj={"hours": [12]}),
        _interp(2, "no_op", applies=False),
    ]
    v = _run_and_validate(interpretations=interps)
    assert v is not None


def test_plan_summary_mentions_no_charge_window() -> None:
    interps = [_interp(0, "no_charge_window", adj={"hours": [10, 11, 12]})]
    v = _run_and_validate(interpretations=interps)
    assert "no-charge" in v.plan_summary.lower()


def test_plan_summary_mentions_grid_cap() -> None:
    interps = [_interp(0, "max_grid_window", adj={"hours": [18, 19], "max_grid_kwh": 100.0})]
    v = _run_and_validate(interpretations=interps)
    assert "capped" in v.plan_summary.lower() or "grid import" in v.plan_summary.lower()


def test_plan_summary_mentions_solar_reduction() -> None:
    interps = [_interp(0, "solar_reduction", adj={"hours": [12, 13], "factor": 0.5})]
    v = _run_and_validate(hours=_flat_24(solar=100.0), interpretations=interps)
    assert "solar" in v.plan_summary.lower()


def test_plan_summary_mentions_reserve() -> None:
    interps = [
        _interp(0, "minimum_battery_reserve", adj={"hours": [18, 19], "minimum_energy_kwh": 80.0}),
    ]
    v = _run_and_validate(interpretations=interps, battery=_battery(cap=200.0))
    assert "reserve" in v.plan_summary.lower()


# ---------- failure: hour range ---------- #

def test_wrong_number_of_hours_rejected() -> None:
    req = _make_request()
    applied = AppliedDirectives()
    plan = [{"hour": h, "grid_kwh": 100.0, "solar_used_kwh": 0.0,
             "battery_action": "idle", "battery_kwh": 0.0,
             "battery_energy_after_kwh": 50.0} for h in range(23)]
    with pytest.raises(HourRangeError):
        validate_schedule(req, applied, plan, 2300.0, 23000.0, 100.0)


def test_non_ascending_hours_rejected() -> None:
    req = _make_request()
    applied = AppliedDirectives()
    plan = [{"hour": h, "grid_kwh": 100.0, "solar_used_kwh": 0.0,
             "battery_action": "idle", "battery_kwh": 0.0,
             "battery_energy_after_kwh": 50.0} for h in range(24)]
    plan[0], plan[1] = plan[1], plan[0]
    with pytest.raises(HourRangeError):
        validate_schedule(req, applied, plan, 2400.0, 24000.0, 100.0)


# ---------- failure: non-negativity ---------- #

def test_negative_grid_rejected() -> None:
    req = _make_request()
    applied = AppliedDirectives()
    res = optimize_schedule(req.hours, req.battery, applied)
    plan = copy.deepcopy(res.hourly_plan)
    plan[0]["grid_kwh"] = -1.0
    with pytest.raises(GridNegative):
        validate_schedule(req, applied, plan, res.total_grid_kwh - 1.0, res.total_cost_bdt, res.peak_grid_kwh)


def test_negative_solar_rejected() -> None:
    req = _make_request()
    applied = AppliedDirectives()
    res = optimize_schedule(req.hours, req.battery, applied)
    plan = copy.deepcopy(res.hourly_plan)
    plan[0]["solar_used_kwh"] = -0.5
    with pytest.raises(SolarNegative):
        validate_schedule(req, applied, plan, res.total_grid_kwh, res.total_cost_bdt, res.peak_grid_kwh)


def test_negative_battery_rejected() -> None:
    req = _make_request()
    applied = AppliedDirectives()
    res = optimize_schedule(req.hours, req.battery, applied)
    plan = copy.deepcopy(res.hourly_plan)
    plan[0]["battery_energy_after_kwh"] = -1.0
    with pytest.raises(BatteryNegative):
        validate_schedule(req, applied, plan, res.total_grid_kwh, res.total_cost_bdt, res.peak_grid_kwh)


# ---------- failure: action vs magnitude ---------- #

def test_charge_action_with_zero_kwh_rejected() -> None:
    req = _make_request()
    applied = AppliedDirectives()
    res = optimize_schedule(req.hours, req.battery, applied)
    plan = copy.deepcopy(res.hourly_plan)
    plan[0]["battery_action"] = "charge"
    plan[0]["battery_kwh"] = 0.0
    with pytest.raises(ChargeActionConflict):
        validate_schedule(req, applied, plan, res.total_grid_kwh, res.total_cost_bdt, res.peak_grid_kwh)


def test_idle_action_with_nonzero_kwh_rejected() -> None:
    req = _make_request()
    applied = AppliedDirectives()
    res = optimize_schedule(req.hours, req.battery, applied)
    plan = copy.deepcopy(res.hourly_plan)
    plan[0]["battery_action"] = "idle"
    plan[0]["battery_kwh"] = 5.0
    with pytest.raises(ChargeActionConflict):
        validate_schedule(req, applied, plan, res.total_grid_kwh, res.total_cost_bdt, res.peak_grid_kwh)


def test_unknown_battery_action_rejected() -> None:
    req = _make_request()
    applied = AppliedDirectives()
    res = optimize_schedule(req.hours, req.battery, applied)
    plan = copy.deepcopy(res.hourly_plan)
    plan[0]["battery_action"] = "destroy"
    with pytest.raises(ChargeActionConflict):
        validate_schedule(req, applied, plan, res.total_grid_kwh, res.total_cost_bdt, res.peak_grid_kwh)


# ---------- failure: energy balance ---------- #

def test_energy_balance_violation_rejected() -> None:
    req = _make_request()
    applied = AppliedDirectives()
    res = optimize_schedule(req.hours, req.battery, applied)
    plan = copy.deepcopy(res.hourly_plan)
    # Shift 10 kWh from grid to nothing.
    plan[0]["grid_kwh"] -= 10.0
    with pytest.raises(EnergyBalanceError):
        validate_schedule(req, applied, plan, res.total_grid_kwh - 10.0, res.total_cost_bdt - 100.0, res.peak_grid_kwh)


# ---------- failure: solar overshoot ---------- #

def test_solar_overshoot_rejected() -> None:
    interps = [_interp(0, "solar_reduction", adj={"hours": [12, 13], "factor": 0.25})]
    # raw solar = 100, factor = 0.25 -> effective = 25. Demand is set well above
    # 25 so the optimizer must draw a large positive grid_kwh at hour 12; that
    # way we can bump solar_used by 5 and reduce grid by 5 without going
    # negative, which would otherwise trip GridNegative before SolarOvershoot.
    hours = _flat_24(demand=300.0, solar=100.0)
    battery = _battery(cap=500.0, init=100.0, lo=0.0, c_rate=200.0, d_rate=200.0)
    req = OptimizeEnergyRequest(scenario_id="T", operator_notes=["a"], hours=hours, battery=battery)
    applied = build_applied_directives(interps, req.hours, req.battery)
    res = optimize_schedule(req.hours, req.battery, applied)
    plan = copy.deepcopy(res.hourly_plan)
    # Force solar_used above effective bound. Effective is 25, push to 30.
    # Energy balance requires grid to absorb the extra 5 kWh from demand.
    plan[12]["solar_used_kwh"] = applied.effective_solar[12] + 5.0
    plan[12]["grid_kwh"] -= 5.0
    new_total_grid = sum(p["grid_kwh"] for p in plan)
    new_total_cost = sum(
        p["grid_kwh"] * req.hours[p["hour"]].tariff_bdt_per_kwh for p in plan
    )
    new_peak = max(p["grid_kwh"] for p in plan)
    with pytest.raises(SolarOvershoot):
        validate_schedule(req, applied, plan, new_total_grid, new_total_cost, new_peak)


# ---------- failure: battery bounds ---------- #

def test_battery_above_capacity_rejected() -> None:
    req = _make_request()
    applied = AppliedDirectives()
    res = optimize_schedule(req.hours, req.battery, applied)
    plan = copy.deepcopy(res.hourly_plan)
    plan[0]["battery_energy_after_kwh"] = req.battery.capacity_kwh + 5.0
    with pytest.raises(BatteryBoundError):
        validate_schedule(req, applied, plan, res.total_grid_kwh, res.total_cost_bdt, res.peak_grid_kwh)


def test_battery_below_minimum_rejected() -> None:
    # Battery minimum is 30; the optimizer respects it. Force a violation.
    req_obj = OptimizeEnergyRequest(
        scenario_id="T",
        operator_notes=["a"],
        hours=_flat_24(),
        battery=_battery(lo=30.0, init=50.0, cap=100.0),
    )
    applied = build_applied_directives([], req_obj.hours, req_obj.battery)
    res = optimize_schedule(req_obj.hours, req_obj.battery, applied)
    plan = copy.deepcopy(res.hourly_plan)
    plan[0]["battery_energy_after_kwh"] = 5.0  # below lo=30
    with pytest.raises(BatteryBoundError):
        validate_schedule(
            req_obj, applied, plan,
            res.total_grid_kwh, res.total_cost_bdt, res.peak_grid_kwh,
        )


def test_battery_below_directive_reserve_rejected() -> None:
    """If a min_reserve directive raises the floor, dropping below it must fail."""
    interps = [_interp(0, "minimum_battery_reserve", adj={"hours": [5, 6, 7], "minimum_energy_kwh": 80.0})]
    battery = _battery(cap=200.0, init=100.0, lo=0.0)
    hours = _flat_24(demand=200.0, solar=0.0)
    req = OptimizeEnergyRequest(scenario_id="T", operator_notes=["a"], hours=hours, battery=battery)
    applied = build_applied_directives(interps, req.hours, req.battery)
    res = optimize_schedule(req.hours, req.battery, applied)
    plan = copy.deepcopy(res.hourly_plan)
    plan[5]["battery_energy_after_kwh"] = 50.0  # below 80 floor
    with pytest.raises(BatteryBoundError):
        validate_schedule(req, applied, plan, res.total_grid_kwh, res.total_cost_bdt, res.peak_grid_kwh)


# ---------- failure: rate limits ---------- #

def test_charge_rate_violation_rejected() -> None:
    # Use a battery with high capacity so e_after stays in bounds.
    req = OptimizeEnergyRequest(
        scenario_id="T",
        operator_notes=["a"],
        hours=_flat_24(),
        battery=_battery(cap=500.0, init=100.0, lo=0.0, c_rate=50.0, d_rate=50.0),
    )
    applied = build_applied_directives([], req.hours, req.battery)
    res = optimize_schedule(req.hours, req.battery, applied)
    plan = copy.deepcopy(res.hourly_plan)
    # Set hour 0 to charge way over the rate limit; balance grid to keep
    # energy equation satisfied.
    new_charge = req.battery.max_charge_kwh_per_hour + 5.0
    plan[0]["battery_action"] = "charge"
    plan[0]["battery_kwh"] = new_charge
    plan[0]["battery_energy_after_kwh"] = req.battery.initial_energy_kwh + new_charge
    new_grid = 100.0 + new_charge
    plan[0]["grid_kwh"] = new_grid
    new_total_grid = res.total_grid_kwh + (new_grid - plan[0]["grid_kwh"] + new_charge)
    # Simpler: just feed totals that match the mutated plan.
    new_total_grid = sum(p["grid_kwh"] for p in plan)
    new_total_cost = sum(p["grid_kwh"] * req.hours[p["hour"]].tariff_bdt_per_kwh for p in plan)
    new_peak = max(p["grid_kwh"] for p in plan)
    with pytest.raises(BatteryRateError):
        validate_schedule(req, applied, plan, new_total_grid, new_total_cost, new_peak)


# ---------- failure: directive violations ---------- #

def test_no_charge_window_violation_rejected() -> None:
    interps = [_interp(0, "no_charge_window", adj={"hours": [12]})]
    hours = _flat_24()
    battery = _battery(cap=500.0, init=50.0, lo=0.0, c_rate=100.0, d_rate=100.0)
    req = OptimizeEnergyRequest(scenario_id="T", operator_notes=["a"], hours=hours, battery=battery)
    applied = build_applied_directives(interps, req.hours, req.battery)
    # Manually construct a plan that violates the no_charge directive at hour 12.
    plan = []
    for h in range(24):
        plan.append({
            "hour": h,
            "grid_kwh": 100.0,
            "solar_used_kwh": 0.0,
            "battery_action": "idle",
            "battery_kwh": 0.0,
            "battery_energy_after_kwh": 50.0,
        })
    # Force charge at hour 12 with adjusted balance.
    plan[12]["battery_action"] = "charge"
    plan[12]["battery_kwh"] = 10.0
    plan[12]["battery_energy_after_kwh"] = 60.0
    plan[12]["grid_kwh"] = 110.0  # 100 demand + 10 charge
    with pytest.raises(DirectiveViolation):
        validate_schedule(req, applied, plan, sum(p["grid_kwh"] for p in plan), 100.0 * 11, 110.0)


def test_max_grid_window_violation_rejected() -> None:
    interps = [_interp(0, "max_grid_window", adj={"hours": list(range(24)), "max_grid_kwh": 50.0})]
    hours = _flat_24(demand=80.0)
    battery = _battery(cap=100.0, init=100.0, lo=0.0, d_rate=50.0)
    req = OptimizeEnergyRequest(scenario_id="T", operator_notes=["a"], hours=hours, battery=battery)
    applied = build_applied_directives(interps, req.hours, req.battery)
    # A plan where hour 0 exceeds the cap.
    plan = []
    for h in range(24):
        plan.append({
            "hour": h,
            "grid_kwh": 30.0,
            "solar_used_kwh": 0.0,
            "battery_action": "discharge",
            "battery_kwh": 50.0,
            "battery_energy_after_kwh": 50.0,
        })
    # Force hour 0 to exceed the 50 kWh cap.
    plan[0]["grid_kwh"] = 80.0
    plan[0]["battery_kwh"] = 0.0
    plan[0]["battery_action"] = "idle"
    with pytest.raises(DirectiveViolation):
        validate_schedule(req, applied, plan, sum(p["grid_kwh"] for p in plan), 0.0, 80.0)


# ---------- failure: end-of-day neutrality ---------- #

def test_end_of_day_mismatch_rejected() -> None:
    req = _make_request()
    applied = AppliedDirectives()
    res = optimize_schedule(req.hours, req.battery, applied)
    plan = copy.deepcopy(res.hourly_plan)
    plan[-1]["battery_energy_after_kwh"] = req.battery.initial_energy_kwh + 10.0
    with pytest.raises(EndOfDayMismatch):
        validate_schedule(req, applied, plan, res.total_grid_kwh, res.total_cost_bdt, res.peak_grid_kwh)


# ---------- failure: total mismatches ---------- #

def test_total_grid_mismatch_rejected() -> None:
    req = _make_request()
    applied = AppliedDirectives()
    res = optimize_schedule(req.hours, req.battery, applied)
    with pytest.raises(TotalMismatch):
        validate_schedule(
            req, applied, res.hourly_plan,
            res.total_grid_kwh + 5.0,
            res.total_cost_bdt,
            res.peak_grid_kwh,
        )


def test_total_cost_mismatch_rejected() -> None:
    req = _make_request()
    applied = AppliedDirectives()
    res = optimize_schedule(req.hours, req.battery, applied)
    with pytest.raises(TotalMismatch):
        validate_schedule(
            req, applied, res.hourly_plan,
            res.total_grid_kwh,
            res.total_cost_bdt + 5.0,
            res.peak_grid_kwh,
        )


def test_peak_grid_mismatch_rejected() -> None:
    req = _make_request()
    applied = AppliedDirectives()
    res = optimize_schedule(req.hours, req.battery, applied)
    with pytest.raises(TotalMismatch):
        validate_schedule(
            req, applied, res.hourly_plan,
            res.total_grid_kwh,
            res.total_cost_bdt,
            res.peak_grid_kwh + 5.0,
        )


# ---------- integration: validator + sample harness ---------- #

def test_validator_passes_all_public_samples() -> None:
    """End-to-end: run optimizer + validator on every public sample."""
    from pathlib import Path
    from app.samples.loader import (
        load_samples,
        sample_to_expected_directives,
        sample_to_request_dict,
    )
    from app.schemas.interpretation import DirectiveInterpretation

    samples_path = Path(__file__).resolve().parents[1] / "tests" / "data" / "public_samples.json"
    if not samples_path.exists():
        pytest.skip("public samples not present")
    cases = load_samples(samples_path)
    for case in cases:
        req = OptimizeEnergyRequest(**sample_to_request_dict(case))
        interps = [DirectiveInterpretation(**d) for d in sample_to_expected_directives(case)]
        applied = build_applied_directives(interps, req.hours, req.battery)
        result = optimize_schedule(req.hours, req.battery, applied)
        v = validate_schedule(
            req, applied, result.hourly_plan,
            result.total_grid_kwh, result.total_cost_bdt, result.peak_grid_kwh,
        )
        assert v.scenario_id == case["id"]
