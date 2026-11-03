"""HTTP routes: health, shutdown, file browsing (for picking a script's source
path when creating a shortcut), and finalized run-log download ("Export Log").
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from hamilton_workflow_framework.routes_http import build_carrier_sites_router
from hamilton_workflow_framework.run_summary import RunLogError, load_run_log, summarize_run

from backend.config import load_backend_config
from backend.routes_ws import close_all_runs

router = APIRouter()
router.include_router(build_carrier_sites_router())  # deck viewer: carrier site heights


def _resolve_run_log_path(filename: str) -> Path:
    # Shared by both /api/logs/{filename} and its /summary sibling so the
    # traversal check can't drift between them.
    if "/" in filename or "\\" in filename or not filename.endswith("_SdkRunLog.json"):
        raise HTTPException(status_code=400, detail="Invalid log filename.")
    log_path = load_backend_config().run_log_root / filename
    if not log_path.is_file():
        raise HTTPException(status_code=404, detail="No run log found with that filename.")
    return log_path


@router.get("/api/browse-files")
async def browse_files(
    directory: str | None = Query(default=None, alias="dir"),
    ext: str | None = None,
) -> dict[str, Any]:
    config = load_backend_config()
    default_dir = config.default_browse_dir
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
                entries.append({"name": child.name, "is_dir": True, "path": str(child)})
            elif wanted_suffix is None or child.suffix.lower() == wanted_suffix:
                entries.append({"name": child.name, "is_dir": False, "path": str(child)})
    except (OSError, PermissionError):
        pass

    entries.sort(key=lambda e: (not e["is_dir"], e["name"].lower()))
    parent = current.parent
    parent_dir = str(parent) if parent != current else None
    return {"current_dir": str(current), "parent_dir": parent_dir, "entries": entries}


@router.get("/api/logs/{filename}")
async def download_run_log(filename: str) -> FileResponse:
    # Finalized run logs sit flat in the shared LogFiles folder (see
    # BackendConfig.run_log_root / script_runner.py), not a per-run subfolder,
    # so the filename itself -- reported back via the run_state message once a
    # run finishes -- is the only thing identifying which log to serve.
    log_path = _resolve_run_log_path(filename)
    return FileResponse(log_path, media_type="application/json", filename=log_path.name)


@router.get("/api/logs/{filename}/summary")
async def get_run_log_summary(filename: str) -> dict[str, Any]:
    """Condensed Summary-tab payload (duration, errors, tips used, grouped
    TADM curves) computed from the same finalized run log as /api/logs/{filename}.
    """
    log_path = _resolve_run_log_path(filename)
    try:
        log = load_run_log(log_path)
    except RunLogError as exc:
        raise HTTPException(status_code=422, detail=f"Run log could not be parsed: {exc}") from exc

    # Sibling file written by ScriptRunner._persist_line_timeline (same run,
    # same directory) -- optional: older runs predating this feature, or a run
    # whose script never advanced past the bootstrap, simply won't have one.
    line_timeline = None
    lines_path = log_path.with_name(log_path.name.replace("_SdkRunLog.json", "_ScriptLines.json"))
    if lines_path.is_file():
        try:
            line_timeline = json.loads(lines_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            line_timeline = None

    return summarize_run(log, line_timeline=line_timeline)


# Echoes the token the Photino shell generated for this launch, so the shell's
# health check only accepts the backend it started itself -- not another app
# that happens to be listening on the same port (see BackendProcessManager.cs).
@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "instance": os.environ.get("HAMILTON_APP_INSTANCE_TOKEN", "")}


@router.post("/api/shutdown")
async def shutdown() -> dict[str, str]:
    async def _cleanup_then_exit() -> None:
        # Terminate any in-progress script subprocess before exiting, so the
        # instrument's method doesn't stay running orphaned after the app closes.
        try:
            await close_all_runs()
        except Exception:
            pass
        os._exit(0)  # noqa: SLF001 - deliberate hard exit once cleanup has been requested

    asyncio.create_task(_cleanup_then_exit())
    return {"status": "shutting_down"}
