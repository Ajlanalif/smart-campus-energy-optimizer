"""Gemini provider implementation of the LLM interface."""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from google import genai
from google.genai import types

from app.llm.base import LLMProvider, LLMResult

logger = logging.getLogger("gridwise.llm")


# JSON schema the LLM must produce. Mirrors app.schemas.interpretation but
# is also directly accepted by Gemini's response_schema.
DIRECTIVES_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "directives": {
            "type": "array",
            "minItems": 1,
            "maxItems": 3,
            "items": {
                "type": "object",
                "properties": {
                    "note_index": {"type": "integer", "minimum": 0, "maximum": 2},
                    "applies": {"type": "boolean"},
                    "directive_type": {
                        "type": "string",
                        "enum": [
                            "solar_reduction",
                            "minimum_battery_reserve",
                            "no_charge_window",
                            "no_discharge_window",
                            "max_grid_window",
                            "no_op",
                        ],
                    },
                    "structured_adjustment": {
                        "type": "object",
                        "nullable": True,
                        "description": (
                            "For no_op, must be null. Otherwise, an object whose "
                            "shape depends on directive_type: solar_reduction "
                            "{hours:[..], factor:0..1}, "
                            "minimum_battery_reserve {hours:[..], minimum_energy_kwh:>=0}, "
                            "no_charge_window/no_discharge_window {hours:[..]}, "
                            "max_grid_window {hours:[..], max_grid_kwh:>=0}."
                        ),
                        "properties": {
                            "hours": {
                                "type": "array",
                                "items": {"type": "integer", "minimum": 0, "maximum": 23},
                                "minItems": 1,
                            },
                            "factor": {"type": "number", "minimum": 0, "maximum": 1},
                            "minimum_energy_kwh": {"type": "number", "minimum": 0},
                            "max_grid_kwh": {"type": "number", "minimum": 0},
                        },
                    },
                    "explanation": {"type": "string", "minLength": 1},
                },
                "required": [
                    "note_index",
                    "applies",
                    "directive_type",
                    "structured_adjustment",
                    "explanation",
                ],
            },
        },
    },
    "required": ["directives"],
}


SYSTEM_INSTRUCTION = """\
You are a strict operator-note interpreter for a campus energy optimizer.

Given 1 to 3 natural-language operator notes, return a JSON object with key
"directives" containing exactly one entry per note, in note_index order.

Supported directive types (use exactly one per note):
- solar_reduction         : usable solar fraction. factor = remaining fraction
                            (e.g. "80% reduction" -> factor 0.2).
- minimum_battery_reserve : raise battery floor. structured_adjustment has
                            "minimum_energy_kwh".
- no_charge_window        : battery must not charge in those hours.
- no_discharge_window     : battery must not discharge in those hours.
- max_grid_window         : cap grid_kwh in those hours.
- no_op                   : note is irrelevant. applies=false, adjustment=null.

Rules:
1. Hours are whole 0..23 integers. Time windows are START-INCLUSIVE, END-EXCLUSIVE:
   "1 PM to 3 PM" -> [13, 14]. "6 PM to 9 PM" -> [18, 19, 20].
2. factor is the fraction of solar STILL usable after reduction, not the
   reduction amount. An 80% reduction leaves 20%, so factor=0.2.
3. Hours must be unique, integers, ascending, between 0 and 23 inclusive.
4. If a note does not match any supported directive, emit no_op with
   applies=false and structured_adjustment=null.
5. Never invent new directive types.
6. Do not modify demand, solar forecasts, tariffs, or battery parameters.
7. Output ONLY the JSON object. No markdown, no commentary.
"""


def _build_user_prompt(operator_notes: list[str]) -> str:
    lines = ["Interpret these operator notes:", ""]
    for i, note in enumerate(operator_notes):
        lines.append(f"[note_index={i}] {note.strip()}")
    lines.append("")
    lines.append(
        'Return JSON: {"directives": [...]} with one entry per note_index, '
        "in ascending note_index order."
    )
    return "\n".join(lines)


class GeminiProvider(LLMProvider):
    """Gemini-backed implementation using structured JSON output."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        timeout_seconds: float = 25.0,
    ) -> None:
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        if not self._api_key:
            raise ValueError(
                "GEMINI_API_KEY is not set. Set it in .env or pass api_key=."
            )
        self._model = model or os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
        self._timeout = timeout_seconds
        self._client = genai.Client(api_key=self._api_key)

    @property
    def model_name(self) -> str:
        return self._model

    def interpret_notes(self, operator_notes: list[str]) -> LLMResult:
        if not 1 <= len(operator_notes) <= 3:
            raise ValueError("operator_notes must contain 1 to 3 non-empty strings")
        for i, note in enumerate(operator_notes):
            if not isinstance(note, str) or not note.strip():
                raise ValueError(f"operator_notes[{i}] must be a non-empty string")

        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            temperature=0.0,
            response_mime_type="application/json",
            response_schema=DIRECTIVES_RESPONSE_SCHEMA,
            max_output_tokens=2048,
        )

        logger.info(
            "calling Gemini model=%s notes=%d", self._model, len(operator_notes)
        )

        # Retry on transient 5xx with exponential backoff. Then optionally
        # fall back to a different model if the primary keeps failing.
        import time

        from google.genai.errors import ServerError

        models_to_try = [self._model]
        if self._model != "gemini-3.5-flash":
            models_to_try.append("gemini-3.5-flash")

        response = None
        for model_name in models_to_try:
            for attempt in range(4):
                try:
                    response = self._client.models.generate_content(
                        model=model_name,
                        contents=_build_user_prompt(operator_notes),
                        config=config,
                    )
                    break
                except ServerError as exc:
                    wait = 1.5 * (2**attempt)
                    logger.warning(
                        "Gemini %s 5xx (attempt %d), retrying in %.1fs: %s",
                        model_name,
                        attempt + 1,
                        wait,
                        str(exc)[:120],
                    )
                    time.sleep(wait)
                    continue
            if response is not None:
                if model_name != self._model:
                    logger.warning("Fell back from %s to %s", self._model, model_name)
                break
        if response is None:
            raise RuntimeError("Gemini model and fallback both returned 5xx")

        raw_text = (response.text or "").strip()
        if not raw_text:
            raise RuntimeError("Gemini returned an empty response body")

        raw_text = (response.text or "").strip()
        if not raw_text:
            raise RuntimeError("Gemini returned an empty response body")

        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Gemini returned non-JSON: {raw_text[:200]!r}"
            ) from exc

        if not isinstance(parsed, dict) or "directives" not in parsed:
            raise RuntimeError(
                f"Gemini output missing 'directives' key: {parsed!r}"
            )

        logger.info("Gemini returned %d directives", len(parsed["directives"]))
        return LLMResult(raw_text=raw_text, parsed=parsed)


class StaticProvider(LLMProvider):
    """Deterministic provider used by tests and offline reproduction.

    Returns a pre-canned directive payload. Useful for CI, local
    smoke tests without an API key, and unit-testing the guardrails.
    """

    def __init__(self, payload: dict[str, Any], model_name: str = "static") -> None:
        self._payload = payload
        self._model_name = model_name

    @property
    def model_name(self) -> str:
        return self._model_name

    def interpret_notes(self, operator_notes: list[str]) -> LLMResult:
        # Deep-copy so callers cannot mutate our test fixture.
        import copy

        return LLMResult(
            raw_text=json.dumps(self._payload),
            parsed=copy.deepcopy(self._payload),
        )
