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

The verification helpers (and the cost-slack tolerance) live in
``tests/_public_sample_helpers.py`` so that the LLM-driven
``test_live_samples.py`` can reuse them.
"""
from __future__ import annotations

import sys

import pytest

from app.directives.apply import build_applied_directives
from app.optimizer.solver import optimize_schedule
from app.schemas.interpretation import DirectiveInterpretation
from app.schemas.request import OptimizeEnergyRequest
from tests._public_sample_helpers import (
    SAMPLES_FILE,
    _all_samples,
    _build_expected_interpretations,
    _build_request_from_case,
    _case_ids,
    _run_optimizer_for_case,
    _verify_24_unique_hours,
    _verify_battery_bounds,
    _verify_battery_rate_limits,
    _verify_cost_within_slack,
    _verify_energy_balance,
    _verify_end_of_day_neutrality,
    _verify_max_grid_window,
    _verify_min_reserve,
    _verify_no_charge_window,
    _verify_no_discharge_window,
    _verify_solar_within_effective,
    _verify_totals,
)


# ---------- parametrized per-case test ---------- #

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
    _verify_cost_within_slack(case, result.total_cost_bdt)


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
