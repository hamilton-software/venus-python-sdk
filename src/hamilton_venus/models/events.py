"""Event and response models for the Hamilton VENUS Python SDK."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from hamilton_venus.models.enums import _EXECUTOR_EVENT_STR_MAP, ExecutorEvent


class CmdResult(BaseModel):
    """Standard response body returned by most execution endpoints."""

    model_config = ConfigDict(populate_by_name=True)

    result: bool
    message: str = ""
    reset_run_executor: bool = Field(False, alias="resetRunExecutor")


class RuntimeStatusEvent(BaseModel):
    """Payload of the ``NewRuntimeStatus`` SignalR event.

    The ``executor_event`` field may arrive as an integer or a string
    (e.g. ``"Running"``) depending on the server's JSON serialiser config.
    Both forms are accepted and normalized to an integer internally.
    """

    model_config = ConfigDict(populate_by_name=True)

    executor_event: int = Field(
        ...,
        alias="executorEvent",
        description="Normalized integer value of the ExecutorEvent enum.",
    )
    message: str = Field("", description="Optional status message.")

    @field_validator("executor_event", mode="before")
    @classmethod
    def _coerce_executor_event(cls, v: Any) -> int:
        if isinstance(v, int):
            return v
        if isinstance(v, str):
            key = v.strip().lower().replace("_", "")
            return _EXECUTOR_EVENT_STR_MAP.get(key, 0)
        return int(v)

    @property
    def event(self) -> ExecutorEvent:
        return ExecutorEvent.from_api_value(self.executor_event)


class ProgressChangedEvent(BaseModel):
    """Payload of the ``OnProgressChanged`` SignalR event."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    method_name: str = Field("", alias="methodName")
    progress_percentage: float = Field(0.0, alias="progressPercentage")


class RunMessageQueuedEvent(BaseModel):
    """Payload of the ``OnRunMessageQueued`` SignalR event."""

    model_config = ConfigDict(populate_by_name=True)

    channel: str = ""
    message_id: str = Field("", alias="messageId")
    timestamp: datetime | None = None
    queue_depth: int = Field(0, alias="queueDepth")


class CommandCommunicationData(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str = ""
    category: str = ""
    command: str = ""
    status: str = ""


class CommandCommunicationMessage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    channel: str = "communication"
    has_message: bool = Field(False, alias="hasMessage")
    message_id: str = Field("", alias="messageId")
    timestamp: str = ""
    data: CommandCommunicationData = Field(default_factory=CommandCommunicationData)

    @field_validator("message_id", "timestamp", mode="before")
    @classmethod
    def _coerce_nullable_str(cls, value: Any) -> Any:
        if value is None:
            return ""
        return value


class LabwarePositionStateChangedEvent(BaseModel):
    """Payload of the ``LabwarePositionStateChanged`` SignalR event."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    labware_id: str = Field("", alias="labwareId")
    position_id: str = Field("", alias="positionId")
    state: int = 0


class LabwareLoadedStateChangedEvent(BaseModel):
    """Payload of the ``LabwareLoadedStateChanged`` SignalR event."""

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    labware_id: str = Field("", alias="labwareId")
