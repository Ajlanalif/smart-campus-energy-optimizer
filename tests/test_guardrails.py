"""Tests for the deterministic guardrails."""
from __future__ import annotations

import pytest

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
from app.guardrails.validator import validate_directives


# ---------- helpers ---------- #

def _good_entry(
    note_index: int = 0,
    directive_type: str = "no_op",
    **overrides,
) -> dict:
    base = {
        "note_index": note_index,
        "applies": directive_type != "no_op",
        "directive_type": directive_type,
        "structured_adjustment": None if directive_type == "no_op" else {"hours": [13, 14]},
        "explanation": "test",
    }
    if directive_type == "solar_reduction":
        base["structured_adjustment"] = {"hours": [13, 14], "factor": 0.25}
    elif directive_type == "minimum_battery_reserve":
        base["structured_adjustment"] = {"hours": [18, 19, 20], "minimum_energy_kwh": 30.0}
    elif directive_type == "no_charge_window":
        base["structured_adjustment"] = {"hours": [12, 13, 14]}
    elif directive_type == "no_discharge_window":
        base["structured_adjustment"] = {"hours": [18, 19]}
    elif directive_type == "max_grid_window":
        base["structured_adjustment"] = {"hours": [18, 19, 20], "max_grid_kwh": 100.0}
    base.update(overrides)
    return base


# ---------- top-level shape ---------- #

def test_payload_must_be_dict() -> None:
    with pytest.raises(BadLLMOutput):
        validate_directives([], n_notes=1, battery_capacity_kwh=100)


def test_payload_must_contain_directives_key() -> None:
    with pytest.raises(BadLLMOutput):
        validate_directives({"foo": "bar"}, n_notes=1, battery_capacity_kwh=100)


def test_directives_must_be_list() -> None:
    with pytest.raises(BadLLMOutput):
        validate_directives({"directives": "not a list"}, n_notes=1, battery_capacity_kwh=100)


def test_n_notes_too_small_rejected() -> None:
    with pytest.raises(BadLLMOutput):
        validate_directives({"directives": []}, n_notes=0, battery_capacity_kwh=100)


def test_n_notes_too_large_rejected() -> None:
    payload = {"directives": [_good_entry(i) for i in range(4)]}
    with pytest.raises(BadLLMOutput):
        validate_directives(payload, n_notes=4, battery_capacity_kwh=100)


def test_count_mismatch_rejected() -> None:
    payload = {"directives": [_good_entry(0), _good_entry(1)]}
    with pytest.raises(NoteMappingError):
        validate_directives(payload, n_notes=1, battery_capacity_kwh=100)


def test_duplicate_note_index_rejected() -> None:
    payload = {
        "directives": [
            _good_entry(0),
            _good_entry(0),  # duplicate
        ]
    }
    with pytest.raises(NoteMappingError):
        validate_directives(payload, n_notes=2, battery_capacity_kwh=100)


def test_missing_note_index_field_rejected() -> None:
    payload = {"directives": [{"applies": False, "directive_type": "no_op", "structured_adjustment": None, "explanation": "x"}]}
    with pytest.raises(NoteMappingError):
        validate_directives(payload, n_notes=1, battery_capacity_kwh=100)


def test_note_index_wrong_type_rejected() -> None:
    payload = {"directives": [{**_good_entry(0), "note_index": "zero"}]}
    with pytest.raises(NoteMappingError):
        validate_directives(payload, n_notes=1, battery_capacity_kwh=100)


def test_out_of_order_note_index_rejected() -> None:
    payload = {
        "directives": [
            _good_entry(1),
            _good_entry(0),  # out of order
        ]
    }
    with pytest.raises(NoteMappingError):
        validate_directives(payload, n_notes=2, battery_capacity_kwh=100)


# ---------- directive_type whitelist ---------- #

def test_unknown_directive_type_rejected() -> None:
    payload = {"directives": [_good_entry(0, "made_up_directive")]}
    with pytest.raises(UnknownDirectiveType):
        validate_directives(payload, n_notes=1, battery_capacity_kwh=100)


def test_missing_directive_type_rejected() -> None:
    payload = {
        "directives": [
            {
                "note_index": 0,
                "applies": True,
                "structured_adjustment": {"hours": [1]},
                "explanation": "x",
            }
        ]
    }
    with pytest.raises(BadLLMOutput):
        validate_directives(payload, n_notes=1, battery_capacity_kwh=100)


# ---------- applies / adjustment semantics ---------- #

def test_no_op_with_applies_true_rejected() -> None:
    payload = {"directives": [_good_entry(0, "no_op", applies=True)]}
    with pytest.raises(AppliesAdjustmentMismatch):
        validate_directives(payload, n_notes=1, battery_capacity_kwh=100)


def test_no_op_with_non_null_adjustment_rejected() -> None:
    payload = {
        "directives": [
            _good_entry(0, "no_op", structured_adjustment={"hours": [1]})
        ]
    }
    with pytest.raises(AppliesAdjustmentMismatch):
        validate_directives(payload, n_notes=1, battery_capacity_kwh=100)


def test_real_directive_with_applies_false_rejected() -> None:
    payload = {"directives": [_good_entry(0, "solar_reduction", applies=False)]}
    with pytest.raises(AppliesAdjustmentMismatch):
        validate_directives(payload, n_notes=1, battery_capacity_kwh=100)


def test_real_directive_with_null_adjustment_rejected() -> None:
    payload = {"directives": [_good_entry(0, "solar_reduction", structured_adjustment=None)]}
    with pytest.raises(AppliesAdjustmentMismatch):
        validate_directives(payload, n_notes=1, battery_capacity_kwh=100)


# ---------- explanation ---------- #

def test_empty_explanation_rejected() -> None:
    payload = {"directives": [_good_entry(0, "no_op", explanation="   ")]}
    with pytest.raises(BadLLMOutput):
        validate_directives(payload, n_notes=1, battery_capacity_kwh=100)


def test_non_string_explanation_rejected() -> None:
    payload = {"directives": [_good_entry(0, "no_op", explanation=42)]}
    with pytest.raises(BadLLMOutput):
        validate_directives(payload, n_notes=1, battery_capacity_kwh=100)


# ---------- hours validation ---------- #

def test_hours_empty_rejected() -> None:
    payload = {"directives": [_good_entry(0, "solar_reduction", structured_adjustment={"hours": [], "factor": 0.5})]}
    with pytest.raises(InvalidHours):
        validate_directives(payload, n_notes=1, battery_capacity_kwh=100)


def test_hours_not_a_list_rejected() -> None:
    payload = {"directives": [_good_entry(0, "solar_reduction", structured_adjustment={"hours": "13-14", "factor": 0.5})]}
    with pytest.raises(InvalidHours):
        validate_directives(payload, n_notes=1, battery_capacity_kwh=100)


def test_hours_non_integer_rejected() -> None:
    payload = {"directives": [_good_entry(0, "solar_reduction", structured_adjustment={"hours": [13.5], "factor": 0.5})]}
    with pytest.raises(InvalidHours):
        validate_directives(payload, n_notes=1, battery_capacity_kwh=100)


def test_hours_out_of_range_rejected() -> None:
    payload = {"directives": [_good_entry(0, "solar_reduction", structured_adjustment={"hours": [13, 24], "factor": 0.5})]}
    with pytest.raises(InvalidHours):
        validate_directives(payload, n_notes=1, battery_capacity_kwh=100)


def test_hours_negative_rejected() -> None:
    payload = {"directives": [_good_entry(0, "solar_reduction", structured_adjustment={"hours": [-1], "factor": 0.5})]}
    with pytest.raises(InvalidHours):
        validate_directives(payload, n_notes=1, battery_capacity_kwh=100)


def test_hours_unsorted_rejected() -> None:
    payload = {"directives": [_good_entry(0, "solar_reduction", structured_adjustment={"hours": [14, 13], "factor": 0.5})]}
    with pytest.raises(InvalidHours):
        validate_directives(payload, n_notes=1, battery_capacity_kwh=100)


def test_hours_duplicate_rejected() -> None:
    payload = {"directives": [_good_entry(0, "solar_reduction", structured_adjustment={"hours": [13, 13], "factor": 0.5})]}
    with pytest.raises(InvalidHours):
        validate_directives(payload, n_notes=1, battery_capacity_kwh=100)


def test_hours_bool_rejected() -> None:
    payload = {"directives": [_good_entry(0, "solar_reduction", structured_adjustment={"hours": [True], "factor": 0.5})]}
    with pytest.raises(InvalidHours):
        validate_directives(payload, n_notes=1, battery_capacity_kwh=100)


# ---------- solar_reduction numeric ---------- #

def test_solar_factor_negative_rejected() -> None:
    payload = {"directives": [_good_entry(0, "solar_reduction", structured_adjustment={"hours": [13], "factor": -0.1})]}
    with pytest.raises(InvalidNumericRange):
        validate_directives(payload, n_notes=1, battery_capacity_kwh=100)


def test_solar_factor_above_one_rejected() -> None:
    payload = {"directives": [_good_entry(0, "solar_reduction", structured_adjustment={"hours": [13], "factor": 1.5})]}
    with pytest.raises(InvalidNumericRange):
        validate_directives(payload, n_notes=1, battery_capacity_kwh=100)


def test_solar_factor_nan_rejected() -> None:
    payload = {"directives": [_good_entry(0, "solar_reduction", structured_adjustment={"hours": [13], "factor": float("nan")})]}
    with pytest.raises(InvalidNumericRange):
        validate_directives(payload, n_notes=1, battery_capacity_kwh=100)


def test_solar_factor_non_numeric_rejected() -> None:
    payload = {"directives": [_good_entry(0, "solar_reduction", structured_adjustment={"hours": [13], "factor": "0.5"})]}
    with pytest.raises(InvalidNumericRange):
        validate_directives(payload, n_notes=1, battery_capacity_kwh=100)


# ---------- minimum_battery_reserve numeric ---------- #

def test_reserve_negative_rejected() -> None:
    payload = {"directives": [_good_entry(0, "minimum_battery_reserve", structured_adjustment={"hours": [18], "minimum_energy_kwh": -5})]}
    with pytest.raises(InvalidNumericRange):
        validate_directives(payload, n_notes=1, battery_capacity_kwh=100)


def test_reserve_above_capacity_rejected() -> None:
    payload = {"directives": [_good_entry(0, "minimum_battery_reserve", structured_adjustment={"hours": [18], "minimum_energy_kwh": 150})]}
    with pytest.raises(InvalidNumericRange):
        validate_directives(payload, n_notes=1, battery_capacity_kwh=100)


# ---------- max_grid_window numeric ---------- #

def test_max_grid_negative_rejected() -> None:
    payload = {"directives": [_good_entry(0, "max_grid_window", structured_adjustment={"hours": [18], "max_grid_kwh": -1})]}
    with pytest.raises(InvalidNumericRange):
        validate_directives(payload, n_notes=1, battery_capacity_kwh=100)


def test_max_grid_non_numeric_rejected() -> None:
    payload = {"directives": [_good_entry(0, "max_grid_window", structured_adjustment={"hours": [18], "max_grid_kwh": "100"})]}
    with pytest.raises(InvalidNumericRange):
        validate_directives(payload, n_notes=1, battery_capacity_kwh=100)


# ---------- required / extra fields ---------- #

def test_missing_factor_in_solar_reduction_rejected() -> None:
    payload = {"directives": [_good_entry(0, "solar_reduction", structured_adjustment={"hours": [13]})]}
    with pytest.raises(MissingAdjustmentField):
        validate_directives(payload, n_notes=1, battery_capacity_kwh=100)


def test_extra_field_in_no_op_rejected() -> None:
    # no_op with non-null adjustment triggers the applies/adjustment contract
    # check first (most specific failure).
    payload = {"directives": [_good_entry(0, "no_op", structured_adjustment={"hours": [13]})]}
    with pytest.raises(AppliesAdjustmentMismatch):
        validate_directives(payload, n_notes=1, battery_capacity_kwh=100)


def test_extra_field_in_solar_reduction_rejected() -> None:
    payload = {"directives": [_good_entry(0, "solar_reduction", structured_adjustment={"hours": [13], "factor": 0.5, "max_grid_kwh": 100})]}
    with pytest.raises(ExtraAdjustmentField):
        validate_directives(payload, n_notes=1, battery_capacity_kwh=100)


# ---------- happy paths ---------- #

def test_no_op_happy_path() -> None:
    payload = {"directives": [_good_entry(0, "no_op")]}
    out = validate_directives(payload, n_notes=1, battery_capacity_kwh=100)
    assert len(out) == 1
    assert out[0].directive_type == "no_op"
    assert out[0].applies is False
    assert out[0].structured_adjustment is None


def test_solar_reduction_happy_path() -> None:
    payload = {"directives": [_good_entry(0, "solar_reduction")]}
    out = validate_directives(payload, n_notes=1, battery_capacity_kwh=100)
    assert out[0].applies is True
    assert out[0].structured_adjustment == {"hours": [13, 14], "factor": 0.25}


def test_three_notes_all_different_types() -> None:
    payload = {
        "directives": [
            _good_entry(0, "solar_reduction"),
            _good_entry(1, "no_charge_window"),
            _good_entry(2, "no_op"),
        ]
    }
    out = validate_directives(payload, n_notes=3, battery_capacity_kwh=100)
    assert [d.directive_type for d in out] == [
        "solar_reduction",
        "no_charge_window",
        "no_op",
    ]


def test_paraphrase_solar_reduction_factor_zero_point_two() -> None:
    """Equivalent semantics: '80% reduction' must be 0.2 factor after LLM mapping."""
    payload = {
        "directives": [
            {
                "note_index": 0,
                "applies": True,
                "directive_type": "solar_reduction",
                "structured_adjustment": {"hours": [13, 14], "factor": 0.2},
                "explanation": "80% reduction during 1-3 PM",
            }
        ]
    }
    out = validate_directives(payload, n_notes=1, battery_capacity_kwh=100)
    assert out[0].structured_adjustment == {"hours": [13, 14], "factor": 0.2}


def test_factor_boundary_zero_accepted() -> None:
    payload = {"directives": [_good_entry(0, "solar_reduction", structured_adjustment={"hours": [13], "factor": 0.0})]}
    out = validate_directives(payload, n_notes=1, battery_capacity_kwh=100)
    assert out[0].structured_adjustment["factor"] == 0.0


def test_factor_boundary_one_accepted() -> None:
    payload = {"directives": [_good_entry(0, "solar_reduction", structured_adjustment={"hours": [13], "factor": 1.0})]}
    out = validate_directives(payload, n_notes=1, battery_capacity_kwh=100)
    assert out[0].structured_adjustment["factor"] == 1.0
