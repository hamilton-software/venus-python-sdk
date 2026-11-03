"""Data shapes for run-monitoring: sample/well status, liquid-level readings,
and TADM results. All state is in-memory, scoped to one WorkflowSession/
ExecutionEngine pairing -- see sample_tracker.py.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SampleWellMapping(BaseModel):
    sample_id: str
    plate_id: str
    well: str
    status: Literal["pending", "in_progress", "complete", "error"] = "pending"


class LiquidLevelReading(BaseModel):
    position: str
    channel: int
    liquid_level_mm: float
    liquid_volume_ul: float
    timestamp: str


class TadmResult(BaseModel):
    position: str
    channel: int
    step_type_name: str
    curve_flagged: bool
    error_code: str | None = None
    # Raw curve points (timeMs/pressure), when the instrument populated them.
    # Treat as best-effort telemetry, not guaranteed non-empty -- see tadm.py.
    curve_points: list[dict[str, int]] = Field(default_factory=list)


class SampleEvent(BaseModel):
    type: Literal["scan", "status_change", "error"]
    sample_id: str | None = None
    detail: str
    timestamp: str
