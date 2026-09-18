"""Request schema for POST /optimize-energy."""
from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.common import HOURS_LEN, MAX_OPERATOR_NOTES, MIN_OPERATOR_NOTES


class HourData(BaseModel):
    """One hour of the planning horizon."""

    model_config = ConfigDict(extra="forbid")

    hour: Annotated[int, Field(ge=0, le=23)]
    demand_kwh: Annotated[float, Field(ge=0)]
    solar_kwh: Annotated[float, Field(ge=0)]
    tariff_bdt_per_kwh: Annotated[float, Field(ge=0)]


class BatterySpec(BaseModel):
    """Battery physical limits for the day."""

    model_config = ConfigDict(extra="forbid")

    capacity_kwh: Annotated[float, Field(gt=0)]
    initial_energy_kwh: Annotated[float, Field(ge=0)]
    minimum_energy_kwh: Annotated[float, Field(ge=0)]
    max_charge_kwh_per_hour: Annotated[float, Field(ge=0)]
    max_discharge_kwh_per_hour: Annotated[float, Field(ge=0)]


class OptimizeEnergyRequest(BaseModel):
    """Top-level request body."""

    model_config = ConfigDict(extra="forbid")

    scenario_id: Annotated[str, Field(min_length=1)]
    operator_notes: Annotated[
        list[str],
        Field(min_length=MIN_OPERATOR_NOTES, max_length=MAX_OPERATOR_NOTES),
    ]
    hours: Annotated[list[HourData], Field(min_length=HOURS_LEN, max_length=HOURS_LEN)]
    battery: BatterySpec

    @field_validator("operator_notes")
    @classmethod
    def _notes_non_empty(cls, v: list[str]) -> list[str]:
        for i, note in enumerate(v):
            if not isinstance(note, str) or not note.strip():
                raise ValueError(
                    f"operator_notes[{i}] must be a non-empty natural-language string"
                )
        return v

    @field_validator("hours")
    @classmethod
    def _hours_unique_and_sorted(cls, v: list[HourData]) -> list[HourData]:
        hours_seen = [h.hour for h in v]
        if sorted(hours_seen) != hours_seen:
            raise ValueError("hours must be sorted in ascending order")
        if len(set(hours_seen)) != HOURS_LEN:
            raise ValueError("hours must contain exactly 24 unique entries")
        if hours_seen != list(range(HOURS_LEN)):
            raise ValueError("hours must contain every hour from 0 to 23")
        return v

    @field_validator("battery")
    @classmethod
    def _battery_consistent(cls, v: BatterySpec) -> BatterySpec:
        if v.minimum_energy_kwh > v.capacity_kwh:
            raise ValueError("minimum_energy_kwh cannot exceed capacity_kwh")
        if v.initial_energy_kwh < v.minimum_energy_kwh:
            raise ValueError("initial_energy_kwh cannot be below minimum_energy_kwh")
        if v.initial_energy_kwh > v.capacity_kwh:
            raise ValueError("initial_energy_kwh cannot exceed capacity_kwh")
        return v
