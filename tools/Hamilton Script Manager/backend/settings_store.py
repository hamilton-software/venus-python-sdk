"""JSON-file-backed store for app-wide user preferences (Settings modal).

Mirrors shortcuts_store.py/consumables_store.py's pattern: no database,
single-writer, rewritten whole under a lock on every mutation. A single flat
dict rather than a list of records -- there's only ever one settings object.
"""

from __future__ import annotations

import json
import threading
from typing import Any

from backend.config import BackendConfig

DEFAULT_SETTINGS: dict[str, Any] = {
    # When a shortcut's source file has changed since its snapshot was last
    # synced (see shortcuts_store.py's is_stale), warn with a modal at the
    # moment the operator selects it rather than silently loading the stale copy.
    "warn_on_stale_shortcut": True,
    # If a shortcut is stale, re-sync it automatically instead of warning --
    # takes priority over warn_on_stale_shortcut when both are enabled, since
    # there's nothing left to ask once the snapshot is refreshed on its own.
    "auto_resync_shortcuts": False,
    # Fallback "warn below N tips remaining" applied to a tip pool the operator
    # has never explicitly set a threshold for (see consumables_store.py's
    # own now-superseded DEFAULT_LOW_THRESHOLD and script_runner.py's
    # _DEFAULT_TIP_THRESHOLD, both previously hardcoded to this same value).
    "default_tip_warning_threshold": 10,
    "reservoir_warning_percent": 10,
    # Scrape VENUS's firmware COM trace (.trc) during a run and stream it into
    # the Terminal under the (hidden-by-default) "COM Trace" filter. On by
    # default; no Settings-modal control -- edit data/settings.json to change.
    "com_trace_enabled": True,
    # Directory VENUS writes its .trc files to. "" -> the SDK default
    # C:\Program Files (x86)\Hamilton\Logfiles.
    "com_trace_logfiles_dir": "",
    # Run scripts with the SDK's DEBUG logging and VENUS's runtime trace printed to
    # the Terminal. Every line is relayed through this backend, which measurably
    # slows instrument commands; off keeps INFO-level SDK messages only. The run log
    # (*_SdkRunLog.json) is captured either way.
    "debug_logging_enabled": True,
}


class SettingsStore:
    def __init__(self, config: BackendConfig) -> None:
        self._config = config
        self._lock = threading.Lock()
        config.settings_file.parent.mkdir(parents=True, exist_ok=True)
        if not config.settings_file.is_file():
            self._write(dict(DEFAULT_SETTINGS))

    def _read(self) -> dict[str, Any]:
        try:
            data = json.loads(self._config.settings_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        # Merge over defaults rather than replace, so a settings.json saved by
        # an older version of this app (missing a key this version added)
        # still gets a sane value for the new key instead of a KeyError.
        merged = dict(DEFAULT_SETTINGS)
        merged.update(data)
        return merged

    def _write(self, data: dict[str, Any]) -> None:
        tmp = self._config.settings_file.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(self._config.settings_file)

    def get_settings(self) -> dict[str, Any]:
        with self._lock:
            return self._read()

    def update_settings(self, **changes: Any) -> dict[str, Any]:
        """Partial update -- only keys present in *changes* (and not None) are
        applied; unknown keys are ignored so a stray/future client field can't
        corrupt the store."""
        with self._lock:
            data = self._read()
            for key, value in changes.items():
                if key in DEFAULT_SETTINGS and value is not None:
                    data[key] = value
            self._write(data)
            return data
