"""FastAPI application entry point for the GridWise LLM service."""
from __future__ import annotations

import logging

from fastapi import FastAPI

from app.api.routes import router

logger = logging.getLogger("gridwise")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def create_app() -> FastAPI:
    """Build the FastAPI application instance."""
    app = FastAPI(
        title="GridWise LLM Energy Optimizer",
        version="0.1.0",
        description=(
            "LLM-assisted 24-hour campus energy optimizer. "
            "Interprets operator notes via a language model, applies deterministic "
            "guardrails, then solves an LP/MIP to minimize grid cost."
        ),
    )

    app.include_router(router)

    return app


app = create_app()
