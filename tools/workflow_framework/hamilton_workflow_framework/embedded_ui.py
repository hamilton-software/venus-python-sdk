"""Serve an app's UI from memory instead of from files on disk.

A released app's exe carries its HTML, JS, CSS and images as one zip. The exe sets
HAMILTON_EMBEDDED_UI and writes that zip to the backend's stdin, so the UI never sits on
disk next to the backend. Run from source (dev, tests) the variable is unset and
app_factory serves the static folders as usual.
"""

from __future__ import annotations

import hashlib
import io
import mimetypes
import os
import sys
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass, field

from starlette.exceptions import HTTPException
from starlette.responses import RedirectResponse, Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

ENV_VAR = "HAMILTON_EMBEDDED_UI"
_APP_PREFIX = "app/"
_FRAMEWORK_PREFIX = "framework/"

# Windows takes content types from the registry, where .js can be text/plain and module
# scripts then refuse to load; these are fixed so a PC's registry cannot break the UI.
_CONTENT_TYPES = {
    ".css": "text/css",
    ".gltf": "model/gltf+json",
    ".html": "text/html",
    ".js": "text/javascript",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".woff2": "font/woff2",
}


@dataclass(frozen=True)
class EmbeddedBundle:
    app: dict[str, bytes] = field(default_factory=dict)
    framework: dict[str, bytes] = field(default_factory=dict)


def parse_bundle(data: bytes) -> EmbeddedBundle:
    """Split the zip the exe sends into the app's files and the framework's files."""
    bundle = EmbeddedBundle()
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for name in archive.namelist():
            path = name.replace("\\", "/")
            if path.endswith("/"):
                continue
            if path.startswith(_APP_PREFIX):
                bundle.app[path.removeprefix(_APP_PREFIX)] = archive.read(name)
            elif path.startswith(_FRAMEWORK_PREFIX):
                bundle.framework[path.removeprefix(_FRAMEWORK_PREFIX)] = archive.read(name)
    if "index.html" not in bundle.app:
        raise ValueError("The embedded UI has no index.html")
    return bundle


_bundle: EmbeddedBundle | None = None


def load_bundle() -> EmbeddedBundle | None:
    """The bundle from stdin, or None when the UI should come from disk.

    `python -m backend.main` followed by uvicorn importing backend.main builds the app twice, and
    stdin can only be read once, so the first read is kept.
    """
    global _bundle
    if not os.environ.get(ENV_VAR):
        return None
    if _bundle is None:
        _bundle = parse_bundle(sys.stdin.buffer.read())
    return _bundle


def _content_type(path: str) -> str:
    known = _CONTENT_TYPES.get(os.path.splitext(path)[1].lower())
    return known or mimetypes.guess_type(path)[0] or "application/octet-stream"


class EmbeddedStaticFiles(StaticFiles):
    """StaticFiles over an in-memory {path: bytes}, with the same URLs, html=True and ETag behavior."""

    def __init__(self, files: Mapping[str, bytes], html: bool = False) -> None:
        super().__init__(directory=None, packages=None, html=html, check_dir=False)
        self._files = dict(files)
        self._etags = {path: hashlib.sha256(content).hexdigest() for path, content in self._files.items()}

    async def check_config(self) -> None:
        return None

    def _file_response(self, path: str, scope: Scope, status_code: int = 200) -> Response:
        content = self._files[path]
        etag = f'"{self._etags[path]}"'
        if status_code == 200 and etag in dict(scope["headers"]).get(b"if-none-match", b"").decode("latin-1"):
            return Response(status_code=304, headers={"etag": etag})
        headers = {"etag": etag, "content-length": str(len(content))}
        body = b"" if scope["method"] == "HEAD" else content
        return Response(body, status_code=status_code, media_type=_content_type(path), headers=headers)

    async def get_response(self, path: str, scope: Scope) -> Response:
        if scope["method"] not in ("GET", "HEAD"):
            raise HTTPException(status_code=405)
        # get_path gives a normalized OS path; a path that escapes the root keeps its ".." and matches nothing.
        name = "" if path == "." else path.replace("\\", "/")
        if name in self._files:
            return self._file_response(name, scope)
        if self.html:
            index = f"{name}/index.html" if name else "index.html"
            if index in self._files:
                if name and not scope["path"].endswith("/"):
                    return RedirectResponse(url=f'{scope["path"]}/', status_code=307)
                return self._file_response(index, scope)
            if "404.html" in self._files:
                return self._file_response("404.html", scope, status_code=404)
        raise HTTPException(status_code=404)

