"""Write ``<instrument>_Simulator.cfg`` via the VENUS ``HxCfgFile`` COM object.

``Bin\\HxCfgFil.dll`` is a 32-bit in-proc COM server, but Hamilton registers its
``AppID`` with an empty ``DllSurrogate``, so COM hosts it out-of-process in a
32-bit ``dllhost.exe`` and marshals calls from 64-bit Python. All this module
does is what the HSL ``_SetConfigValue`` did: ``LoadFile`` ->
``PutStringValueInDataDef("Simulator", 1, "default", key, value)`` -> ``StoreFile``,
with the HSL's retry loop for file-sharing violations while Run Control has the
file open.

Import is lazy and Windows-only; ``pywin32`` is required.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from hamilton_venus.error_simulator.exceptions import ConfigWriteError

_PROGID = "HXCFGFILLIB.HxCfgFile"
_DATA_DEF = "Simulator"
_INSTANCE = 1
_SECTION = "default"
_RETRIES = 100
_RETRY_DELAY_S = 0.02


class SimulatorConfig:
    """A handle to one ``*_Simulator.cfg`` file."""

    def __init__(self, config_path: str | Path) -> None:
        self.config_path = Path(config_path)

    def apply(self, values: dict[str, str]) -> None:
        """Load the cfg, ``PutStringValueInDataDef`` every *values* entry, store.

        Runs entirely on the calling thread with one COM object kept alive for
        the batch. Order is preserved (dicts are ordered), so callers put the
        firmware-command key(s) before the ``updateKeyValue`` / ``updateParamValue``
        / ``reload`` control keys.
        """
        if not values:
            return
        import pythoncom
        import win32com.client

        pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)
        try:
            try:
                cfg = win32com.client.Dispatch(_PROGID)
            except pythoncom.com_error as exc:  # pragma: no cover - environ dependent
                raise ConfigWriteError(
                    f"could not create {_PROGID!r} -- is VENUS installed and its "
                    f"HxCfgFile AppID/DllSurrogate registered? ({exc})"
                ) from exc

            self._load(cfg, pythoncom)
            for key, value in values.items():
                cfg.PutStringValueInDataDef(_DATA_DEF, _INSTANCE, _SECTION, key, str(value))
            self._store(cfg, pythoncom)
        finally:
            pythoncom.CoUninitialize()

    # -- retrying load / store --------------------------------------------------

    def _load(self, cfg: Any, pythoncom: Any) -> None:
        path = str(self.config_path)
        last: Exception | None = None
        for _ in range(_RETRIES):
            try:
                if cfg.LoadFile(path) == 1:
                    return
            except pythoncom.com_error as exc:
                last = exc
            time.sleep(_RETRY_DELAY_S)
        raise ConfigWriteError(
            f"could not load simulator config {path!r} after {_RETRIES} attempts ({last})"
        )

    def _store(self, cfg: Any, pythoncom: Any) -> None:
        last: Exception | None = None
        for _ in range(_RETRIES):
            try:
                cfg.StoreFile(cfg.FileSpec, cfg.CfgStatus)
                return
            except pythoncom.com_error as exc:
                last = exc
                time.sleep(_RETRY_DELAY_S)
        raise ConfigWriteError(
            f"could not store simulator config {self.config_path!r} after {_RETRIES} attempts ({last})"
        )
