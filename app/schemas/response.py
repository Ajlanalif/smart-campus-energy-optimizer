"""Response schema for POST /optimize-energy."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import HOURS_LEN
from app.schemas.interpretation import DirectiveInterpretation


BatteryAction = Literal["charge", "discharge", "idle"]


class HourlyPlanEntry(BaseModel):
    """One row in the final 24-hour schedule."""

    model_config = ConfigDict(extra="forbid")

    hour: Annotated[int, Field(ge=0, le=23)]
    grid_kwh: Annotated[float, Field(ge=0)]
    solar_used_kwh: Annotated[float, Field(ge=0)]
    battery_action: BatteryAction
    battery_kwh: Annotated[float, Field(ge=0)]  # charge (+) or discharge (-) magnitude
    battery_energy_after_kwh: Annotated[float, Field(ge=0)]


class OptimizeEnergyResponse(BaseModel):
    """Top-level response."""

    model_config = ConfigDict(extra="forbid")

    scenario_id: Annotated[str, Field(min_length=1)]
    directive_interpretation: Annotated[
        list[DirectiveInterpretation], Field(min_length=1, max_length=3)
    ]
    hourly_plan: Annotated[
        list[HourlyPlanEntry], Field(min_length=HOURS_LEN, max_length=HOURS_LEN)
    ]
    total_grid_kwh: Annotated[float, Field(ge=0)]
    total_cost_bdt: Annotated[float, Field(ge=0)]
    peak_grid_kwh: Annotated[float, Field(ge=0)]
    plan_summary: Annotated[str, Field(min_length=1)]
