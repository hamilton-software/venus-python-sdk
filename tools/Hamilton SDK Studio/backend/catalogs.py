"""The SDK's labware-type and liquid-class catalogs, for the pickers.

Labware types come from the same catalog the MCP server's `search_labware` / `list_labware_categories`
tools read (hamilton_venus_mcp.labware_catalog), so a type found here is a type an agent finds there,
and the value a card gets is the labware id the SDK accepts (e.g. `Nun_96_Fl`, `TIP_CAR_480BC`).
Liquid classes come from `hamilton_venus.catalog.LIQUID_CLASSES` for this PC's instrument; the live
"find for a transfer" search goes through the SDK's own `find_liquid_classes` (see routes_catalog).
"""

from __future__ import annotations

from collections import Counter
from typing import Any

# How the "find for a transfer" dispense-mode choices read; the value is what find_liquid_classes accepts.
DISPENSE_MODES = [
    {"value": "jet_empty", "label": "Jet, empty (no liquid contact, single dispense)"},
    {"value": "jet_part", "label": "Jet, part volume (no contact, multi-dispense)"},
    {"value": "surface_empty", "label": "Surface, empty (touching the liquid, single dispense)"},
    {"value": "surface_part", "label": "Surface, part volume (touching, multi-dispense)"},
    {"value": "whipip", "label": "WhiPip (MagPip sub-µL)"},
]


def labware_categories() -> list[dict[str, Any]]:
    from hamilton_venus_mcp.labware_catalog import LABWARE_CATALOG

    counts = Counter(entry.category for entry in LABWARE_CATALOG)
    return [{"category": category, "count": counts[category]} for category in sorted(counts)]


def search_labware(category: str | None = None, q: str | None = None, limit: int = 400) -> dict[str, Any]:
    """Labware types, filtered like the MCP search_labware tool (category, and a substring over name and id).
    Several words in `q` must all match. Carriers also report how many deck tracks they take."""
    from hamilton_venus_mcp import deck_tracks
    from hamilton_venus_mcp.labware_catalog import LABWARE_CATALOG

    words = (q or "").lower().split()
    found: list[dict[str, Any]] = []
    for entry in LABWARE_CATALOG:
        if category and entry.category.lower() != category.lower():
            continue
        haystack = f"{entry.name} {entry.labware_id} {entry.category}".lower()
        if any(word not in haystack for word in words):
            continue
        item: dict[str, Any] = {"name": entry.name, "labware_id": entry.labware_id, "category": entry.category}
        if entry.category in ("CARRIER", "TUBE_RACK"):
            width = deck_tracks.carrier_width(entry.labware_id)
            if width is not None:
                item["width_tracks"] = width
        found.append(item)
    return {"total": len(found), "labware": found[:limit], "truncated": len(found) > limit}


def liquid_classes(instrument_type: str) -> list[dict[str, str]]:
    """Every liquid class this instrument type knows: the SDK's system library, then the user's own."""
    from hamilton_venus.catalog import LIQUID_CLASSES

    namespace = LIQUID_CLASSES.VANTAGE if instrument_type == "Vantage" else LIQUID_CLASSES.STAR
    classes: list[dict[str, str]] = []
    for library, group in (("System", namespace.SYSTEM), ("User", namespace.USER)):
        classes += [{"name": name, "library": library} for name in sorted(set(group.all_values()))]
    return classes
