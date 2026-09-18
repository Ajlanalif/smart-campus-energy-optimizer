"""Typed exceptions raised by the deterministic guardrails.

These exceptions are caught by the FastAPI layer and translated into
controlled HTTP error responses. The exception names are descriptive
enough that logs make the failure mode obvious to judges/operators.
"""
from __future__ import annotations


class GuardrailError(Exception):
    """Base class for every deterministic guardrail failure."""


class BadLLMOutput(GuardrailError):
    """LLM output could not be parsed or had the wrong top-level shape."""


class UnknownDirectiveType(GuardrailError):
    """LLM returned a directive_type that is not in the whitelist."""


class NoteMappingError(GuardrailError):
    """note_index coverage is wrong (missing, duplicate, or out of range)."""


class AppliesAdjustmentMismatch(GuardrailError):
    """applies / structured_adjustment combination violates the contract."""


class InvalidHours(GuardrailError):
    """Hours array has wrong shape: not unique, out of range, or unsorted."""


class InvalidNumericRange(GuardrailError):
    """Numeric value out of the allowed range for its directive type."""


class MissingAdjustmentField(GuardrailError):
    """structured_adjustment is missing a required field for its directive type."""


class ExtraAdjustmentField(GuardrailError):
    """structured_adjustment contains an unknown field for its directive type."""
