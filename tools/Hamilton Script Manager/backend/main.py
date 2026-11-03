"""FastAPI app factory + uvicorn entrypoint.

Run standalone with: python -m backend.main (cwd must be the folder that
directly contains this "backend" package -- the repo's python_script_manager_app\
folder in a dev checkout, or an installed app's own root folder).
"""

from __future__ import annotations

import logging

import uvicorn

from hamilton_workflow_framework.app_factory import create_app as _create_app

from backend import routes_http, routes_ws
from backend.config import load_backend_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


def create_app():
    config = load_backend_config()
    return _create_app(
        title="Hamilton Script Manager",
        static_dir=config.static_dir,
        routers=[routes_http.router, routes_ws.router],
    )


app = create_app()


def main() -> None:
    config = load_backend_config()
    uvicorn.run("backend.main:app", host=config.host, port=config.port, log_level="info")


if __name__ == "__main__":
    main()
