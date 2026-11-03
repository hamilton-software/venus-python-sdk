"""Routes behind the labware and liquid-class pickers."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend import catalogs, instrument, service
from backend.mcp_bridge import BridgeError

router = APIRouter(prefix="/api/catalog")


class FindBody(BaseModel):
    liquid: str
    dispense_mode: str | None = None
    volume: float | None = None
    tip_pool: str | None = None


@router.get("/labware/categories")
def labware_categories() -> dict[str, Any]:
    return {"categories": catalogs.labware_categories()}


@router.get("/labware")
def labware(category: str | None = None, q: str | None = None) -> dict[str, Any]:
    return catalogs.search_labware(category, q)


@router.get("/liquid-classes")
def liquid_classes() -> dict[str, Any]:
    kind = instrument.instrument_type()
    return {"instrument": kind, "classes": catalogs.liquid_classes(kind), "dispense_modes": catalogs.DISPENSE_MODES}


@router.post("/liquid-classes/find")
async def find_liquid_classes(body: FindBody) -> dict[str, Any]:
    """The SDK's own best-first search for a transfer. It needs a session (not a connected instrument),
    because the answer depends on the pipetting devices and registered tips of this instrument."""
    if service.bridge.connection_id is None:
        raise HTTPException(409, detail="Start a session first: the search uses the tips and devices fitted on this instrument.")
    arguments = {key: value for key, value in body.model_dump().items() if value not in (None, "")}
    try:
        response = await asyncio.to_thread(service.bridge.run_command, "find_liquid_classes", arguments, recovery=True)
    except BridgeError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    result = response.get("result") if isinstance(response, dict) else None
    return {"result": result if result is not None else response}


@router.get("/simulator")
def simulator() -> dict[str, Any]:
    """The module, firmware-step and error names the error simulator accepts on this instrument, from the
    SDK's own knowledge base, so the Inject Simulated Error card can offer them without a session."""
    from hamilton_venus.error_simulator.knowledge_base import KnowledgeBase

    kind = instrument.instrument_type()
    key = "VANTAGE" if kind == "Vantage" else "STAR"
    kb = KnowledgeBase.load()
    modules = []
    for module in kb.modules:
        if not kb.has_table(key, module):
            continue
        modules.append({
            "value": module.table, "label": module.description or module.table,
            "per_channel": module.table in ("1mL", "5mL", "X1", "MagPip"),
            "steps": [r.description for r in kb.firmware_rows(key, module)],
            "errors": [r.description for r in kb.error_rows(key, module)],
        })
    return {"instrument": kind, "modules": modules}


# -- deck and positions (the positions wizard and the name suggestions) -------------------------------------------

deck_router = APIRouter()


class ComposeBody(BaseModel):
    labware: str
    rows: int
    cols: int
    wells: list[str]
    compact: bool = True


class ExpandBody(BaseModel):
    selector: str
    rows: int
    cols: int


@deck_router.get("/api/deck")
async def deck() -> dict[str, Any]:
    """Labware, carriers and tip pools on the deck now (empty without a session). While a flow is running the
    last answer is returned, so a lookup never queues behind a long command."""
    from backend import deck_info

    if service.runner.active and service.deck_cache is not None:
        return service.deck_cache
    service.deck_cache = await asyncio.to_thread(deck_info.read_deck, service.bridge)
    service.layout_cache.clear()  # the deck may have changed, so labware are read again when chosen
    return service.deck_cache


@deck_router.get("/api/deck/labware")
async def deck_labware(name: str) -> dict[str, Any]:
    """The well layout of one labware on the deck (one lookup; remembered until the deck listing is read again)."""
    from backend import deck_info

    key = name.lower()
    if key in service.layout_cache:
        return service.layout_cache[key]
    layout = await asyncio.to_thread(deck_info.read_layout, service.bridge, name)
    if layout.get("count"):  # an empty answer is a failed lookup: ask again next time
        service.layout_cache[key] = layout
    return layout


@deck_router.post("/api/positions/compose")
def compose_positions(body: ComposeBody) -> dict[str, str]:
    from backend import positions

    try:
        return {"selector": positions.compose(body.labware.strip(), body.rows, body.cols, body.wells, body.compact)}
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc


@deck_router.post("/api/positions/expand")
def expand_positions(body: ExpandBody) -> dict[str, Any]:
    from backend import positions

    try:
        return positions.expand(body.selector, body.rows, body.cols)
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
