"""The UI served from memory (a released app's exe) instead of from the static folders."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from hamilton_workflow_framework import app_factory, embedded_ui
from hamilton_workflow_framework.embedded_ui import EmbeddedBundle, parse_bundle


def bundle_bytes(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


BUNDLE = EmbeddedBundle(
    app={
        "index.html": b"<html>home</html>",
        "js/app.js": b"console.log(1)",
        "deck-viewer/index.html": b"<html>deck</html>",
        "deck-viewer/viewer.html": b"<html>viewer</html>",
        "fonts/a.woff2": b"font",
    },
    framework={"js/theme.js": b"theme"},
)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(app_factory, "load_bundle", lambda: BUNDLE)
    return TestClient(app_factory.create_app(title="t", static_dir=Path("missing"), routers=[APIRouter()]))


def test_app_files_are_served_with_the_right_types(client):
    response = client.get("/")
    assert response.text == "<html>home</html>" and response.headers["content-type"].startswith("text/html")
    assert client.get("/js/app.js").headers["content-type"].startswith("text/javascript")
    assert client.get("/fonts/a.woff2").headers["content-type"] == "font/woff2"


def test_framework_files_are_under_their_own_prefix(client):
    assert client.get("/framework-static/js/theme.js").content == b"theme"
    assert client.get("/js/theme.js").status_code == 404


def test_a_folder_opens_its_index_like_static_files(client):
    assert client.get("/deck-viewer/").text == "<html>deck</html>"
    redirected = client.get("/deck-viewer", follow_redirects=False)
    assert redirected.status_code == 307 and redirected.headers["location"].endswith("/deck-viewer/")
    assert client.get("/deck-viewer/viewer.html").text == "<html>viewer</html>"


def test_missing_files_and_paths_out_of_the_bundle_are_404(client):
    assert client.get("/nope.js").status_code == 404
    assert client.get("/..%2f..%2fbackend/main.py").status_code == 404
    assert client.get("/framework-static/..%2fjs/app.js").status_code == 404


def test_etag_revalidation_and_head(client):
    first = client.get("/js/app.js")
    again = client.get("/js/app.js", headers={"if-none-match": first.headers["etag"]})
    assert again.status_code == 304 and again.content == b""
    assert first.headers["cache-control"] == "no-cache"
    head = client.head("/js/app.js")
    assert head.status_code == 200 and head.content == b"" and head.headers["content-length"] == "14"


def test_writes_are_refused(client):
    assert client.post("/js/app.js").status_code == 405


def test_parse_bundle_splits_the_zip_and_accepts_backslash_names():
    bundle = parse_bundle(bundle_bytes({"app\\index.html": b"a", "app/js/a.js": b"b", "framework/js/t.js": b"c"}))
    assert bundle.app == {"index.html": b"a", "js/a.js": b"b"} and bundle.framework == {"js/t.js": b"c"}


def test_parse_bundle_refuses_a_bundle_without_a_page():
    with pytest.raises(ValueError, match="index.html"):
        parse_bundle(bundle_bytes({"framework/js/t.js": b"c"}))


class _Stdin:
    def __init__(self, data: bytes) -> None:
        self.buffer = io.BytesIO(data)


def test_stdin_is_read_once_and_kept(monkeypatch):
    # backend.main builds the app twice in one process; the second build must not read an empty stdin.
    monkeypatch.setenv(embedded_ui.ENV_VAR, "1")
    monkeypatch.setattr(embedded_ui, "_bundle", None)
    monkeypatch.setattr(embedded_ui.sys, "stdin", _Stdin(bundle_bytes({"app/index.html": b"a"})))
    assert embedded_ui.load_bundle() is embedded_ui.load_bundle()


def test_from_source_the_ui_stays_on_disk(monkeypatch):
    monkeypatch.delenv(embedded_ui.ENV_VAR, raising=False)
    assert embedded_ui.load_bundle() is None
