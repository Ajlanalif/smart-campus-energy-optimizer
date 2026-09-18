"""Live LLM-driven end-to-end tests against the 10 public samples.

Two test paths are exercised for every case:

1. ``test_live_in_process``: calls :func:`app.services.optimize.run_optimize`
   directly — fast, no HTTP overhead. Verifies the in-process pipeline.

2. ``test_live_http``: POSTs the case's input block to
   ``/optimize-energy`` via :class:`fastapi.testclient.TestClient`.
   Verifies the full HTTP contract the judges will hit.

Both paths share :func:`_assert_response_valid`, which re-runs every
constraint from :mod:`tests._public_sample_helpers` against the actual
returned plan. They DO NOT assert against the organizer's reference
``expected_output.directive_interpretation`` — the LLM may produce a
different-but-valid interpretation for paraphrased notes. We only
assert:

* structural validity of the response (allowed directive types,
  exactly one entry per operator note, ascending hours, etc.);
* every GridWise constraint (energy balance, bounds, rate limits,
  directive windows, end-of-day neutrality, totals match recalculation);
* cost is within +10% of the reference (looser than the deterministic
  +5% slack because paraphrased notes may produce valid-but-suboptimal
  directive sets, e.g. ``factor=0.3`` instead of the reference ``0.2``).

All tests are gated on ``GEMINI_API_KEY`` so they are no-ops in CI
without secrets; locally they exercise the real Gemini API.
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from app.directives.apply import build_applied_directives
from app.main import app
from app.samples.loader import load_samples
from app.services.optimize import run_optimize
from tests._public_sample_helpers import (
    ABS_TOL,
    SAMPLES_FILE,
    _all_samples,
    _build_request_from_case,
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


# ---------- gating + config ---------- #

LIVE = pytest.mark.skipif(
    not os.environ.get("GEMINI_API_KEY"),
    reason="GEMINI_API_KEY not set; skipping live LLM test",
)

# Looser cost slack for LLM-driven runs. The LLM may produce a valid but
# slightly suboptimal directive set for paraphrased notes (e.g. factor=0.3
# instead of the reference 0.2). The judge contract is "equivalent valid
# schedules are accepted" so 10% headroom covers paraphrasing without
# masking real regressions.
COST_SLACK_LIVE = 1.10

ALLOWED_DIRECTIVE_TYPES: frozenset[str] = frozenset(
    {
        "solar_reduction",
        "minimum_battery_reserve",
        "no_charge_window",
        "no_discharge_window",
        "max_grid_window",
        "no_op",
    }
)


def _case_ids() -> list[str]:
    if not SAMPLES_FILE.exists():
        pytest.skip(
            f"Public sample file not found at {SAMPLES_FILE}",
            allow_module_level=True,
        )
    return [c["id"] for c in load_samples(SAMPLES_FILE)]


# Module-level client; FastAPI TestClient is cheap to construct but we
# don't want to pay for re-imports per test.
client = TestClient(app)


# ---------- shared assertion ---------- #

class _PlanLike:
    """Tiny adapter so the existing _verify_* helpers (which expect an
    OptimizationResult-like object with .hourly_plan + .total_grid_kwh +
    .total_cost_bdt + .peak_grid_kwh) can be reused against an HTTP
    response payload without copying their bodies.
    """

    __slots__ = ("hourly_plan", "total_grid_kwh", "total_cost_bdt", "peak_grid_kwh")

    def __init__(self, payload: dict) -> None:
        self.hourly_plan = payload["hourly_plan"]
        self.total_grid_kwh = payload["total_grid_kwh"]
        self.total_cost_bdt = payload["total_cost_bdt"]
        self.peak_grid_kwh = payload["peak_grid_kwh"]


def _assert_response_valid(req, case: dict, payload: dict) -> None:
    """Run every shared constraint check against a response payload (dict)."""
    # 1. Structural sanity on the envelope.
    assert payload["scenario_id"] == case["id"], (
        f"scenario_id mismatch: response={payload['scenario_id']} case={case['id']}"
    )

    directives = payload["directive_interpretation"]
    assert isinstance(directives, list), "directive_interpretation must be a list"
    assert len(directives) == len(req.operator_notes), (
        f"got {len(directives)} directives for {len(req.operator_notes)} notes"
    )
    for i, d in enumerate(directives):
        assert d["note_index"] == i, (
            f"directive[{i}].note_index must be {i}, got {d['note_index']}"
        )
        assert d["directive_type"] in ALLOWED_DIRECTIVE_TYPES, (
            f"directive[{i}].directive_type={d['directive_type']!r} not allowed"
        )

    # 2. Plan shape.
    plan = payload["hourly_plan"]
    assert isinstance(plan, list), "hourly_plan must be a list"
    assert len(plan) == 24, f"hourly_plan must have 24 entries, got {len(plan)}"
    assert [row["hour"] for row in plan] == list(range(24)), (
        "hourly_plan hours must be ascending 0..23"
    )

    # 3. Re-derive constraints. Reconstruct AppliedDirectives from the
    # response's directives so we re-check no_charge/no_discharge/max_grid/
    # min_reserve against the actual returned plan.
    from app.schemas.interpretation import DirectiveInterpretation

    interps = [DirectiveInterpretation(**d) for d in directives]
    applied = build_applied_directives(interps, req.hours, req.battery)

    result_like = _PlanLike(payload)
    _verify_24_unique_hours(result_like)
    _verify_energy_balance(req, result_like)
    _verify_solar_within_effective(case, req, applied, result_like)
    _verify_battery_bounds(req, result_like)
    _verify_battery_rate_limits(req, result_like)
    _verify_no_charge_window(applied, result_like)
    _verify_no_discharge_window(applied, result_like)
    _verify_max_grid_window(applied, result_like)
    _verify_min_reserve(applied, req, result_like)
    _verify_end_of_day_neutrality(req, result_like)
    _verify_totals(req, result_like)

    # 4. Cost slack against the organizer reference.
    _verify_cost_within_slack(case, payload["total_cost_bdt"], slack=COST_SLACK_LIVE)

    # 5. Plan summary is non-empty.
    assert isinstance(payload["plan_summary"], str) and payload["plan_summary"], (
        "plan_summary must be a non-empty string"
    )

    # 6. Totals non-negative (the response schema also enforces this; here
    # we just protect against pathological floats).
    for k in ("total_grid_kwh", "total_cost_bdt", "peak_grid_kwh"):
        assert payload[k] >= -ABS_TOL, f"{k}={payload[k]} is negative"


# ---------- parametrized tests ---------- #

@LIVE
@pytest.mark.parametrize(
    "case_id", _case_ids(), ids=lambda x: x if isinstance(x, str) else ""
)
def test_live_in_process(case_id: str) -> None:
    """Run the full pipeline in-process and re-verify every constraint."""
    case = next(c for c in _all_samples() if c["id"] == case_id)
    req = _build_request_from_case(case)
    resp = run_optimize(req)
    # ``resp`` is an OptimizeEnergyResponse Pydantic model; serialize for the
    # shared assertion helper.
    payload = resp.model_dump(mode="json")
    _assert_response_valid(req, case, payload)


@LIVE
@pytest.mark.parametrize(
    "case_id", _case_ids(), ids=lambda x: x if isinstance(x, str) else ""
)
def test_live_http(case_id: str) -> None:
    """POST the case to /optimize-energy and re-verify every constraint."""
    case = next(c for c in _all_samples() if c["id"] == case_id)
    req = _build_request_from_case(case)
    r = client.post("/optimize-energy", json=req.model_dump(mode="json"))
    assert r.status_code == 200, (
        f"POST /optimize-energy returned {r.status_code} for {case_id}: {r.text}"
    )
    payload = r.json()
    _assert_response_valid(req, case, payload)
