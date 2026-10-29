"""Pydantic model for structured run log entries."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel


class RunLogEntry(BaseModel):
    """A single entry in the structured JSON run log."""

    timestamp: datetime
    sequence: int
    source: Literal["WebAPI", "SignalR", "Console", "SDK"]
    direction: Literal["Out", "In"]
    type: str
    payload: dict[str, Any]
