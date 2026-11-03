"""Backend-level settings for the Log Viewer app."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Where VENUS -- and the SDK's run logs -- write by default.
VENUS_LOG_FILES = Path(r"C:\Program Files (x86)\HAMILTON\LogFiles")


@dataclass(frozen=True)
class BackendConfig:
    host: str = "127.0.0.1"
    port: int = 8738
    static_dir: Path = Path(__file__).parent / "static"
    # Settings live inside the app folder, like the sibling apps keep their state.
    data_dir: Path = Path(__file__).parent / "data"
    # The file picker opens in LogFiles when it exists, else the SDK root (three levels up).
    default_browse_dir: Path = (
        VENUS_LOG_FILES
        if VENUS_LOG_FILES.is_dir()
        else Path(__file__).resolve().parents[3 if Path(__file__).resolve().parents[2].name == "tools" else 2]
    )
    # Opened logs kept in memory, most recent first; older ones are dropped.
    max_open_logs: int = 5

    @property
    def settings_file(self) -> Path:
        return self.data_dir / "settings.json"


def load_backend_config() -> BackendConfig:
    port = int(os.environ.get("HAMILTON_LOG_VIEWER_PORT", "8738"))
    host = os.environ.get("HAMILTON_LOG_VIEWER_HOST", "127.0.0.1")
    return BackendConfig(host=host, port=port)
