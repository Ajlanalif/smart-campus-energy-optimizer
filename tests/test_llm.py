"""Tests for the LLM provider layer."""
from __future__ import annotations

import json
import os

import pytest

from app.llm.provider import GeminiProvider, StaticProvider, _build_user_prompt


# ---------- pure helpers ---------- #

def test_user_prompt_includes_all_notes_in_order() -> None:
    notes = [
        "Wash panels 1 PM to 3 PM.",
        "Battery reserve 50 kWh from 6 to 9 PM.",
    ]
    text = _build_user_prompt(notes)
    assert "[note_index=0]" in text
    assert "[note_index=1]" in text
    # Order must match input order.
    idx0 = text.find("[note_index=0]")
    idx1 = text.find("[note_index=1]")
    assert idx0 < idx1


def test_user_prompt_ends_with_return_json_instruction() -> None:
    text = _build_user_prompt(["hi"])
    assert "directives" in text


# ---------- static provider ---------- #

def test_static_provider_returns_payload() -> None:
    payload = {
        "directives": [
            {
                "note_index": 0,
                "applies": False,
                "directive_type": "no_op",
                "structured_adjustment": None,
                "explanation": "irrelevant",
            }
        ]
    }
    sp = StaticProvider(payload=payload)
    result = sp.interpret_notes(["anything"])
    assert result.parsed == payload
    assert sp.model_name == "static"


def test_static_provider_deep_copies_payload() -> None:
    payload = {"directives": [{"note_index": 0, "applies": False, "directive_type": "no_op", "structured_adjustment": None, "explanation": "x"}]}
    sp = StaticProvider(payload=payload)
    result = sp.interpret_notes(["y"])
    result.parsed["directives"][0]["explanation"] = "MUTATED"
    # Original payload must be untouched.
    assert payload["directives"][0]["explanation"] == "x"


# ---------- gemini provider: validation ---------- #

def test_gemini_provider_requires_api_key() -> None:
    saved = os.environ.pop("GEMINI_API_KEY", None)
    try:
        with pytest.raises(ValueError, match="GEMINI_API_KEY"):
            GeminiProvider(api_key="")
    finally:
        if saved is not None:
            os.environ["GEMINI_API_KEY"] = saved


def test_gemini_provider_rejects_empty_note_list() -> None:
    p = GeminiProvider(api_key="dummy")
    with pytest.raises(ValueError, match="1 to 3"):
        p.interpret_notes([])


def test_gemini_provider_rejects_blank_note() -> None:
    p = GeminiProvider(api_key="dummy")
    with pytest.raises(ValueError, match="non-empty"):
        p.interpret_notes(["ok", "   "])


def test_gemini_provider_rejects_too_many_notes() -> None:
    p = GeminiProvider(api_key="dummy")
    with pytest.raises(ValueError, match="1 to 3"):
        p.interpret_notes(["a", "b", "c", "d"])


# ---------- live gemini smoke (skipped if no key) ---------- #

LIVE = pytest.mark.skipif(
    not os.environ.get("GEMINI_API_KEY"),
    reason="GEMINI_API_KEY not set; skipping live Gemini test",
)


@LIVE
def test_gemini_live_returns_valid_directives_payload() -> None:
    p = GeminiProvider()
    notes = [
        "Facilities will wash the rooftop solar panels from noon until 2 PM. "
        "During cleaning, usable solar should be treated as roughly 25% of the forecast.",
    ]
    result = p.interpret_notes(notes)
    assert "directives" in result.parsed
    assert isinstance(result.parsed["directives"], list)
    assert len(result.parsed["directives"]) == 1
    d = result.parsed["directives"][0]
    assert d["note_index"] == 0
    assert d["directive_type"] == "solar_reduction"
    assert d["applies"] is True
    assert d["structured_adjustment"]["factor"] == pytest.approx(0.25, abs=0.01)
    assert 12 in d["structured_adjustment"]["hours"]
    assert 13 in d["structured_adjustment"]["hours"]
