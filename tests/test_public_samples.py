"""Replay the public sample cases through the optimizer.

For each of the 10 cases in the official public sample pack:

1. Build an :class:`OptimizeEnergyRequest` from the case's ``input`` block.
2. Build an :class:`AppliedDirectives` from the case's *expected*
   ``directive_interpretation`` (the public pack provides the organizer's
   reference interpretation, so we test the optimizer + directive
   application path end-to-end without involving the LLM).
3. Run the optimizer.
4. Verify every GridWise constraint:
   - 24 unique hours in [0, 23], sorted ascending
   - per-hour energy balance
   - solar_used <= effective_solar
   - battery bounds and rate limits
   - directive constraints (no_charge, no_discharge, max_grid, min_reserve)
   - end-of-day neutrality
   - totals match recalculation from hourly_plan
5. Verify cost is no worse than the reference cost plus a small slack
   (the public pack notes that equivalent valid schedules are accepted).

The LLM is deliberately NOT exercised here. These tests focus on the
deterministic optimizer + directive application pipeline.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

from app.directives.apply import build_applied_directives
from app.optimizer.solver import InfeasibleProblem, optimize_schedule
from app.samples.loader import (
    load_samples,
    sample_to_expected_directives,
    sample_to_request_dict,
)
from app.schemas.interpretation import DirectiveInterpretation
from app.schemas.request import OptimizeEnergyRequest

# Add repo root so we can find the JSON regardless of where pytest runs from.
REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLES_FILE = REPO_ROOT / "tests" / "data" / "public_samples.json"

# Per-case cost slack: the public pack states "equivalent valid schedules
# are accepted". We allow a small multiplier so that legitimate alternative
# schedules are not falsely flagged. Anything significantly worse than the
# reference would suggest a real optimization-quality regression.
COST_SLACK = 1.05  # +5% over the reference is acceptable

# Absolute tolerance for kWh / BDT values, per the canonical contract.
ABS_TOL = 0.01


def _all_samples() -> list[dict]:
    """Load and return all public samples, skipping if the file is absent."""
    if not SAMPLES_FILE.exists():
        pytest.skip(f"Public sample file not found at {SAMPLES_FILE}")
    return load_samples(SAMPLES_FILE)


def _build_request_from_case(case: dict) -> OptimizeEnergyRequest:
    """Convert a sample's input block into a Pydantic request."""
    return OptimizeEnergyRequest(**sample_to_request_dict(case))


def _build_expected_interpretations(case: dict) -> list[DirectiveInterpretation]:
    """Convert a sample's expected directive_interpretation into Pydantic models."""
    return [
        DirectiveInterpretation(**d) for d in sample_to_expected_directives(case)
    ]


def _run_optimizer_for_case(case: dict) -> tuple[OptimizeEnergyRequest, object]:
    """Run the optimizer on a sample case; returns (request, result)."""
    req = _build_request_from_case(case)
    interps = _build_expected_interpretations(case)
    applied = build_applied_directives(interps, req.hours, req.battery)
    result = optimize_schedule(req.hours, req.battery, applied)
    return req, result


# ---------- per-constraint verification helpers ---------- #

def _verify_24_unique_hours(result) -> None:
    hours_seen = [row["hour"] for row in result.hourly_plan]
    assert hours_seen == list(range(24)), (
        f"hourly_plan must contain hours 0..23 in order, got {hours_seen}"
    )


def _verify_energy_balance(req, result) -> None:
    for row in result.hourly_plan:
        h = row["hour"]
        demand = req.hours[h].demand_kwh
        charge = row["battery_kwh"] if row["battery_action"] == "charge" else 0.0
        discharge = row["battery_kwh"] if row["battery_action"] == "discharge" else 0.0
        lhs = row["grid_kwh"] + row["solar_used_kwh"] + discharge
        rhs = demand + charge
        assert math.isclose(lhs, rhs, abs_tol=ABS_TOL), (
            f"hour {h}: grid+solar+discharge={lhs} != demand+charge={rhs}"
        )


def _verify_solar_within_effective(case, req, applied, result) -> None:
    for row in result.hourly_plan:
        h = row["hour"]
        eff = applied.effective_solar[h]
        assert row["solar_used_kwh"] <= eff + ABS_TOL, (
            f"hour {h}: solar_used={row['solar_used_kwh']} > effective={eff}"
        )
        # Also: solar_used <= raw solar forecast.
        assert row["solar_used_kwh"] <= req.hours[h].solar_kwh + ABS_TOL, (
            f"hour {h}: solar_used={row['solar_used_kwh']} > raw forecast={req.hours[h].solar_kwh}"
        )


def _verify_battery_bounds(req, result) -> None:
    cap = req.battery.capacity_kwh
    lo = req.battery.minimum_energy_kwh
    for row in result.hourly_plan:
        e = row["battery_energy_after_kwh"]
        assert e >= lo - ABS_TOL, f"hour {row['hour']}: e={e} < minimum={lo}"
        assert e <= cap + ABS_TOL, f"hour {row['hour']}: e={e} > capacity={cap}"


def _verify_battery_rate_limits(req, result) -> None:
    c_rate = req.battery.max_charge_kwh_per_hour
    d_rate = req.battery.max_discharge_kwh_per_hour
    for row in result.hourly_plan:
        if row["battery_action"] == "charge":
            assert row["battery_kwh"] <= c_rate + ABS_TOL
        elif row["battery_action"] == "discharge":
            assert row["battery_kwh"] <= d_rate + ABS_TOL


def _verify_no_charge_window(applied, result) -> None:
    for h in applied.no_charge_hours:
        assert result.hourly_plan[h]["battery_action"] != "charge", (
            f"hour {h}: charging in no_charge_window"
        )


def _verify_no_discharge_window(applied, result) -> None:
    for h in applied.no_discharge_hours:
        assert result.hourly_plan[h]["battery_action"] != "discharge", (
            f"hour {h}: discharging in no_discharge_window"
        )


def _verify_max_grid_window(applied, result) -> None:
    for h in range(24):
        cap = applied.max_grid[h]
        if cap < 1e8:  # sentinel for "no cap"
            assert result.hourly_plan[h]["grid_kwh"] <= cap + ABS_TOL, (
                f"hour {h}: grid={result.hourly_plan[h]['grid_kwh']} > cap={cap}"
            )


def _verify_min_reserve(applied, req, result) -> None:
    """The per-hour min_reserve floor must be respected."""
    for h in range(24):
        floor = applied.min_reserve[h]
        # Floor is max(battery.minimum, directive_reserve).
        assert floor >= req.battery.minimum_energy_kwh - ABS_TOL
        e = result.hourly_plan[h]["battery_energy_after_kwh"]
        assert e >= floor - ABS_TOL, (
            f"hour {h}: e={e} < min_reserve={floor}"
        )


def _verify_end_of_day_neutrality(req, result) -> None:
    init = req.battery.initial_energy_kwh
    final = result.hourly_plan[-1]["battery_energy_after_kwh"]
    assert math.isclose(final, init, abs_tol=ABS_TOL), (
        f"end-of-day battery {final} != initial {init}"
    )


def _verify_totals(req, result) -> None:
    expected_grid = sum(r["grid_kwh"] for r in result.hourly_plan)
    expected_cost = sum(
        r["grid_kwh"] * req.hours[r["hour"]].tariff_bdt_per_kwh
        for r in result.hourly_plan
    )
    expected_peak = max(r["grid_kwh"] for r in result.hourly_plan)
    assert math.isclose(result.total_grid_kwh, expected_grid, abs_tol=ABS_TOL)
    assert math.isclose(result.total_cost_bdt, expected_cost, abs_tol=ABS_TOL)
    assert math.isclose(result.peak_grid_kwh, expected_peak, abs_tol=ABS_TOL)


def _verify_cost_within_slack(case, result) -> None:
    ref_cost = case["expected_output"]["total_cost_bdt"]
    # If reference is 0 (degenerate), just skip.
    if ref_cost <= 0:
        return
    limit = ref_cost * COST_SLACK
    assert result.total_cost_bdt <= limit, (
        f"team cost {result.total_cost_bdt} > {COST_SLACK:.0%} of reference {ref_cost}"
    )


# ---------- parametrized per-case test ---------- #

def _case_ids() -> list[str]:
    if not SAMPLES_FILE.exists():
        pytest.skip(f"Public sample file not found at {SAMPLES_FILE}", allow_module_level=True)
    return [c["id"] for c in _all_samples()]


@pytest.mark.parametrize(
    "case_id", _case_ids(), ids=lambda x: x if isinstance(x, str) else ""
)
def test_public_sample_round_trip(case_id: str) -> None:
    """End-to-end: load, validate, apply directives, optimize, verify."""
    samples = {c["id"]: c for c in _all_samples()}
    case = samples[case_id]

    # Build request + applied directives from the case.
    req = _build_request_from_case(case)
    interps = _build_expected_interpretations(case)
    applied = build_applied_directives(interps, req.hours, req.battery)

    # Run the optimizer.
    result = optimize_schedule(req.hours, req.battery, applied)

    # Constraint verification.
    _verify_24_unique_hours(result)
    _verify_energy_balance(req, result)
    _verify_solar_within_effective(case, req, applied, result)
    _verify_battery_bounds(req, result)
    _verify_battery_rate_limits(req, result)
    _verify_no_charge_window(applied, result)
    _verify_no_discharge_window(applied, result)
    _verify_max_grid_window(applied, result)
    _verify_min_reserve(applied, req, result)
    _verify_end_of_day_neutrality(req, result)
    _verify_totals(req, result)
    _verify_cost_within_slack(case, result)


def test_all_samples_load() -> None:
    """Sanity check: all 10 cases loaded."""
    samples = _all_samples()
    assert len(samples) == 10, f"expected 10 cases, got {len(samples)}"
    for c in samples:
        assert "id" in c
        assert "label" in c
        assert "input" in c
        assert "expected_output" in c


def test_sample_count_matches_meta() -> None:
    """The JSON's _meta says case_count = 10; verify."""
    samples = _all_samples()
    assert len(samples) == 10


def test_all_sample_inputs_validate_against_schema() -> None:
    """Every sample's input block must be a valid OptimizeEnergyRequest."""
    for case in _all_samples():
        # This will raise ValidationError on a malformed sample.
        req = _build_request_from_case(case)
        assert req.scenario_id == case["input"]["scenario_id"]
        assert 1 <= len(req.operator_notes) <= 3
        assert len(req.hours) == 24


def test_all_expected_directives_validate() -> None:
    """Every expected directive_interpretation entry must parse."""
    for case in _all_samples():
        interps = _build_expected_interpretations(case)
        assert len(interps) == len(case["input"]["operator_notes"])
        for i, interp in enumerate(interps):
            assert interp.note_index == i


# ---------- diagnostic: dump optimizer results vs reference ---------- #

def test_diagnostic_compare_to_reference(caplog) -> None:
    """For each sample, compare our optimizer's totals with the reference.

    This test always passes (informational only); it logs the comparison
    so reviewers can see where our optimizer matches or diverges from the
    organizer's reference schedule.
    """
    import logging as _logging

    caplog.set_level(_logging.INFO)
    for case in _all_samples():
        req, result = _run_optimizer_for_case(case)
        ref = case["expected_output"]
        print(
            f"\n[{case['id']}] {case['label']}\n"
            f"  ref  grid={ref['total_grid_kwh']} cost={ref['total_cost_bdt']} peak={ref['peak_grid_kwh']}\n"
            f"  ours grid={result.total_grid_kwh} cost={result.total_cost_bdt} peak={result.peak_grid_kwh}",
            file=sys.stdout,
        )
