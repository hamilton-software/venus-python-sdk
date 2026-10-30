"""The local liquid class library: what each class applies to, and finding the right one.

Every liquid class JSON in the SDK's ``Liquid Class`` folder
(``<STAR|VANTAGE>\\<System|User>\\<device>\\<tip>\\<liquid>\\<mode>\\<name>.json``) states what
it is for in ``appliesTo`` (pipetting device, tip type, liquid, dispense mode, volume range)
and ``_internal`` (``tipTypeId`` -- the key in VENUS's ``get_tip_types`` list -- and the
dispense mode's number). A class is only right for a transfer when all of them match:

- the pipetting device is fitted on this instrument (``instrument_get_configuration``) --
  e.g. MagPip classes exist only in the Vantage library and need MagPip channels;
- the tip type is registered in VENUS (``get_tip_types``), loaded for the transfer, and
  usable on that device (its "Liquid Device List");
- the dispense mode fits the transfer (jet / surface, empty / part volume);
- the volume is within the class's range and the tip's "Max Liquid Volume";
- the liquid is the closest match.

``find_liquid_classes`` on StarClient / VantageClient applies all of this; the device of a
liquid class is also checked before every pipetting command (see
``_AsyncInstrumentClient._before_command``).
"""

from __future__ import annotations

import difflib
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, computed_field

_logger = logging.getLogger(__name__)

# Liquid class pipettingDevice <-> the device names in a tip type's "Liquid Device List".
TIP_DEVICE_NAMES: dict[str, tuple[str, ...]] = {
    "channels_1000ul": ("1mL Channels", "1mL X1 Channels"),
    "channels_5ml": ("5mL channels", "5mL X5 Channels"),
    "channels_magpip": ("MagPip",),
    "head_96": ("96 head",),
    "head_384": ("384 head",),
}

# What each pipetting device is called for people.
DEVICE_LABELS: dict[str, str] = {
    "channels_1000ul": "1 mL channels",
    "channels_5ml": "5 mL channels",
    "channels_magpip": "MagPip channels",
    "head_96": "96-channel head (MPH96)",
    "head_384": "384-channel head (MPH384)",
}

# The VENUS action prefix of each pipetting command family -> its liquid class device.
DEVICE_BY_ACTION_PREFIX: dict[str, str] = {
    "channels.1mL.": "channels_1000ul",
    "channels.5mL.": "channels_5ml",
    "channels.MagPip.": "channels_magpip",
    "mph96.": "head_96",
    "mph384.": "head_384",
}

# Accepted spellings for a device argument.
_DEVICE_ALIASES: dict[str, str] = {
    "1ml": "channels_1000ul", "channels1ml": "channels_1000ul", "channels1000ul": "channels_1000ul",
    "5ml": "channels_5ml", "channels5ml": "channels_5ml",
    "magpip": "channels_magpip", "channelsmagpip": "channels_magpip",
    "mph96": "head_96", "96head": "head_96", "head96": "head_96", "core96": "head_96",
    "mph384": "head_384", "384head": "head_384", "head384": "head_384",
}

# Dispense mode names in appliesTo, and the spellings accepted for them.
DISPENSE_MODES = ("jet_empty", "jet_part", "surface_empty", "surface_part", "whipip")
_MODE_ALIASES = {
    "jetempty": "jet_empty", "jetemptytip": "jet_empty",
    "jetpart": "jet_part", "jetpartvolume": "jet_part",
    "surfaceempty": "surface_empty", "surfaceemptytip": "surface_empty",
    "surfacepart": "surface_part", "surfacepartvolume": "surface_part",
    "whipip": "whipip",
}


def _key(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text).lower())


def normalize_device(device: str) -> str:
    """'1mL' / 'channels_1000ul' / 'MPH96' / ... -> the liquid class device name."""
    if device in TIP_DEVICE_NAMES:
        return device
    key = _key(device)
    if key in _DEVICE_ALIASES:
        return _DEVICE_ALIASES[key]
    raise ValueError(f"Unknown pipetting device {device!r}; use one of {', '.join(TIP_DEVICE_NAMES)}.")


def normalize_dispense_mode(mode: Any) -> str:
    """DispenseMode enum / 'Jet Empty' / 'JET_EMPTY_TIP' / 'jet_empty' -> 'jet_empty'."""
    raw = getattr(mode, "name", None) or getattr(mode, "value", None) or mode
    key = _key(str(raw))
    if key in _MODE_ALIASES:
        return _MODE_ALIASES[key]
    raise ValueError(f"Unknown dispense mode {mode!r}; use one of {', '.join(DISPENSE_MODES)}.")


def device_for_action(action_name: str) -> str | None:
    """The pipetting device a VENUS action runs on ('channels.1mL.aspirate' -> 'channels_1000ul')."""
    return next((d for prefix, d in DEVICE_BY_ACTION_PREFIX.items() if action_name.startswith(prefix)), None)


def fitted_devices(configuration: Any) -> set[str]:
    """The pipetting devices an ``instrument_get_configuration`` result reports, on any arm."""
    params = getattr(configuration, "return_parameters", configuration)
    devices: set[str] = set()
    for arm in (getattr(params, "left_arm", None), getattr(params, "right_arm", None)):
        if arm is None:
            continue
        if getattr(arm, "channels_1_ml", None):
            devices.add("channels_1000ul")
        if getattr(arm, "channels_5_ml", None):
            devices.add("channels_5ml")
        if getattr(arm, "channels_mag_pip", None):
            devices.add("channels_magpip")
        if getattr(arm, "mph96", None):
            devices.add("head_96")
        if getattr(arm, "mph384", None):
            devices.add("head_384")
    return devices


class TipTypeInfo(BaseModel):
    """One registered tip type, from VENUS's ``get_tip_types``.

    ``tip_length`` is the whole tip, collar included. What reaches below the channel is
    ``length_below_channel``: the tip length minus the collar depth that sits on the channel
    up to its stop disk (``stop_disk_immersion_depth``) -- e.g. 59.9 - 8 = 51.9 mm for a
    300 µL tip. Use that one for heights and clearances.
    """

    id: int
    name: str = ""
    max_liquid_volume: float = 0.0
    max_tip_volume: float = 0.0
    tip_length: float | None = None
    stop_disk_immersion_depth: float | None = None
    filter: bool = False
    conductive: bool = False
    liquid_devices: list[str] = Field(default_factory=list)
    tip_class: str = ""
    visible: bool = True

    @computed_field  # type: ignore[prop-decorator]
    @property
    def length_below_channel(self) -> float | None:
        """Tip length from the channel's stop disk to the tip end, in mm."""
        if self.tip_length is None:
            return None
        return round(self.tip_length - (self.stop_disk_immersion_depth or 0.0), 3)

    def usable_on(self, device: str) -> bool:
        return any(name in self.liquid_devices for name in TIP_DEVICE_NAMES.get(device, ()))

    def devices(self) -> list[str]:
        return [device for device in TIP_DEVICE_NAMES if self.usable_on(device)]


def parse_tip_types(tip_types: dict[str, Any]) -> dict[int, TipTypeInfo]:
    """``get_tip_types().return_parameters.tip_types`` -> {tip type id: TipTypeInfo}."""
    parsed: dict[int, TipTypeInfo] = {}
    for key, data in (tip_types or {}).items():
        if not isinstance(data, dict):
            continue
        try:
            tip_id = int(key)
        except ValueError:
            continue
        parsed[tip_id] = TipTypeInfo(
            id=tip_id,
            # "300ul Standard Volume Tip (Ham org. name)" -> "300ul Standard Volume Tip"
            name=re.sub(r"\s*\(Ham org\.? name\)\s*$", "", str(data.get("Tip View Name", ""))).strip(),
            max_liquid_volume=float(data.get("Max Liquid Volume") or 0),
            max_tip_volume=float(data.get("Max Tip Volume") or 0),
            tip_length=data.get("Tip Length"),
            stop_disk_immersion_depth=data.get("Stop Disk Immersion Depth"),
            filter=bool(data.get("Filter", False)),
            conductive=bool(data.get("Conductivity", False)),
            liquid_devices=[str(d) for d in data.get("Liquid Device List") or []],
            tip_class=str(data.get("Tip Class", "")),
            visible=bool(data.get("Visibility Flag", True)),
        )
    return parsed


def _numbers(values: Any) -> dict[str, float]:
    """The numeric entries of a ``pipettingProperties`` section."""
    return {k: float(v) for k, v in (values or {}).items() if isinstance(v, (int, float)) and not isinstance(v, bool)}


@dataclass(frozen=True)
class LiquidClassInfo:
    name: str
    original: bool
    pipetting_device: str
    tip_type: str
    tip_type_id: int | None
    liquid: str
    dispense_mode: str
    volume_min: float
    volume_max: float
    tadm_enabled: bool
    validated: bool
    path: Path = field(compare=False)
    # Flow rates, blow-out, air transport ... as stored in the class (``pipettingProperties``).
    aspirate: dict[str, float] = field(default_factory=dict, compare=False)
    dispense: dict[str, float] = field(default_factory=dict, compare=False)


class LiquidClassLibrary:
    """The liquid classes of one instrument's library folder, read once and on demand."""

    def __init__(self, root: Path, instrument_folder: str) -> None:
        self.root = root
        self.instrument_folder = instrument_folder.upper()
        self._classes: dict[str, LiquidClassInfo] | None = None

    @property
    def available(self) -> bool:
        return (self.root / self.instrument_folder).is_dir()

    def _scan(self) -> dict[str, LiquidClassInfo]:
        classes: dict[str, LiquidClassInfo] = {}
        library = self.root / self.instrument_folder
        for path in sorted(library.rglob("*.json")) if library.is_dir() else []:
            try:
                data = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                _logger.debug("Skipping unreadable liquid class %s", path)
                continue
            applies = data.get("appliesTo") or {}
            internal = data.get("_internal") or {}
            volume = applies.get("volumeRange") or {}
            original = path.relative_to(library).parts[0].lower() == "system"
            properties = data.get("pipettingProperties") or {}
            info = LiquidClassInfo(
                name=str(data.get("id") or path.stem),
                original=original,
                pipetting_device=str(applies.get("pipettingDevice", "")),
                tip_type=str(applies.get("tipType", "")),
                tip_type_id=internal.get("tipTypeId"),
                liquid=str(applies.get("liquid", "")),
                dispense_mode=str(applies.get("dispenseMode", "")),
                volume_min=float(volume.get("min") or 0),
                volume_max=float(volume.get("max") or 0),
                tadm_enabled=bool(data.get("tadmEnabled", False)),
                validated=bool(data.get("validated", False)),
                path=path,
                aspirate=_numbers(properties.get("aspirate")),
                dispense=_numbers(properties.get("dispense")),
            )
            # A custom class shadows a same-named original, as in VENUS's own database.
            if info.name not in classes or not info.original:
                classes[info.name] = info
        return classes

    def classes(self) -> dict[str, LiquidClassInfo]:
        if self._classes is None:
            self._classes = self._scan()
        return self._classes

    def get(self, name: str) -> LiquidClassInfo | None:
        info = self.classes().get(name)
        if info is None and self.available:
            # Created during the session (e.g. while developing one): rescan once.
            self._classes = self._scan()
            info = self._classes.get(name)
        return info

    def liquids(self) -> list[str]:
        return sorted({c.liquid for c in self.classes().values() if c.liquid})


def liquid_match(wanted: str, liquid: str) -> float:
    """0..1: how well a class's liquid matches the liquid being transferred."""
    a, b = _key(wanted), _key(liquid)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.85
    return difflib.SequenceMatcher(None, a, b).ratio() * 0.8


class LiquidClassCandidate(BaseModel):
    name: str
    liquid: str
    liquid_match: str  # "exact", "close" or "fallback"
    dispense_mode: str
    pipetting_device: str
    tip_type: str
    tip_type_id: int | None
    volume_min: float
    volume_max: float
    original: bool
    validated: bool
    tadm_enabled: bool
    # What the class is for, from its definition. Judge a class by this (and the numbers below),
    # never by its name: "1000ul" in a 96-head class name is the head, not the tip.
    summary: str = ""
    aspirate: dict[str, float] = Field(default_factory=dict)
    dispense: dict[str, float] = Field(default_factory=dict)


class LiquidClassSearchResult(BaseModel):
    """What ``find_liquid_classes`` matched against, and the ranked candidates (best first)."""

    instrument: str
    device: str
    device_label: str
    tip_type_id: int
    tip: TipTypeInfo
    dispense_mode: str | None
    liquid: str
    volume: float | None
    candidates: list[LiquidClassCandidate]
    notes: list[str] = Field(default_factory=list)


def rank_candidates(
    library: LiquidClassLibrary,
    *,
    liquid: str,
    device: str,
    tip_type_id: int,
    dispense_mode: str | None,
    volume: float | None,
    include_custom: bool = True,
    limit: int = 10,
) -> tuple[list[LiquidClassCandidate], list[str]]:
    """The library's classes for exactly this device, tip type and dispense mode (and volume),
    best liquid match first, Hamilton's validated originals before custom ones."""
    notes: list[str] = []
    pool = [
        c for c in library.classes().values()
        if c.pipetting_device == device
        and c.tip_type_id == tip_type_id
        and (dispense_mode is None or c.dispense_mode == dispense_mode)
        and (include_custom or c.original)
    ]
    if volume is not None:
        in_range = [c for c in pool if c.volume_min <= volume <= (c.volume_max or float("inf"))]
        if pool and not in_range:
            notes.append(f"No class covers {volume:g} µL exactly; showing the nearest ranges.")
        else:
            pool = in_range
    scored = []
    for c in pool:
        score = liquid_match(liquid, c.liquid)
        span = (c.volume_max - c.volume_min) if c.volume_max else float("inf")
        scored.append((-score, not c.original, not c.validated, span, c.name, c, score))
    scored.sort(key=lambda item: item[:5])
    candidates = []
    for *_, c, score in scored[:limit]:
        kind = "exact" if score >= 1.0 else ("close" if score >= 0.6 else "fallback")
        candidates.append(LiquidClassCandidate(
            name=c.name, liquid=c.liquid, liquid_match=kind, dispense_mode=c.dispense_mode,
            pipetting_device=c.pipetting_device, tip_type=c.tip_type, tip_type_id=c.tip_type_id,
            volume_min=c.volume_min, volume_max=c.volume_max, original=c.original,
            validated=c.validated, tadm_enabled=c.tadm_enabled,
            summary=(f"{DEVICE_LABELS.get(c.pipetting_device, c.pipetting_device)}, {c.tip_type} tip, "
                     f"{c.volume_min:g}-{c.volume_max:g} µL, {c.liquid}, {c.dispense_mode}"),
            aspirate=c.aspirate, dispense=c.dispense,
        ))
    if candidates and candidates[0].liquid_match != "exact":
        notes.append(f"No class is made for {liquid!r} with this tip and mode; the closest liquids are listed. "
                     "Check the choice, or create a custom class for this liquid.")
    if not candidates:
        notes.append("No liquid class matches this device, tip type and dispense mode.")
    else:
        notes.append("Each class was matched on what its definition says it is for (device, tip type, volume "
                     "range, dispense mode), shown in 'summary'. Judge a class by that and by its aspirate / "
                     "dispense numbers, not by its name.")
    return candidates, notes
