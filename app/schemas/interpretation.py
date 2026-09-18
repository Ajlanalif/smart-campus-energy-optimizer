"""Directive interpretation shapes (LLM output, validated)."""
from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ---------- Structured adjustments ---------- #

class SolarReductionAdjustment(BaseModel):
    """`solar_reduction`: factor is the usable fraction remaining."""

    model_config = ConfigDict(extra="forbid")

    hours: Annotated[list[int], Field(min_length=1)]
    factor: Annotated[float, Field(ge=0.0, le=1.0)]


class MinimumBatteryReserveAdjustment(BaseModel):
    """`minimum_battery_reserve`: raise the floor on battery_energy_after_kwh."""

    model_config = ConfigDict(extra="forbid")

    hours: Annotated[list[int], Field(min_length=1)]
    minimum_energy_kwh: Annotated[float, Field(ge=0)]


class HoursOnlyAdjustment(BaseModel):
    """For `no_charge_window` and `no_discharge_window`."""

    model_config = ConfigDict(extra="forbid")

    hours: Annotated[list[int], Field(min_length=1)]


class MaxGridWindowAdjustment(BaseModel):
    """`max_grid_window`: cap grid_kwh per hour."""

    model_config = ConfigDict(extra="forbid")

    hours: Annotated[list[int], Field(min_length=1)]
    max_grid_kwh: Annotated[float, Field(ge=0)]


DirectiveType = Literal[
    "solar_reduction",
    "minimum_battery_reserve",
    "no_charge_window",
    "no_discharge_window",
    "max_grid_window",
    "no_op",
]


class DirectiveInterpretation(BaseModel):
    """One per operator note, in note_index order."""

    model_config = ConfigDict(extra="forbid")

    note_index: Annotated[int, Field(ge=0)]
    applies: bool
    directive_type: DirectiveType
    structured_adjustment: dict[str, Any] | None
    explanation: Annotated[str, Field(min_length=1)]

    @model_validator(mode="after")
    def _check_applies_vs_adjustment(self) -> "DirectiveInterpretation":
        if self.directive_type == "no_op":
            if self.applies is not False:
                raise ValueError("no_op requires applies=false")
            if self.structured_adjustment is not None:
                raise ValueError("no_op requires structured_adjustment=null")
        else:
            if self.applies is not True:
                raise ValueError(f"{self.directive_type} requires applies=true")
            if not isinstance(self.structured_adjustment, dict):
                raise ValueError(
                    f"{self.directive_type} requires a structured_adjustment object"
                )
        return self
