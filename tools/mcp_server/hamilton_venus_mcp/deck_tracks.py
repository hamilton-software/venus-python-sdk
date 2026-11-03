"""Carrier widths and which deck tracks are taken, so carriers are placed by fact, not by guess.

A carrier is ``widthAsTracks`` tracks wide (its definition's
``customAttributes["hamilton:star"]["widthAsTracks"]``; a sample / tube carrier's is its rack
properties' ``MlStarCarWidthAsT``; a carrier with neither, its x dimension / 22.5 mm, the
width of a track): most plate and tip carriers 6 or 7,
reagent and sample/tube carriers 1 or 2, TIP_CAR_288 4. A carrier at ``left_track`` t takes
tracks t .. t + width - 1.

What is on the deck now comes from ``<SDK>\\Active Layout\\LayoutTracking.json``, which the VENUS
method keeps up to date (track -> {"occupied", "carrier", ...}) and clears when a method starts.
The spoke always runs on the VENUS PC, so it reads the file directly. VENUS's own check misses
some overlaps (it accepted a 6-track carrier over a 1-track one), so placements are checked
here before they are sent.
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

from hamilton_venus._internal._sdk_paths import get_sdk_active_layout_path, get_sdk_labware_path

LAYOUT_TRACKING_FILE = "LayoutTracking.json"
TRACK_WIDTH_MM = 22.5  # one deck track
PLACEMENT_COMMANDS = ("add_carrier", "add_tube_carrier", "move_carrier")


@lru_cache(maxsize=4)
def _definition_index(labware_dir: str) -> dict[str, Path]:
    """Every labware definition file under the SDK's Labware folder (System and User), by
    lower-case type name. User definitions win over system ones of the same name."""
    index: dict[str, Path] = {}
    root = Path(labware_dir)
    for sub in ("System", "User"):
        base = root / sub
        if base.is_dir():
            for path in base.rglob("*.json"):
                index[path.stem.lower()] = path
    return index


def carrier_width(type_name: str, labware_dir: Path | None = None) -> int | None:
    """``widthAsTracks`` of a labware type's definition, or None if it has none (not a
    carrier) or the definition isn't found."""
    directory = str(labware_dir or get_sdk_labware_path())
    path = _definition_index(directory).get(str(type_name).lower())
    if path is None:
        _definition_index.cache_clear()  # a definition added since the index was built
        path = _definition_index(directory).get(str(type_name).lower())
    if path is None:
        return None
    try:
        definition = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    attributes = definition.get("customAttributes") or {}
    # Carriers: hamilton:star.widthAsTracks. Sample / tube carriers (tube racks that sit on the
    # deck themselves): their rack properties' MlStarCarWidthAsT.
    width = (attributes.get("hamilton:star") or {}).get("widthAsTracks")
    if width is None:
        width = (attributes.get("hamilton:rck_properties") or {}).get("MlStarCarWidthAsT")
    if isinstance(width, (int, float)) and width > 0:
        return int(width)
    # Neither property (e.g. PLT_CAR_L4HHC): the carrier's x dimension in tracks of 22.5 mm,
    # rounded up -- a carrier a little over a whole number of tracks still takes the next one.
    if attributes.get("hamilton:star") is not None or attributes.get("hamilton:rck_properties") is not None \
            or "carrier" in path.parent.name.lower():
        x = (definition.get("dimensions") or {}).get("x")
        if isinstance(x, (int, float)) and x > 0:
            return max(1, math.ceil(x / TRACK_WIDTH_MM - 0.01))
    return None


def read_occupancy(active_layout_dir: Path | None = None) -> tuple[dict[int, str], int | None]:
    """(track -> carrier name for every occupied deck track, the deck's last track or None).
    Empty when there is no layout file yet (a blank deck)."""
    path = (active_layout_dir or get_sdk_active_layout_path()) / LAYOUT_TRACKING_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}, None
    occupied: dict[int, str] = {}
    last = None
    for key, entry in (data.items() if isinstance(data, dict) else []):
        try:
            track = int(key)
        except ValueError:
            continue
        if track < 1:
            continue
        last = max(last or 0, track)
        if isinstance(entry, dict) and entry.get("occupied"):
            occupied[track] = str(entry.get("carrier") or "?")
    return occupied, last


def _ranges(tracks: list[int]) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for track in sorted(tracks):
        if ranges and track == ranges[-1][1] + 1:
            ranges[-1] = (ranges[-1][0], track)
        else:
            ranges.append((track, track))
    return ranges


def _fmt(start: int, end: int) -> str:
    return str(start) if start == end else f"{start}-{end}"


def carrier_spans(occupied: dict[int, str]) -> dict[str, tuple[int, int]]:
    """carrier name -> (first track, last track)."""
    spans: dict[str, tuple[int, int]] = {}
    for track, name in occupied.items():
        first, last = spans.get(name, (track, track))
        spans[name] = (min(first, track), max(last, track))
    return spans


def first_fit(width: int, occupied: dict[int, str], last_track: int | None, start: int = 1) -> int | None:
    """The first left track at or after *start* where *width* free tracks fit, or None."""
    end = last_track or 999
    track = max(1, start)
    while track + width - 1 <= end:
        clash = [t for t in range(track, track + width) if t in occupied]
        if not clash:
            return track
        track = max(clash) + 1
    return None


def placement_problem(
    command: str, type_name: str, left_track: int, width: int, occupied: dict[int, str], last_track: int | None
) -> str | None:
    """Why a carrier *width* tracks wide can't go at *left_track*, with what would fit; None if it can."""
    wanted = range(left_track, left_track + width)
    spans = carrier_spans(occupied)
    if left_track < 1 or (last_track is not None and wanted[-1] > last_track):
        problem = (f"{type_name} is {width} track(s) wide, so left_track {left_track} would take tracks "
                   f"{_fmt(wanted[0], wanted[-1])}, off the deck (tracks 1-{last_track or '?'}).")
    else:
        hit = sorted({occupied[t] for t in wanted if t in occupied})
        if not hit:
            return None
        taken = ", ".join(f"{name} (tracks {_fmt(*spans[name])})" for name in hit)
        problem = (f"{type_name} is {width} track(s) wide, so left_track {left_track} would take tracks "
                   f"{_fmt(wanted[0], wanted[-1])}, overlapping {taken}.")
    fit_right = first_fit(width, occupied, last_track, start=left_track)
    fit_any = first_fit(width, occupied, last_track)
    free = [t for t in range(1, (last_track or max(occupied, default=0) + width) + 1) if t not in occupied]
    free_text = ", ".join(_fmt(a, b) for a, b in _ranges(free)) or "none"
    suggestion = (f" The first left_track where it fits at or right of {left_track} is {fit_right}."
                  if fit_right is not None else " It doesn't fit anywhere right of that.")
    if fit_any is not None and fit_any != fit_right:
        suggestion += f" (Leftmost fit: {fit_any}.)"
    return f"{command} refused: {problem}{suggestion} Free tracks now: {free_text}. Nothing was sent to VENUS."


def check(command: str, kwargs: dict[str, Any], labware_dir: Path | None = None,
          active_layout_dir: Path | None = None) -> tuple[str | None, dict[str, Any] | None]:
    """(problem or None, what the carrier will take) for an add_carrier / add_tube_carrier /
    move_carrier call. Unknown widths (not in the SDK's Labware folder) are not checked."""
    if command not in PLACEMENT_COMMANDS or "left_track" not in kwargs:
        return None, None
    try:
        left_track = int(kwargs["left_track"])
    except (TypeError, ValueError):
        return None, None
    occupied, last_track = read_occupancy(active_layout_dir)
    if command == "move_carrier":
        if kwargs.get("site"):
            return None, None  # onto a carrier's site, not a deck track
        name = str(kwargs.get("labware_name") or "")
        own = [t for t, carrier in occupied.items() if carrier.lower() == name.lower()]
        if not own:
            return None, None
        width = len(own)
        occupied = {t: c for t, c in occupied.items() if c.lower() != name.lower()}
        type_name = name
    else:
        type_name = str(kwargs.get("labware_definition") or "")
        width = carrier_width(type_name, labware_dir)
        if width is None:
            return None, None
    problem = placement_problem(command, type_name, left_track, width, occupied, last_track)
    takes = {"width_tracks": width, "tracks": _fmt(left_track, left_track + width - 1),
             "first_track_after_it": left_track + width}
    return problem, takes
