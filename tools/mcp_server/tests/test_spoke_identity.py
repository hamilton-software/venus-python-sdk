"""Tests for this spoke's self-reported display name and its /ping route (see
hamilton_venus_mcp_hub.discovery for the hub-side scanner that calls /ping). The
"name" field get_spoke_state() also reports is exercised in test_server_scripts.py
instead, next to that tool's other heavier (RunManager-backed) tests.
"""

from __future__ import annotations

import json
import os
import unittest
from unittest import mock

import hamilton_venus_mcp.server as srv


class SpokeNameTests(unittest.TestCase):
    def test_uses_the_configured_env_var_when_set(self):
        with mock.patch.dict(os.environ, {srv.SPOKE_NAME_ENV: "  star3-test  "}):
            self.assertEqual(srv._spoke_name(), "star3-test")

    def test_falls_back_to_the_hostname_when_unset(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(srv.SPOKE_NAME_ENV, None)
            with mock.patch.object(srv.socket, "gethostname", return_value="FAKE-PC-01"):
                self.assertEqual(srv._spoke_name(), "FAKE-PC-01")

    def test_falls_back_to_the_hostname_when_blank(self):
        with mock.patch.dict(os.environ, {srv.SPOKE_NAME_ENV: "   "}):
            with mock.patch.object(srv.socket, "gethostname", return_value="FAKE-PC-01"):
                self.assertEqual(srv._spoke_name(), "FAKE-PC-01")


class _FakeRequest:
    """ping() takes a Request but never reads it -- a bare placeholder is enough,
    matching how the hub's own tests call its custom_route handlers directly."""


class PingRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_the_configured_name_and_service_marker(self):
        with mock.patch.dict(os.environ, {srv.SPOKE_NAME_ENV: "star3-test", "HAMILTON_MCP_AUTH_TOKEN": ""}):
            response = await srv.ping(_FakeRequest())

        self.assertEqual(
            json.loads(response.body),
            {"service": "hamilton-venus-mcp", "name": "star3-test", "auth_required": False},
        )


if __name__ == "__main__":
    unittest.main()
