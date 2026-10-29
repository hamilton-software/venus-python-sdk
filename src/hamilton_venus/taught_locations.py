"""Record operator *taught locations* into the SDK's Active Layout directory.

A "taught location" is a fine position correction an operator dials in for a
specific piece of labware or for a carrier/site combination. This module writes
those corrections to a single JSON file --
``<SDK install>\\Active Layout\\TaughtLocations.json`` -- that a VENUS method can
read back and enforce at runtime. Nothing here talks to the instrument or the
VENUS runtime; it is plain local file I/O and works with no client connection.

VENUS clears the Active Layout directory, this file included, each time a new
session connects. A saved deck (``deck_save``) carries the file, and starting a
session from it (``deck_name=...``) restores it.

The file holds two maps, each keyed for a direct (no-iteration) lookup::

    {
      "schemaVersion": 1,
      "labwarePositions": {
        "<labware name>": {
          "<carrier>/<site>": { "labware": ..., "carrier": ..., "site": ...,
                                "x": ..., "y": ..., "z": ..., "angle": ...,
                                "note": ..., "recordedUtc": ... }
        }
      },
      "carrierSiteOffsets": {
        "<carrier>/<site>": { "carrier": ..., "site": ...,
                              "dx": ..., "dy": ..., "dz": ..., "dAngle": ...,
                              "note": ..., "recordedUtc": ... }
      }
    }

``labwarePositions`` is nested: one entry per labware name, and within it one
entry per ``"<carrier>/<site>"`` the labware has been taught at (a plate can hold
different coordinates on different sites). VENUS is expected to resolve a location
by checking ``labwarePositions[<plate>][<carrier>/<site>]`` first and falling back
to ``carrierSiteOffsets[<carrier>/<site>]`` (see :func:`resolve_taught_location`,
which mirrors that order for parity checks). Each ``register_*`` call is *latest
wins*: it overwrites the record under that key -- a new key is added, an existing
key is replaced. No history is retained.

``labware``, ``carrier`` and ``site`` are **lower-cased** on the way in -- both in
the stored record fields and in the map keys -- so ``"Plate1"`` and ``"plate1"``
address the same entry. The VENUS side must lower-case these before it builds a
lookup key.

The public function names all carry a ``taught`` stem so they sit apart from the
deck-layout query commands (e.g. ``get_labware_positions``) on the clients.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_serializer, field_validator

from hamilton_venus._internal._sdk_paths import get_sdk_active_layout_path

DEFAULT_FILENAME = "TaughtLocations.json"
SCHEMA_VERSION = 1

__all__ = [
    "DEFAULT_FILENAME",
    "SCHEMA_VERSION",
    "CarrierSiteOffset",
    "LabwarePosition",
    "TaughtLocationsFile",
    "carrier_site_key",
    "clear_taught_locations",
    "get_taught_locations",
    "get_taught_offset",
    "get_taught_position",
    "get_taught_positions",
    "register_taught_offset",
    "register_taught_position",
    "remove_taught_offset",
    "remove_taught_position",
    "resolve_taught_location",
]


def _norm(value: object) -> str:
    """Normalize an identifier the way it is stored: stringified and lower-cased."""
    return str(value).lower()


def carrier_site_key(carrier: str | int, site: str | int) -> str:
    """Build the map key for a carrier/site combination.

    Used for the ``carrierSiteOffsets`` map and for the inner ``labwarePositions``
    map. ``carrier`` and ``site`` are stringified and lower-cased; the VENUS side
    must build the identical string (``"<carrier>/<site>"``) to look a record up.
    """
    return f"{_norm(carrier)}/{_norm(site)}"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _to_utc_z(value: datetime) -> str:
    aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return aware.astimezone(UTC).isoformat().replace("+00:00", "Z")


class CarrierSiteOffset(BaseModel):
    """A relative X/Y/Z (+ angle) correction for a carrier/site combination."""

    model_config = ConfigDict(populate_by_name=True)

    carrier: str
    site: str
    dx: float
    dy: float
    dz: float
    d_angle: float = Field(default=0.0, alias="dAngle")
    note: str | None = None
    recorded_utc: datetime = Field(default_factory=_utc_now, alias="recordedUtc")

    @field_validator("carrier", "site", mode="before")
    @classmethod
    def _normalize_identifier(cls, value: object) -> str:
        return _norm(value)

    @field_serializer("recorded_utc")
    def _serialize_recorded_utc(self, value: datetime) -> str:
        return _to_utc_z(value)


class LabwarePosition(BaseModel):
    """Absolute X/Y/Z (+ angle) coordinates taught for a labware item at one carrier/site."""

    model_config = ConfigDict(populate_by_name=True)

    labware: str
    carrier: str
    site: str
    x: float
    y: float
    z: float
    angle: float = 0.0
    note: str | None = None
    recorded_utc: datetime = Field(default_factory=_utc_now, alias="recordedUtc")

    @field_validator("labware", "carrier", "site", mode="before")
    @classmethod
    def _normalize_identifier(cls, value: object) -> str:
        return _norm(value)

    @field_serializer("recorded_utc")
    def _serialize_recorded_utc(self, value: datetime) -> str:
        return _to_utc_z(value)


class TaughtLocationsFile(BaseModel):
    """In-memory view of ``TaughtLocations.json``."""

    model_config = ConfigDict(populate_by_name=True)

    schema_version: int = Field(default=SCHEMA_VERSION, alias="schemaVersion")
    labware_positions: dict[str, dict[str, LabwarePosition]] = Field(
        default_factory=dict,
        alias="labwarePositions",
    )
    carrier_site_offsets: dict[str, CarrierSiteOffset] = Field(
        default_factory=dict,
        alias="carrierSiteOffsets",
    )


# --- file I/O -----------------------------------------------------------------


def _resolve_path(path: str | Path | None) -> Path:
    if path is not None:
        return Path(path)
    return get_sdk_active_layout_path() / DEFAULT_FILENAME


def _read(path: Path) -> TaughtLocationsFile:
    """Load *path*; a missing / empty / ``{}`` file yields an empty model.

    A file that exists but is unparseable raises :class:`ValueError` rather than
    being silently discarded -- it most likely holds real operator data.
    """
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return TaughtLocationsFile()
    if not raw:
        return TaughtLocationsFile()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"taught-locations file {path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(
            f"taught-locations file {path} must contain a JSON object, got {type(data).__name__}"
        )
    try:
        return TaughtLocationsFile.model_validate(data)
    except ValidationError as exc:
        raise ValueError(
            f"taught-locations file {path} does not match the expected schema: {exc}"
        ) from exc


def _atomic_write(path: Path, document: TaughtLocationsFile) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(document.model_dump(by_alias=True, mode="json"), indent=2)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(payload + "\n", encoding="utf-8")
    os.replace(tmp, path)


# --- public API -------------------------------------------------------------


def register_taught_offset(
    carrier: str,
    site: str | int,
    *,
    dx: float,
    dy: float,
    dz: float,
    d_angle: float = 0.0,
    note: str | None = None,
    path: str | Path | None = None,
) -> CarrierSiteOffset:
    """Record an X/Y/Z (+ angle) offset for *carrier* / *site*, replacing any prior one."""
    target = _resolve_path(path)
    document = _read(target)
    record = CarrierSiteOffset(
        carrier=carrier, site=str(site), dx=dx, dy=dy, dz=dz, d_angle=d_angle, note=note
    )
    document.carrier_site_offsets[carrier_site_key(record.carrier, record.site)] = record
    _atomic_write(target, document)
    return record


def register_taught_position(
    labware: str,
    carrier: str,
    site: str | int,
    *,
    x: float,
    y: float,
    z: float,
    angle: float = 0.0,
    note: str | None = None,
    path: str | Path | None = None,
) -> LabwarePosition:
    """Record absolute coordinates for *labware* at *carrier* / *site*, replacing any prior one."""
    target = _resolve_path(path)
    document = _read(target)
    record = LabwarePosition(
        labware=labware, carrier=carrier, site=str(site), x=x, y=y, z=z, angle=angle, note=note
    )
    by_site = document.labware_positions.setdefault(record.labware, {})
    by_site[carrier_site_key(record.carrier, record.site)] = record
    _atomic_write(target, document)
    return record


def get_taught_locations(*, path: str | Path | None = None) -> TaughtLocationsFile:
    """Return the whole taught-locations file (an empty model when it does not exist)."""
    return _read(_resolve_path(path))


def get_taught_offset(
    carrier: str,
    site: str | int,
    *,
    path: str | Path | None = None,
) -> CarrierSiteOffset | None:
    """Return the offset recorded for *carrier* / *site*, or ``None`` (case-insensitive)."""
    document = _read(_resolve_path(path))
    return document.carrier_site_offsets.get(carrier_site_key(carrier, site))


def get_taught_positions(
    labware: str,
    *,
    path: str | Path | None = None,
) -> dict[str, LabwarePosition]:
    """Return every taught position for *labware*, keyed by ``"<carrier>/<site>"`` (``{}`` if none)."""
    document = _read(_resolve_path(path))
    return document.labware_positions.get(_norm(labware), {})


def get_taught_position(
    labware: str,
    carrier: str,
    site: str | int,
    *,
    path: str | Path | None = None,
) -> LabwarePosition | None:
    """Return the position recorded for *labware* at *carrier* / *site*, or ``None`` (case-insensitive)."""
    document = _read(_resolve_path(path))
    return document.labware_positions.get(_norm(labware), {}).get(carrier_site_key(carrier, site))


def resolve_taught_location(
    labware: str,
    carrier: str,
    site: str | int,
    *,
    path: str | Path | None = None,
) -> LabwarePosition | CarrierSiteOffset | None:
    """Resolve a teach point the way VENUS is expected to: *labware* at
    *carrier* / *site* first, then the *carrier* / *site* offset."""
    document = _read(_resolve_path(path))
    key = carrier_site_key(carrier, site)
    hit = document.labware_positions.get(_norm(labware), {}).get(key)
    if hit is not None:
        return hit
    return document.carrier_site_offsets.get(key)


def remove_taught_offset(
    carrier: str,
    site: str | int,
    *,
    path: str | Path | None = None,
) -> bool:
    """Delete the offset for *carrier* / *site* (case-insensitive). Returns ``True`` if one was present."""
    target = _resolve_path(path)
    document = _read(target)
    if document.carrier_site_offsets.pop(carrier_site_key(carrier, site), None) is None:
        return False
    _atomic_write(target, document)
    return True


def remove_taught_position(
    labware: str,
    carrier: str | None = None,
    site: str | int | None = None,
    *,
    path: str | Path | None = None,
) -> bool:
    """Delete taught positions for *labware*.

    Pass *carrier* and *site* together to delete just that one combination; omit
    both to delete every taught position for *labware*. Returns ``True`` if
    anything was removed.
    """
    if (carrier is None) != (site is None):
        raise ValueError("pass both 'carrier' and 'site', or neither")
    target = _resolve_path(path)
    document = _read(target)
    labware = _norm(labware)
    if carrier is None:
        removed = document.labware_positions.pop(labware, None) is not None
    else:
        by_site = document.labware_positions.get(labware)
        removed = by_site is not None and by_site.pop(
            carrier_site_key(carrier, cast("str | int", site)), None
        ) is not None
        if removed and not by_site:
            del document.labware_positions[labware]
    if not removed:
        return False
    _atomic_write(target, document)
    return True


def clear_taught_locations(*, path: str | Path | None = None) -> None:
    """Empty both maps, leaving a canonical empty file (with ``schemaVersion``) in place."""
    target = _resolve_path(path)
    document = _read(target)
    document.labware_positions.clear()
    document.carrier_site_offsets.clear()
    _atomic_write(target, document)
