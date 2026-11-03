"""Generic FastAPI app factory: mount an app's static UI + routers, disable caching.

Every workflow app's own main.py calls this instead of hand-assembling FastAPI.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.staticfiles import StaticFiles

from hamilton_workflow_framework.embedded_ui import EmbeddedStaticFiles, load_bundle

_FRAMEWORK_STATIC_DIR = Path(__file__).parent / "static_assets"


def create_app(*, title: str, static_dir: Path, routers: list[APIRouter]) -> FastAPI:
    app = FastAPI(title=title)
    for router in routers:
        app.include_router(router)
    # Mounted before the app's own catch-all "/" mount below, so requests under
    # this prefix resolve to the framework's shared JS (ws-client, param-form,
    # theme, console-pane, operator-prompt-modal, position-picker, ...) instead
    # of ever reaching the app's static directory.
    # A released app's exe hands over its UI as one bundle; from source it comes from the folders.
    bundle = load_bundle()
    if bundle is not None:
        app.mount("/framework-static", EmbeddedStaticFiles(bundle.framework), name="framework-static")
        app.mount("/", EmbeddedStaticFiles(bundle.app, html=True), name="static")
    else:
        app.mount("/framework-static", StaticFiles(directory=str(_FRAMEWORK_STATIC_DIR)), name="framework-static")
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    @app.middleware("http")
    async def no_cache(request, call_next):
        # This is a live control app under active iteration, not a CDN-served site --
        # always revalidate static assets (via ETag) rather than letting the browser's
        # heuristic cache silently serve a stale HTML/JS/CSS file with no request at all.
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-cache"
        return response

    return app
