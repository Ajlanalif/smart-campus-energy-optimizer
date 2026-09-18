"""Shared verification helpers for public-sample tests.

Imported by:

* ``tests/test_public_samples.py`` (deterministic, uses organizer's
  reference ``expected_output.directive_interpretation``)
* ``tests/test_live_samples.py`` (LLM-driven, skips when
  ``GEMINI_API_KEY`` is not set)

The helpers here are intentionally generic: they only depend on the
``req``, ``applied``, ``result`` and ``case`` objects. They do NOT
hard-code any sample ID, note phrase, numeric value, or reference
schedule.

Pytest must be run from the repo root so ``from tests._public_sample_helpers
import ...`` resolves via the sys.path that pytest sets up.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from app.directives.apply import build_applied_directives
from app.optimizer.solver import optimize_schedule
from app.samples.loader import (
    sample_to_expected_directives,
    sample_to_request_dict,
)
from app.schemas.interpretation import DirectiveInterpretation
from app.schemas.request import OptimizeEnergyRequest

# Repo + sample paths.
REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLES_FILE = REPO_ROOT / "tests" / "data" / "public_samples.json"

# Per-case cost slack for DETERMINISTIC tests. The public pack states
# "equivalent valid schedules are accepted", so we allow a small multiplier
# so legitimate alternative schedules are not falsely flagged. Anything
# significantly worse than the reference would suggest a real
# optimization-quality regression.
COST_SLACK = 1.05  # +5% over the reference is acceptable

# Absolute tolerance for kWh / BDT values, per the canonical contract.
ABS_TOL = 0.01


# ---------- sample loaders ---------- #

def _all_samples() -> list[dict]:
    """Load and return all public samples, skipping if the file is absent."""
    if not SAMPLES_FILE.exists():
        pytest_skip(f"Public sample file not found at {SAMPLES_FILE}")
    from app.samples.loader import load_samples
    return load_samples(SAMPLES_FILE)


def pytest_skip(reason: str) -> None:
    """Tiny wrapper so the helpers module does not need a hard pytest import."""
    import pytest

    pytest.skip(reason)


def _build_request_from_case(case: dict) -> OptimizeEnergyRequest:
    """Convert a sample's input block into a Pydantic request."""
    return OptimizeEnergyRequest(**sample_to_request_dict(case))


def _build_expected_interpretations(case: dict) -> list[DirectiveInterpretation]:
    """Convert a sample's expected directive_interpretation into Pydantic models."""
    return [
        DirectiveInterpretation(**d) for d in sample_to_expected_directives(case)
    ]


def _run_optimizer_for_case(case: dict) -> tuple[OptimizeEnergyRequest, Any]:
    """Run the optimizer on a sample case; returns (request, result).

    Uses the organizer's reference interpretation (NOT the LLM). Used by the
    deterministic test path.
    """
    req = _build_request_from_case(case)
    interps = _build_expected_interpretations(case)
    applied = build_applied_directives(interps, req.hours, req.battery)
    result = optimize_schedule(req.hours, req.battery, applied)
    return req, result


def _case_ids() -> list[str]:
    """Case IDs for parametrize; skip the whole module if samples are absent."""
    if not SAMPLES_FILE.exists():
        pytest_skip(
            f"Public sample file not found at {SAMPLES_FILE}",
        )
    return [c["id"] for c in _all_samples()]


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


def _verify_cost_within_slack(case, total_cost_bdt: float, slack: float = COST_SLACK) -> None:
    """Assert total_cost_bdt is within `slack` (default 5%) of the reference.

    Pass ``slack=1.10`` (10%) for LLM-driven runs where paraphrased notes
    may produce a valid-but-suboptimal directive set (e.g. ``factor=0.3``
    instead of the reference ``0.2``).
    """
    ref_cost = case["expected_output"]["total_cost_bdt"]
    # If reference is 0 (degenerate), just skip.
    if ref_cost <= 0:
        return
    limit = ref_cost * slack
    assert total_cost_bdt <= limit, (
        f"team cost {total_cost_bdt} > {slack:.0%} of reference {ref_cost}"
    )
