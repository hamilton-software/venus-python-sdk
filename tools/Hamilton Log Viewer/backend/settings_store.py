"""JSON-file-backed store for the viewer's preferences: the VENUS host and recent files.

Same pattern as the Script Manager's settings_store.py: one flat dict, rewritten whole
under a lock on every change.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any

from backend.config import BackendConfig

MAX_RECENT_FILES = 10

DEFAULT_SETTINGS: dict[str, Any] = {
    # VENUS PC whose run history the "Recent VENUS runs" list reads ("localhost", "pc-name"
    # or "pc-name:port"; the Vector API's default port 42400 is assumed when none is given).
    "venus_host": "localhost",
    # Most recently opened log files, newest first.
    "recent_files": [],
}


class SettingsStore:
    def __init__(self, config: BackendConfig) -> None:
        self._config = config
        self._lock = threading.Lock()
        config.settings_file.parent.mkdir(parents=True, exist_ok=True)

    def _read(self) -> dict[str, Any]:
        try:
            data = json.loads(self._config.settings_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        return {**DEFAULT_SETTINGS, **(data if isinstance(data, dict) else {})}

    def _write(self, settings: dict[str, Any]) -> None:
        self._config.settings_file.write_text(json.dumps(settings, indent=2), encoding="utf-8")

    def get(self) -> dict[str, Any]:
        with self._lock:
            return self._read()

    def update(self, **changes: Any) -> dict[str, Any]:
        with self._lock:
            settings = self._read()
            settings.update({k: v for k, v in changes.items() if k in DEFAULT_SETTINGS})
            self._write(settings)
            return settings

    def add_recent_file(self, path: str) -> None:
        """Move *path* to the top. The same file under another spelling (case, slashes,
        a relative path) counts as the same entry; a copy in another folder does not."""
        path = _normalized(path)
        with self._lock:
            settings = self._read()
            recent = [p for p in settings["recent_files"] if isinstance(p, str) and _normalized(p).lower() != path.lower()]
            settings["recent_files"] = [path, *recent][:MAX_RECENT_FILES]
            self._write(settings)

    def remove_recent_file(self, path: str) -> dict[str, Any]:
        with self._lock:
            settings = self._read()
            target = _normalized(path).lower()
            settings["recent_files"] = [
                p for p in settings["recent_files"] if isinstance(p, str) and _normalized(p).lower() != target
            ]
            self._write(settings)
            return settings


def _normalized(path: str) -> str:
    return os.path.normpath(os.path.abspath(path))
