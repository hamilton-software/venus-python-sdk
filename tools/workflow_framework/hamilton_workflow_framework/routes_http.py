"""Generic HTTP routes shared by every workflow app: health, shutdown, file browsing,
carrier site heights for the deck viewer.

Command-catalog, labware-catalog, saved-decks, and codegen/import endpoints are
app-specific (they depend on each app's own curated registry/labware set) and stay
in each app's own routes_http.py, which ``include_router()``s this alongside its
own routes.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Query

from hamilton_workflow_framework.routes_ws import close_all_sessions

_logger = logging.getLogger("hamilton_workflow_framework.http")

_CARRIER_ID = re.compile(r"^[A-Za-z0-9_.\- ]{1,128}$")
_SITE_FIELD = re.compile(r'^\s*Site\.(\d+)\.(Id|X|Y|Z|Dx|Dy|Visible)\s*,\s*"([^"]*)"', re.MULTILINE)


def _active_layout_dir() -> Path:
    from hamilton_venus._internal._sdk_paths import get_sdk_active_layout_path

    return get_sdk_active_layout_path()


def read_carrier_sites(carrier_id: str, layout_dir: Path | None = None) -> dict[str, Any]:
    """Sites of a deck carrier from the SDK's active-layout template (``<carrier>.tml``).

    Per site: ``x``/``y`` (front-left corner) and ``z`` (surface height) relative to
    the template origin, ``dx``/``dy`` footprint, all in mm. ``lowestSiteZ`` is the
    lowest visible site (all sites when none is marked visible), or ``None``.
    """
    if not _CARRIER_ID.match(carrier_id) or carrier_id.strip(". ") != carrier_id or ".." in carrier_id:
        raise ValueError(f"invalid carrier id {carrier_id!r}")
    folder = layout_dir or _active_layout_dir()
    path = folder / f"{carrier_id}.tml"
    if path.resolve().parent != folder.resolve():
        raise ValueError(f"invalid carrier id {carrier_id!r}")
    text = path.read_text(encoding="utf-8", errors="replace")
    fields: dict[str, dict[str, str]] = {}
    for num, key, value in _SITE_FIELD.findall(text):
        fields.setdefault(num, {})[key] = value
    sites = []
    for site in fields.values():
        try:
            z = float(site["Z"])
        except (KeyError, ValueError):
            continue
        def num(key: str) -> float | None:
            try:
                return float(site[key])
            except (KeyError, ValueError):
                return None

        sites.append({
            "id": site.get("Id", ""), "x": num("X"), "y": num("Y"), "z": z,
            "dx": num("Dx"), "dy": num("Dy"), "visible": site.get("Visible", "1") != "0",
        })
    candidates = [s["z"] for s in sites if s["visible"]] or [s["z"] for s in sites]
    return {"carrierId": carrier_id, "sites": sites, "lowestSiteZ": min(candidates) if candidates else None}


def build_carrier_sites_router() -> APIRouter:
    """``GET /api/deck/carrier-sites/{carrier_id}`` - site heights the deck-layout API does not provide.

    The deck viewer uses ``lowestSiteZ`` to cap the placeholder box drawn for a
    carrier without a 3D model, so labware placed on its sites stays visible.
    """
    router = APIRouter()

    @router.get("/api/deck/carrier-sites/{carrier_id}")
    async def carrier_sites(carrier_id: str) -> dict[str, Any]:
        try:
            return read_carrier_sites(carrier_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"no template for carrier {carrier_id!r}") from exc

    return router


def build_generic_http_router(*, default_browse_dir: Callable[[], Path]) -> APIRouter:
    router = APIRouter()
    router.include_router(build_carrier_sites_router())

    @router.get("/api/browse-files")
    async def browse_files(
        directory: str | None = Query(default=None, alias="dir"),
        ext: str | None = None,
    ) -> dict[str, Any]:
        """List a directory's contents for the param-form's file-path Browse dialog.

        Directories are always listed (so the user can navigate anywhere on disk --
        files aren't confined to one folder); files are filtered to `ext` when given.
        Falls back to *default_browse_dir()* when `dir` is omitted or no longer exists.
        """
        default_dir = default_browse_dir()
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

    # Echoes the token the Photino shell generated for this launch, so the shell's
    # health check only accepts the backend it started itself -- not another app
    # that happens to be listening on the same port (see BackendProcessManager.cs).
    @router.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "instance": os.environ.get("HAMILTON_APP_INSTANCE_TOKEN", "")}

    @router.post("/api/shutdown")
    async def shutdown() -> dict[str, str]:
        async def _cleanup_then_exit() -> None:
            # Close every active session (StarClient.__exit__) BEFORE exiting the process,
            # so the instrument's method is properly terminated/unloaded rather than left
            # stale for the next connection attempt to trip over. This can legitimately
            # take up to ~30s (the SDK's disconnect timeout) if a method is running.
            try:
                await close_all_sessions()
            except Exception:
                _logger.exception("Error during shutdown cleanup")
            os._exit(0)  # noqa: SLF001 - deliberate hard exit once cleanup has completed

        asyncio.create_task(_cleanup_then_exit())
        return {"status": "shutting_down"}

    return router
