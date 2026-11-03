"""Bearer-token protection of a network spoke (hamilton_venus_mcp.auth)."""

from __future__ import annotations

import os
import unittest
from unittest import mock

from hamilton_venus_mcp.auth import AUTH_TOKEN_ENV, BearerTokenMiddleware, bearer_matches, configured_token
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient


def _app() -> Starlette:
    async def ok(_request):
        return JSONResponse({"ok": True})

    return Starlette(routes=[Route("/mcp", ok, methods=["GET", "POST"]), Route("/ping", ok)])


class BearerTokenMiddlewareTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(BearerTokenMiddleware(_app(), "s3cret"))

    def test_mcp_needs_the_token(self) -> None:
        response = self.client.post("/mcp")
        self.assertEqual(response.status_code, 401)
        self.assertIn("Bearer", response.headers["www-authenticate"])

    def test_wrong_token_or_scheme_is_refused(self) -> None:
        self.assertEqual(self.client.post("/mcp", headers={"Authorization": "Bearer nope"}).status_code, 401)
        self.assertEqual(self.client.post("/mcp", headers={"Authorization": "Basic s3cret"}).status_code, 401)

    def test_right_token_passes(self) -> None:
        response = self.client.post("/mcp", headers={"Authorization": "Bearer s3cret"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True})
        self.assertEqual(self.client.post("/mcp", headers={"authorization": "bearer s3cret"}).status_code, 200)

    def test_ping_stays_open_for_discovery(self) -> None:
        self.assertEqual(self.client.get("/ping").status_code, 200)

    def test_an_empty_token_is_rejected_up_front(self) -> None:
        with self.assertRaises(ValueError):
            BearerTokenMiddleware(_app(), "")


class TokenHelperTests(unittest.TestCase):
    def test_bearer_matches(self) -> None:
        self.assertTrue(bearer_matches("Bearer abc", "abc"))
        self.assertTrue(bearer_matches("  bearer   abc  ", "abc"))
        self.assertFalse(bearer_matches(None, "abc"))
        self.assertFalse(bearer_matches("Bearer abcd", "abc"))

    def test_configured_token_reads_the_environment(self) -> None:
        with mock.patch.dict(os.environ, {AUTH_TOKEN_ENV: "  tok  "}):
            self.assertEqual(configured_token(), "tok")
        with mock.patch.dict(os.environ, {AUTH_TOKEN_ENV: "  "}):
            self.assertIsNone(configured_token())


if __name__ == "__main__":
    unittest.main()
