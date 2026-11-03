"""What is on the deck right now, for the pickers: labware names with their well layout, tip pools, carriers.

Read from the instrument session with the SDK's own deck queries (get_added_plates, get_labware_positions,
...), as lookups that stay out of the command journal. VENUS returns names in lower case; callers may show
the person's own spelling where a flow card defines the same name.
"""

from __future__ import annotations

import re
from typing import Any

from backend import positions

_WELL = re.compile(r"^[A-Za-z]+\d+$")


def _parameters(bridge: Any, command: str, **kwargs: Any) -> dict[str, Any]:
    try:
        response = bridge.run_command(command, kwargs, recovery=True)
    except Exception:  # noqa: BLE001 - a lookup that fails just yields nothing
        return {}
    result = response.get("result") if isinstance(response, dict) else None
    found = result.get("returnParameters") if isinstance(result, dict) else None
    return found if isinstance(found, dict) else {}


def layout_from_positions(wells: list[str]) -> dict[str, Any]:
    """rows / cols of a labware from its well names: a grid for A1..H12, a list for numbered sections or tubes."""
    if wells and all(_WELL.match(w) for w in wells):
        rows = max(positions.parse_well(w)[0] for w in wells) + 1
        cols = max(positions.parse_well(w)[1] for w in wells)
        return {"layout": "grid", "rows": rows, "cols": cols, "count": len(wells)}
    return {"layout": "list", "count": len(wells), "wells": wells}


def read_layout(bridge: Any, name: str) -> dict[str, Any]:
    """The well layout of ONE labware: a single lookup, made only when the person picks that labware."""
    info = _parameters(bridge, "get_labware_positions", labware_name=name)
    entry = info.get(name) or next(iter(info.values()), None) or {}
    return {"name": name, **layout_from_positions(list(entry.get("positions", [])))}


def _labware(names: list[str], kind: str) -> list[dict[str, Any]]:
    return [{"name": name, "kind": kind} for name in names]


def read_deck(bridge: Any) -> dict[str, Any]:
    """{"session": bool, "plates": [...], "reservoirs": [...], "tip_racks": [...], "carriers": [...], "tip_pools": [...]}

    Labware are listed by name and kind only (four lookups however much is on the deck); the wells of one
    labware come from read_layout when it is chosen."""
    if getattr(bridge, "connection_id", None) is None:
        return {"session": False, "plates": [], "reservoirs": [], "tip_racks": [], "carriers": [], "tip_pools": []}
    plates = _parameters(bridge, "get_added_plates").get("platesAdded", [])
    reservoirs = _parameters(bridge, "get_added_reservoirs").get("reservoirsAdded", [])
    racks = _parameters(bridge, "get_added_tip_racks").get("tipRacksAdded", [])
    return {
        "session": True,
        "plates": _labware(plates, "plate"),
        "reservoirs": _labware(reservoirs, "reservoir"),
        "tip_racks": _labware(racks, "tip_rack"),
        "carriers": _parameters(bridge, "get_added_carriers").get("carriersAdded", []),
        "tip_pools": _parameters(bridge, "tip_pool_get_tip_counters").get("tipCounterNames", []),
    }
