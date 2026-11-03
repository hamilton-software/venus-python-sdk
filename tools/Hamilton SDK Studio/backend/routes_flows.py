"""Routes for saved flows, Generate Script, Import Script and sending a script to the MCP store."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from hamilton_venus_mcp.script_validator import validate_source

from backend import code_import, codegen, flow, flow_store, instrument, service
from backend.mcp_bridge import BridgeError

router = APIRouter()
_store = flow_store.FlowStore(service.config.flows_dir)


class FlowBody(BaseModel):
    flow: dict[str, Any]


class ScriptBody(BaseModel):
    steps: list[dict[str, Any]]
    variables: list[dict[str, Any]] = []
    flow_name: str = ""
    simulate: bool = True
    subflows: list[dict[str, Any]] = []


class ImportBody(BaseModel):
    source: str


class SaveScriptBody(BaseModel):
    name: str
    source: str
    overwrite: bool = False


# -- saved flows ---------------------------------------------------------------------------------


@router.get("/api/flows")
def list_flows() -> dict[str, Any]:
    return {"flows": _store.list()}


@router.get("/api/flows/{name}")
def open_flow(name: str) -> dict[str, Any]:
    try:
        return _store.load(name)
    except FileNotFoundError as exc:
        raise HTTPException(404, detail=f"No saved flow named {name!r}.") from exc
    except flow_store.FlowError as exc:
        raise HTTPException(422, detail=str(exc)) from exc


@router.put("/api/flows/{name}")
def save_flow(name: str, body: FlowBody) -> dict[str, Any]:
    try:
        return _store.save(name, body.flow, instrument=instrument.instrument_type())
    except flow_store.FlowError as exc:
        raise HTTPException(422, detail=str(exc)) from exc


@router.delete("/api/flows/{name}")
def delete_flow(name: str) -> dict[str, str]:
    try:
        _store.delete(name)
    except FileNotFoundError as exc:
        raise HTTPException(404, detail=f"No saved flow named {name!r}.") from exc
    except flow_store.FlowError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    return {"deleted": name}


@router.post("/api/flows/validate")
def validate_flow_file(body: FlowBody) -> dict[str, Any]:
    """Check a flow file the page read from disk (Import file) and return it normalized."""
    try:
        return flow_store.normalize(body.flow)
    except flow_store.FlowError as exc:
        raise HTTPException(422, detail=str(exc)) from exc


# -- scripts -------------------------------------------------------------------------------------


@router.post("/api/generate-script")
def generate_script(body: ScriptBody) -> dict[str, Any]:
    kind = instrument.instrument_type()

    def label(command: str) -> str | None:
        found = service.catalog.command(command, kind)
        return found["label"] if found else None

    try:
        flow.expand(body.steps, body.subflows)  # a missing subflow or a subflow that calls itself stops here, with its message
    except flow.FlowError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    result = codegen.render_script(body.steps, body.variables, instrument_type=kind, simulate=body.simulate,
                                   flow_name=body.flow_name, command_label=label, subflows=body.subflows)
    result["validation"] = validate_source(result["source"]).to_dict()
    return result


@router.post("/api/import-script")
def import_script(body: ImportBody) -> dict[str, Any]:
    return code_import.parse_script(body.source)


@router.post("/api/scripts/save")
async def save_script(body: SaveScriptBody) -> dict[str, Any]:
    """Store the script in the MCP spoke's script store (where AI agents and run_script find it)."""
    try:
        await asyncio.to_thread(service.bridge.ensure_spoke)
        return await asyncio.to_thread(service.bridge.import_script, body.name, body.source, body.overwrite)
    except BridgeError as exc:
        raise HTTPException(502, detail=str(exc)) from exc
