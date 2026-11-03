"""Backend-level settings for the SDK Studio app."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BackendConfig:
    host: str = "127.0.0.1"
    port: int = 8740
    static_dir: Path = Path(__file__).parent / "static"
    # Shipped command overlays (label, group, widget hints); the SDK catalog supplies the rest.
    command_defs_dir: Path = Path(__file__).parent / "command_defs"
    # Settings and saved flows live inside the app folder, like the sibling apps keep their state.
    data_dir: Path = Path(__file__).parent / "data"
    # VENUS stores each saved deck layout as <name>.json here.
    deck_layout_dir: Path = Path(r"C:\Program Files (x86)\HAMILTON\SDK\layout")
    # Port of the MCP spoke Studio drives. Defaults to the local spoke's own default.
    spoke_port: int = 8000

    @property
    def settings_file(self) -> Path:
        return self.data_dir / "settings.json"

    @property
    def flows_dir(self) -> Path:
        return self.data_dir / "flows"

    @property
    def user_command_defs_dir(self) -> Path:
        """Overlays a user adds without touching the shipped ones; loaded after them."""
        return self.data_dir / "command_defs"


def load_backend_config() -> BackendConfig:
    port = int(os.environ.get("HAMILTON_SDK_STUDIO_PORT", "8740"))
    host = os.environ.get("HAMILTON_SDK_STUDIO_HOST", "127.0.0.1")
    spoke_port = int(os.environ.get("HAMILTON_SDK_STUDIO_SPOKE_PORT", "8000"))
    return BackendConfig(host=host, port=port, spoke_port=spoke_port)
