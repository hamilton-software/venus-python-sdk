"""Command request/response envelope models for the Hamilton VENUS Python SDK."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class CommandRequest(BaseModel):
    """JSON request envelope sent to the liquid handler software."""

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(default_factory=lambda: str(uuid4()))
    category: str
    action_name: str = Field(..., alias="actionName")
    parameters: dict[str, Any] = Field(default_factory=dict)


class CommandResponse(BaseModel):
    """JSON response envelope returned by the liquid handler software.

    Unknown response keys are accepted and preserved for forward compatibility
    because VENUS may add metadata before the SDK model is updated. Consumers
    should continue to use the documented envelope fields for control flow and
    inspect ``model_extra`` only when they need server-specific or newly added
    values. Extra fields are preserved when the model is serialized again.
    """

    model_config = ConfigDict(populate_by_name=True, extra="allow")

    id: str = Field("", validation_alias=AliasChoices("id", "actionId"))
    category: str = ""
    action_name: str = Field("", alias="actionName")
    parameters: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = Field(None, alias="createdAt")
    started_at: datetime | None = Field(None, alias="startedAt")
    completed_at: datetime | None = Field(None, alias="completedAt")
    status: str = ""
    return_status: str = Field("", alias="returnStatus")
    return_code: int = Field(0, alias="returnCode")
    return_parameters: Any = Field(default_factory=dict, alias="returnParameters")

    @property
    def success(self) -> bool:
        return self.return_code == 0 and self.return_status == "Success"


__all__ = ["CommandRequest", "CommandResponse"]
