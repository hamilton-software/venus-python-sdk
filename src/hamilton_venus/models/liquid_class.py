"""Liquid class models used by aspirate and dispense commands."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class LiquidClass(BaseModel):
    """Liquid class definition serialized into command payloads."""

    model_config = ConfigDict(populate_by_name=True)

    name: str
    aspir_flow_rate: float | None = Field(None, alias="aspirFlowRate")
    disp_flow_rate: float | None = Field(None, alias="dispFlowRate")
    cut_off_speed: float | None = Field(None, alias="cutOffSpeed")
    stop_back_volume: float | None = Field(None, alias="stopBackVolume")

    def to_dict(self) -> dict[str, Any]:
        """Return the wire-format representation without unset optional fields."""
        return self.model_dump(by_alias=True, exclude_none=True)


__all__ = ["LiquidClass"]
