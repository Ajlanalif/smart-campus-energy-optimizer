"""Deterministic validation of LLM-produced directive interpretations.

The LLM is treated as an untrusted text-to-structured-data translator.
This module is the security boundary: every field is checked, every
number is range-checked, every hour is normalised, and the result is
guaranteed to be safe to feed into the optimizer.

The validator returns a list of :class:`DirectiveInterpretation`
Pydantic models in note_index order. Any failure raises a
:class:`GuardrailError` subclass.
"""
from __future__ import annotations

import logging
import math
from typing import Any

from pydantic import ValidationError

from app.guardrails.errors import (
    AppliesAdjustmentMismatch,
    BadLLMOutput,
    ExtraAdjustmentField,
    InvalidHours,
    InvalidNumericRange,
    MissingAdjustmentField,
    NoteMappingError,
    UnknownDirectiveType,
)
from app.schemas.common import ALLOWED_DIRECTIVE_TYPES
from app.schemas.interpretation import DirectiveInterpretation

logger = logging.getLogger("gridwise.guardrails")


# Per-directive allowed fields in structured_adjustment.
_ALLOWED_FIELDS: dict[str, frozenset[str]] = {
    "solar_reduction": frozenset({"hours", "factor"}),
    "minimum_battery_reserve": frozenset({"hours", "minimum_energy_kwh"}),
    "no_charge_window": frozenset({"hours"}),
    "no_discharge_window": frozenset({"hours"}),
    "max_grid_window": frozenset({"hours", "max_grid_kwh"}),
    "no_op": frozenset(),  # adjustment must be null
}


# Per-directive required fields in structured_adjustment.
_REQUIRED_FIELDS: dict[str, frozenset[str]] = {
    "solar_reduction": frozenset({"hours", "factor"}),
    "minimum_battery_reserve": frozenset({"hours", "minimum_energy_kwh"}),
    "no_charge_window": frozenset({"hours"}),
    "no_discharge_window": frozenset({"hours"}),
    "max_grid_window": frozenset({"hours", "max_grid_kwh"}),
    "no_op": frozenset(),  # no fields required because adjustment is null
}


def _check_hours(hours: Any, directive_type: str, note_index: int) -> list[int]:
    """Validate an hours array: list of unique ints, ascending, 0..23."""
    if not isinstance(hours, list):
        raise InvalidHours(
            f"note_index={note_index} ({directive_type}): 'hours' must be a list, "
            f"got {type(hours).__name__}"
        )
    if len(hours) == 0:
        raise InvalidHours(
            f"note_index={note_index} ({directive_type}): 'hours' must contain "
            f"at least one entry"
        )

    out: list[int] = []
    for i, h in enumerate(hours):
        # bool is a subclass of int in Python; reject it explicitly.
        if isinstance(h, bool) or not isinstance(h, int):
            raise InvalidHours(
                f"note_index={note_index} ({directive_type}): 'hours[{i}]' must be "
                f"an integer, got {type(h).__name__}: {h!r}"
            )
        if not (0 <= h <= 23):
            raise InvalidHours(
                f"note_index={note_index} ({directive_type}): 'hours[{i}]={h}' "
                f"is outside the 0..23 range"
            )
        out.append(h)

    if len(set(out)) != len(out):
        raise InvalidHours(
            f"note_index={note_index} ({directive_type}): 'hours' contains "
            f"duplicates: {out}"
        )
    if out != sorted(out):
        raise InvalidHours(
            f"note_index={note_index} ({directive_type}): 'hours' must be in "
            f"ascending order, got {out}"
        )
    return out


def _validate_adjustment(
    directive_type: str,
    adjustment: Any,
    note_index: int,
    battery_capacity_kwh: float,
) -> dict[str, Any]:
    """Per-directive structured_adjustment shape + numeric range checks."""
    if adjustment is None:
        if directive_type == "no_op":
            return {}
        raise AppliesAdjustmentMismatch(
            f"note_index={note_index} ({directive_type}): structured_adjustment "
            f"must not be null"
        )

    if directive_type == "no_op":
        # no_op requires null adjustment; surface that contract before
        # drilling into fields.
        raise AppliesAdjustmentMismatch(
            f"note_index={note_index} (no_op): structured_adjustment must be null"
        )

    if not isinstance(adjustment, dict):
        raise AppliesAdjustmentMismatch(
            f"note_index={note_index} ({directive_type}): structured_adjustment "
            f"must be an object or null, got {type(adjustment).__name__}"
        )

    allowed = _ALLOWED_FIELDS[directive_type]
    required = _REQUIRED_FIELDS[directive_type]

    extra = set(adjustment.keys()) - allowed
    if extra:
        raise ExtraAdjustmentField(
            f"note_index={note_index} ({directive_type}): "
            f"structured_adjustment has unknown field(s): {sorted(extra)}"
        )

    missing = required - set(adjustment.keys())
    if missing:
        raise MissingAdjustmentField(
            f"note_index={note_index} ({directive_type}): "
            f"structured_adjustment is missing required field(s): {sorted(missing)}"
        )

    # hours is shared across every applicable directive.
    hours = _check_hours(adjustment.get("hours"), directive_type, note_index)
    result: dict[str, Any] = {"hours": hours}

    # Per-directive numeric checks.
    if directive_type == "solar_reduction":
        factor = adjustment.get("factor")
        if isinstance(factor, bool) or not isinstance(factor, (int, float)):
            raise InvalidNumericRange(
                f"note_index={note_index} (solar_reduction): 'factor' must be "
                f"a number, got {type(factor).__name__}"
            )
        if not math.isfinite(factor):
            raise InvalidNumericRange(
                f"note_index={note_index} (solar_reduction): 'factor' must be finite"
            )
        if not (0.0 <= factor <= 1.0):
            raise InvalidNumericRange(
                f"note_index={note_index} (solar_reduction): 'factor' must be in "
                f"[0, 1], got {factor}"
            )
        result["factor"] = float(factor)

    elif directive_type == "minimum_battery_reserve":
        reserve = adjustment.get("minimum_energy_kwh")
        if isinstance(reserve, bool) or not isinstance(reserve, (int, float)):
            raise InvalidNumericRange(
                f"note_index={note_index} (minimum_battery_reserve): "
                f"'minimum_energy_kwh' must be a number"
            )
        if not math.isfinite(reserve) or reserve < 0:
            raise InvalidNumericRange(
                f"note_index={note_index} (minimum_battery_reserve): "
                f"'minimum_energy_kwh' must be finite and >= 0, got {reserve}"
            )
        if reserve > battery_capacity_kwh:
            raise InvalidNumericRange(
                f"note_index={note_index} (minimum_battery_reserve): "
                f"'minimum_energy_kwh'={reserve} exceeds battery capacity "
                f"{battery_capacity_kwh}"
            )
        result["minimum_energy_kwh"] = float(reserve)

    elif directive_type == "max_grid_window":
        cap = adjustment.get("max_grid_kwh")
        if isinstance(cap, bool) or not isinstance(cap, (int, float)):
            raise InvalidNumericRange(
                f"note_index={note_index} (max_grid_window): 'max_grid_kwh' "
                f"must be a number"
            )
        if not math.isfinite(cap) or cap < 0:
            raise InvalidNumericRange(
                f"note_index={note_index} (max_grid_window): 'max_grid_kwh' "
                f"must be finite and >= 0, got {cap}"
            )
        result["max_grid_kwh"] = float(cap)

    return result


def _validate_one(
    raw: dict[str, Any],
    expected_note_index: int,
    battery_capacity_kwh: float,
) -> DirectiveInterpretation:
    """Validate a single directive entry. Returns a Pydantic model."""
    # 1. note_index must match its position.
    if "note_index" not in raw:
        raise NoteMappingError(
            f"entry at position {expected_note_index} is missing 'note_index'"
        )
    note_index = raw["note_index"]
    if isinstance(note_index, bool) or not isinstance(note_index, int):
        raise NoteMappingError(
            f"'note_index' must be an integer, got {type(note_index).__name__}"
        )
    if note_index != expected_note_index:
        raise NoteMappingError(
            f"expected note_index={expected_note_index} in position "
            f"{expected_note_index}, got {note_index}"
        )

    # 2. directive_type must be in the whitelist.
    if "directive_type" not in raw:
        raise BadLLMOutput(
            f"note_index={note_index}: missing 'directive_type'"
        )
    dtype = raw["directive_type"]
    if not isinstance(dtype, str) or dtype not in ALLOWED_DIRECTIVE_TYPES:
        raise UnknownDirectiveType(
            f"note_index={note_index}: directive_type={dtype!r} is not allowed. "
            f"Allowed: {sorted(ALLOWED_DIRECTIVE_TYPES)}"
        )

    # 3. applies flag.
    if "applies" not in raw:
        raise BadLLMOutput(f"note_index={note_index}: missing 'applies'")
    applies = raw["applies"]
    if not isinstance(applies, bool):
        raise BadLLMOutput(
            f"note_index={note_index}: 'applies' must be a boolean, got "
            f"{type(applies).__name__}"
        )

    # 4. explanation must be a non-empty string.
    explanation = raw.get("explanation", "")
    if not isinstance(explanation, str) or not explanation.strip():
        raise BadLLMOutput(
            f"note_index={note_index}: 'explanation' must be a non-empty string"
        )

    # 5. structured_adjustment shape + numeric checks.
    adjustment_raw = raw.get("structured_adjustment", None)
    adjustment_validated = _validate_adjustment(
        dtype, adjustment_raw, note_index, battery_capacity_kwh
    )

    # 6. applies vs adjustment contract.
    if dtype == "no_op":
        if applies is not False:
            raise AppliesAdjustmentMismatch(
                f"note_index={note_index}: no_op must have applies=false"
            )
        if adjustment_raw is not None:
            raise AppliesAdjustmentMismatch(
                f"note_index={note_index}: no_op must have "
                f"structured_adjustment=null"
            )
    else:
        if applies is not True:
            raise AppliesAdjustmentMismatch(
                f"note_index={note_index} ({dtype}): must have applies=true"
            )
        if adjustment_raw is None:
            raise AppliesAdjustmentMismatch(
                f"note_index={note_index} ({dtype}): must have a non-null "
                f"structured_adjustment"
            )

    # 7. Final Pydantic parse as the second-line guarantee.
    try:
        return DirectiveInterpretation(
            note_index=note_index,
            applies=applies,
            directive_type=dtype,
            structured_adjustment=adjustment_validated if adjustment_validated else None,
            explanation=explanation.strip(),
        )
    except ValidationError as exc:
        # Wrap for cleaner upstream handling.
        raise BadLLMOutput(
            f"note_index={note_index}: Pydantic validation failed: {exc}"
        ) from exc


def validate_directives(
    raw_llm_payload: Any,
    n_notes: int,
    battery_capacity_kwh: float,
) -> list[DirectiveInterpretation]:
    """Validate the raw LLM payload and return trusted DirectiveInterpretations.

    Parameters
    ----------
    raw_llm_payload
        The output of :meth:`LLMProvider.interpret_notes`, i.e. the
        ``parsed`` field of :class:`LLMResult`.
    n_notes
        The number of operator_notes in the original request. The LLM must
        produce exactly this many directive entries in note_index order.
    battery_capacity_kwh
        Used for sanity-checking directive minima against physical limits.

    Returns
    -------
    list[DirectiveInterpretation]
        Validated directive list in note_index order.

    Raises
    ------
    GuardrailError
        On any failure. The API layer translates this into a 400 response.
    """
    if not isinstance(raw_llm_payload, dict):
        raise BadLLMOutput(
            f"LLM payload must be a JSON object, got {type(raw_llm_payload).__name__}"
        )

    if "directives" not in raw_llm_payload:
        raise BadLLMOutput("LLM payload is missing the 'directives' key")

    directives = raw_llm_payload["directives"]
    if not isinstance(directives, list):
        raise BadLLMOutput(
            f"'directives' must be a list, got {type(directives).__name__}"
        )

    if n_notes < 1 or n_notes > 3:
        raise BadLLMOutput(f"n_notes must be 1..3, got {n_notes}")

    if len(directives) != n_notes:
        raise NoteMappingError(
            f"LLM returned {len(directives)} directives but the request has "
            f"{n_notes} operator_notes (expected exactly {n_notes})"
        )

    # Check no duplicate note_index values up front.
    seen_indices: set[int] = set()
    for i, d in enumerate(directives):
        if not isinstance(d, dict):
            raise BadLLMOutput(
                f"directives[{i}] must be an object, got {type(d).__name__}"
            )
        if "note_index" in d:
            ni = d["note_index"]
            if isinstance(ni, int) and not isinstance(ni, bool):
                if ni in seen_indices:
                    raise NoteMappingError(
                        f"duplicate note_index={ni} in LLM output"
                    )
                seen_indices.add(ni)

    validated: list[DirectiveInterpretation] = []
    for i, d in enumerate(directives):
        interp = _validate_one(d, expected_note_index=i, battery_capacity_kwh=battery_capacity_kwh)
        validated.append(interp)

    logger.info(
        "guardrails accepted %d directive(s); types=%s",
        len(validated),
        [v.directive_type for v in validated],
    )
    return validated
