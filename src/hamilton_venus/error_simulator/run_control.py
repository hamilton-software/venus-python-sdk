"""Resolve the target instrument, simulator-config path and simulation state
for :mod:`hamilton_venus.error_simulator`.

The running firmware simulator (``HxProtocolSimulator``) reads the file named by
``HxRegistry.InstCfgFile(<class>)`` with ``.cfg`` -> ``_Simulator.cfg`` -- e.g.
``ML_STAR.cfg`` -> ``ML_STAR_Simulator.cfg`` for *any* STAR-class model
(STARlet / STAR / FlexSTAR all use ``ML_STAR_Simulator.cfg``). Instrument class
and the config directory come from the Vector WebAPI; the cfg *name* comes from
``HxRegistry`` (COM), matching the HSL ``InitializeLibrary`` exactly, with a
platform-based fallback if the registry lookup fails.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hamilton_venus.error_simulator.exceptions import InstrumentNotResolved

_HXREG_PROGID = "HXREGLib.HxRegistry.1"

#: Fallback cfg name per instrument class when the registry lookup is unavailable.
_FALLBACK_CFG = {"STAR": "ML_STAR_Simulator.cfg", "VANTAGE": "HxVantage_Simulator.cfg"}


@dataclass(frozen=True)
class RunControlInfo:
    """Everything the simulator needs about the running VENUS instance."""

    instrument: str  # "STAR" | "VANTAGE" -- matches the HSL SETTINGS.Instrument
    instrument_class: str  # e.g. "ML_STAR"
    config_path: Path
    is_simulating: bool


def _instrument_from_class(instrument_class: str) -> str:
    return "STAR" if (instrument_class or "").upper().startswith("ML_STAR") else "VANTAGE"


def _inst_cfg_file(instrument_class: str) -> str | None:
    """``HxRegistry.InstCfgFile(<class>)`` (e.g. ``"ML_STAR.cfg"``) or ``None``."""
    try:
        import pythoncom
        import win32com.client
    except ImportError:  # pragma: no cover - non-Windows
        return None
    pythoncom.CoInitialize()
    try:
        registry = win32com.client.Dispatch(_HXREG_PROGID)
        name = registry.InstCfgFile(instrument_class, "")
        return str(name) or None
    except Exception:
        return None
    finally:
        pythoncom.CoUninitialize()


def _simulator_cfg_name(instrument: str, inst_cfg_file: str | None) -> str:
    if inst_cfg_file:
        stem = inst_cfg_file[:-4] if inst_cfg_file.lower().endswith(".cfg") else inst_cfg_file
        return f"{stem}_Simulator.cfg"
    return _FALLBACK_CFG[instrument]


def resolve(
    *,
    instrument_data: list[dict[str, object]],
    config_dir: str,
    is_simulating: bool,
    inst_cfg_file: str | None = None,
    instrument: str | None = None,
) -> RunControlInfo:
    """Build :class:`RunControlInfo` from already-fetched payloads.

    Payload-in / value-out for testability. ``inst_cfg_file`` is
    ``HxRegistry.InstCfgFile(<class>)``; when ``None`` a platform-based fallback
    name is used. The mixin's :func:`resolve_live` fills it in via COM.

    ``instrument`` (``"STAR"`` / ``"VANTAGE"``) overrides the platform-based
    guess. A Vantage driven through the STAR translator registers with platform
    ``ML_STAR``, so the platform alone would pick the STAR knowledge-base
    tables and write STAR firmware commands the Vantage simulator never sends;
    the instrument clients pass their own instrument type here.
    """
    if not instrument_data:
        raise InstrumentNotResolved("no instruments registered (GET /instrumentdata was empty)")
    entry = instrument_data[0]
    instrument_class = str(entry.get("platform") or "").strip()
    if not instrument_class:
        raise InstrumentNotResolved(f"instrumentdata entry missing 'platform': {entry!r}")

    instrument = (instrument or "").upper() or _instrument_from_class(instrument_class)
    cfg_name = _simulator_cfg_name(instrument, inst_cfg_file)
    return RunControlInfo(
        instrument=instrument,
        instrument_class=instrument_class,
        config_path=Path(config_dir) / cfg_name,
        is_simulating=bool(is_simulating),
    )


def resolve_live(venus: Any, run_coro: Any, instrument: str | None = None) -> RunControlInfo:
    """Resolve against a live session. ``venus`` is a ``VenusClient``; ``run_coro``
    runs a coroutine to completion (the sync client's ``_run``). ``instrument``
    overrides the platform-based guess -- see :func:`resolve`."""
    instrument_data = run_coro(venus.get_instrument_data())
    paths = run_coro(venus.get_system_paths())
    is_simulating = run_coro(venus.get_simulation())
    instrument_class = str((instrument_data or [{}])[0].get("platform") or "")
    return resolve(
        instrument_data=instrument_data,
        config_dir=paths["Config"],
        is_simulating=is_simulating,
        inst_cfg_file=_inst_cfg_file(instrument_class),
        instrument=instrument,
    )
