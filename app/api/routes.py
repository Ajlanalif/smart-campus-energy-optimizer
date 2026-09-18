"""HTTP routes: GET /health and POST /optimize-energy."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status

from app.schemas.request import OptimizeEnergyRequest
from app.schemas.response import OptimizeEnergyResponse

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
    """Phase 2: schemas are validated; pipeline is still a placeholder."""
    logger.info(
        "POST /optimize-energy received scenario_id=%s notes=%d",
        payload.scenario_id,
        len(payload.operator_notes),
    )
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Optimization pipeline is not yet wired up. See Phase 3+.",
    )
