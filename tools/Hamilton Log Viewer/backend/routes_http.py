"""HTTP routes: open a log (file or VENUS run), its views, recent VENUS runs, file browsing,
settings, health and shutdown."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from hamilton_venus.exceptions import VenusError
from hamilton_workflow_framework.run_log.venus_runs import fetch_run_bundle, list_runs

from backend.config import VENUS_LOG_FILES, load_backend_config
from backend.log_store import LogOpenError, LogStore
from backend.settings_store import SettingsStore

router = APIRouter()
_config = load_backend_config()
_logs = LogStore(_config.max_open_logs)
_settings = SettingsStore(_config)

_VIEWS = ("trace", "summary", "errors", "samples", "commands")


class OpenFileRequest(BaseModel):
    path: str


class DroppedFile(BaseModel):
    name: str
    data: str  # base64


class OpenDroppedRequest(BaseModel):
    files: list[DroppedFile]


class OpenRunRequest(BaseModel):
    host: str
    run: dict[str, Any]


class SettingsUpdate(BaseModel):
    venus_host: str | None = None


def _venus_error(exc: Exception, host: str) -> HTTPException:
    return HTTPException(status_code=502, detail=f"VENUS at {host or 'localhost'}: {exc}")


@router.post("/api/logs/open-file")
def open_file(request: OpenFileRequest) -> dict[str, Any]:
    try:
        opened = _logs.open_file(request.path)
    except LogOpenError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _settings.add_recent_file(str(Path(request.path)))
    return opened.header()


@router.post("/api/logs/open-dropped")
def open_dropped(request: OpenDroppedRequest) -> dict[str, Any]:
    # Where a dropped log most likely also lives: LogFiles and the folders of recent logs.
    known_dirs = [VENUS_LOG_FILES, _config.default_browse_dir]
    known_dirs += [Path(p).parent for p in _settings.get().get("recent_files", []) if isinstance(p, str)]
    try:
        opened = _logs.open_dropped([f.model_dump() for f in request.files], list(dict.fromkeys(known_dirs)))
    except LogOpenError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if opened.origin.get("kind") == "file":
        _settings.add_recent_file(opened.origin["path"])
    return opened.header()


@router.post("/api/logs/open-run")
async def open_run(request: OpenRunRequest) -> dict[str, Any]:
    run_guid, method = request.run.get("run_guid"), request.run.get("method")
    if not run_guid or not method:
        raise HTTPException(status_code=400, detail="The run needs run_guid and method.")
    try:
        bundle = await fetch_run_bundle(request.host, run_guid, method)
    except VenusError as exc:
        raise _venus_error(exc, request.host) from exc
    if bundle["log"] is None and not bundle["trace_lines"]:
        raise HTTPException(status_code=404, detail=" ".join(bundle["notes"]) or "Nothing found for this run.")
    return _logs.open_bundle(request.host, request.run, bundle).header()


@router.get("/api/logs/{log_id}/commands/{command_id}")
def get_command(log_id: str, command_id: str) -> dict[str, Any]:
    opened = _logs.get(log_id)
    if opened is None:
        raise HTTPException(status_code=404, detail="This log is no longer open; open it again.")
    detail = opened.command_detail(command_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="No such command in this log.")
    return detail


@router.get("/api/logs/{log_id}/{view}")
def get_view(log_id: str, view: str) -> Any:
    if view not in _VIEWS:
        raise HTTPException(status_code=404, detail=f"Unknown view {view!r}.")
    opened = _logs.get(log_id)
    if opened is None:
        raise HTTPException(status_code=404, detail="This log is no longer open; open it again.")
    result = opened.view(view)
    return {"lines": result} if view == "trace" else result


@router.get("/api/venus/runs")
async def venus_runs(
    host: str = Query(default="localhost"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=1, ge=1),
) -> dict[str, Any]:
    try:
        return await list_runs(host, limit=limit, offset=offset)
    except VenusError as exc:
        raise _venus_error(exc, host) from exc


@router.get("/api/settings")
def get_settings() -> dict[str, Any]:
    return {**_settings.get(), "default_browse_dir": str(_config.default_browse_dir)}


@router.put("/api/settings")
def put_settings(update: SettingsUpdate) -> dict[str, Any]:
    changes = {k: v for k, v in update.model_dump().items() if v is not None}
    return _settings.update(**changes)


@router.post("/api/settings/recent-files/remove")
def remove_recent_file(request: OpenFileRequest) -> dict[str, Any]:
    return _settings.remove_recent_file(request.path)


@router.get("/api/browse-files")
def browse_files(
    directory: str | None = Query(default=None, alias="dir"),
    ext: str | None = None,
) -> dict[str, Any]:
    """Same contract as the Script Manager's file browser endpoint (file-browser-modal.js)."""
    default_dir = _config.default_browse_dir
    current = Path(directory) if directory else default_dir
    if not current.is_dir():
        current = default_dir if default_dir.is_dir() else Path(current.anchor or "C:\\")

    wanted_suffix = f".{ext.lower().lstrip('.')}" if ext else None
    entries: list[dict[str, Any]] = []
    try:
        for child in current.iterdir():
            try:
                is_dir = child.is_dir()
            except OSError:
                continue
            if is_dir:
                entries.append({"name": child.name, "is_dir": True, "path": str(child), "mtime": 0.0})
            elif wanted_suffix is None or child.suffix.lower() == wanted_suffix:
                if child.name.endswith("_ScriptLines.json"):
                    continue  # a run log's companion, opened with it -- never a log itself
                try:
                    mtime = child.stat().st_mtime
                except OSError:
                    mtime = 0.0
                entries.append({"name": child.name, "is_dir": False, "path": str(child), "mtime": mtime})
    except (OSError, PermissionError):
        pass

    # Folders by name, then files newest first: run log names start with the method, not a
    # date, so name order would bury the latest run among hundreds in LogFiles.
    entries.sort(key=lambda e: (not e["is_dir"], e["name"].lower() if e["is_dir"] else -e["mtime"]))
    parent = current.parent
    parent_dir = str(parent) if parent != current else None
    return {"current_dir": str(current), "parent_dir": parent_dir, "entries": entries}


# Echoes the token the Photino shell generated for this launch, so the shell's
# health check only accepts the backend it started itself -- not another app
# that happens to be listening on the same port (see BackendProcessManager.cs).
@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "instance": os.environ.get("HAMILTON_APP_INSTANCE_TOKEN", "")}


@router.post("/api/shutdown")
async def shutdown() -> dict[str, str]:
    async def _exit_soon() -> None:
        await asyncio.sleep(0.1)
        os._exit(0)  # noqa: SLF001 - deliberate hard exit; nothing to clean up

    asyncio.create_task(_exit_soon())
    return {"status": "shutting_down"}
