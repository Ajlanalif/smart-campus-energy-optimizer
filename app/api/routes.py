"""HTTP routes: GET /health and POST /optimize-energy."""
from __future__ import annotations

import logging

from fastapi import APIRouter

from app.schemas.request import OptimizeEnergyRequest
from app.schemas.response import OptimizeEnergyResponse
from app.services.optimize import run_optimize

router = APIRouter()
logger = logging.getLogger("gridwise.api")


@router.get("/health", tags=["health"])
def health() -> dict[str, str]:
    """Readiness probe. Must return {"status": "ok"} within 60 seconds of startup."""
    return {"status": "ok"}


@router.post(
    "/optimize-energy",
    tags=["optimize"],
    response_model=OptimizeEnergyResponse,
)
def optimize_energy(payload: OptimizeEnergyRequest) -> OptimizeEnergyResponse:
    """End-to-end optimization for one scenario.

    Runs the canonical pipeline (LLM → guardrails → apply → optimize →
    validate) via :func:`app.services.optimize.run_optimize`. All
    exception-to-HTTP translation happens inside the orchestrator, so
    this function is a thin wrapper.
    """
    logger.info(
        "POST /optimize-energy scenario=%s notes=%d",
        payload.scenario_id,
        len(payload.operator_notes),
    )
    return run_optimize(payload)