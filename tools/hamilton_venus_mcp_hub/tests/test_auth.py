"""Hub-side bearer tokens: protecting the hub's own MCP endpoint, sending tokens to spokes,
and the keyed callback spokes push their events to."""

from __future__ import annotations

import os
import unittest
from unittest import mock

from hamilton_venus_mcp_hub import auth
from hamilton_venus_mcp_hub.spokes import SpokeConfig, SpokeGroup
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient


def _app() -> Starlette:
    async def ok(_request):
        return JSONResponse({"ok": True})

    return Starlette(routes=[Route("/mcp", ok, methods=["POST"]), Route("/dashboard", ok), Route("/api/status.json", ok)])


class McpBearerMiddlewareTests(unittest.TestCase):
    def test_only_the_mcp_endpoint_is_protected(self) -> None:
        client = TestClient(auth.McpBearerMiddleware(_app(), "hub-tok"))
        self.assertEqual(client.post("/mcp").status_code, 401)
        self.assertEqual(client.post("/mcp", headers={"Authorization": "Bearer hub-tok"}).status_code, 200)
        self.assertEqual(client.get("/dashboard").status_code, 200)
        self.assertEqual(client.get("/api/status.json").status_code, 200)


class SpokeTokenTests(unittest.TestCase):
    def test_per_spoke_tokens_override_the_shared_one(self) -> None:
        env = {auth.SPOKE_TOKEN_ENV: "shared", auth.SPOKE_TOKENS_ENV: "star1=one, star2 = two"}
        with mock.patch.dict(os.environ, env):
            self.assertEqual(auth.spoke_token("star1"), "one")
            self.assertEqual(auth.spoke_token("star2"), "two")
            self.assertEqual(auth.spoke_token("star3"), "shared")
            self.assertEqual(auth.spoke_headers("star1"), {"Authorization": "Bearer one"})

    def test_no_token_no_header(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(auth.spoke_headers("star1"))
            self.assertIsNone(auth.callback_key("star1"))

    def test_the_hub_sends_each_spoke_its_own_token(self) -> None:
        group = SpokeGroup([SpokeConfig("star1", "http://star1/mcp"), SpokeConfig("star2", "http://star2/mcp")])
        with mock.patch.dict(os.environ, {auth.SPOKE_TOKENS_ENV: "star1=one"}, clear=True):
            self.assertEqual(group._headers_for("http://star1/mcp"), {"Authorization": "Bearer one"})
            self.assertIsNone(group._headers_for("http://star2/mcp"))

    def test_callback_key_is_stable_and_per_spoke(self) -> None:
        with mock.patch.dict(os.environ, {auth.AUTH_TOKEN_ENV: "hub-tok"}, clear=True):
            first = auth.callback_key("star1")
            self.assertEqual(first, auth.callback_key("star1"))
            self.assertNotEqual(first, auth.callback_key("star2"))
            self.assertEqual(len(first), 32)


if __name__ == "__main__":
    unittest.main()
