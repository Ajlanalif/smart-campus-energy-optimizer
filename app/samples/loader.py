"""Loader for the organizer's public sample cases JSON file.

This module is intentionally generic: it does not hard-code case IDs,
note wording, or numeric values. It only knows the structural contract
documented in the public JSON's ``_meta`` field.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("gridwise.samples")


# Default location of the public sample pack (relative to project root).
DEFAULT_SAMPLES_PATH = Path(
    "hackathon_guide/BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json"
)


def load_samples(path: str | Path = DEFAULT_SAMPLES_PATH) -> list[dict[str, Any]]:
    """Load and return all public sample cases from the JSON pack.

    Returns
    -------
    list[dict]
        Each entry contains ``id``, ``label``, ``input``, ``expected_output``,
        ``input_request`` (a parsed Pydantic-ready dict).
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"Public sample file not found at {p}. "
            f"Check the relative path or pass an explicit path=."
        )

    with p.open() as f:
        data = json.load(f)

    if "cases" not in data or not isinstance(data["cases"], list):
        raise ValueError(f"Public sample file {p} has unexpected structure")

    cases = data["cases"]
    logger.info("Loaded %d public sample cases from %s", len(cases), p)
    return cases


def sample_to_request_dict(case: dict[str, Any]) -> dict[str, Any]:
    """Convert a case's ``input`` block into a Pydantic-ready request dict.

    The public JSON's input block already matches the OptimizeEnergyRequest
    schema, so this is mostly a pass-through with one defensive check.
    """
    return dict(case["input"])


def sample_to_expected_directives(case: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the expected directive_interpretation list for a sample case."""
    return list(case["expected_output"]["directive_interpretation"])
