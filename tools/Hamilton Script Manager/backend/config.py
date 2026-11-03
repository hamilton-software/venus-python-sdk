"""Backend-level settings for the script manager app (not part of the hamilton_venus SDK config)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BackendConfig:
    host: str = "127.0.0.1"
    port: int = 8736
    static_dir: Path = Path(__file__).parent / "static"
    # Shortcut metadata and read-only script copies live under here -- kept
    # inside the app folder (not a user AppData path) so the whole install is
    # self-contained, matching how the sibling apps keep their state.
    data_dir: Path = Path(__file__).parent / "data"
    default_simulate: bool = True
    # Default directory the "browse for a script" file picker opens to -- the SDK
    # root, three levels up from this file (backend/ -> app folder -> SDK root,
    # whether that's a dev checkout or an installed "Hamilton Script Manager\"
    # folder next to .venv\, since the SDK can be installed anywhere).
    # (In the dev layout the app sits one level deeper, under tools\.)
    default_browse_dir: Path = Path(__file__).resolve().parents[
        3 if Path(__file__).resolve().parents[2].name == "tools" else 2
    ]
    # Finalized SDK run logs are dropped flat in here (no per-run subfolder) --
    # same shared, already-VENUS-managed location demo_app points its
    # WorkflowBackendConfig.run_log_root at, which has its own retention/cleanup
    # so logs don't build up under the app's own data_dir indefinitely.
    run_log_root: Path = Path(r"C:\Program Files (x86)\HAMILTON\LogFiles")

    @property
    def shortcuts_file(self) -> Path:
        return self.data_dir / "shortcuts.json"

    @property
    def consumables_file(self) -> Path:
        return self.data_dir / "consumables.json"

    @property
    def settings_file(self) -> Path:
        return self.data_dir / "settings.json"

    @property
    def scripts_dir(self) -> Path:
        return self.data_dir / "scripts"


def load_backend_config() -> BackendConfig:
    port = int(os.environ.get("HAMILTON_SCRIPT_MANAGER_PORT", "8736"))
    host = os.environ.get("HAMILTON_SCRIPT_MANAGER_HOST", "127.0.0.1")
    return BackendConfig(host=host, port=port)
