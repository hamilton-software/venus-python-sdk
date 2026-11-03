"""FastAPI app factory + uvicorn entrypoint.

Run standalone with: python -m backend.main (cwd must be the folder that directly
contains this "backend" package -- the repo's ai_assistant_app\\ folder in a dev checkout,
or an installed app's own root folder).
"""

from __future__ import annotations

import logging

import uvicorn
from fastapi import Request
from fastapi.responses import JSONResponse

from hamilton_workflow_framework.app_factory import create_app as _create_app

from backend import routes
from backend.config import load_backend_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


_logger = logging.getLogger(__name__)


async def _unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    # The page shows "detail"; without this a crash reaches it as a bare "HTTP 500".
    _logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": f"Unexpected error ({type(exc).__name__}): {exc}"})


def create_app():
    config = load_backend_config()
    app = _create_app(
        title="Hamilton AI Assistant",
        static_dir=config.static_dir,
        routers=[routes.router],
    )
    app.add_exception_handler(Exception, _unexpected_error)
    return app


app = create_app()


def main() -> None:
    config = load_backend_config()
    uvicorn.run("backend.main:app", host=config.host, port=config.port, log_level="info")


if __name__ == "__main__":
    main()
