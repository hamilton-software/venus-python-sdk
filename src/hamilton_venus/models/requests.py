"""Request models for the Hamilton VENUS Python SDK."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class LoadMethodRequest(BaseModel):
    """Request body for ``PUT /api/vector/v3/execution/load``."""

    model_config = ConfigDict(populate_by_name=True)

    file_path: str = Field(
        ...,
        alias="filePath",
        description="Fully-qualified path to the .hsl method file.",
    )
    simulation: bool = Field(False, description="If True, the instrument is simulated.")
    parent_window_handle: int = Field(
        0,
        alias="parentWindowHandle",
        description="Parent window handle (0 for headless/SDK use).",
    )
